import argparse
import os
import time

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import requests

from telegram_service import (
    send_telegram_message,
)


API_BASE_URL = os.getenv(
    "MARKET_RADAR_API_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

BINANCE_FUTURES_BASE_URL = os.getenv(
    "BINANCE_FUTURES_BASE_URL",
    "https://fapi.binance.com",
).rstrip("/")

PERIOD = "1h"

PUSH_MINUTE = int(
    os.getenv(
        "CRYPTO_METRICS_PUSH_MINUTE",
        "2",
    )
)

REQUEST_TIMEOUT = int(
    os.getenv(
        "CRYPTO_METRICS_REQUEST_TIMEOUT",
        "15",
    )
)

UTC8 = timezone(
    timedelta(hours=8)
)


CONTRACT_SEGMENTS = {
    "FUTURES",
    "FUTURE",
    "PERPETUAL",
    "USDT_PERPETUAL",
    "USDT_FUTURES",
    "USD_M",
    "USD-M",
    "UM_FUTURES",
    "DELIVERY",
    "CONTRACT",
    "SWAP",
}


def log(message):
    now = datetime.now(
        UTC8
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(
        f"[CRYPTO METRICS] "
        f"[{now}] "
        f"{message}",
        flush=True,
    )


def is_contract_segment(
    segment,
):
    if not segment:
        return False

    value = (
        str(segment)
        .strip()
        .upper()
    )

    if value == "SPOT":
        return False

    if value in CONTRACT_SEGMENTS:
        return True

    markers = (
        "FUTURE",
        "PERPETUAL",
        "DELIVERY",
        "CONTRACT",
        "SWAP",
    )

    return any(
        marker in value
        for marker in markers
    )


def load_watched_contract_assets():
    # 推送名单来源：推送订阅表（alert_type=longshort_digest）。
    # 原来读的是观察名单全部启用合约（"一刀切"），现改为只推订阅了的币。
    response = requests.get(
        f"{API_BASE_URL}/api/internal/subscriptions",
        params={
            "alert_type":
                "longshort_digest",
        },
        headers={"X-Radar-Worker-Token": os.getenv("RADAR_WORKER_TOKEN", "")},
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(
        data,
        list,
    ):
        raise RuntimeError(
            "Subscriptions API did not "
            "return a list"
        )

    assets = []
    seen_symbols = set()

    for item in data:

        venue = str(
            item.get(
                "venue",
                "",
            )
        ).upper()

        if venue != "BINANCE":
            continue

        segment = item.get(
            "segment"
        )

        if not is_contract_segment(
            segment
        ):
            continue

        symbol = str(
            item.get(
                "symbol",
                "",
            )
        ).upper()

        if not symbol:
            continue

        # 同一个 symbol 避免重复推送
        if symbol in seen_symbols:
            continue

        seen_symbols.add(
            symbol
        )

        assets.append(
            {
                "asset_id":
                    item.get(
                        "asset_id"
                    ),
                "symbol":
                    symbol,
                "name":
                    item.get(
                        "name"
                    ),
                "segment":
                    segment,
            }
        )

    return assets


def fetch_binance_rows(
    endpoint,
    symbol,
):
    url = (
        f"{BINANCE_FUTURES_BASE_URL}"
        f"/futures/data/"
        f"{endpoint}"
    )

    response = requests.get(
        url,
        params={
            "symbol":
                symbol,
            "period":
                PERIOD,
            "limit":
                8,
        },
        headers={
            "User-Agent":
                "Market-Radar/1.0",
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(
        data,
        list,
    ):
        raise RuntimeError(
            f"{endpoint} "
            f"returned invalid data: "
            f"{data}"
        )

    return data


def find_timestamp_row(
    rows,
    target_ms,
):
    for row in rows:

        try:
            timestamp = int(
                row.get(
                    "timestamp"
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        if timestamp == target_ms:
            return row

    return None


def ratio_value(
    row,
    field,
):
    return float(
        row[field]
    )


def direction_arrow(
    current,
    previous,
):
    difference = (
        current
        - previous
    )

    if abs(
        difference
    ) < 0.00005:
        return "→"

    if difference > 0:
        return "↑"

    return "↓"


def build_hour_targets():
    now_utc = datetime.now(
        timezone.utc
    )

    # 当前整点。
    # 例如现在 22:02，
    # 刚结束完整周期就是：
    # 21:00 - 22:00
    hour_end = (
        now_utc.replace(
            minute=0,
            second=0,
            microsecond=0,
        )
    )

    hour_start = (
        hour_end
        - timedelta(
            hours=1
        )
    )

    previous_start = (
        hour_start
        - timedelta(
            hours=1
        )
    )

    return {
        "hour_start":
            hour_start,
        "hour_end":
            hour_end,
        "previous_start":
            previous_start,
    }


def fetch_metrics(
    symbol,
):
    targets = (
        build_hour_targets()
    )

    hour_start = targets[
        "hour_start"
    ]

    hour_end = targets[
        "hour_end"
    ]

    previous_start = targets[
        "previous_start"
    ]

    # =====================================
    # Binance 三个账户/持仓 Ratio 接口
    #
    # 根据当前接口返回方式：
    # timestamp 使用周期结束整点。
    #
    # 例如：
    # 21:00-22:00
    # timestamp = 22:00
    # =====================================

    global_rows = (
        fetch_binance_rows(
            "globalLongShortAccountRatio",
            symbol,
        )
    )

    top_account_rows = (
        fetch_binance_rows(
            "topLongShortAccountRatio",
            symbol,
        )
    )

    top_position_rows = (
        fetch_binance_rows(
            "topLongShortPositionRatio",
            symbol,
        )
    )

    # =====================================
    # Taker 接口
    #
    # timestamp 使用周期开始整点。
    #
    # 例如：
    # 21:00-22:00
    # timestamp = 21:00
    # =====================================

    taker_rows = (
        fetch_binance_rows(
            "takerlongshortRatio",
            symbol,
        )
    )

    hour_end_ms = int(
        hour_end.timestamp()
        * 1000
    )

    hour_start_ms = int(
        hour_start.timestamp()
        * 1000
    )

    previous_start_ms = int(
        previous_start.timestamp()
        * 1000
    )

    # 当前完整小时

    global_current = (
        find_timestamp_row(
            global_rows,
            hour_end_ms,
        )
    )

    top_account_current = (
        find_timestamp_row(
            top_account_rows,
            hour_end_ms,
        )
    )

    top_position_current = (
        find_timestamp_row(
            top_position_rows,
            hour_end_ms,
        )
    )

    taker_current = (
        find_timestamp_row(
            taker_rows,
            hour_start_ms,
        )
    )

    # 上一个完整小时

    global_previous = (
        find_timestamp_row(
            global_rows,
            hour_start_ms,
        )
    )

    top_account_previous = (
        find_timestamp_row(
            top_account_rows,
            hour_start_ms,
        )
    )

    top_position_previous = (
        find_timestamp_row(
            top_position_rows,
            hour_start_ms,
        )
    )

    taker_previous = (
        find_timestamp_row(
            taker_rows,
            previous_start_ms,
        )
    )

    required = {
        "global_current":
            global_current,
        "global_previous":
            global_previous,
        "top_account_current":
            top_account_current,
        "top_account_previous":
            top_account_previous,
        "top_position_current":
            top_position_current,
        "top_position_previous":
            top_position_previous,
        "taker_current":
            taker_current,
        "taker_previous":
            taker_previous,
    }

    missing = [
        name
        for name, row
        in required.items()
        if row is None
    ]

    if missing:
        raise RuntimeError(
            "missing completed "
            "1H data: "
            + ", ".join(
                missing
            )
        )

    return {
        "hour_start":
            hour_start,
        "hour_end":
            hour_end,

        "global_current":
            global_current,
        "global_previous":
            global_previous,

        "top_account_current":
            top_account_current,
        "top_account_previous":
            top_account_previous,

        "top_position_current":
            top_position_current,
        "top_position_previous":
            top_position_previous,

        "taker_current":
            taker_current,
        "taker_previous":
            taker_previous,
    }


def build_message(
    symbol,
    metrics,
):
    global_current = metrics[
        "global_current"
    ]

    global_previous = metrics[
        "global_previous"
    ]

    top_account_current = metrics[
        "top_account_current"
    ]

    top_account_previous = metrics[
        "top_account_previous"
    ]

    top_position_current = metrics[
        "top_position_current"
    ]

    top_position_previous = metrics[
        "top_position_previous"
    ]

    taker_current = metrics[
        "taker_current"
    ]

    taker_previous = metrics[
        "taker_previous"
    ]

    global_ratio = ratio_value(
        global_current,
        "longShortRatio",
    )

    global_previous_ratio = (
        ratio_value(
            global_previous,
            "longShortRatio",
        )
    )

    top_account_ratio = (
        ratio_value(
            top_account_current,
            "longShortRatio",
        )
    )

    top_account_previous_ratio = (
        ratio_value(
            top_account_previous,
            "longShortRatio",
        )
    )

    top_position_ratio = (
        ratio_value(
            top_position_current,
            "longShortRatio",
        )
    )

    top_position_previous_ratio = (
        ratio_value(
            top_position_previous,
            "longShortRatio",
        )
    )

    taker_ratio = ratio_value(
        taker_current,
        "buySellRatio",
    )

    taker_previous_ratio = (
        ratio_value(
            taker_previous,
            "buySellRatio",
        )
    )

    long_pct = (
        ratio_value(
            global_current,
            "longAccount",
        )
        * 100
    )

    short_pct = (
        ratio_value(
            global_current,
            "shortAccount",
        )
        * 100
    )

    global_arrow = (
        direction_arrow(
            global_ratio,
            global_previous_ratio,
        )
    )

    top_account_arrow = (
        direction_arrow(
            top_account_ratio,
            top_account_previous_ratio,
        )
    )

    top_position_arrow = (
        direction_arrow(
            top_position_ratio,
            top_position_previous_ratio,
        )
    )

    taker_arrow = (
        direction_arrow(
            taker_ratio,
            taker_previous_ratio,
        )
    )

    hour_start = (
        metrics[
            "hour_start"
        ]
        .astimezone(
            UTC8
        )
    )

    hour_end = (
        metrics[
            "hour_end"
        ]
        .astimezone(
            UTC8
        )
    )

    period_text = (
        f"{hour_start:%H:%M}"
        f"–"
        f"{hour_end:%H:%M}"
    )

    date_text = (
        hour_start.strftime(
            "%Y年%m月%d日"
        )
    )

    return (
        f"📊 {symbol} 1H 多空数据\n"
        f"全体 多{long_pct:.2f}% / "
        f"空{short_pct:.2f}% ｜ "
        f"{global_ratio:.2f} "
        f"{global_arrow}\n\n"

        f"全体账户："
        f"{global_ratio:.2f} "
        f"{global_arrow} "
        f"｜上小时 "
        f"{global_previous_ratio:.2f}\n"

        f"大户账户："
        f"{top_account_ratio:.2f} "
        f"{top_account_arrow} "
        f"｜上小时 "
        f"{top_account_previous_ratio:.2f}\n"

        f"大户持仓："
        f"{top_position_ratio:.2f} "
        f"{top_position_arrow} "
        f"｜上小时 "
        f"{top_position_previous_ratio:.2f}\n"

        f"主动买卖："
        f"{taker_ratio:.2f} "
        f"{taker_arrow} "
        f"｜上小时 "
        f"{taker_previous_ratio:.2f}\n\n"

        f"🕐 {date_text} "
        f"{period_text}"
    )


def run_once(
    dry_run=False,
):
    assets = (
        load_watched_contract_assets()
    )

    log(
        "Watched Binance "
        f"crypto contracts: "
        f"{len(assets)}"
    )

    if not assets:
        log(
            "No watched Binance "
            "crypto contracts"
        )
        return

    success = 0
    failed = 0

    for asset in assets:

        symbol = asset[
            "symbol"
        ]

        segment = asset.get(
            "segment"
        )

        try:
            log(
                f"Fetching {symbol} "
                f"| segment={segment}"
            )

            metrics = (
                fetch_metrics(
                    symbol
                )
            )

            message = (
                build_message(
                    symbol,
                    metrics,
                )
            )

            if dry_run:
                print()
                print(
                    "===== DRY RUN ====="
                )
                print(message)
                print(
                    "==================="
                )
                print()

            else:
                sent = (
                    send_telegram_message(
                        message
                    )
                )

                if not sent:
                    raise RuntimeError(
                        "Telegram send failed"
                    )

                log(
                    f"SENT {symbol}"
                )

            success += 1

        except Exception as error:
            failed += 1

            log(
                f"SKIP {symbol} | "
                f"{type(error).__name__}: "
                f"{error}"
            )

    log(
        f"Cycle complete | "
        f"success={success} | "
        f"failed={failed}"
    )


def next_run_time():
    now = datetime.now(
        timezone.utc
    )

    next_run = (
        now.replace(
            minute=PUSH_MINUTE,
            second=0,
            microsecond=0,
        )
    )

    if next_run <= now:
        next_run += timedelta(
            hours=1
        )

    return next_run


def run_forever(
    dry_run=False,
):
    log(
        "Crypto Metrics Worker started"
    )

    log(
        f"Push minute: "
        f"HH:{PUSH_MINUTE:02d}"
    )

    while True:

        next_run = (
            next_run_time()
        )

        next_local = (
            next_run.astimezone(
                UTC8
            )
        )

        sleep_seconds = max(
            1,
            (
                next_run
                - datetime.now(
                    timezone.utc
                )
            ).total_seconds(),
        )

        log(
            "Next run: "
            f"{next_local:%Y-%m-%d %H:%M:%S}"
        )

        time.sleep(
            sleep_seconds
        )

        try:
            run_once(
                dry_run=dry_run
            )

        except Exception as error:
            log(
                "Worker cycle error | "
                f"{type(error).__name__}: "
                f"{error}"
            )


def main():
    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--once",
        action="store_true",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    args = parser.parse_args()

    if args.once:
        run_once(
            dry_run=args.dry_run
        )
    else:
        run_forever(
            dry_run=args.dry_run
        )


if __name__ == "__main__":
    main()
