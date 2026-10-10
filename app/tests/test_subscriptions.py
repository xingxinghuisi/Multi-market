"""Subscription contracts: real isolated DB/API, mocked market data and Telegram."""
from datetime import datetime, timedelta, timezone
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session

import api
import crypto_metrics_worker as digest
import longshort_metrics
import subscription_service as service
import whale_print_worker as whale
from database import Base
from models import AlertSubscription, Asset, Notification, SubscriptionDelivery, User, WatchlistItem
from schemas import SubscriptionEvent
from test_mobile_api import client


def member():
    c = TestClient(api.app)
    registered = c.post("/api/auth/register", json={"username": "subscriber", "password": "long-member-password"})
    assert registered.status_code == 201
    c.headers.update({"X-CSRF-Token": registered.json()["csrf_token"]})
    return c


def subscribe(c, alert_type="whale_print", **config):
    response = c.put("/api/subscriptions", json={"asset_id": 2, "alert_type": alert_type, "config": config})
    assert response.status_code == 200, response.text
    return response.json()


def worker(monkeypatch, c):
    monkeypatch.setenv("RADAR_WORKER_TOKEN", "test-worker-token")
    c.headers.update({"X-Radar-Worker-Token": "test-worker-token"})
    return c


def emit(c, sub, key="whale:BTCUSDT:1", notional=100000):
    return c.post(f"/api/internal/subscriptions/{sub['id']}/events", json={
        "event_key": key, "title": "BTCUSDT 大额成交", "message": "test fixture only", "notional_usd": notional})


def test_subscriptions_are_private_upsertable_and_independent_of_collection(client):
    first = subscribe(client, whale_min_usd=8000, cooldown_seconds=60)
    second = member()
    own = subscribe(second, whale_min_usd=1000000, cooldown_seconds=900)
    assert first["id"] != own["id"]
    assert len(client.get("/api/subscriptions").json()) == 1
    assert second.delete(f"/api/subscriptions/{first['id']}").status_code == 404
    assert subscribe(client, whale_min_usd=9000)["id"] == first["id"]
    with api.app.state.auth_session_factory() as db:
        assert db.get(Asset, 2).enabled is True
    assert client.get("/api/watchlist").json() == []
    assert client.delete(f"/api/subscriptions/{first['id']}").status_code == 200
    assert second.get("/api/subscriptions").json()[0]["id"] == own["id"]
    assert client.get("/api/assets/2").status_code == 200


@pytest.mark.parametrize("config", [
    {"whale_min_usd": 0}, {"whale_min_usd": -1}, {"whale_min_usd": "NaN"},
    {"whale_min_usd": "Infinity"}, {"cooldown_seconds": -1},
    {"cooldown_seconds": 1.5}, {"cooldown_seconds": 86401}, {"unknown": 1},
])
def test_invalid_subscription_config_is_rejected(client, config):
    assert client.put("/api/subscriptions", json={
        "asset_id": 2, "alert_type": "whale_print", "config": config}).status_code == 422


def test_unsupported_assets_types_and_worker_access_are_rejected(client, monkeypatch):
    assert client.put("/api/subscriptions", json={
        "asset_id": 1, "alert_type": "whale_print"}).status_code == 400
    assert client.put("/api/subscriptions", json={
        "asset_id": 2, "alert_type": "price_step"}).status_code == 422
    assert client.put("/api/subscriptions", json={
        "asset_id": 2, "alert_type": "longshort_digest", "config": {"whale_min_usd": 1}}).status_code == 422
    sub = subscribe(client)
    monkeypatch.setenv("RADAR_WORKER_TOKEN", "test-worker-token")
    assert client.get("/api/internal/subscriptions?alert_type=whale_print").status_code == 403
    assert emit(client, sub).status_code == 403
    assert TestClient(api.app).get("/api/subscriptions").status_code == 401
    rows = worker(monkeypatch, client).get("/api/internal/subscriptions?alert_type=whale_print").json()
    assert rows[0]["subscription_id"] == sub["id"]
    assert "telegram_chat_id" not in rows[0]


def test_same_symbol_delivers_to_each_person_and_records_history(client, monkeypatch):
    first = subscribe(client, whale_min_usd=8000)
    second_client = member()
    second = subscribe(second_client, whale_min_usd=9000)
    with api.app.state.auth_session_factory() as db:
        account = db.scalar(select(User).where(User.username == "subscriber"))
        account.telegram_chat_id = "second-private-target"
        db.commit()
    sent = []
    monkeypatch.setattr(service, "send_telegram_message", lambda text, chat_id: sent.append(chat_id) or True)
    worker(monkeypatch, client)
    for sub in (first, second):
        assert emit(client, sub).json()["status"] == "sent"
        assert emit(client, sub).json()["duplicate"] is True
    assert sent == ["private-test-target", "second-private-target"]
    for c in (client, second_client):
        records = [n for n in c.get("/api/notifications").json() if n["category"] == "whale_print"]
        assert len(records) == 1 and records[0]["status"] == "sent"


