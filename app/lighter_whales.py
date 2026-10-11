"""Public Lighter mainnet data. No signing, private credentials or trading APIs."""
import os
import time
from decimal import Decimal

import requests

from hyperliquid_whales import PublicAPIError, address_value, decimal, milliseconds
from whale_sources import LIGHTER_SOURCE, account_index

API_URL = "https://mainnet.zklighter.elliot.ai/api/v1/"
WS_URL = "wss://mainnet.zklighter.elliot.ai/stream?readonly=true"


def integer(value, maximum=2 ** 48 - 1):
    if not isinstance(value, (int, str)) or isinstance(value, bool) or str(value) != str(int(value)) or not 0 <= int(value) <= maximum:
        raise ValueError("Invalid public identifier")
    return int(value)


def market_key(value):
    return f"lighter:mainnet:{integer(value, 99999)}"


def parse_markets(raw):
    if not isinstance(raw, dict) or raw.get("code") != 200 or not isinstance(raw.get("order_book_details"), list):
        raise ValueError("Invalid Lighter catalog")
    markets = {}
    for item in raw["order_book_details"]:
        if not isinstance(item, dict) or item.get("market_type") != "perp" or item.get("status") != "active":
            continue
        config = item.get("market_config") or {}
        if config.get("hidden"):
            continue
        coin = market_key(item.get("market_id"))
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not symbol or len(symbol) > 80 or coin in markets:
            raise ValueError("Invalid or duplicate market")
        markets[coin] = {"coin": coin, "symbol": symbol, "name": f"{symbol} 永续合约",
                         "venue": "lighter", "source": LIGHTER_SOURCE,
                         "reduce_only": bool(config.get("force_reduce_only")),
                         "frozen": bool(item.get("is_frozen")),
                         "volume_24h_usd": str(decimal(item.get("daily_quote_token_volume", 0)))}
    return sorted(markets.values(), key=lambda m: m["symbol"])


def normalize_trade(trade):
    """Only public counterparties. Trade time is ms; transaction_time is microseconds."""
    if trade.get("market_kind", "perps") != "perps":
        raise ValueError("Not a perpetual trade")
    coin = market_key(trade["market_id"])
    stamp = integer(trade["timestamp"], 10 ** 14)
    if not 0 < stamp <= milliseconds() + 60000 or decimal(trade["size"]) <= 0 or decimal(trade["price"]) <= 0:
        raise ValueError("Invalid public trade")
    ask, bid = integer(trade["ask_account_id"]), integer(trade["bid_account_id"])
    return {"coin": coin, "time": stamp, "px": trade["price"], "sz": trade["size"],
            "users": [f"lighter:mainnet:{ask}", f"lighter:mainnet:{bid}"]}


def stream_trades(packet, subscribed):
    if not isinstance(packet, dict):
        raise ValueError("Invalid public stream packet")
    result = []
    for field in ("trades", "liquidation_trades"):
        trades = packet.get(field) or []
        if not isinstance(trades, list):
            raise ValueError("Invalid public trade list")
        for trade in trades:
            try:
                normalized = normalize_trade(trade)
                if normalized["coin"] in subscribed:
                    result.append(normalized)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
    return result


def parse_account(raw, key, markets, stamp):
    """Only a complete successful response can establish an absent/closed position."""
    index = account_index(key)
    if (not isinstance(raw, dict) or raw.get("code") != 200 or raw.get("total") != 1
            or raw.get("next_cursor") or not isinstance(raw.get("accounts"), list) or len(raw["accounts"]) != 1):
        raise ValueError("Incomplete Lighter account")
    account = raw["accounts"][0]
    if (not isinstance(account, dict) or account.get("code", 0) != 0 or integer(account.get("account_index")) != index
            or not isinstance(account.get("positions"), list)):
        raise ValueError("Invalid Lighter account positions")
    wallet = address_value(account.get("l1_address"))
    metadata = {"source": LIGHTER_SOURCE, "venue": "lighter", "wallet_address": wallet,
                "account_index": index, "snapshot_basis": "observed_at"}
    result = {coin: {**metadata, "symbol": markets[coin]["symbol"], "qty": "0", "notional_usd": "0",
                     "entry_price": None, "unrealized_pnl": None, "leverage": None,
                     "leverage_type": None, "snapshot_ms": stamp} for coin in markets}
    seen = set()
    for p in account["positions"]:
        if not isinstance(p, dict):
            raise ValueError("Invalid account position")
        coin = market_key(p.get("market_id"))
        if coin not in result:
            continue
        if coin in seen or p.get("symbol") != markets[coin]["symbol"]:
            raise ValueError("Duplicate or mismatched position")
        seen.add(coin)
        qty, value = decimal(p.get("position")), abs(decimal(p.get("position_value")))
        if qty < 0 or qty > Decimal("1e30") or value > Decimal("1e18") or (qty == 0) != (value == 0):
            raise ValueError("Invalid Lighter position value")
        sign = p.get("sign")
        if qty and (isinstance(sign, bool) or sign not in (-1, 1)):
            raise ValueError("Invalid position direction")
        entry = decimal(p.get("avg_entry_price")) if qty else None
        if entry is not None and entry <= 0:
            raise ValueError("Invalid entry price")
        try:
            pnl = decimal(p.get("unrealized_pnl"))
            pnl = str(pnl) if qty and abs(pnl) <= Decimal("1e18") else None
        except ValueError:
            pnl = None
        # REST account field is percent ("5.00" => 20x), NOT catalog basis points.
        try:
            margin_pct = decimal(p.get("initial_margin_fraction"))
            leverage = str(100 / margin_pct) if 0 < margin_pct <= 100 else None
        except ValueError:
            leverage = None
        result[coin].update(qty=str(qty * sign) if qty else "0", notional_usd=str(value),
                            entry_price=str(entry) if entry is not None else None,
                            unrealized_pnl=pnl, leverage=leverage if qty else None,
                            leverage_type={0: "cross", 1: "isolated"}.get(p.get("margin_mode")),
                            leverage_basis="initial_margin_fraction")
    return stamp, result


