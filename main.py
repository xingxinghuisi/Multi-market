import json
from datetime import datetime, timedelta
from pathlib import Path

from pykrx import stock

from telegram_service import send_telegram_message


# =========================================================
# 股票列表
# =========================================================

WATCHLIST = [
    {
        "ticker": "000660",
        "name": "SK Hynix",
    },
    {
        "ticker": "005930",
        "name": "Samsung Electronics",
    },
    {
        "ticker": "035420",
        "name": "NAVER",
    },
    {
        "ticker": "005380",
        "name": "Hyundai Motor",
    },
    {
        "ticker": "035720",
        "name": "Kakao",
    },
]


# =========================================================
# 提醒阈值
# =========================================================

ALERT_PERCENT = 3.0
STRONG_ALERT_PERCENT = 5.0


# =========================================================
# 状态文件
# =========================================================

DATA_DIR = Path("data")

STATE_FILE = DATA_DIR / "alert_state.json"


# =========================================================
# 获取股票行情
# =========================================================

def get_stock_data(ticker):

    end_date = datetime.now()

    start_date = (
        end_date
        - timedelta(days=14)
    )

    start = start_date.strftime(
        "%Y%m%d"
    )

    end = end_date.strftime(
        "%Y%m%d"
    )

    df = stock.get_market_ohlcv_by_date(
        start,
        end,
        ticker,
    )

    if df.empty:
        return None

    if len(df) < 2:
        return None

    latest = df.iloc[-1]

    previous = df.iloc[-2]

    latest_date = df.index[-1]

    current_price = int(
        latest["종가"]
    )

    previous_close = int(
        previous["종가"]
    )

    change_pct = (
        (
            current_price
            - previous_close
        )
        / previous_close
        * 100
    )

    return {
        "date": latest_date,
        "price": current_price,
        "previous_close": previous_close,
        "change_pct": change_pct,
        "volume": int(
            latest["거래량"]
        ),
        "open": int(
            latest["시가"]
        ),
        "high": int(
            latest["고가"]
        ),
        "low": int(
            latest["저가"]
        ),
    }


# =========================================================
# 判断提醒等级
# =========================================================

def get_alert_type(change_pct):

    if (
        change_pct
        >= STRONG_ALERT_PERCENT
    ):
        return "UP_5"

    if (
        change_pct
        >= ALERT_PERCENT
    ):
        return "UP_3"

    if (
        change_pct
        <= -STRONG_ALERT_PERCENT
    ):
        return "DOWN_5"

    if (
        change_pct
        <= -ALERT_PERCENT
    ):
        return "DOWN_3"

    return None


def get_alert_name(alert_type):

    names = {
        "UP_3": "📈 上涨提醒",
        "UP_5": "🔥 强上涨提醒",
        "DOWN_3": "📉 下跌提醒",
        "DOWN_5": "🚨 强下跌提醒",
    }

    return names.get(
        alert_type,
        "正常",
    )


def get_alert_condition(alert_type):

    conditions = {
        "UP_3": "上涨 ≥ +3%",
        "UP_5": "上涨 ≥ +5%",
        "DOWN_3": "下跌 ≤ -3%",
        "DOWN_5": "下跌 ≤ -5%",
    }

    return conditions.get(
        alert_type,
        "",
    )


# =========================================================
# 读取提醒状态
# =========================================================

def load_state(trading_date):

    DATA_DIR.mkdir(
        exist_ok=True
    )

    if not STATE_FILE.exists():

        return {
            "date": trading_date,
            "sent": {},
        }

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            state = json.load(file)

    except Exception:

        return {
            "date": trading_date,
            "sent": {},
        }

    # 新交易日自动清空提醒记录
    if (
        state.get("date")
        != trading_date
    ):

        return {
            "date": trading_date,
            "sent": {},
        }

    return state


# =========================================================
# 保存提醒状态
# =========================================================

def save_state(state):

    DATA_DIR.mkdir(
        exist_ok=True
    )

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )


# =========================================================
# 判断是否已经提醒
# =========================================================

def already_sent(
    state,
    ticker,
    alert_type,
):

    sent = state.get(
        "sent",
        {}
    )

    ticker_alerts = sent.get(
        ticker,
        []
    )

    return (
        alert_type
        in ticker_alerts
    )


