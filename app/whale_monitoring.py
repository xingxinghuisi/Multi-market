"""Coverage of the retained candidate pool, with personal notification outcomes."""
from sqlalchemy import func, select

from hyperliquid_whales import decimal
from whale_models import WhaleEventDecision, WhaleMarketAddress


def market_monitoring(db, user_id, subscriptions, addresses, now):
    coins = {s.coin for s in subscriptions}
    known = {coin: set() for coin in coins}
    for coin, address in db.execute(select(WhaleMarketAddress.coin, WhaleMarketAddress.address)
                                   .where(WhaleMarketAddress.coin.in_(coins))):
        known[coin].add(address)
    # Existing snapshots provide real evidence of old holdings after an upgrade.
    # Never infer that every wallet in the shared pool traded every market.
    for row in addresses:
        for coin, position in row.positions.items():
            if coin in coins and decimal(position["qty"]) != 0:
                known[coin].add(row.address)
    by_address = {row.address: row for row in addresses}
    outcomes = {coin: {} for coin in coins}
    for coin, outcome, count in db.execute(select(WhaleEventDecision.coin, WhaleEventDecision.outcome,
            func.count()).where(WhaleEventDecision.user_id == user_id,
            WhaleEventDecision.coin.in_(coins), WhaleEventDecision.observed_ms >= now - 86400000)
            .group_by(WhaleEventDecision.coin, WhaleEventDecision.outcome)):
        outcomes[coin][outcome] = count
    result = []
    for sub in subscriptions:
        verified, eligible, stale, last_verified = 0, 0, 0, 0
        for address in known[sub.coin]:
            row = by_address.get(address)
            p = row.positions.get(sub.coin) if row else None
            if not p or not row.checked_ms:
                continue
            verified += 1
            last_verified = max(last_verified, row.checked_ms)
            if decimal(p["qty"]) != 0 and decimal(p["notional_usd"]) >= decimal(sub.min_position_usd):
                eligible += 1
                stale += now - p.get("snapshot_ms", row.snapshot_ms) > 180000
        result.append({"coin": sub.coin, "known_addresses": len(known[sub.coin]),
            "verified_addresses": verified, "pending_addresses": len(known[sub.coin]) - verified,
            "eligible_positions": eligible, "stale_positions": stale,
            "last_verified_ms": last_verified, "outcomes_24h": outcomes[sub.coin]})
    return result
