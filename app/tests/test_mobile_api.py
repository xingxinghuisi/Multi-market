"""Real API contract tests with an isolated in-memory database; no providers/workers."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api
import crypto_metrics
from deployment_preflight import validate_environment
from auth_api import password_hash
from database import Base
from models import AlertRule, Asset, NewsImpact, NewsItem, Notification, User, UserCredential, WatchlistItem


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        user = User(username="default", telegram_chat_id="private-test-target")
        other = User(username="other")
        db.add_all([user, other])
        db.flush()
        db.add_all([
            Asset(symbol="BTCUSDT", name="Test Spot", asset_type="crypto", venue="BINANCE", segment="SPOT", currency="USDT", provider="BINANCE"),
            Asset(symbol="BTCUSDT", name="Test Futures", asset_type="crypto", venue="BINANCE", segment="FUTURES", currency="USDT", provider="BINANCE_FUTURES"),
            Notification(user_id=user.id, category="price", title="Visible", message="test", channel="telegram", status="sent"),
            Notification(user_id=other.id, category="price", title="Private", message="hidden", channel="telegram", status="sent"),
        ])
        db.flush()
        db.add(AlertRule(user_id=other.id, asset_id=1, metric="price", operator="crossing_up", value=100))
        db.add(UserCredential(user_id=user.id, password_hash=password_hash("a-long-test-password")))
        db.commit()

    def get_db():
        with sessions() as db:
            yield db

    api.app.dependency_overrides[api.get_db] = get_db
    api.app.state.auth_session_factory = sessions
    api.app.state.auth_insecure_local_cookie = True
    # No lifespan: never start the production market broadcaster in a unit test.
    test_client = TestClient(api.app)
    login = test_client.post("/api/auth/login", json={"username": "default", "password": "a-long-test-password"})
    assert login.status_code == 200
    test_client.headers.update({"X-CSRF-Token": login.json()["csrf_token"]})
    yield test_client
    api.app.dependency_overrides.clear()
    del api.app.state.auth_session_factory
    del api.app.state.auth_insecure_local_cookie
    engine.dispose()


def test_profile_reports_capabilities_without_contact_details(client):
    response = client.get("/api/client-profile")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "account"
    assert body["telegram_configured"] is True
    assert body["telegram_mode"] == "personal"
    assert body["capabilities"]["authentication"] is True
    assert body["capabilities"]["crypto_metrics"] is True
    assert "private-test-target" not in response.text


def test_catalog_delete_is_private_and_preserves_shared_market_data(client):
    from fastapi.testclient import TestClient

    asset_id = client.get("/api/assets").json()[0]["id"]
    assert client.post("/api/watchlist", json={"asset_id": asset_id}).status_code == 200
    rule = client.post("/api/alert-rules", json={
        "asset_id": asset_id, "metric": "price", "operator": "crossing_up", "value": 100,
    }).json()
    response = client.put(f"/api/client-assets/{asset_id}/hidden")
    assert response.status_code == 200
    assert client.get("/api/client-assets/hidden").json() == [asset_id]
    assert client.get("/api/watchlist").json() == []
    assert client.get(f'/api/alert-rules/{rule["id"]}').json()["enabled"] is False
    assert len(client.get("/api/assets").json()) == 2

    second = TestClient(api.app)
    registered = second.post("/api/auth/register", json={
        "username": "catalog_other", "password": "another-long-password",
    })
    assert registered.status_code == 201
    assert second.get("/api/client-assets/hidden").json() == []
    assert second.get("/api/assets").json()[0]["id"] == asset_id
    assert client.delete(f"/api/client-assets/{asset_id}/hidden").status_code == 200
    assert client.get("/api/client-assets/hidden").json() == []
    assert client.get(f'/api/alert-rules/{rule["id"]}').json()["enabled"] is False


def test_telegram_binding_requires_a_code_sent_to_the_target(client, monkeypatch):
    import mobile_api

    sent = []
    monkeypatch.setattr(mobile_api, "BOT_TOKEN", "test-bot-token")
    monkeypatch.setattr(mobile_api, "send_telegram_message", lambda message, chat_id: sent.append((message, chat_id)) or True)
    original = client.get("/api/client-profile").json()
    assert original["telegram_mode"] == "personal"
    assert client.post("/api/client-profile/telegram/challenge", json={"chat_id": "not-a-chat"}).status_code == 400
    response = client.post("/api/client-profile/telegram/challenge", json={"chat_id": "123456789"})
    assert response.status_code == 200
    assert sent[0][1] == "123456789"
    code = sent[0][0].split("：", 1)[1].split("。", 1)[0]
    assert client.post("/api/client-profile/telegram/challenge", json={"chat_id": "999999999"}).status_code == 429
    assert client.post("/api/client-profile/telegram/confirm", json={"code": "00000000"}).status_code == 400
    assert client.post("/api/client-profile/telegram/confirm", json={"code": code}).status_code == 200
    assert client.get("/api/client-profile").json()["telegram_mode"] == "personal"
    with api.app.state.auth_session_factory() as db:
        assert db.get(User, 1).telegram_chat_id == "123456789"
    assert client.post("/api/client-profile/telegram/test").status_code == 200
    assert sent[-1][1] == "123456789"
    assert client.post("/api/client-profile/telegram/test").status_code == 429


def test_client_version_is_uncached(client):
    response = client.get("/api/client-version")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["version"] == (api.WEB_DIR / "version.txt").read_text(encoding="utf-8").strip()


def test_notifications_are_scoped_and_bounded(client):
    response = client.get("/api/notifications")
    assert response.headers["cache-control"] == "no-store"
    rows = response.json()
    assert [row["title"] for row in rows] == ["Visible"]
    assert client.get("/api/notifications?limit=201").status_code == 422
    assert client.get("/api/notifications?before_id=1").json() == []


def test_alerts_do_not_expose_or_mutate_another_users_rule(client):
    assert client.get("/api/alert-rules").json() == []
    assert client.get("/api/alert-rules/1").status_code == 404
    assert client.patch("/api/alert-rules/1", json={"enabled": False}).status_code == 404
    assert client.delete("/api/alert-rules/1").status_code == 404


def test_open_registration_creates_an_isolated_account(client):
    from fastapi.testclient import TestClient

    second = TestClient(api.app)
    assert second.get("/api/watchlist").status_code == 401
    assert second.get("/api/auth/session").status_code == 401
    registered = second.post("/api/auth/register", json={
        "username": "new_member", "password": "another-long-password",
    })
    assert registered.status_code == 201
    assert registered.json()["username"] == "new_member"
    assert "httponly" in registered.headers["set-cookie"].lower()
    second.headers.update({"X-CSRF-Token": registered.json()["csrf_token"]})
    assert second.get("/api/client-profile").json()["username"] == "new_member"
    assert second.get("/api/notifications").json() == []
    assert second.get("/api/alert-rules").json() == []
    assert second.post("/api/watchlist", json={"asset_id": 2}).status_code == 200
    assert client.get("/api/watchlist").json() == []
    assert client.get("/api/client-profile").json()["username"] == "default"
    assert second.post("/api/auth/logout").status_code == 200
    assert second.get("/api/watchlist").status_code == 401
    assert second.post("/api/auth/login", json={
        "username": "new_member", "password": "another-long-password",
    }).status_code == 200


def test_https_domain_sets_secure_cookie_and_checks_origin(client, monkeypatch):
    monkeypatch.setenv("RADAR_PUBLIC_ORIGIN", "https://market.wyao.cc")
    public = TestClient(api.app, base_url="https://market.wyao.cc")
    account = {"username": "public_member", "password": "long-public-password"}
    assert public.post("/api/auth/register", json=account,
                       headers={"Origin": "https://wrong.example"}).status_code == 403
    registered = public.post("/api/auth/register", json=account,
                             headers={"Origin": "https://market.wyao.cc"})
    assert registered.status_code == 201
    cookie = registered.headers["set-cookie"]
    assert "__Host-radar_session=" in cookie
    assert "secure" in cookie.lower() and "httponly" in cookie.lower()
    assert public.get("/api/auth/session").json()["username"] == "public_member"
    assert public.post("/api/auth/logout", headers={
        "Origin": "https://wrong.example", "X-CSRF-Token": registered.json()["csrf_token"],
    }).status_code == 403


def test_production_preflight_rejects_missing_or_insecure_account_settings():
    values = {"RADAR_PUBLIC_ORIGIN": "https://market.wyao.cc",
              "RADAR_WORKER_TOKEN": "r" * 40}
    assert validate_environment(values) == []
    errors = validate_environment({**values, "RADAR_PUBLIC_ORIGIN": "http://market.wyao.cc/",
                                   "RADAR_WORKER_TOKEN": "short", "RADAR_ALLOW_HTTP_LOCAL": "1"})
    assert len(errors) == 3


def test_mutations_require_csrf_token(client):
    from fastapi.testclient import TestClient

    unauthenticated = TestClient(api.app)
    assert unauthenticated.post("/api/watchlist", json={"asset_id": 1}).status_code == 401
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/watchlist", json={"asset_id": 1}).status_code == 403
    assert client.get("/api/watchlist").json() == []


def test_market_websocket_requires_login(client, monkeypatch):
    monkeypatch.setattr(api, "load_realtime_market_quotes", lambda: [])
    unauthenticated = TestClient(api.app)
    with pytest.raises(WebSocketDisconnect) as error:
        with unauthenticated.websocket_connect("/ws/market"):
            pass
    assert error.value.code == 1008
    with client.websocket_connect("/ws/market") as socket:
        assert socket.receive_json() == {"type": "market_snapshot", "count": 0, "data": []}


def test_news_worker_requires_service_token_and_aggregates_watched_assets(client, monkeypatch):
    with api.app.state.auth_session_factory() as db:
        db.add(WatchlistItem(user_id=2, asset_id=1, news_enabled=True))
        db.add(WatchlistItem(user_id=1, asset_id=2, news_enabled=True))
        db.commit()
    monkeypatch.setenv("RADAR_WORKER_TOKEN", "test-worker-secret")
    assert client.get("/api/internal/news-watchlist").status_code == 403
    response = client.get("/api/internal/news-watchlist", headers={
        "X-Radar-Worker-Token": "test-worker-secret",
    })
    assert response.status_code == 200
    assert [item["asset_id"] for item in response.json()] == [1, 2]
    assert "user_id" not in response.text
    assert client.get("/api/internal/default-contract-watchlist").status_code == 403
    legacy = client.get("/api/internal/default-contract-watchlist", headers={
        "X-Radar-Worker-Token": "test-worker-secret",
    })
    assert [item["asset_id"] for item in legacy.json()] == [2]
    assert client.post("/api/news/test", json={"asset_id": 1, "title": "test"}).status_code == 403
    assert client.patch("/api/assets/1", json={"name": "Changed"}).status_code == 403


def test_hourly_contract_worker_uses_subscription_internal_route(monkeypatch):
    import crypto_metrics_worker

    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"asset_id": 2, "symbol": "BTCUSDT", "asset_type": "crypto",
                     "venue": "BINANCE", "segment": "FUTURES", "enabled": True}]

    def fake_get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setenv("RADAR_WORKER_TOKEN", "test-worker-secret")
    monkeypatch.setattr(crypto_metrics_worker.requests, "get", fake_get)
    assert [item["asset_id"] for item in crypto_metrics_worker.load_watched_contract_assets()] == [2]
    assert captured["url"].endswith("/api/internal/subscriptions")
    assert captured["params"] == {"alert_type": "longshort_digest"}
    assert captured["headers"] == {"X-Radar-Worker-Token": "test-worker-secret"}


def test_new_users_news_notifications_stay_in_app_without_telegram_binding(client, monkeypatch):
    import news_notification_service

    def must_not_send(*_args, **_kwargs):
        raise AssertionError("A new user's news must not reach the legacy global Telegram target")

    monkeypatch.setattr(news_notification_service, "send_telegram_message", must_not_send)
    with api.app.state.auth_session_factory() as db:
        db.add(WatchlistItem(user_id=2, asset_id=1, news_enabled=True))
        news = NewsItem(source="test", url="https://example.com/news", title="Test story")
        db.add(news)
        db.flush()
        impact = NewsImpact(news_id=news.id, asset_id=1, sentiment="positive",
                            impact_score=80, relevance_score=90, analysis_source="groq")
        db.add(impact)
        db.flush()
        news_notification_service.maybe_send_news_notification(db, db.get(Asset, 1), news, impact)
        db.commit()
        item = db.query(Notification).filter_by(user_id=2, news_id=news.id).one()
        assert (item.channel, item.status) == ("in_app", "in_app")


def test_new_users_price_notifications_stay_in_app_without_telegram_binding(client, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import notification_service

    def must_not_send(*_args, **_kwargs):
        raise AssertionError("A new user's alert must not reach the legacy global Telegram target")

    monkeypatch.setattr(notification_service, "send_telegram_message", must_not_send)
    with api.app.state.auth_session_factory() as db:
        rule = db.get(AlertRule, 1)
        asset = db.get(Asset, 1)
        snapshot = SimpleNamespace(price=123, change_pct=1.5, event_time=datetime.now(timezone.utc))
        item = notification_service.send_alert_notification(db, rule, asset, snapshot,
                                                            {"previous_value": 100, "current_value": 123})
        assert (item.user_id, item.channel, item.status) == (2, "in_app", "in_app")


def test_watchlist_and_alert_roundtrip_preserves_product_identity(client):
    assets = client.get("/api/assets").json()
    spot, futures = assets
    assert client.post("/api/watchlist", json={"asset_id": futures["id"]}).status_code == 200
    watched = client.get("/api/watchlist").json()
    assert len(watched) == 1 and watched[0]["segment"] == "FUTURES"
    payload = {"asset_id": futures["id"], "metric": "price", "operator": "step", "value": 10, "step_anchor": 100}
    response = client.post("/api/alert-rules", json=payload)
    assert response.status_code == 201
    rule = response.json()
    assert rule["asset"]["id"] == futures["id"]
    assert client.patch(f'/api/alert-rules/{rule["id"]}', json={"enabled": False}).json()["enabled"] is False
    assert client.post("/api/alert-rules", json={**payload, "asset_id": spot["id"]}).status_code == 400
    assert client.delete(f'/api/watchlist/{futures["id"]}').status_code == 200
    assert client.get("/api/watchlist").json() == []
    assert client.delete(f'/api/alert-rules/{rule["id"]}').status_code in (200, 204)


def test_new_shell_legacy_and_pwa_assets(client):
    assert "mobile.js" in client.get("/").text
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert "/static/app.js" in client.get("/legacy").text
    response = client.get("/sw.js")
    assert response.headers["service-worker-allowed"] == "/"
    assert response.headers["cache-control"] == "no-cache"
    manifest = client.get("/static/manifest.webmanifest").json()
    assert manifest["display"] == "standalone"
    for image in manifest["icons"]:
        assert client.get(image["src"]).status_code == 200


def test_no_quotes_or_news_are_invented(client):
    assert client.get("/api/market/latest").json() == []
    assert client.get("/api/market/history/assets/1").json()["data"] == []
    assert client.get("/api/assets/1/news").json() == []


def test_binance_futures_metrics_use_source_values_and_preserve_spot(client, monkeypatch):
    crypto_metrics._cache.clear()
    calls = []

    def read_json(url):
        calls.append(url)
        if "premiumIndex" in url:
            return {"symbol": "BTCUSDT", "markPrice": "123.45", "indexPrice": "123.00",
                    "lastFundingRate": "0.0001", "nextFundingTime": 1780000000000,
                    "time": 1779990000000}
        return {"symbol": "BTCUSDT", "openInterest": "12.5", "time": 1779990001000}

    monkeypatch.setattr(api, "_binance_read_json", read_json)
    response = client.get("/api/assets/2/crypto-metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["mark_price"] == 123.45
    assert data["last_funding_rate"] == 0.0001
    assert data["open_interest"] == 12.5
    assert data["unavailable"] == []
    assert len(calls) == 2
    assert client.get("/api/assets/1/crypto-metrics").status_code == 404
    assert len(calls) == 2
    assert client.get("/api/assets/2/crypto-metrics").json() == data
    assert len(calls) == 2  # 20-second source cache
    crypto_metrics._cache.clear()


def test_partial_futures_metrics_leave_missing_values_blank(client, monkeypatch):
    crypto_metrics._cache.clear()

    def read_json(url):
        if "premiumIndex" in url:
            return {"symbol": "BTCUSDT", "markPrice": "NaN", "indexPrice": "123",
                    "lastFundingRate": None, "time": None}
        raise OSError("upstream unavailable")

    monkeypatch.setattr(api, "_binance_read_json", read_json)
    data = client.get("/api/assets/2/crypto-metrics").json()
    assert data["mark_price"] is None
    assert data["index_price"] == 123
    assert data["last_funding_rate"] is None
    assert data["open_interest"] is None
    assert data["unavailable"] == ["open_interest"]


def seed_whale_catalog():
    from hyperliquid_whales import milliseconds
    from whale_models import WhaleRuntime
    with api.app.state.auth_session_factory() as db:
        db.add(WhaleRuntime(id=1, data={"catalog_ms": milliseconds(), "heartbeat_ms": milliseconds(),
            "markets": [{"coin": "xyz:KORU", "name": "Synthetic test market", "max_leverage": 10}]}))
        db.commit()


def test_whale_subscriptions_are_private_and_require_verified_markets(client):
    from fastapi.testclient import TestClient
    from whale_models import WhaleSubscription
    anonymous = TestClient(api.app)
    assert anonymous.get("/api/whales").status_code == 401
    body = {"coin": "xyz:KORU", "min_position_usd": 1000000}
    assert client.put("/api/whales/subscriptions", json=body).status_code == 422
    seed_whale_catalog()
    assert client.put("/api/whales/subscriptions", json={**body, "coin": "KORUUSDT"}).status_code == 422
    assert client.put("/api/whales/subscriptions", json={**body, "coin": "xyz:FAKE"}).status_code == 422
    assert client.put("/api/whales/subscriptions", json={**body, "min_position_usd": 0}).status_code == 422
    assert client.put("/api/whales/subscriptions", json={**body, "address": "0x123"}).status_code == 422
    result = client.put("/api/whales/subscriptions", json=body)
    assert result.status_code == 200
    data = client.get("/api/whales")
    assert data.headers["cache-control"] == "no-store"
    assert len(data.json()["subscriptions"]) == 1
    assert "private-test-target" not in data.text
    assert data.json()["events"] == [] and data.json()["positions"] == []
    with api.app.state.auth_session_factory() as db:
        other = db.query(User).filter_by(username="other").one()
        sub = WhaleSubscription(user_id=other.id, coin="xyz:KORU", started_ms=0)
        db.add(sub); db.commit()
        other_id = sub.id
    assert client.delete(f"/api/whales/subscriptions/{other_id}").status_code == 404
    assert client.delete(f'/api/whales/subscriptions/{result.json()["id"]}').status_code == 200
    assert client.get("/api/whales").json()["subscriptions"] == []


def test_whale_updates_require_csrf_and_stale_catalog_is_rejected(client):
    from whale_models import WhaleRuntime
    seed_whale_catalog()
    body = {"coin": "xyz:KORU"}
    assert client.put("/api/whales/subscriptions", json=body).status_code == 200
    assert client.put("/api/whales/subscriptions", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    with api.app.state.auth_session_factory() as db:
        row = db.get(WhaleRuntime, 1)
        row.data = {**row.data, "catalog_ms": 1}
        db.commit()
    assert client.put("/api/whales/subscriptions", json=body).status_code == 503
    assert client.put("/api/whales/subscriptions", json={**body,"enabled":False}).status_code == 200


def test_whale_catalog_allows_new_markets_and_delisting_never_prevents_pausing(client):
    from whale_models import WhaleRuntime
    seed_whale_catalog()
    body = {"coin": "xyz:GOLD"}
    # Being a syntactically valid xyz coin is insufficient without venue verification.
    assert client.put("/api/whales/subscriptions", json=body).status_code == 422
    with api.app.state.auth_session_factory() as db:
        row = db.get(WhaleRuntime, 1)
        row.data = {**row.data, "markets": [*row.data["markets"],
            {"coin": "xyz:GOLD", "name": "Synthetic catalog gold perpetual"}]}
        db.commit()
    assert client.put("/api/whales/subscriptions", json=body).status_code == 200
    assert client.get("/api/whales").json()["subscriptions"][0]["coin"] == "xyz:GOLD"
    with api.app.state.auth_session_factory() as db:
        row = db.get(WhaleRuntime, 1)
        row.data = {**row.data, "markets": []}
        db.commit()
    assert client.put("/api/whales/subscriptions", json=body).status_code == 422
    assert client.put("/api/whales/subscriptions", json={**body,"enabled":False}).status_code == 200


def test_whale_feed_filters_threshold_and_flags_stale_snapshots(client):
    from hyperliquid_whales import milliseconds, position_event
    from whale_models import WhaleAddress, WhalePositionEvent, WhaleSubscription
    seed_whale_catalog()
    address = "0x" + "a" * 40
    p = {"qty": "100000", "notional_usd": "2000000", "entry_price": "19.5", "leverage": "10", "leverage_type": "isolated"}
    with api.app.state.auth_session_factory() as db:
        owner = db.query(User).filter_by(username="default").one()
        db.add(WhaleSubscription(user_id=owner.id, coin="xyz:KORU", started_ms=0, min_position_usd=1000000))
        db.add(WhaleAddress(address=address, discovered_ms=1, last_trade_ms=1,
            checked_ms=milliseconds(), snapshot_ms=milliseconds()-240000, positions={"xyz:KORU": p}))
        event = position_event(address, "xyz:KORU", None, p, milliseconds())
        db.add(WhalePositionEvent(event_key=event["event_key"], address=address, coin="xyz:KORU",
            kind="discovered", qualifying_usd=2000000, observed_ms=milliseconds(), payload=event))
        db.commit()
    result = client.get("/api/whales").json()
    assert len(result["positions"]) == 1 and result["positions"][0]["stale"] is True
    assert result["events"][0]["kind"] == "discovered"
    assert client.put("/api/whales/subscriptions", json={"coin":"xyz:KORU", "min_position_usd":3000000}).status_code == 200
    result = client.get("/api/whales").json()
    assert result["positions"] == [] and result["events"] == []
