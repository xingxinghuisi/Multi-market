"""Real indicators/SQLite/API; all cloud requests and Telegram delivery are mocked."""
import base64
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import api
import gemini_service as gemini
import signal_worker as worker
import subscription_service
from database import Base
from models import AlertSubscription, Asset, Notification, User
from signal_models import AiBudgetNotice, GeminiAnalysis, TechnicalState, initialize_signal_tables
from technical_indicators import TechnicalConfig, closed_candles, ema, evaluate, rsi
from test_mobile_api import client
from deployment_preflight import validate_environment
from gemini_check import check as check_connection

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
STEP = 3600000


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    db_engine = create_engine(f"sqlite:///{tmp_path / 'isolated.sqlite'}")
    Base.metadata.create_all(db_engine)
    initialize_signal_tables(db_engine)
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(username="default", telegram_chat_id="private-test-target"))
        db.add(Asset(symbol="KORUUSDT", name="test", asset_type="crypto", venue="BINANCE",
                     segment="FUTURES", currency="USDT", provider="BINANCE_FUTURES"))
        db.commit()
    monkeypatch.setenv("GEMINI_ENABLED", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "mirao-unit-test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GEMINI_BUDGET_USERNAME", "default")
    monkeypatch.setenv("GEMINI_MONTHLY_WARNING_USD", "8.5")
    monkeypatch.delenv("GEMINI_BILLING_SUBSCRIPTION", raising=False)
    monkeypatch.delenv("GEMINI_BILLING_BUDGET_ID", raising=False)
    yield factory
    db_engine.dispose()


def candle_rows(last=100, previous=100, count=200, offset=0):
    end = int(NOW.timestamp() * 1000) + offset * STEP
    rows = []
    for i in range(count):
        close = last if i == count - 1 else previous if i == count - 2 else 100
        start = end - (count - i) * STEP
        rows.append([start, str(close), str(close + 1), str(close - 1), str(close), "100",
                     start + STEP - 1, "10000", 50, "0", "0", "0"])
    return rows


def response(text=None, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": text or json.dumps({
        "bias": "neutral", "summary": "信号相互抵消。", "reasons": ["价格尚未脱离区间。"],
        "risks": ["关注后续收盘确认。"]})}]}}],
        "usageMetadata": {"promptTokenCount": 3000, "candidatesTokenCount": 500,
                          "thoughtsTokenCount": 500, "cachedContentTokenCount": 1000}}


def test_wilder_rsi_and_seeded_ema_known_arithmetic():
    assert ema([1, 2, 3, 4], 3) == [None, None, 2, 3]
    assert rsi([1, 2, 1, 2], 2) == [None, None, 50, 75]
    assert rsi([2] * 20)[-1] == 50
    assert rsi(list(range(1, 30)))[-1] == 100
    assert rsi(list(range(30, 0, -1)))[-1] == 0


def test_closed_candles_reject_stale_gaps_nan_and_unfinished_prices():
    rows = candle_rows()
    now = int(NOW.timestamp() * 1000)
    assert len(closed_candles(rows + [[now, "1", "2", "1", "2", "1", now + STEP - 1, "2"]], "1h", now)) == 200
    for invalid in (rows[:-1], rows[:50] + rows[51:]):
        with pytest.raises(ValueError):
            closed_candles(invalid, "1h", now)
    rows[-1][4] = "NaN"
    with pytest.raises(ValueError):
        closed_candles(rows, "1h", now)


def test_real_crossover_volume_and_explicit_fibonacci_anchors():
    rows = candle_rows(last=101, previous=99)
    rows[-1][7] = "30000"
    config = TechnicalConfig(indicators=["ma", "volume", "fibonacci"], fib_low=90, fib_high=110)
    result = evaluate(closed_candles(rows, "1h", int(NOW.timestamp() * 1000)), config)
    assert result["fibonacci"]["0.5"] == 100
    assert any("0.5 突破" in s for s in result["signals"])
    assert any("3.00 倍" in s for s in result["signals"])
    assert result["turnover_rate"] is None
    assert result["relative_volume"] == 3


@pytest.mark.parametrize("values", [{"rsi_low": 80, "rsi_high": 30}, {"ma_fast": 30, "ma_slow": 20},
    {"indicators": []}, {"indicators": ["fibonacci"]}, {"rsi_low": float("nan")},
    {"indicators": ["rsi", "rsi"]}, {"timeframe": "1m"}, {"unknown": 2}])
def test_invalid_signal_parameters_fail_before_cloud_call(values):
    with pytest.raises(ValueError):
        TechnicalConfig(**values)


def test_cost_includes_reasoning_and_cache_and_persists_after_restart(sessions):
    calls = []
    with sessions() as db:
        result, _ = gemini.analyze(db, {"close": 100}, lambda s: calls.append(s) or response(), NOW)
        assert result["bias"] == "neutral"
        row = db.scalar(select(GeminiAnalysis))
        # (2000*.25 + 1000*.025 + (500+500)*1.5) / 1M = .002025
        assert row.cost_nano_usd == 2025000
        assert row.thinking_tokens == 500 and row.usage_known
    with sessions() as db:
        assert gemini.analyze(db, {"close": 100}, lambda s: pytest.fail("Must reuse"), NOW)[0]
        assert gemini.usage_summary(db, NOW)["estimated_usd"] == 0.002025
    assert len(calls) == 1


