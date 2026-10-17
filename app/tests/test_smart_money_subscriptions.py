"""Isolated API/DB and synthetic provider: never contacts Binance or Telegram."""
from datetime import datetime, timedelta, timezone

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session

import api
from binance_smart_money import parse_overview, SmartMoneyUnavailable
from database import Base
from models import AlertSubscription, Asset, MarketQuote, Notification, User
from schemas import SmartMoneyConfig
from smart_money_models import SmartMoneyState, initialize_smart_money_tables
import smart_money_service as service
from smart_money_worker import tick
import subscription_service
from test_binance_smart_money import payload
from test_mobile_api import client
from test_subscriptions import member, worker


class Clock(datetime):
    moment = datetime.now(timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.moment.astimezone(tz) if tz else cls.moment.replace(tzinfo=None)


@pytest.fixture
def source(monkeypatch):
    Clock.moment = datetime.now(timezone.utc)
    monkeypatch.setattr(service, "datetime", Clock)
    data = {"calls": 0, "long": 65, "short": 166, "quantity": 100, "error": None,
            "source_ms": int(Clock.moment.timestamp()*1000) - 8*3600000}

    def get(symbol):
        data["calls"] += 1
        if isinstance(data["error"], Exception):
            raise data["error"]
        now = int(Clock.moment.timestamp()*1000)
        raw = payload(symbol, data["source_ms"])
        raw["data"].update(longWhales=data["long"], shortWhales=data["short"], longWhalesQty=data["quantity"])
        result = parse_overview(raw, symbol, now)
        if data["error"]:
            result["refresh_error"] = "Synthetic unavailable data"
        return result

    monkeypatch.setattr(service.client, "get", get)
    monkeypatch.setattr(subscription_service, "send_telegram_message", lambda *a, **k: pytest.fail("Unexpected Telegram"))
    return data


def subscribe(c, enabled=True, **config):
    response = c.put("/api/subscriptions", json={"asset_id": 2, "alert_type": "smart_money",
                                                "enabled": enabled, "config": config})
    assert response.status_code == 200, response.text
    return response.json()


def poll(c):
    response = c.post("/api/internal/smart-money/2/poll")
    assert response.status_code == 200, response.text
    return response.json()


def advance(seconds=600):
    Clock.moment += timedelta(seconds=seconds)


def records(c):
    return [row for row in c.get("/api/notifications").json() if row["category"] == "smart_money"]


@pytest.mark.parametrize("config", [
    {"min_whale_count_change": 0}, {"min_whale_count_change": 1.5},
    {"min_whale_quantity_change_pct": "NaN"}, {"min_whale_quantity_change_pct": 0},
    {"cooldown_seconds": 599}, {"cooldown_seconds": 86401}, {"unknown": 1},
    {"watch_whale_count": False, "watch_whale_quantity": False},
])
def test_invalid_settings_rejected(client, config):
    assert client.put("/api/subscriptions", json={"asset_id": 2, "alert_type": "smart_money", "config": config}).status_code == 422


def test_baseline_change_and_cache_are_durable_and_source_time_does_not_gate_them(client, monkeypatch, source):
    sub = subscribe(client, min_whale_count_change=2)
    sent = []
    monkeypatch.setattr(subscription_service, "send_telegram_message", lambda message, chat_id: sent.append((message, chat_id)) or True)
    worker(monkeypatch, client)
    assert poll(client)["results"][0]["status"] == "baseline"
    assert not records(client)
    advance()
    source["long"] = 62
    source["short"] = 169
    assert poll(client)["results"][0]["status"] == "sent"
    assert poll(client)["results"][0]["status"] == "cached"
    assert len(sent) == 1 and sent[0][1] == "private-test-target"
    assert "多头巨鲸：65 → 62（-3 人）" in sent[0][0]
    assert "空头巨鲸：166 → 169（+3 人）" in sent[0][0]
    assert "不是个人成交" in sent[0][0] and "源时间含义待核实" in sent[0][0]
    assert "刚开仓" not in sent[0][0] and "0x" not in sent[0][0]
    status = client.get("/api/subscriptions").json()[0]["monitoring"]
    assert status["status"] == "sent" and status["observed_at"]
    # A second DB session/request still sees the checkpoint and persistent cooldown.
    advance()
    source["long"] = 65
    assert poll(client)["results"][0]["status"] == "cooldown"
    assert len(records(client)) == 1
    # Arbitrary worker text cannot bypass the snapshot comparator.
    response = client.post(f"/api/internal/subscriptions/{sub['id']}/events", json={
        "event_key": "forged", "title": "fake", "message": "fake"})
    assert response.status_code == 422


def test_source_is_shared_but_thresholds_recipients_and_status_are_private(client, monkeypatch, source):
    own = subscribe(client, min_whale_count_change=50)
    other = member()
    theirs = subscribe(other, min_whale_count_change=2)
    worker(monkeypatch, client)
    assert len(poll(client)["results"]) == 2 and source["calls"] == 1
    advance()
    source["long"] += 3
    result = poll(client)["results"]
    assert [r["status"] for r in result] == ["below_threshold", "in_app"]
    assert source["calls"] == 2
    assert not records(client) and len(records(other)) == 1
    assert other.get("/api/subscriptions").json()[0]["id"] == theirs["id"]
    assert client.get("/api/subscriptions").json()[0]["id"] == own["id"]
    other.close()


def test_selected_percentage_zero_and_missing_are_not_fabricated(client, monkeypatch, source):
    subscribe(client, watch_whale_count=False, min_whale_quantity_change_pct=5)
    worker(monkeypatch, client)
    source["quantity"] = 0
    poll(client)
    advance()
    source["quantity"] = 100
    assert poll(client)["results"][0]["status"] == "below_threshold"  # No denominator.
    advance()
    source["quantity"] = None
    assert poll(client)["results"][0]["status"] == "below_threshold"
    advance()
    source["quantity"] = 110
    assert poll(client)["results"][0]["status"] == "below_threshold"  # Missing previous quantity.
    advance()
    source["quantity"] = 121
    with api.app.state.auth_session_factory() as db:
        db.get(User, 1).telegram_chat_id = None
        db.commit()
    monkeypatch.setattr(subscription_service, "CHAT_ID", None)
    assert poll(client)["results"][0]["status"] == "in_app"
    assert "110 → 121（+10.00%）" in records(client)[0]["message"]


def test_disable_reenable_and_config_change_rebaseline_without_side_effects(client, monkeypatch, source):
    sub = subscribe(client)
    worker(monkeypatch, client)
    poll(client)
    subscribe(client, enabled=False)
    assert poll(client)["status"] == "inactive"
    assert source["calls"] == 1
    subscribe(client, min_whale_count_change=1)
    advance()
    source["long"] += 10
    assert poll(client)["results"][0]["status"] == "baseline"
    assert not records(client)
    with api.app.state.auth_session_factory() as db:
        assert db.get(Asset, 2).enabled
        db.get(AlertSubscription, sub["id"]).config = {"broken": True}
        db.commit()
    assert client.get("/api/subscriptions").json()[0]["config_valid"] is False
    assert subscribe(client)["config_valid"] is True
    assert client.delete(f"/api/subscriptions/{sub['id']}").status_code == 200


def test_failure_preserves_previous_observation_and_gap_does_not_look_like_new_trade(client, monkeypatch, source):
    subscribe(client, min_whale_count_change=1)
    worker(monkeypatch, client)
    poll(client)
    advance()
    source["error"] = SmartMoneyUnavailable("rate_limited", 7200)
    assert poll(client)["status"] == "source_error"
    before = client.get("/api/subscriptions").json()[0]["monitoring"]["observed_at"]
    source["error"] = True  # A client fallback is still a failed source read.
    advance()
    assert poll(client)["status"] == "source_error"
    assert client.get("/api/subscriptions").json()[0]["monitoring"]["observed_at"] == before
    source["error"] = None
    advance(601)
    source["long"] += 20
    assert poll(client)["results"][0]["status"] == "gap_reset"
    assert not records(client)


def test_worker_routes_require_token_and_recheck_disabled_assets(client, monkeypatch, source):
    subscribe(client)
    monkeypatch.setenv("RADAR_WORKER_TOKEN", "test-worker-token")
    assert client.post("/api/internal/smart-money/2/poll").status_code == 403
    assert not source["calls"]
    worker(monkeypatch, client)
    with api.app.state.auth_session_factory() as db:
        db.get(Asset, 2).enabled = False
        db.commit()
    assert client.get("/api/internal/subscriptions?alert_type=smart_money").json() == []
    assert client.post("/api/internal/smart-money/2/poll").status_code == 404
    assert not source["calls"]
    anonymous = TestClient(api.app)
    assert anonymous.get("/api/subscriptions").status_code == 401
    anonymous.close()


def test_zero_counts_and_metric_or_semantics():
    before = {"sides": {"long": {"whales": 0, "whale_quantity": 100}}}
    after = {"sides": {"long": {"whales": 5, "whale_quantity": 101}}}
    result = service.changes(before, after, SmartMoneyConfig().model_dump())
    assert len(result) == 1 and result[0]["before"] == 0
    after["sides"]["long"]["whales"] = None
    after["sides"]["long"]["whale_quantity"] = float("nan")
    assert service.changes(before, after, SmartMoneyConfig().model_dump()) == []
    before["sides"]["long"]["whale_quantity"] = 1e-320
    after["sides"]["long"]["whale_quantity"] = 1e30
    assert service.changes(before, after, SmartMoneyConfig().model_dump()) == []


def test_scheduler_does_nothing_without_opt_in_and_visits_each_asset():
    visited = []
    def collect(asset):
        visited.append(asset)
        return {"status": "checked", "results": []}
    assert tick(load=lambda kind: [], poll=collect) == 0
    assert not visited
    load = lambda kind: [{"asset_id": 3}, {"asset_id": 2}, {"asset_id": 2}]
    cursor = 0
    for _ in range(3):
        cursor = tick(cursor, load=load, poll=collect)
    assert visited == [2, 3, 2]


def test_additive_upgrade_preserves_old_rules_and_state_deletion_cascades():
    engine = create_engine("sqlite://")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables
                                           if table.name != "smart_money_states"])
    with Session(engine) as db:
        user = User(username="existing")
        asset = Asset(symbol="BTCUSDT", name="Fixture", asset_type="crypto", venue="BINANCE",
                      segment="FUTURES", currency="USDT", provider="BINANCE_FUTURES")
        db.add_all([user, asset]); db.flush()
        sub = AlertSubscription(user_id=user.id, asset_id=asset.id, alert_type="whale_print", enabled=False)
        db.add(sub); db.commit()
        ident = sub.id
    assert not inspect(engine).has_table("smart_money_states")
    initialize_smart_money_tables(engine)
    initialize_smart_money_tables(engine)
    with Session(engine) as db:
        assert len(db.scalars(select(AlertSubscription)).all()) == 1
        assert db.get(AlertSubscription, ident).enabled is False
        assert not db.scalars(select(SmartMoneyState)).all()
        db.add(SmartMoneyState(subscription_id=ident, config_key="fixture")); db.commit()
        db.delete(db.get(AlertSubscription, ident)); db.commit()
        assert not db.scalars(select(SmartMoneyState)).all()
    engine.dispose()