def test_unbound_user_never_falls_back_to_legacy_chat(client, monkeypatch):
    c = member()
    sub = subscribe(c)
    monkeypatch.setattr(service, "CHAT_ID", "legacy-owner")
    monkeypatch.setattr(service, "send_telegram_message", lambda *a, **kw: pytest.fail("Must not send Telegram"))
    worker(monkeypatch, client)
    assert emit(client, sub).json()["status"] == "in_app"
    assert c.get("/api/notifications").json()[0]["channel"] == "in_app"


def test_rechecks_threshold_disable_and_persistent_cooldown(client, monkeypatch):
    sub = subscribe(client, whale_min_usd=50000, cooldown_seconds=600)
    sent = []
    monkeypatch.setattr(service, "send_telegram_message", lambda text, chat_id: sent.append(text) or True)
    worker(monkeypatch, client)
    assert emit(client, sub, notional=10000).json()["status"] == "below_threshold"
    assert emit(client, sub).json()["status"] == "sent"
    assert emit(client, sub, key="whale:BTCUSDT:2").json()["status"] == "cooldown"
    client.put("/api/subscriptions", json={"asset_id": 2, "alert_type": "whale_print", "enabled": False})
    assert emit(client, sub, key="whale:BTCUSDT:3").json()["status"] == "inactive"
    assert len(sent) == 1
    assert client.put("/api/client-assets/2/hidden").status_code == 200
    assert client.get("/api/subscriptions").json()[0]["enabled"] is False


def test_failed_send_can_retry_same_event_without_duplicate_history(client, monkeypatch):
    sub = subscribe(client, cooldown_seconds=300)
    attempts = iter([False, True])
    monkeypatch.setattr(service, "send_telegram_message", lambda text, chat_id: next(attempts))
    worker(monkeypatch, client)
    assert emit(client, sub).json()["status"] == "failed"
    with api.app.state.auth_session_factory() as db:
        notification = db.scalar(select(Notification).where(Notification.category == "whale_print"))
        notification.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    assert emit(client, sub).json()["status"] == "sent"
    assert emit(client, sub).json()["duplicate"] is True
    assert emit(client, sub, key="whale:BTCUSDT:2").json()["status"] == "cooldown"
    assert len([n for n in client.get("/api/notifications").json() if n["category"] == "whale_print"]) == 1
    assert client.delete(f"/api/subscriptions/{sub['id']}").status_code == 200
    # A deleted subscription must leave its notification history visible.
    assert any(n["category"] == "whale_print" for n in client.get("/api/notifications").json())


def test_legacy_invalid_config_remains_editable_and_is_not_collected(client, monkeypatch):
    sub = subscribe(client)
    with api.app.state.auth_session_factory() as db:
        db.get(AlertSubscription, sub["id"]).config = {"whale_min_usd": "NaN"}
        db.commit()
    assert client.get("/api/subscriptions").json()[0]["config_valid"] is False
    worker(monkeypatch, client)
    assert client.get("/api/internal/subscriptions?alert_type=whale_print").json() == []
    assert subscribe(client, whale_min_usd=8000)["config_valid"] is True


def test_additive_upgrade_preserves_legacy_digest_and_never_reenables_it():
    engine = create_engine("sqlite://")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    old_tables = [t for t in Base.metadata.sorted_tables if t.name not in {"alert_subscriptions", "subscription_deliveries"}]
    Base.metadata.create_all(engine, tables=old_tables)
    with Session(engine) as db:
        user = User(username="default")
        asset = Asset(symbol="BTCUSDT", name="Fixture", asset_type="crypto", venue="BINANCE",
                      segment="FUTURES", currency="USDT", provider="BINANCE")
        db.add_all([user, asset])
        db.flush()
        db.add(WatchlistItem(user_id=user.id, asset_id=asset.id))
        db.commit()
    service.initialize_subscription_tables(engine)
    with Session(engine) as db:
        sub = db.scalar(select(AlertSubscription))
        assert sub.alert_type == "longshort_digest"
        sub.enabled = False
        db.add(Notification(user_id=1, asset_id=1, category="longshort_digest",
                            title="history", message="fixture", channel="in_app", status="in_app"))
        db.flush()
        db.add(SubscriptionDelivery(subscription_id=sub.id, notification_id=1, event_key="digest:1"))
        db.commit()
    service.initialize_subscription_tables(engine)
    with Session(engine) as db:
        assert db.scalar(select(AlertSubscription)).enabled is False
        assert len(db.scalars(select(Asset)).all()) == 1
        db.delete(db.scalar(select(AlertSubscription)))
        db.commit()
        assert db.scalar(select(SubscriptionDelivery)) is None
        assert db.get(Notification, 1).title == "history"
    assert "subscription_deliveries" in inspect(engine).get_table_names()
    engine.dispose()


def subscriptions():
    return [
        {"subscription_id": 1, "symbol": "BTCUSDT", "config": {"whale_min_usd": 8000, "cooldown_seconds": 300}},
        {"subscription_id": 2, "symbol": "BTCUSDT", "config": {"whale_min_usd": 1000000, "cooldown_seconds": 60}},
    ]