@pytest.mark.parametrize("bad", [response("not json"), response(finish="MAX_TOKENS")])
def test_invalid_or_truncated_output_is_still_accounted(sessions, bad):
    with sessions() as db:
        assert gemini.analyze(db, {"close": 100}, lambda s: bad, NOW)[0] is None
        row = db.scalar(select(GeminiAnalysis))
        assert row.status == "error" and row.usage_known and row.cost_nano_usd > 0


def test_timeout_is_visible_and_never_automatically_recharged(sessions):
    def timeout(_):
        raise requests.Timeout("redacted test fixture")
    with sessions() as db:
        assert gemini.analyze(db, {"close": 101}, timeout, NOW)[0] is None
        assert gemini.analyze(db, {"close": 101}, lambda _: pytest.fail("No paid retry"), NOW)[0] is None
        summary = gemini.usage_summary(db, NOW)
        assert summary["unverified_calls"] == 1
        assert summary["calls"] == 1


def test_answer_without_output_usage_is_marked_unverified(sessions):
    partial = response()
    del partial["usageMetadata"]["candidatesTokenCount"]
    with sessions() as db:
        assert gemini.analyze(db, {"close": 101}, lambda _: partial, NOW)[0]
        assert gemini.usage_summary(db, NOW)["unverified_calls"] == 1


def test_daily_limit_and_disabled_configuration_preserve_free_signals(sessions, monkeypatch):
    monkeypatch.setenv("GEMINI_MAX_CALLS_PER_DAY", "1")
    with sessions() as db:
        assert gemini.analyze(db, {"close": 100}, lambda _: response(), NOW)[0]
        assert gemini.analyze(db, {"close": 101}, lambda _: pytest.fail("Daily cap"), NOW)[0] is None
        monkeypatch.setenv("GEMINI_ENABLED", "0")
        assert gemini.analyze(db, {"close": 102}, lambda _: pytest.fail("Disabled"), NOW)[0] is None


def test_budget_warning_threshold_retry_dedupe_and_new_month(sessions):
    sent = []
    with sessions() as db:
        assert not gemini.notify_budget(db, "8.49", month="2026-10", sender=lambda *a, **k: pytest.fail("Too early"))
        assert not gemini.notify_budget(db, "8.5", month="2026-10", sender=lambda *a, **k: False)
    with sessions() as db:
        assert gemini.notify_budget(db, "8.6", month="2026-10", sender=lambda text, chat_id: sent.append((text, chat_id)) or True)
        assert gemini.notify_budget(db, "9", month="2026-10", sender=lambda *a, **k: pytest.fail("Duplicate"))
        assert gemini.notify_budget(db, "8.5", month="2026-11", sender=lambda text, chat_id: sent.append((text, chat_id)) or True)
        assert len(db.scalars(select(AiBudgetNotice)).all()) == 2
    assert len(sent) == 2 and sent[0][1] == "private-test-target"
    assert "估算" in sent[0][0] and "继续运行" in sent[0][0]


def test_budget_owner_is_explicit_not_broadcast_to_members(sessions, monkeypatch):
    monkeypatch.setenv("GEMINI_BUDGET_USERNAME", "missing-owner")
    with sessions() as db:
        assert not gemini.notify_budget(db, 9, sender=lambda *a, **k: pytest.fail("No target"))
        assert not db.scalars(select(Notification)).all()


def test_month_follows_cloud_pacific_boundary():
    assert gemini.billing_month(datetime(2026, 11, 1, 0, tzinfo=timezone.utc)) == "2026-10"
    assert gemini.billing_month(datetime(2026, 11, 1, 12, tzinfo=timezone.utc)) == "2026-11"


def test_cloud_budget_validates_currency_period_identity_and_actual_cost(sessions):
    def message(cost=8.5, currency="USD", budget="budget-fixture", start="2026-10-01T07:00:00Z"):
        data = {"costAmount": cost, "currencyCode": currency, "costIntervalStart": start,
                "forecastThresholdExceeded": 2}
        return {"attributes": {"budgetId": budget}, "data": base64.b64encode(json.dumps(data).encode()).decode()}
    sent = []
    sender = lambda text, chat_id: sent.append(text) or True
    with sessions() as db:
        assert worker.handle_billing_message(db, message(8), "budget-fixture", sender, NOW)
        assert not sent  # Forecast alone must never trigger the actual cost warning.
        assert worker.handle_billing_message(db, message(budget="other"), "budget-fixture", sender, NOW)
        assert worker.handle_billing_message(db, message(start="2026-09-01T07:00:00Z"), "budget-fixture", sender, NOW)
        assert not sent
        with pytest.raises(ValueError):
            worker.handle_billing_message(db, message(currency="CNY"), "budget-fixture", sender, NOW)
        assert worker.handle_billing_message(db, message(), "budget-fixture", sender, NOW)
        assert len(sent) == 1 and "账单已报告" in sent[0]
        assert worker.handle_billing_message(db, message(), "budget-fixture", lambda *a, **k: pytest.fail("Duplicate"), NOW)


