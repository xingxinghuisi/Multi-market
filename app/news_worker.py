import argparse
import json
import os
import time
from datetime import datetime
from urllib.error import (
    HTTPError,
    URLError,
)
from urllib.request import (
    Request,
    urlopen,
)

MAX_AI_PER_CYCLE = int(
    os.getenv(
        "NEWS_MAX_AI_PER_CYCLE",
        "12",
    )
)


ASSET_INTERVAL = float(
    os.getenv(
        "NEWS_ASSET_INTERVAL",
        "1",
    )
)

API_BASE_URL = os.getenv(
    "MARKET_RADAR_API_URL",
    "http://127.0.0.1:8000",
).rstrip("/")


POLL_INTERVAL = int(
    os.getenv(
        "NEWS_POLL_INTERVAL",
        "1800",
    )
)


FETCH_LIMIT = int(
    os.getenv(
        "NEWS_FETCH_LIMIT",
        "3",
    )
)


REQUEST_TIMEOUT = int(
    os.getenv(
        "NEWS_REQUEST_TIMEOUT",
        "180",
    )
)


def log(
    message: str,
):

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(
        f"[NEWS] [{now}] {message}",
        flush=True,
    )


def request_json(
    url: str,
    method: str = "GET",
):

    request = Request(
        url=url,
        method=method,
        headers={
            "Accept":
                "application/json",
            "X-Radar-Worker-Token":
                os.getenv("RADAR_WORKER_TOKEN", ""),
        },
    )

    with urlopen(
        request,
        timeout=REQUEST_TIMEOUT,
    ) as response:

        raw = response.read()

    return json.loads(
        raw.decode("utf-8")
    )


def load_watched_news_assets():

    url = (
        f"{API_BASE_URL}"
        "/api/internal/news-watchlist"
    )

    data = request_json(
        url
    )

    if not isinstance(
        data,
        list,
    ):

        raise RuntimeError(
            "Watchlist API did not "
            "return a list"
        )

    assets = []

    for item in data:

        if not item.get(
            "enabled",
            False,
        ):
            continue

        if not item.get(
            "news_enabled",
            False,
        ):
            continue

        assets.append(
            {
                "id":
                    item["asset_id"],

                "symbol":
                    item["symbol"],

                "name":
                    item.get(
                        "name"
                    ),

                "asset_type":
                    item.get(
                        "asset_type"
                    ),

                "venue":
                    item.get(
                        "venue"
                    ),

                "segment":
                    item.get(
                        "segment"
                    ),

                "provider":
                    item.get(
                        "provider"
                    ),
            }
        )

    return assets


def fetch_asset_news(
    asset: dict,
    max_analyze: int,
):

    asset_id = asset[
        "id"
    ]

    symbol = asset.get(
        "symbol",
        "?",
    )

    url = (
        f"{API_BASE_URL}"
        f"/api/news/fetch/{asset_id}"
        f"?limit={FETCH_LIMIT}"
        f"&max_analyze={max_analyze}"
    )

    result = request_json(
        url,
        method="POST",
    )

    created_news = int(
        result.get(
            "created_news",
            0,
        )
        or 0
    )

    created_links = int(
        result.get(
            "created_links",
            0,
        )
        or 0
    )

    analyzed_news = int(
        result.get(
            "analyzed_news",
            0,
        )
        or 0
    )

    queued_news = int(
        result.get(
            "queued_news",
            0,
        )
        or 0
    )

    if (
            created_news > 0
            or created_links > 0
            or analyzed_news > 0
            or queued_news > 0
    ):
        log(
            f"{symbol} "
            f"id={asset_id} | "
            f"fetched={result.get('fetched')} | "
            f"new={created_news} | "
            f"links={created_links} | "
            f"analyzed={analyzed_news} | "
            f"queued={queued_news}"
        )

    return result


def analyze_pending(
    limit: int,
):

    if limit <= 0:

        return {
            "analyzed": 0,
        }

    url = (
        f"{API_BASE_URL}"
        "/api/news/analyze-pending"
        f"?limit={limit}"
    )

    return request_json(
        url,
        method="POST",
    )