def execution_fill(trade, key):
    normalized = normalize_trade(trade)
    index = account_index(key)
    ask, bid = integer(trade["ask_account_id"]), integer(trade["bid_account_id"])
    if (index == ask) == (index == bid) or not isinstance(trade.get("is_maker_ask"), bool):
        raise ValueError("Mismatched execution account")
    is_ask = index == ask
    maker = is_ask == trade["is_maker_ask"]
    before = decimal(trade["maker_position_size_before" if maker else "taker_position_size_before"])
    return {"coin": normalized["coin"], "time": normalized["time"],
            "tid": integer(trade["trade_id"], 2 ** 63 - 1), "px": normalized["px"], "sz": normalized["sz"],
            "side": "A" if is_ask else "B", "startPosition": str(before)}


class LighterClient:
    def __init__(self):
        self.session = requests.Session()
        self.proxies = {"https": os.environ["LIGHTER_PROXY"]} if os.getenv("LIGHTER_PROXY") else None
        self.next_request_at = 0
        self.catalog = {}

    def get(self, endpoint, **params):
        # Standard public REST limit is 60/min, shared by all these requests.
        delay = max(0, self.next_request_at - time.monotonic())
        if delay > 2:
            # Keep heartbeats alive during a long upstream cooldown.
            raise PublicAPIError(429, min(300, max(1, int(delay) + 1)), source="Lighter cooldown")
        time.sleep(delay)
        self.next_request_at = time.monotonic() + 1.2
        response = self.session.get(API_URL + endpoint, params=params, proxies=self.proxies,
                                    headers={"Cache-Control": "no-cache"}, timeout=(5, 12))
        if response.status_code != 200:
            retry = response.headers.get("Retry-After", "60")
            retry = min(300, max(10, int(retry))) if retry.isdigit() else 60
            if response.status_code in (405, 429) or response.status_code >= 500:
                self.next_request_at = max(self.next_request_at, time.monotonic() + retry)
            raise PublicAPIError(response.status_code, retry, source="Lighter")
        raw = response.json()
        if not isinstance(raw, dict) or raw.get("code") != 200:
            raise ValueError("Invalid Lighter response")
        return raw

    def markets(self):
        markets = parse_markets(self.get("orderBookDetails"))
        self.catalog = {m["coin"]: m for m in markets}
        return markets

    def snapshot(self, key, floors):
        raw = self.get("account", by="index", value=account_index(key))
        stamp = milliseconds()  # Observation time, not the account's last transaction.
        return parse_account(raw, key, {coin: self.catalog[coin] for coin in floors}, stamp)

    def fills(self, key, start_ms, end_ms):
        # Public account history is bounded and unauthenticated. Fail closed on
        # denied access, malformed data, pagination caps, or missing position chain.
        cursor, seen, result, last_time = None, set(), [], 10 ** 14
        for _ in range(3):
            params = {"account_index": account_index(key), "limit": 100,
                      "sort_by": "timestamp", "sort_dir": "desc"}
            if cursor:
                params["cursor"] = cursor
            raw = self.get("trades", **params)
            trades = raw.get("trades")
            if not isinstance(trades, list):
                raise ValueError("Incomplete execution history")
            oldest = end_ms + 1
            for trade in trades:
                fill = execution_fill(trade, key)
                if fill["time"] > last_time:
                    raise ValueError("Unsorted execution history")
                last_time = fill["time"]
                oldest = min(oldest, fill["time"])
                if start_ms <= fill["time"] <= end_ms:
                    result.append(fill)
            next_cursor = raw.get("next_cursor")
            if oldest < start_ms or not next_cursor:
                return result
            if not trades or next_cursor in seen:
                raise ValueError("Incomplete execution pagination")
            seen.add(next_cursor)
            cursor = next_cursor
        raise ValueError("Execution history exceeds safe page limit")