# =========================================================
# 标记提醒已发送
# =========================================================

def mark_sent(
    state,
    ticker,
    alert_type,
):

    if ticker not in state["sent"]:
        state["sent"][ticker] = []

    if (
        alert_type
        not in state["sent"][ticker]
    ):
        state["sent"][ticker].append(
            alert_type
        )


# =========================================================
# 生成 Telegram 消息
# =========================================================

def build_alert_message(
    data,
    alert_type,
):

    alert_name = get_alert_name(
        alert_type
    )

    condition = get_alert_condition(
        alert_type
    )

    return (
        f"{alert_name}\n\n"
        f"{data['name']}\n"
        f"{data['ticker']}\n\n"

        f"当前价格："
        f"{data['price']:,} KRW\n"

        f"今日涨跌："
        f"{data['change_pct']:+.2f}%\n"

        f"成交量："
        f"{data['volume']:,}\n\n"

        f"触发条件：\n"
        f"{condition}\n\n"

        f"交易日："
        f"{data['date']:%Y-%m-%d}"
    )


# =========================================================
# 主程序
# =========================================================

def main():

    print()
    print("=" * 75)
    print("Korea Market Radar V0.1")
    print("=" * 75)

    print(
        f"监控规则："
        f"±{ALERT_PERCENT:.0f}% 提醒 / "
        f"±{STRONG_ALERT_PERCENT:.0f}% 强提醒"
    )

    print()

    results = []

    # =====================================================
    # 获取所有股票
    # =====================================================

    for item in WATCHLIST:

        ticker = item["ticker"]
        name = item["name"]

        print(
            f"正在获取："
            f"{name} ({ticker}) ..."
        )

        try:

            data = get_stock_data(
                ticker
            )

            if data is None:

                print(
                    "  ❌ 没有行情数据"
                )

                continue

            data["ticker"] = ticker
            data["name"] = name

            results.append(data)

        except Exception as error:

            print(
                f"  ❌ 获取失败："
                f"{error}"
            )

    if not results:

        print(
            "没有成功获取任何股票数据。"
        )

        return

    # =====================================================
    # 今天交易日
    # =====================================================

    latest_date = max(
        data["date"]
        for data in results
    )

    trading_date = (
        latest_date.strftime(
            "%Y-%m-%d"
        )
    )

    state = load_state(
        trading_date
    )

    # =====================================================
    # 显示市场扫描
    # =====================================================

    print()
    print("=" * 75)
    print("市场扫描结果")
    print("=" * 75)

    for data in results:

        alert_type = get_alert_type(
            data["change_pct"]
        )

        alert_name = (
            get_alert_name(
                alert_type
            )
            if alert_type
            else "正常"
        )

        print()

        print(
            f"{data['name']} "
            f"({data['ticker']})"
        )

        print(
            f"价格："
            f"{data['price']:,} KRW"
        )

        print(
            f"涨跌："
            f"{data['change_pct']:+.2f}%"
        )

        print(
            f"成交量："
            f"{data['volume']:,}"
        )

        print(
            f"状态：{alert_name}"
        )

    # =====================================================
    # 提醒检测
    # =====================================================

    print()
    print("=" * 75)
    print("⚡ 提醒检测")
    print("=" * 75)

    triggered_count = 0

    for data in results:

        alert_type = get_alert_type(
            data["change_pct"]
        )

        if not alert_type:
            continue

        alert_name = get_alert_name(
            alert_type
        )

        # 已经发过
        if already_sent(
            state,
            data["ticker"],
            alert_type,
        ):

            print(
                f"⏭ 已提醒："
                f"{data['name']} "
                f"{alert_name}"
            )

            continue

        message = build_alert_message(
            data,
            alert_type,
        )

        success = (
            send_telegram_message(
                message
            )
        )

        if success:

            print(
                f"✅ 已发送："
                f"{data['name']} "
                f"{alert_name}"
            )

            mark_sent(
                state,
                data["ticker"],
                alert_type,
            )

            triggered_count += 1

        else:

            print(
                f"❌ 发送失败："
                f"{data['name']}"
            )

    save_state(state)

    if triggered_count == 0:

        print()
        print(
            "本次没有新的提醒需要发送。"
        )

    print()
    print("=" * 75)
    print("扫描完成")
    print("=" * 75)


if __name__ == "__main__":
    main()