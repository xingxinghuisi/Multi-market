"""Delayed upstream data and delivery outages must retry the same hour safely."""
from datetime import datetime, timedelta, timezone

import pytest
import requests

import crypto_metrics_worker as digest


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 10, 11, 8, 2, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        Clock.current += timedelta(seconds=seconds)

    monkeypatch.setattr(digest, "datetime", Clock)
    monkeypatch.setattr(digest.time, "sleep", sleep)
    return Clock, sleeps


def test_delayed_data_retries_without_waiting_an_hour(monkeypatch, clock):
    monkeypatch.setattr(digest, "load_watched_contract_assets", lambda: [
        {"symbol": "BTCUSDT", "subscription_id": 1}])
    calls, deliveries = [], []

    def fetch(symbol, targets):
        calls.append(targets["hour_end"])
        if len(calls) == 1:
            raise digest.IncompleteHourData("missing completed 1H data: taker_current")
        return targets

    monkeypatch.setattr(digest, "fetch_metrics", fetch)
    monkeypatch.setattr(digest, "build_message", lambda *a: "fixture")
    monkeypatch.setattr(digest, "submit_event", lambda *a: deliveries.append(a) or {"status": "sent"})
    assert digest.run_hour() is True
    assert clock[1] == [60]
    assert calls[0] == calls[1]
    assert len(deliveries) == 1


def test_only_failed_recipient_is_retried_with_identical_event_key(monkeypatch, clock):
    monkeypatch.setattr(digest, "load_watched_contract_assets", lambda: [
        {"symbol": "BTCUSDT", "subscription_id": 1},
        {"symbol": "BTCUSDT", "subscription_id": 2}])
    monkeypatch.setattr(digest, "fetch_metrics", lambda symbol, targets: targets)
    monkeypatch.setattr(digest, "build_message", lambda *a: "fixture")
    calls = []

    def deliver(*args):
        calls.append(args)
        return {"status": "failed" if len(calls) == 2 else "sent"}

    monkeypatch.setattr(digest, "submit_event", deliver)
    assert digest.run_hour() is True
    assert [a[0] for a in calls] == [1, 2, 2]
    assert len({a[1] for a in calls}) == 1


def test_subscription_api_outage_has_bounded_retries(monkeypatch, clock):
    calls = []

    def unavailable():
        calls.append(1)
        raise requests.ConnectionError("secret URL must never be logged")

    monkeypatch.setattr(digest, "load_watched_contract_assets", unavailable)
    assert digest.run_hour() is False
    assert len(calls) == digest.MAX_ATTEMPTS
    assert clock[1] == [60] * (digest.MAX_ATTEMPTS - 1)


def test_late_retry_stops_before_next_hour_is_due(monkeypatch, clock):
    clock[0].current = datetime(2026, 10, 11, 8, 59, 30, tzinfo=timezone.utc)
    targets = digest.build_hour_targets()
    seen = []

    def unavailable(dry_run, fixed, completed):
        seen.append(fixed["hour_end"])
        return True

    monkeypatch.setattr(digest, "run_once", unavailable)
    assert digest.run_hour(targets=targets) is False
    assert len(seen) == 3
    assert len(set(seen)) == 1
    assert len(clock[1]) == 2


def test_explicit_hour_is_preserved_when_clock_crosses_hour(clock):
    targets = digest.build_hour_targets()
    clock[0].current += timedelta(hours=1)

    def read_json(url):
        stamps = ([targets["hour_start"], targets["previous_start"]]
                  if "takerlongshortRatio" in url else [targets["hour_end"], targets["hour_start"]])
        return [{"timestamp": int(t.timestamp() * 1000)} for t in stamps]

    result = digest.fetch_metrics("BTCUSDT", read_json=read_json, targets=targets)
    assert result["hour_end"] == targets["hour_end"]


def test_safe_diagnostics_explain_missing_data_and_http_status():
    message = digest.error_detail(digest.IncompleteHourData("missing completed 1H data: taker_current"))
    assert "taker_current" in message
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError("https://secret.invalid/token", response=response)
    assert digest.error_detail(error) == "HTTPError status=429"
    assert digest.error_detail(requests.ConnectionError("credential")) == "ConnectionError"


def test_restart_catches_up_and_slow_cycle_does_not_skip_next_due_hour(monkeypatch, clock):
    class StopWorker(BaseException):
        pass

    seen = []

    def run(dry_run, targets):
        seen.append(targets["hour_end"])
        if len(seen) == 2:
            raise StopWorker()
        # A slow request crosses the next scheduled time.
        clock[0].current += timedelta(hours=1, seconds=5)

    monkeypatch.setattr(digest, "run_hour", run)
    with pytest.raises(StopWorker):
        digest.run_forever()
    assert seen == [datetime(2026, 10, 11, h, tzinfo=timezone.utc) for h in (8, 9)]
    assert clock[1] == []


def test_restart_before_push_minute_waits_until_due(monkeypatch, clock):
    class StopWorker(BaseException):
        pass

    clock[0].current = datetime(2026, 10, 11, 8, 1, tzinfo=timezone.utc)
    seen = []

    def run(dry_run, targets):
        seen.append(targets["hour_end"])
        raise StopWorker()

    monkeypatch.setattr(digest, "run_hour", run)
    with pytest.raises(StopWorker):
        digest.run_forever()
    assert clock[1] == [60]
    assert seen == [datetime(2026, 10, 11, 8, tzinfo=timezone.utc)]
