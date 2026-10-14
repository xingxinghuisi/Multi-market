"""Read-only Binance web Smart Signal aggregates, separate from wallet positions.

This is a web endpoint, not a documented Futures developer API. No credentials,
trading, automatic retries, anti-bot workarounds or Telegram delivery are used.
"""
import copy
import hashlib
import json
import math
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import requests

ENDPOINT = 'https://www.binance.com/bapi/futures/v1/public/future/smart-money/signal/overview'
SOURCE = 'Binance Futures Smart Signal'
MAX_AGE_SECONDS = 900  # Warn about the raw time field; its upstream meaning is unconfirmed.


def validate_symbol(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Z0-9]{1,46}USDT', value):
        raise ValueError('Only a verified Binance USDT contract symbol is accepted')
    return value


def number(value, integer=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(result) or result < 0 or result > 1e30 or (integer and not result.is_integer()):
        return None
    return int(result) if integer else result


def iso(milliseconds):
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat()


def parse_overview(payload, symbol, fetched_ms=None):
    validate_symbol(symbol)
    now = fetched_ms if fetched_ms is not None else int(time.time() * 1000)
    if (not isinstance(payload, dict) or payload.get('code') != '000000'
            or payload.get('success') is not True or not isinstance(payload.get('data'), dict)):
        raise ValueError('Smart Signal did not return a valid dataset')
    data = payload['data']
    stamp = number(data.get('updateTime'), integer=True)
    if data.get('symbol') != symbol or not stamp or stamp > now + 60000:
        raise ValueError('Invalid Smart Signal symbol or update time')
    # Validate the field without assuming it is the dataset's last refresh time.
    try:
        updated_at = iso(stamp)
    except (ValueError, OverflowError, OSError):
        raise ValueError('Invalid Smart Signal update time') from None
    sides = {}
    for side in ('long', 'short'):
        sides[side] = {
            'traders': number(data.get(side + 'Traders'), integer=True),
            'quantity': number(data.get(side + 'TradersQty')),
            'avg_entry_price': number(data.get(side + 'TradersAvgEntryPrice')),
            'whales': number(data.get(side + 'Whales'), integer=True),
            'whale_quantity': number(data.get(side + 'WhalesQty')),
            'whale_avg_entry_price': number(data.get(side + 'WhalesAvgEntryPrice')),
            'profitable_traders': number(data.get(side + 'ProfitTraders'), integer=True),
            'profitable_whales': number(data.get(side + 'ProfitWhales'), integer=True),
        }
        for total, profitable in (('traders', 'profitable_traders'), ('whales', 'profitable_whales')):
            if sides[side][total] is not None and sides[side][profitable] is not None:
                if sides[side][profitable] > sides[side][total]:
                    sides[side][profitable] = None
    return refresh_age({
        'market': f'binance:usdm:{symbol}', 'symbol': symbol, 'source': SOURCE,
        'source_url': ENDPOINT + '?' + urlencode({'symbol': symbol}),
        'scope': 'aggregate', 'access': 'undocumented_public_web_endpoint',
        'total_position_usd': number(data.get('totalPositions')),
        'total_traders': number(data.get('totalTraders'), integer=True),
        'long_short_ratio': number(data.get('longShortRatio')), 'sides': sides,
        'source_updated_ms': stamp, 'source_updated_at': updated_at,
        'fetched_at': iso(now), 'source_time_warning_seconds': MAX_AGE_SECONDS,
        'source_time_semantics_confirmed': False, 'freshness_confirmed': False,
        'upstream_refresh_interval_seconds': None, 'individual_positions_available': False,
        'telegram_enabled': False,
        'fingerprint': hashlib.sha256(json.dumps({key: value for key, value in data.items()
                                                  if key != 'updateTime'}, sort_keys=True).encode()).hexdigest(),
    }, now)


def refresh_age(snapshot, now_ms=None):
    result = copy.deepcopy(snapshot)
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    result['source_time_lag_seconds'] = max(0, (now - result['source_updated_ms']) // 1000)
    result['source_time_older_than_limit'] = result['source_time_lag_seconds'] > MAX_AGE_SECONDS
    return result


class SmartMoneyUnavailable(RuntimeError):
    def __init__(self, kind, retry_after=600):
        self.kind, self.retry_after = kind, max(1, int(math.ceil(retry_after)))
        messages = {
            'rate_limited': '币安网页数据请求受限，请等待后再试',
            'access_restricted': '当前服务器暂时无法访问币安聪明钱网页数据',
            'unavailable': '该合约暂未返回可用的聪明钱快照',
            'invalid_data': '币安聪明钱响应无法核验，请稍后重试',
        }
        super().__init__(messages.get(kind, '币安聪明钱数据暂不可用'))


def retry_after_seconds(value, now=None):
    now = time.time() if now is None else now
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return max(1, int(math.ceil(seconds)))
    except (ValueError, TypeError, OverflowError):
        pass
    try:
        seconds = parsedate_to_datetime(value).timestamp() - now
        return max(1, int(math.ceil(seconds)))
    except (ValueError, TypeError, OverflowError):
        return 600


class SmartMoneyClient:
    def __init__(self, session=None, cache_seconds=600, spacing_seconds=15):
        self.session = session or requests.Session()
        self.cache_seconds, self.spacing_seconds = cache_seconds, spacing_seconds
        self.cache, self.failures = {}, {}
        self.lock = threading.Lock()
        self.next_request = 0
        self.blocked_until = 0
        self.blocked_kind = 'rate_limited'

    def _fallback(self, symbol, error):
        cached = self.cache.get(symbol)
        if cached is None:
            raise error
        result = refresh_age(cached[1])
        result.update(cached=True, refresh_error=str(error), refresh_status=error.kind,
                      retry_after_seconds=error.retry_after)
        return result

    def get(self, symbol):
        validate_symbol(symbol)
        with self.lock:  # Serialize requests and share limits across users/symbols in the API process.
            now = time.monotonic()
            cached = self.cache.get(symbol)
            failure = self.failures.get(symbol)
            if failure and now < failure[0]:
                return self._fallback(symbol, SmartMoneyUnavailable(failure[1], failure[0] - now))
            if now < self.blocked_until:
                return self._fallback(symbol, SmartMoneyUnavailable(self.blocked_kind, self.blocked_until - now))
            if cached and now - cached[0] < self.cache_seconds:
                result = refresh_age(cached[1])
                result['cached'] = True
                return result
            if now < self.next_request:
                return self._fallback(symbol, SmartMoneyUnavailable('rate_limited', self.next_request - now))
            self.next_request = now + self.spacing_seconds
            try:
                response = self.session.get(ENDPOINT, params={'symbol': symbol},
                    headers={'Accept': 'application/json', 'User-Agent': 'MIRAO-readonly-data-verification/1.0'},
                    timeout=(4, 12), allow_redirects=False)
                if response.status_code in (418, 429):
                    raise SmartMoneyUnavailable('rate_limited', retry_after_seconds(response.headers.get('Retry-After')))
                if response.status_code in (202, 301, 302, 303, 307, 308, 401, 403, 451):
                    raise SmartMoneyUnavailable('access_restricted', 1800)
                if response.status_code != 200:
                    raise SmartMoneyUnavailable('unavailable', 600)
                try:
                    snapshot = parse_overview(response.json(), symbol)
                except (ValueError, TypeError):
                    raise SmartMoneyUnavailable('invalid_data', 600) from None
            except requests.RequestException:
                error = SmartMoneyUnavailable('unavailable', 600)
            except SmartMoneyUnavailable as unavailable:
                error = unavailable
            else:
                self.cache[symbol] = (time.monotonic(), snapshot)
                self.failures.pop(symbol, None)
                # Bound process memory when the shared catalog contains many contracts.
                if len(self.cache) > 128:
                    oldest = min(self.cache, key=lambda key: self.cache[key][0])
                    del self.cache[oldest]
                snapshot = copy.deepcopy(snapshot)
                snapshot['cached'] = False
                return snapshot
            deadline = time.monotonic() + error.retry_after
            self.failures[symbol] = (deadline, error.kind)
            if len(self.failures) > 128:
                oldest = min(self.failures, key=lambda key: self.failures[key][0])
                del self.failures[oldest]
            if error.kind in ('rate_limited', 'access_restricted'):
                self.blocked_until, self.blocked_kind = deadline, error.kind
            return self._fallback(symbol, error)


client = SmartMoneyClient()
