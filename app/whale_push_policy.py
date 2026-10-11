"""Personal, per-market notification filters and conservative same-direction merging."""
from copy import deepcopy
from decimal import Decimal, localcontext

from sqlalchemy import select

from hyperliquid_whales import decimal
from whale_models import WhaleAdjustmentBatch, WhaleEventDecision, WhalePushPolicy

DEFAULT_POLICY = {"min_change_usd": 5000, "min_change_pct": .5,
                  "aggregation_seconds": 300, "priority_events": True}
ADJUSTMENTS = {"increased", "reduced"}
PRIORITY = {"opened", "closed", "flipped"}


def policy_for(db, sub):
    row = db.get(WhalePushPolicy, sub.id)
    return {**DEFAULT_POLICY, **(row.data if row else {})}


def adjustment_metrics(payload):
    with localcontext() as ctx:
        ctx.prec = 80
        old, new = abs(decimal(payload["previous_qty"])), abs(decimal(payload["qty"]))
        delta = abs(new - old)
        execution = payload.get("execution") or {}
        if execution.get("status") == "verified" and execution.get("price") is not None:
            price, basis = decimal(execution["price"]), "fills"
        else:
            price, basis = decimal(payload["notional_usd"]) / new, "snapshot_estimate"
        return {"usd": delta * price, "pct": delta / old * 100, "basis": basis}


def adjustment_passes(payload, policy):
    metrics = adjustment_metrics(payload)
    return (metrics["usd"] >= decimal(policy["min_change_usd"])
            and metrics["pct"] >= decimal(policy["min_change_pct"]))


def can_merge(previous, current):
    return (previous["kind"] == current["kind"] and previous["side"] == current["side"]
            and decimal(previous["qty"]) == decimal(current["previous_qty"])
            and isinstance(current.get("previous_snapshot_ms"), int)
            and current["previous_snapshot_ms"] >= previous["snapshot_ms"])


def merged_payload(previous, current):
    """Only consecutive same-direction changes; unknown execution stays unknown."""
    with localcontext() as ctx:
        ctx.prec = 80
        result = deepcopy(current)
        result.update(previous_qty=previous["previous_qty"],
                      previous_snapshot_ms=previous["previous_snapshot_ms"],
                      previous_notional_usd=previous["previous_notional_usd"],
                      qualifying_usd=str(max(decimal(previous["qualifying_usd"]), decimal(current["qualifying_usd"]))),
                      delta_qty=str(decimal(current["qty"]) - decimal(previous["previous_qty"])))
        count = (previous.get("aggregation") or {}).get("event_count", 1) + 1
        start = ((previous.get("aggregation") or {}).get("from_ms")
                 or result["previous_snapshot_ms"] or previous["snapshot_ms"])
        result["aggregation"] = {"event_count": count, "from_ms": start,
                                 "to_ms": current["snapshot_ms"]}
        old_exec, new_exec = previous.get("execution") or {}, current.get("execution") or {}
        if all(e.get("status") == "verified" and e.get("price") is not None for e in [old_exec, new_exec]):
            a = abs(decimal(previous["qty"]) - decimal(previous["previous_qty"]))
            b = abs(decimal(current["qty"]) - decimal(current["previous_qty"]))
            result["execution"] = {"status": "verified", "basis": "fills_vwap",
                "price": str((a * decimal(old_exec["price"]) + b * decimal(new_exec["price"])) / (a + b)),
                "fill_count": old_exec["fill_count"] + new_exec["fill_count"],
                "start_ms": old_exec["start_ms"], "end_ms": new_exec["end_ms"]}
        else:
            result["execution"] = {"status": "unavailable", "reason": "incomplete_aggregation_fills"}
        return result


def discard_batch(db, batch, outcome):
    for key in batch.data["event_keys"]:
        decision = db.get(WhaleEventDecision, (batch.data["user_id"], key))
        if decision and decision.outcome == "buffering":
            decision.outcome = outcome
    db.delete(batch)


def clear_pending_for_sub(db, sub_id, outcome="settings_changed"):
    for batch in db.scalars(select(WhaleAdjustmentBatch).where(WhaleAdjustmentBatch.subscription_id == sub_id)).all():
        discard_batch(db, batch, outcome)