def test_smart_money_creation_is_disabled_unless_explicitly_enabled(client):
    response = client.put("/api/subscriptions", json={"asset_id": 2, "alert_type": "smart_money"})
    assert response.status_code == 200 and response.json()["enabled"] is False


def test_cancellation_during_source_request_takes_effect_before_comparison(client, monkeypatch, source):
    subscribe(client, min_whale_count_change=1)
    worker(monkeypatch, client)
    poll(client)
    original = service.client.get
    def cancel_then_read(symbol):
        subscribe(client, enabled=False)
        return original(symbol)
    monkeypatch.setattr(service.client, "get", cancel_then_read)
    advance()
    source["long"] += 10
    assert poll(client)["results"] == []
    assert not records(client)
    assert client.get("/api/subscriptions").json()[0]["monitoring"]["status"] == "paused"


def test_failed_asset_does_not_starve_other_subscribed_assets():
    visited = []
    def collect(asset):
        visited.append(asset)
        if asset == 2:
            raise requests.ConnectionError("Synthetic API failure")
        return {"status": "checked", "results": []}
    load = lambda kind: [{"asset_id": 2}, {"asset_id": 3}]
    cursor = tick(load=load, poll=collect)
    tick(cursor, load=load, poll=collect)
    assert visited == [2, 3]