def run_once():

    log(
        "Starting news scan"
    )

    assets = (
        load_watched_news_assets()
    )

    log(
        f"Watched news assets: "
        f"{len(assets)}"
    )

    success = 0
    failed = 0
    new_news = 0
    analyzed = 0
    queued = 0

    remaining_ai = (
        MAX_AI_PER_CYCLE
    )

    for asset in assets:

        symbol = asset.get(
            "symbol",
            "?",
        )

        asset_id = asset.get(
            "id",
            "?",
        )

        try:

            result = (
                fetch_asset_news(
                    asset,
                    max_analyze=remaining_ai,
                )
            )

            success += 1

            new_news += int(
                result.get(
                    "created_news",
                    0,
                )
                or 0
            )

            analyzed += int(
                result.get(
                    "analyzed_news",
                    0,
                )
                or 0
            )

            used_ai = int(
                result.get(
                    "analyzed_news",
                    0,
                )
                or 0
            )

            remaining_ai = max(
                0,
                remaining_ai
                - used_ai,
            )

            queued += int(
                result.get(
                    "queued_news",
                    0,
                )
                or 0
            )

        except HTTPError as error:

            failed += 1

            try:

                detail = (
                    error.read()
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )

            except Exception:

                detail = str(
                    error
                )

                time.sleep(
                    ASSET_INTERVAL
                )

            log(
                f"ERROR "
                f"{symbol} "
                f"id={asset_id} | "
                f"HTTP {error.code} | "
                f"{detail}"
            )

        except URLError as error:

            failed += 1

            log(
                f"ERROR "
                f"{symbol} "
                f"id={asset_id} | "
                f"API connection failed: "
                f"{error.reason}"
            )

        except Exception as error:

            failed += 1

            log(
                f"ERROR "
                f"{symbol} "
                f"id={asset_id} | "
                f"{type(error).__name__}: "
                f"{error}"
            )

    pending_analyzed = 0

    if remaining_ai > 0:

        try:

            pending_result = (
                analyze_pending(
                    remaining_ai
                )
            )

            pending_analyzed = int(
                pending_result.get(
                    "analyzed",
                    0,
                )
                or 0
            )

            analyzed += (
                pending_analyzed
            )

            remaining_ai = max(
                0,
                remaining_ai
                - pending_analyzed,
            )

            if pending_analyzed:
                log(
                    "Pending queue | "
                    f"analyzed="
                    f"{pending_analyzed}"
                )

        except Exception as error:

            log(
                "Pending queue error | "
                f"{type(error).__name__}: "
                f"{error}"
            )

    log(
        "Scan complete | "
        f"success={success} | "
        f"failed={failed} | "
        f"new_news={new_news} | "
        f"analyzed={analyzed} | "
        f"queued={queued} | "
        f"ai_budget_left={remaining_ai}"
    )


def run_forever():

    log(
        "News Worker started"
    )

    log(
        f"API: {API_BASE_URL}"
    )

    log(
        f"Interval: "
        f"{POLL_INTERVAL}s"
    )

    log(
        f"Fetch limit: "
        f"{FETCH_LIMIT}"
    )

    while True:

        started_at = (
            time.monotonic()
        )

        try:

            run_once()

        except Exception as error:

            log(
                "Worker cycle error | "
                f"{type(error).__name__}: "
                f"{error}"
            )

        elapsed = (
            time.monotonic()
            - started_at
        )

        sleep_seconds = max(
            1,
            POLL_INTERVAL
            - elapsed,
        )

        log(
            f"Next scan in "
            f"{int(sleep_seconds)}s"
        )

        time.sleep(
            sleep_seconds
        )


def main():

    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Run one scan and exit"
        ),
    )

    args = (
        parser.parse_args()
    )

    if args.once:

        run_once()

    else:

        run_forever()


if __name__ == "__main__":
    main()
