"""Synthetic aggregates and transport responses; no live provider or Telegram calls."""
import copy
from datetime import datetime, timezone

import pytest
import requests

import binance_smart_money as sm

NOW = 1791988500000


def payload(symbol='KORUUSDT', stamp=NOW):
    return {'code': '000000', 'success': True, 'data': {
        'symbol': symbol, 'updateTime': stamp, 'totalPositions': 1000000,
        'totalTraders': 20, 'longShortRatio': .5,
        'longTraders': 10, 'shortTraders': 10, 'longTradersQty': 100, 'shortTradersQty': 200,
        'longWhales': 3, 'shortWhales': 4, 'longWhalesQty': 75, 'shortWhalesQty': 150,
        'longTradersAvgEntryPrice': 15, 'shortTradersAvgEntryPrice': 18,
        'longWhalesAvgEntryPrice': 14, 'shortWhalesAvgEntryPrice': 19,
        'longProfitTraders': 0, 'shortProfitTraders': 7,
        'longProfitWhales': 0, 'shortProfitWhales': 3,
    }}


class Response:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code, self.data, self.headers = status, data, headers or {}

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return copy.deepcopy(self.data)


class Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_aggregate_semantics_zero_missing_values_and_source_age():
    raw = payload(stamp=NOW - 8 * 3600000)
    del raw['data']['shortProfitWhales']
    raw['data']['longTradersAvgEntryPrice'] = 'NaN'
    result = sm.parse_overview(raw, 'KORUUSDT', NOW)
    assert result['market'] == 'binance:usdm:KORUUSDT'
    assert result['source_time_lag_seconds'] == 8 * 3600 and result['source_time_older_than_limit'] is True
    assert result['freshness_confirmed'] is False
    assert result['sides']['long']['profitable_whales'] == 0
    assert result['sides']['short']['profitable_whales'] is None
    assert result['sides']['long']['avg_entry_price'] is None
    assert result['individual_positions_available'] is False
    assert result['telegram_enabled'] is False
    assert result['upstream_refresh_interval_seconds'] is None
    assert not any(key in result for key in ('address', 'leverage', 'unrealized_pnl', 'kind'))
    assert sm.refresh_age(result, NOW + 600000)['source_time_lag_seconds'] == 8 * 3600 + 600
    assert result['fetched_at'] != result['source_updated_at']


def test_time_changes_and_position_data_changes_are_measured_separately():
    first = sm.parse_overview(payload(stamp=NOW-60000), 'KORUUSDT', NOW)
    newer_time = sm.parse_overview(payload(stamp=NOW), 'KORUUSDT', NOW)
    assert first['fingerprint'] == newer_time['fingerprint']
    raw = payload(stamp=NOW-60000)
    raw['data']['longWhales'] = 4
    changed_value = sm.parse_overview(raw, 'KORUUSDT', NOW)
    assert first['fingerprint'] != changed_value['fingerprint']
    assert first['source_updated_at'] == changed_value['source_updated_at']


