"""Low-frequency, read-only VPS probe. Does not load app DB, secrets, Gemini or Telegram."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone

from binance_smart_money import SmartMoneyClient, SmartMoneyUnavailable, validate_symbol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol', default='KORUUSDT')
    parser.add_argument('--samples', type=int, default=4)
    parser.add_argument('--interval', type=int, default=600)
    args = parser.parse_args()
    try:
        validate_symbol(args.symbol)
    except ValueError as error:
        parser.error(str(error))
    if not 1 <= args.samples <= 24 or args.interval < 300:
        parser.error('Use 1–24 samples and an interval of at least 300 seconds')
    client = SmartMoneyClient(cache_seconds=0)
    prior = None
    changed = 0
    previous_fingerprint = None
    data_changes = 0
    for index in range(args.samples):
        try:
            snapshot = client.get(args.symbol)
        except SmartMoneyUnavailable as error:
            print(json.dumps({'status': error.kind, 'retry_after_seconds': error.retry_after,
                              'message': str(error)}, ensure_ascii=False), flush=True)
            return 1  # No retry loop or host/IP switching after access restrictions.
        if snapshot.get('refresh_error'):
            print(json.dumps({'status': snapshot['refresh_status'],
                              'retry_after_seconds': snapshot['retry_after_seconds'],
                              'message': snapshot['refresh_error']}, ensure_ascii=False), flush=True)
            return 1  # Client fallback data must not be counted as a successful new sample.
        if prior is not None and prior != snapshot['source_updated_ms']:
            changed += 1
        if previous_fingerprint is not None and previous_fingerprint != snapshot['fingerprint']:
            data_changes += 1
        print(json.dumps({'sample': index + 1, 'symbol': args.symbol, 'status': 'DATA_OK',
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'source_updated_at': snapshot['source_updated_at'],
            'source_time_lag_seconds': snapshot['source_time_lag_seconds'],
            'source_time_semantics_confirmed': False,
            'source_time_changed': None if prior is None else prior != snapshot['source_updated_ms'],
            'data_changed': None if previous_fingerprint is None else previous_fingerprint != snapshot['fingerprint'],
            'fingerprint': snapshot['fingerprint'], 'total_traders': snapshot['total_traders'],
            'long_whales': snapshot['sides']['long']['whales'],
            'short_whales': snapshot['sides']['short']['whales']}, ensure_ascii=False), flush=True)
        prior = snapshot['source_updated_ms']
        previous_fingerprint = snapshot['fingerprint']
        if index < args.samples - 1:
            time.sleep(args.interval)
    print(json.dumps({'status': 'PROBE_COMPLETE', 'samples': args.samples,
                      'source_timestamp_changes': changed,
                      'data_changes': data_changes,
                      'upstream_refresh_interval_confirmed': False}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
