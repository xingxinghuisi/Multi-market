"""Read-only Hyperliquid public data and conservative position classification."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import os
import re
import time

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
        self.next_request_at = 0

    def info(self, payload):
        # Sequential worker client: reserve weight for every REST request, including
        # fill lookups. Target <=900 weight/min, below the shared 1200/IP limit.
        time.sleep(max(0, self.next_request_at - time.monotonic()))
        started = time.monotonic()
        weight = 2 if payload["type"] == "clearinghouseState" else 20
        self.next_request_at = started + max(.6, weight / 15)
        response = self.session.post(INFO_URL, json=payload, timeout=(5, 12), proxies=self.proxies)
        if response.status_code != 200:
            # Do not include credentials, proxy URLs or full request details in logs.
            retry = response.headers.get("Retry-After", "60")
            retry = min(300, max(10, int(retry))) if retry.isdigit() else 60
            raise PublicAPIError(response.status_code, retry)
        raw = response.json()
        if payload["type"] == "userFillsByTime" and isinstance(raw, list):
            weight += (len(raw) + 19) // 20
            self.next_request_at = started + max(.6, weight / 15)
        return raw

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

    def fills(self, address, start_ms, end_ms):
        # This endpoint includes HIP-3 fills with their full xyz: coin names.
        return self.info({"type": "userFillsByTime", "user": address,
                          "startTime": start_ms, "endTime": end_ms, "aggregateByTime": False})


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


def _plain_number(value):
    text = format(decimal(value), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _compact_money(value):
    amount = decimal(value)
    for scale, unit in ((Decimal("1e8"), "亿"), (Decimal("1e4"), "万")):
        if amount >= scale:
            return f"${amount / scale:,.2f}{unit}"
    return f"${amount:,.2f}"


def _execution_lines(event):
    execution = event.get("execution") or {}
    verified = execution.get("status") == "verified"
    def price(field):
        value = execution.get(field) if verified else None
        return "未提供" if value is None else f"${_plain_number(format(decimal(value), '.10g'))}"
    if event["kind"] == "flipped":
        return [f"{label}：{price(field)}{'（成交均价）' if verified and execution.get(count, 0) > 1 else ''}"
                for label, field, count in (("平仓价格", "close_price", "close_fill_count"),
                                            ("开仓价格", "open_price", "open_fill_count"))]
    label = {"increased": "加仓价格", "reduced": "减仓价格", "closed": "平仓价格"}.get(event["kind"], "开仓价格")
    suffix = "（成交均价）" if verified and execution.get("fill_count", 0) > 1 else ""
    return [f"{label}：{price('price')}{suffix}"]


def event_text(event):
    """Concise notification copy; full source and snapshot details stay in the event."""
    side = "多单" if event["side"] == "long" else "空单"
    kind = event["kind"]
    if kind == "discovered":
        action = f"新发现已有{side}"
    elif kind == "opened":
        action = f"新开{side}"
    elif kind in {"increased", "reduced"}:
        change = abs(abs(decimal(event["qty"])) - abs(decimal(event["previous_qty"])))
        action = f"{side}{KINDS[kind]} {_plain_number(change)}"
    elif kind == "flipped":
        action = "空单转多单" if event["side"] == "long" else "多单转空单"
    else:
        action = f"{side}{KINDS[kind]}"
    title = f"🐋 {event['coin'].removeprefix('xyz:')} {action}"
    lines = [title, *_execution_lines(event)]
    if kind == "closed":
        lines += [f"上次仓位：{_compact_money(event['previous_notional_usd'])}", "已实现盈亏：未提供"]
    else:
        label = "剩余仓位" if kind in {"increased", "reduced"} else "仓位"
        lines.append(f"{label}：{_compact_money(event['notional_usd'])}")
        entry = "未提供" if event["entry_price"] is None else f"${_plain_number(event['entry_price'])}"
        leverage = "杠杆未提供" if event["leverage"] is None else f"{_plain_number(event['leverage'])}x"
        mode = {"cross": "全仓", "isolated": "逐仓"}.get(event["leverage_type"], "")
        lines.append(f"开仓均价：{entry}｜{leverage}{' ' + mode if mode else ''}")
        pnl = event.get("unrealized_pnl")
        if pnl is None:
            lines.append("浮动盈亏：未提供")
        else:
            amount = decimal(pnl)
            sign = "+" if amount > 0 else "-" if amount < 0 else ""
            lines.append(f"浮动盈亏：{sign}${abs(amount):,.2f}")
    lines.append(f"地址：{event['address'][:8]}…{event['address'][-6:]}")
    stamp = datetime.fromtimestamp(event["snapshot_ms"] / 1000, timezone(timedelta(hours=8))).strftime("%m/%d %H:%M")
    lines.append(f"trade.xyz · {stamp} 北京时间")
    return title, "\n".join(lines)
