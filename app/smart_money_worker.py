"""One round-robin scheduler; the API owns shared source limits and durable checkpoints."""
import time

import requests

from subscription_client import API_BASE_URL, headers, load_subscriptions

INTERVAL_SECONDS = 30


def poll_asset(asset_id):
    response = requests.post(f"{API_BASE_URL}/api/internal/smart-money/{asset_id}/poll",
                             headers=headers(), timeout=(4, 45))
    response.raise_for_status()
    return response.json()


def tick(last_asset=0, load=load_subscriptions, poll=poll_asset):
    # One asset per tick prevents a large catalog from bursting requests at Binance.
    ids = sorted({row["asset_id"] for row in load("smart_money")})
    if not ids:
        return 0
    asset_id = next((ident for ident in ids if ident > last_asset), ids[0])
    try:
        result = poll(asset_id)
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        # A failed/removed asset must not starve the rest of the round-robin queue.
        print(f"[SMART MONEY] asset={asset_id} poll_error={type(error).__name__}", flush=True)
        return asset_id
    statuses = ",".join(row["status"] for row in result.get("results", []))
    print(f"[SMART MONEY] asset={asset_id} status={result['status']} results={statuses}", flush=True)
    return asset_id


def main():
    print("[SMART MONEY] started; opt-in aggregate observations; shared source cache=600s", flush=True)
    last_asset = 0
    while True:
        started = time.monotonic()
        try:
            last_asset = tick(last_asset)
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            # Do not print request headers, tokens, recipients or response bodies.
            print(f"[SMART MONEY] poll_error={type(error).__name__}", flush=True)
        time.sleep(max(1, INTERVAL_SECONDS - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
