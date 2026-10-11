"""Stable public market/account identities; never merge venues by ticker or wallet."""
import re

from hyperliquid_whales import MARKET_PATTERN, SOURCE, address_value

LIGHTER_SOURCE = "Lighter 主网"
SUBSCRIPTION_PATTERN = MARKET_PATTERN[:-1] + r"$|^lighter:mainnet:(?:0|[1-9][0-9]{0,4})$"


def venue_for(coin):
    return "lighter" if coin.startswith("lighter:mainnet:") else "trade_xyz"


def runtime_id(venue):
    return 2 if venue == "lighter" else 1


def account_index(value):
    if not isinstance(value, str) or not re.fullmatch(r"lighter:mainnet:(?:0|[1-9][0-9]{0,14})", value):
        raise ValueError("Invalid Lighter account identity")
    index = int(value.rsplit(":", 1)[1])
    if index >= 2 ** 48:
        raise ValueError("Account index out of range")
    return index


def candidate_value(value, venue):
    if venue == "trade_xyz":
        return address_value(value)
    try:
        account_index(value)
        return value
    except ValueError:
        return None


def account_scope(column, venue):
    return column.like("lighter:mainnet:%") if venue == "lighter" else column.like("0x%")


def market_identity(coin, catalog=None):
    market = next((m for m in (catalog or []) if m.get("coin") == coin), {})
    lighter = venue_for(coin) == "lighter"
    return {"venue": "lighter" if lighter else "trade_xyz",
            "source": LIGHTER_SOURCE if lighter else SOURCE,
            "symbol": market.get("symbol") or (coin if lighter else coin.removeprefix("xyz:"))}