def test_whale_fans_out_thresholds_cooldowns_and_survives_reconnect(monkeypatch):
    monkeypatch.setattr(whale, "load_rows", lambda kind: subscriptions())
    grouped = whale.load_subscriptions()
    assert len(grouped["BTCUSDT"]) == 2
    now = [100.0]
    monkeypatch.setattr(whale.time, "monotonic", lambda: now[0])
    deliveries = []
    monkeypatch.setattr(whale, "submit_event", lambda sub_id, *a, **kw: deliveries.append(sub_id) or {"status": "sent"})
    watcher = whale.WhaleWatcher(grouped)
    def trade(trade_id, qty):
        watcher.handle_trade({"e": "aggTrade", "s": "BTCUSDT", "a": trade_id,
                              "T": 1700000000000, "p": "10000", "q": str(qty), "m": False})
    trade(1, 1)
    assert deliveries == [1]
    now[0] += 1
    trade(2, 200)
    assert deliveries == [1, 2]
    watcher.replace_subscriptions(grouped)
    watcher.reset_flow()
    trade(3, 200)
    assert deliveries == [1, 2]  # Reconnect must preserve per-user cooldown.
    now[0] += 61
    trade(4, 200)
    assert deliveries == [1, 2, 2]
    trade(4, 200)
    assert deliveries == [1, 2, 2]  # Same aggregate trade cannot replay.
    watcher.handle_trade({"e": "aggTrade", "s": "BTCUSDT", "a": 5, "T": 1, "p": "NaN", "q": "1"})
    assert deliveries == [1, 2, 2]


def test_whale_failed_send_does_not_consume_user_cooldown(monkeypatch):
    watcher = whale.WhaleWatcher({"BTCUSDT": subscriptions()[:1]})
    now = [100.0]
    monkeypatch.setattr(whale.time, "monotonic", lambda: now[0])
    statuses = iter(["failed", "sent"])
    monkeypatch.setattr(whale, "submit_event", lambda *a, **kw: {"status": next(statuses)})
    for trade_id in [1, 2]:
        watcher.handle_trade({"e": "aggTrade", "s": "BTCUSDT", "a": trade_id, "T": 1, "p": "10000", "q": "1"})
        now[0] += 6
    assert 1 in watcher.last_alert_at


def test_whale_refreshes_subscriptions_without_trades(monkeypatch):
    watcher = whale.WhaleWatcher({"BTCUSDT": subscriptions()[:1]})
    monkeypatch.setattr(whale, "SUB_REFRESH_SECONDS", .01)
    monkeypatch.setattr(whale, "load_subscriptions", lambda: {})
    class Socket:
        async def recv(self):
            await asyncio.sleep(10)
    class Connection:
        async def __aenter__(self): return Socket()
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(whale.websockets, "connect", lambda *a, **kw: Connection())
    asyncio.run(asyncio.wait_for(whale.watch_streams(watcher), timeout=1))
    assert watcher.subscriptions == {}


def test_digest_fetches_once_and_fans_out_with_stable_hour_key(monkeypatch):
    monkeypatch.setattr(digest, "load_watched_contract_assets", subscriptions)
    fetched, sent = [], []
    end = datetime(2026, 10, 11, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(digest, "fetch_metrics", lambda symbol: fetched.append(symbol) or {"hour_end": end})
    monkeypatch.setattr(digest, "build_message", lambda *args: "1H fixture")
    monkeypatch.setattr(digest, "submit_event", lambda *args: sent.append(args) or {"status": "in_app"})
    digest.run_once()
    assert fetched == ["BTCUSDT"]
    assert [args[0] for args in sent] == [1, 2]
    assert sent[0][1] == sent[1][1] == f"digest:BTCUSDT:{end.isoformat()}"


def test_longshort_detail_uses_real_completed_values_and_handles_outage(client, monkeypatch):
    longshort_metrics._cache.clear()
    targets = digest.build_hour_targets()
    def read_json(url):
        taker = "takerlongshortRatio" in url
        times = [targets["hour_start"], targets["previous_start"]] if taker else [targets["hour_end"], targets["hour_start"]]
        return [{"timestamp": int(stamp.timestamp()*1000), "longShortRatio": "1.23",
                 "buySellRatio": "0.98", "longAccount": "0.55", "shortAccount": "0.45"} for stamp in times]
    monkeypatch.setattr(api, "_binance_read_json", read_json)
    data = client.get("/api/assets/2/longshort-metrics").json()
    assert data["ratios"]["global"]["current"] == 1.23
    assert data["ratios"]["taker"]["previous"] == .98
    assert data["long_account_pct"] == pytest.approx(55)
    assert client.get("/api/assets/1/longshort-metrics").status_code == 404
    longshort_metrics._cache.clear()
    monkeypatch.setattr(api, "_binance_read_json", lambda url: [])
    assert client.get("/api/assets/2/longshort-metrics").status_code == 503
    longshort_metrics._cache.clear()