def test_notifications_include_entry_pnl_and_deltas_without_price_only_spam(client, monkeypatch, source):
    subscribe(client, min_whale_count_change=2)
    worker(monkeypatch, client)
    sent = []
    monkeypatch.setattr(subscription_service, "send_telegram_message", lambda message, chat_id: sent.append(message) or True)
    def update_quote(price):
        with api.app.state.auth_session_factory() as db:
            row = db.scalar(select(MarketQuote).where(MarketQuote.asset_id == 2))
            if row is None:
                row = MarketQuote(asset_id=2, price=price, event_time=Clock.moment)
                db.add(row)
            row.price, row.event_time = price, Clock.moment
            db.commit()
    update_quote(12)
    assert poll(client)["results"][0]["status"] == "baseline"
    advance()
    update_quote(13)
    source["long"] += 3
    source["quantity"] = 110
    assert poll(client)["results"][0]["status"] == "sent"
    assert len(sent) == 1
    assert "多头巨鲸开仓均价：$14｜浮盈亏：-$110.00" in sent[0]
    assert "空头巨鲸开仓均价：$19｜浮盈亏：+$900.00" in sent[0]
    assert "较上次采样：多头 +$90.00｜空头 -$150.00" in sent[0]
    assert "参考成交价：$13" in sent[0] and "不含费用" in sent[0]
    status = client.get("/api/subscriptions").json()[0]["monitoring"]
    assert status["pnl_comparison"]["sides"]["long"]["whales_usdt"] == 90
    # A new price alone updates the stored valuation but does not bypass cohort-change thresholds.
    advance()
    update_quote(14)
    assert poll(client)["results"][0]["status"] == "below_threshold"
    assert len(sent) == 1
    comparison = client.get("/api/subscriptions").json()[0]["monitoring"]["pnl_comparison"]
    assert comparison["sides"]["long"]["whales_usdt"] == 110
    assert poll(client)["results"][0]["status"] == "cached"
    assert client.get("/api/subscriptions").json()[0]["monitoring"]["pnl_comparison"] == comparison