def test_worker_baselines_then_sends_once_and_reuses_paid_analysis_on_telegram_retry(sessions, monkeypatch):
    monkeypatch.setattr(subscription_service, "send_telegram_message", lambda *a, **k: False)
    generated = []
    generator = lambda s: generated.append(s) or response()
    with sessions() as db:
        sub = AlertSubscription(user_id=1, asset_id=1, alert_type="technical_signal",
                                enabled=True, config=TechnicalConfig(indicators=["ma"], cooldown_seconds=0).model_dump())
        db.add(sub); db.commit()
        asset = db.get(Asset, 1)
        first = closed_candles(candle_rows(previous=99, last=101), "1h", int(NOW.timestamp() * 1000))
        assert worker.process_subscription(db, sub, asset, first, NOW, generator)["status"] == "baseline"
        assert not generated
        second = closed_candles(candle_rows(previous=101, last=90, offset=1), "1h", int(NOW.timestamp() * 1000) + STEP)
        assert evaluate(second, TechnicalConfig(indicators=["ma"]))["signals"]
        assert worker.process_subscription(db, sub, asset, second, NOW, generator)["status"] == "failed"
        assert len(generated) == 1
        monkeypatch.setattr(subscription_service, "send_telegram_message", lambda *a, **k: True)
        assert worker.process_subscription(db, sub, asset, second, NOW, generator)["status"] == "sent"
        assert worker.process_subscription(db, sub, asset, second, NOW, generator)["duplicate"]
        assert len(generated) == 1


def test_signal_api_and_subscriptions_are_private_and_validate_config(client, monkeypatch):
    monkeypatch.setenv("GEMINI_BUDGET_USERNAME", "default")
    assert TestClient(api.app).get("/api/signals").status_code == 401
    good = client.put("/api/subscriptions", json={"asset_id": 2, "alert_type": "technical_signal",
                                                "config": {"timeframe": "4h", "indicators": ["rsi"]}})
    assert good.status_code == 200, good.text
    assert good.json()["config"]["rsi_high"] == 70
    assert client.put("/api/subscriptions", json={"asset_id": 2, "alert_type": "technical_signal",
                                                 "config": {"ma_fast": 50, "ma_slow": 20}}).status_code == 422
    status = client.get("/api/signals")
    assert status.status_code == 200 and status.headers["cache-control"] == "no-store"
    assert status.json()["gemini"]["budget_owner"]
    outsider = TestClient(api.app)
    outsider.post("/api/auth/register", json={"username": "ai_other", "password": "long-ai-other-password"})
    assert outsider.get("/api/signals").json()["gemini"]["usage"] is None
    assert outsider.get("/api/signals").json()["states"] == []


def test_rest_payload_uses_cloud_auth_json_output_and_no_tools(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "mirao-unit-test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    captured = []
    class Response:
        def raise_for_status(self): pass
        def json(self): return response()
    class Session:
        def post(self, url, **kwargs):
            captured.append((url, kwargs))
            return Response()
    gemini.generate({"symbol": "KORUUSDT", "close": 18}, Session())
    url, args = captured[0]
    assert url.startswith("https://aiplatform.googleapis.com/v1/projects/mirao-unit-test/")
    assert url.endswith("gemini-3.1-flash-lite:generateContent")
    assert "tools" not in args["json"]
    assert args["json"]["generationConfig"]["maxOutputTokens"] == 768


def test_preflight_rejects_invalid_cloud_configuration_without_secret_output():
    values = {"RADAR_PUBLIC_ORIGIN": "https://market.wyao.cc", "RADAR_WORKER_TOKEN": "x" * 40,
              "GEMINI_ENABLED": "1", "GOOGLE_CLOUD_PROJECT": "mirao-unit-test"}
    assert validate_environment(values) == []
    assert validate_environment({**values, "GEMINI_MONTHLY_WARNING_USD": "NaN"})
    assert validate_environment({**values, "GEMINI_MODEL": "unknown"})
    assert validate_environment({**values, "GEMINI_BILLING_BUDGET_ID": "budget"})


def test_setup_check_uses_real_candle_shape_and_records_cost_without_notifications(sessions):
    calls = []
    with sessions() as db:
        result, usage = check_connection(db, "KORUUSDT", reader=lambda *args: candle_rows(),
            generator=lambda snapshot: calls.append(snapshot) or response(), now=NOW)
        assert result and usage["estimated_usd"] > 0
        assert calls[0]["close"] == 100 and calls[0]["purpose"] == "explicit_connection_check"
        assert not db.scalars(select(Notification)).all()
        assert not db.scalars(select(AlertSubscription)).all()
        with pytest.raises(ValueError):
            check_connection(db, "UNKNOWN", reader=lambda *args: pytest.fail("No unknown market call"), now=NOW)
