"""Read-only Hyperliquid public data and conservative position classification."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import os
import re

import requests

INFO_URL = "https://api.hyperliquid.xyz/info"
WS_URL = "wss://api.hyperliquid.xyz/ws"
DEX = "xyz"
# Friendly labels only; availability always comes from the official xyz catalog.
# Metadata does not classify all instruments as equities, so other names stay neutral.
MARKET_LABELS = {"xyz:KORU": "韩国股票 ETF 关联永续", "xyz:SKHY": "SK Hynix 关联永续",
                 "xyz:NVDA": "NVIDIA 关联永续", "xyz:TSLA": "Tesla 关联永续"}
MARKET_PATTERN = r"^xyz:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
SOURCE = "Hyperliquid / trade.xyz"
KINDS = {"discovered": "新发现已有仓位", "opened": "新开仓", "increased": "加仓",
         "reduced": "减仓", "closed": "平仓", "flipped": "反向开仓"}


def milliseconds():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid numeric field") from None
    if not result.is_finite():
        raise ValueError("Non-finite numeric field")
    return result


def address_value(value):
    if isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value) and int(value[2:], 16):
        return value.lower()
    return None


class PublicAPIError(RuntimeError):
    def __init__(self, status, retry_seconds=60):
        super().__init__(f"Hyperliquid HTTP {status}")
        self.status = status
        self.retry_seconds = retry_seconds


class PublicClient:
    def __init__(self):
        self.session = requests.Session()
        self.proxies = {"https": os.environ["HYPERLIQUID_PROXY"]} if os.getenv("HYPERLIQUID_PROXY") else None

    def info(self, payload):
        response = self.session.post(INFO_URL, json=payload, timeout=(5, 12), proxies=self.proxies)
        if response.status_code != 200:
            # Do not include credentials, proxy URLs or full request details in logs.
            retry = response.headers.get("Retry-After", "60")
            retry = min(300, max(10, int(retry))) if retry.isdigit() else 60
            raise PublicAPIError(response.status_code, retry)
        return response.json()

    def markets(self):
        raw = self.info({"type": "meta", "dex": DEX})
        if not isinstance(raw, dict) or not isinstance(raw.get("universe"), list):
            raise ValueError("Invalid metadata")
        markets = {}
        for item in raw["universe"]:
            if not isinstance(item, dict) or item.get("isDelisted"):
                continue
            coin = item.get("name")
            if not isinstance(coin, str) or not re.fullmatch(MARKET_PATTERN, coin):
                continue
            markets[coin] = {"coin": coin, "name": MARKET_LABELS.get(coin, f"{coin[4:]} 永续合约"),
                             "max_leverage": item.get("maxLeverage"), "source": SOURCE}
        return [markets[coin] for coin in sorted(markets)]

    def positions(self, address):
        return self.info({"type": "clearinghouseState", "user": address, "dex": DEX})


def parse_positions(raw, coins):
    """Missing/malformed responses must never be interpreted as closed positions."""
    if not isinstance(raw, dict) or not isinstance(raw.get("assetPositions"), list):
        raise ValueError("Missing assetPositions")
    stamp = int(raw.get("time", 0))
    if stamp <= 0 or stamp > milliseconds() + 60000:
        raise ValueError("Invalid snapshot time")
    result = {coin: {"qty": "0", "notional_usd": "0", "entry_price": None,
                     "leverage": None, "leverage_type": None, "unrealized_pnl": None} for coin in coins}
    seen = set()
    for row in raw["assetPositions"]:
        p = row.get("position", {})
        coin = p.get("coin")
        if coin not in result:
            continue
        if coin in seen:
            raise ValueError("Duplicate position")
        seen.add(coin)
        qty, notional = decimal(p.get("szi")), decimal(p.get("positionValue"))
        if abs(qty) > Decimal("1e30") or notional > Decimal("1e18"):
            raise ValueError("Position exceeds supported numeric range")
        if notional < 0 or (qty != 0 and notional <= 0) or (qty == 0 and notional != 0):
            raise ValueError("Invalid position value")
        entry = None if p.get("entryPx") is None else decimal(p["entryPx"])
        if entry is not None and entry <= 0:
            raise ValueError("Invalid entry price")
        leverage = p.get("leverage") or {}
        lev = None if leverage.get("value") is None else decimal(leverage["value"])
        if lev is not None and lev <= 0:
            raise ValueError("Invalid leverage")
        # An optional P&L field must not invalidate an otherwise valid position.
        try:
            pnl = decimal(p.get("unrealizedPnl"))
            if abs(pnl) > Decimal("1e18"):
                pnl = None
        except ValueError:
            pnl = None
        result[coin] = {"qty": str(qty), "notional_usd": str(notional),
                        "entry_price": str(entry) if entry is not None else None,
                        "unrealized_pnl": str(pnl) if qty != 0 and pnl is not None else None,
                        "leverage": str(lev) if lev is not None else None,
                        "leverage_type": leverage.get("type") if leverage.get("type") in {"cross", "isolated"} else None}
    for p in result.values():
        p["snapshot_ms"] = stamp
    return stamp, result


def position_event(address, coin, previous, current, snapshot_ms):
    """Compare signed quantities, never dollar changes caused solely by prices.

    A first observation is a discovery/baseline, not evidence of a new opening.
    Later events describe the net change between two verified snapshots. We do
    not infer each trade, execution price, or historical leverage from them.
    """
    qty = decimal(current["qty"])
    old = decimal(previous["qty"]) if previous is not None else None
    if old is None:
        if qty == 0:
            return None
        kind = "discovered"
    elif qty == old:
        return None
    elif old == 0:
        kind = "opened"
    elif qty == 0:
        kind = "closed"
    elif qty * old < 0:
        kind = "flipped"
    else:
        kind = "increased" if abs(qty) > abs(old) else "reduced"
    qualifying = max(decimal(current["notional_usd"]), decimal(previous["notional_usd"]) if previous else Decimal(0))
    key = hashlib.sha256(f"{address}|{coin}|{snapshot_ms}|{kind}".encode()).hexdigest()
    side_qty = qty if qty else old
    payload = {"event_key": key, "address": address, "coin": coin, "source": SOURCE,
               "kind": kind, "side": "long" if side_qty > 0 else "short",
               "previous_qty": str(old) if old is not None else None,
               "qty": str(qty), "delta_qty": str(qty - old) if old is not None else None,
               "notional_usd": current["notional_usd"], "qualifying_usd": str(qualifying),
               "entry_price": current["entry_price"], "leverage": current["leverage"],
               "unrealized_pnl": current.get("unrealized_pnl") if qty != 0 else None,
               "leverage_type": current["leverage_type"], "snapshot_ms": snapshot_ms,
               "previous_snapshot_ms": previous.get("snapshot_ms") if previous else None,
               "previous_notional_usd": previous["notional_usd"] if previous else None,
               "basis": "first_snapshot" if old is None else "snapshot_change"}
    return payload


def event_text(event):
    short = event["address"][:8] + "…" + event["address"][-6:]
    side = "多单" if event["side"] == "long" else "空单"
    title = f"🐋 {event['coin']} {KINDS[event['kind']]} · {side}"
    value = decimal(event["notional_usd"])
    text = f"{title} · ${value:,.0f}\n地址：{event['address']}\n"
    if event["entry_price"] is not None:
        text += f"当前仓位平均开仓价：${decimal(event['entry_price']):,.6f}\n"
    if event["leverage"] is not None:
        mode = {"cross": "全仓", "isolated": "逐仓"}.get(event["leverage_type"], "")
        text += f"当前杠杆设置：{event['leverage']}x {mode}\n"
    if event["previous_qty"] is not None:
        text += f"仓位数量：{event['previous_qty']} → {event['qty']}\n"
    else:
        text += f"仓位数量：{event['qty']}\n"
    text += f"当前仓位名义价值：${value:,.2f}\n"
    if event["kind"] != "closed":
        pnl = event.get("unrealized_pnl")
        if pnl is None:
            text += "当前未实现盈亏：未提供\n"
        else:
            amount = decimal(pnl)
            sign = "+" if amount > 0 else "-" if amount < 0 else ""
            text += f"当前未实现盈亏：{sign}${abs(amount):,.2f}\n"
    if event["kind"] == "closed":
        text += f"上次核验名义价值：${decimal(event['previous_notional_usd']):,.2f}\n"
        text += "已实现盈亏：未提供（需平仓成交记录）\n"
    stamp = datetime.fromtimestamp(event["snapshot_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text += f"核验时间：{stamp}\n来源：{SOURCE}\n"
    if event.get("previous_snapshot_ms"):
        prior = datetime.fromtimestamp(event["previous_snapshot_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        text += f"上次仓位核验：{prior}\n"
    text += ("首次发现的已有持仓，不代表刚开仓。" if event["kind"] == "discovered" else
             "两次仓位核验间的净变化；不代表逐笔成交或精确开仓时间。")
    text += "\n同名 Binance USDT 合约为不同市场。"
    return title + " · " + short, text