def test_probe_stops_on_cached_fallback_instead_of_reporting_new_success(monkeypatch, capsys):
    import verify_binance_smart_money as probe
    first = sm.parse_overview(payload(), 'KORUUSDT', NOW)
    responses = [first, {**first, 'refresh_error': 'blocked', 'refresh_status': 'access_restricted',
                         'retry_after_seconds': 1800}]
    class FakeClient:
        def get(self, _symbol):
            return responses.pop(0)
    monkeypatch.setattr(probe, 'SmartMoneyClient', lambda **_kwargs: FakeClient())
    monkeypatch.setattr(probe.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(probe.sys, 'argv', ['probe', '--samples', '4', '--interval', '300'])
    assert probe.main() == 1
    output = capsys.readouterr().out
    assert output.count('DATA_OK') == 1
    assert 'access_restricted' in output and 'PROBE_COMPLETE' not in output


@pytest.mark.parametrize('raw', [None, {}, {'code': '000000', 'success': True, 'data': None},
    payload('BTCUSDT'), payload(stamp=NOW + 120000), payload(stamp=0)])
def test_invalid_wrong_market_and_future_responses_rejected(raw):
    with pytest.raises(ValueError):
        sm.parse_overview(raw, 'KORUUSDT', NOW)


def test_cached_results_are_shared_but_mutable_response_cannot_change_cache(monkeypatch):
    clock = [0]
    monkeypatch.setattr(sm.time, 'monotonic', lambda: clock[0])
    session = Session(Response(data=payload()))
    client = sm.SmartMoneyClient(session)
    first = client.get('KORUUSDT')
    first['sides']['long']['whales'] = 999
    clock[0] = 300
    second = client.get('KORUUSDT')
    assert second['cached'] is True
    assert second['sides']['long']['whales'] == 3
    assert len(session.calls) == 1
    options = session.calls[0][1]
    assert 'Authorization' not in options['headers'] and 'X-MBX-APIKEY' not in options['headers']
    assert options['allow_redirects'] is False


def test_rate_limit_honors_long_retry_after_across_markets_without_retry(monkeypatch):
    clock = [0]
    monkeypatch.setattr(sm.time, 'monotonic', lambda: clock[0])
    session = Session(Response(429, headers={'Retry-After': '14400'}))
    client = sm.SmartMoneyClient(session)
    with pytest.raises(sm.SmartMoneyUnavailable) as error:
        client.get('KORUUSDT')
    assert error.value.retry_after == 14400
    clock[0] = 3600
    with pytest.raises(sm.SmartMoneyUnavailable) as error:
        client.get('BTCUSDT')
    assert error.value.retry_after == 10800
    assert len(session.calls) == 1


def test_failure_preserves_last_snapshot_and_does_not_refresh_its_time(monkeypatch):
    clock = [0]
    monkeypatch.setattr(sm.time, 'monotonic', lambda: clock[0])
    session = Session(Response(data=payload()), Response(403))
    client = sm.SmartMoneyClient(session)
    first = client.get('KORUUSDT')
    clock[0] = 601
    old = client.get('KORUUSDT')
    assert old['cached'] is True and old['refresh_status'] == 'access_restricted'
    assert old['source_updated_at'] == first['source_updated_at']
    assert old['fetched_at'] == first['fetched_at']
    clock[0] = 700
    assert client.get('KORUUSDT')['refresh_status'] == 'access_restricted'
    assert len(session.calls) == 2


@pytest.mark.parametrize('response', [Response(202), Response(200, ValueError('HTML challenge')),
    Response(200, {}), requests.ConnectionError('no route')])
def test_invalid_or_unreachable_source_never_becomes_zero_positions(response):
    session = Session(response)
    client = sm.SmartMoneyClient(session)
    with pytest.raises(sm.SmartMoneyUnavailable):
        client.get('KORUUSDT')
    with pytest.raises(sm.SmartMoneyUnavailable):
        client.get('KORUUSDT')
    assert len(session.calls) == 1 and not client.cache


def test_cross_symbol_requests_are_spaced_and_http_date_retry_after_is_supported(monkeypatch):
    clock = [0]
    monkeypatch.setattr(sm.time, 'monotonic', lambda: clock[0])
    session = Session(Response(data=payload()), Response(data=payload('BTCUSDT')))
    client = sm.SmartMoneyClient(session)
    client.get('KORUUSDT')
    with pytest.raises(sm.SmartMoneyUnavailable):
        client.get('BTCUSDT')
    clock[0] = 16
    assert client.get('BTCUSDT')['symbol'] == 'BTCUSDT'
    assert len(session.calls) == 2
    assert sm.retry_after_seconds('Wed, 14 Oct 2026 14:40:00 GMT',
        datetime(2026, 10, 14, 14, 30, tzinfo=timezone.utc).timestamp()) == 600
