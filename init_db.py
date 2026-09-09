from sqlalchemy import select

from database import (
    Base,
    SessionLocal,
    engine,
)

from models import (
    AlertRule,
    Asset,
    User,
)


# =========================================================
# 初始资产
# =========================================================

ASSETS = [
    {
        "symbol": "000660",
        "name": "SK Hynix",
        "asset_type": "stock",
        "venue": "KRX",
        "segment": "KOSPI",
        "currency": "KRW",
        "provider": "PYKRX",
    },
    {
        "symbol": "005930",
        "name": "Samsung Electronics",
        "asset_type": "stock",
        "venue": "KRX",
        "segment": "KOSPI",
        "currency": "KRW",
        "provider": "PYKRX",
    },
    {
        "symbol": "035420",
        "name": "NAVER",
        "asset_type": "stock",
        "venue": "KRX",
        "segment": "KOSPI",
        "currency": "KRW",
        "provider": "PYKRX",
    },
    {
        "symbol": "005380",
        "name": "Hyundai Motor",
        "asset_type": "stock",
        "venue": "KRX",
        "segment": "KOSPI",
        "currency": "KRW",
        "provider": "PYKRX",
    },
    {
        "symbol": "035720",
        "name": "Kakao",
        "asset_type": "stock",
        "venue": "KRX",
        "segment": "KOSPI",
        "currency": "KRW",
        "provider": "PYKRX",
    },

    # 先加入两个币种，证明数据库架构已经支持 Crypto
    {
        "symbol": "BTCUSDT",
        "name": "Bitcoin / USDT",
        "asset_type": "crypto",
        "venue": "BINANCE",
        "segment": "SPOT",
        "currency": "USDT",
        "provider": "BINANCE",
    },
    {
        "symbol": "ETHUSDT",
        "name": "Ethereum / USDT",
        "asset_type": "crypto",
        "venue": "BINANCE",
        "segment": "SPOT",
        "currency": "USDT",
        "provider": "BINANCE",
    },
]


# =========================================================
# 初始规则
# =========================================================

DEFAULT_RULES = [
    {
        "symbol": "000660",
        "venue": "KRX",
        "segment": "KOSPI",
        "metric": "change_pct",
        "operator": "crossing_up",
        "value": 3.0,
        "reset_buffer": 0.2,
        "cooldown_seconds": 300,
    },
    {
        "symbol": "000660",
        "venue": "KRX",
        "segment": "KOSPI",
        "metric": "change_pct",
        "operator": "crossing_down",
        "value": -3.0,
        "reset_buffer": 0.2,
        "cooldown_seconds": 300,
    },
    {
        "symbol": "000660",
        "venue": "KRX",
        "segment": "KOSPI",
        "metric": "price",
        "operator": "crossing_up",
        "value": 1900000,
        "reset_buffer": 10000,
        "cooldown_seconds": 300,
    },
    {
        "symbol": "000660",
        "venue": "KRX",
        "segment": "KOSPI",
        "metric": "price_change",
        "operator": "crossing_up",
        "value": 50000,
        "reset_buffer": 10000,
        "cooldown_seconds": 300,
    },
]


def create_tables():

    Base.metadata.create_all(
        bind=engine
    )

    print("✅ 数据库表创建完成")


def create_default_user(session):

    user = session.scalar(
        select(User).where(
            User.username == "default"
        )
    )

    if user:
        return user

    user = User(
        username="default"
    )

    session.add(user)
    session.flush()

    print("✅ 默认用户创建完成")

    return user


def create_assets(session):

    for item in ASSETS:

        existing = session.scalar(
            select(Asset).where(
                Asset.symbol == item["symbol"],
                Asset.venue == item["venue"],
                Asset.segment == item["segment"],
            )
        )

        if existing:
            continue

        asset = Asset(
            symbol=item["symbol"],
            name=item["name"],
            asset_type=item["asset_type"],
            venue=item["venue"],
            segment=item["segment"],
            currency=item["currency"],
            provider=item["provider"],
        )

        session.add(asset)

        print(
            f"✅ 添加资产："
            f"{item['name']} "
            f"[{item['venue']}]"
        )


def create_default_rules(
    session,
    user,
):

    for item in DEFAULT_RULES:

        asset = session.scalar(
            select(Asset).where(
                Asset.symbol
                == item["symbol"],

                Asset.venue
                == item["venue"],

                Asset.segment
                == item["segment"],
            )
        )

        if not asset:
            continue

        existing = session.scalar(
            select(AlertRule).where(
                AlertRule.user_id
                == user.id,

                AlertRule.asset_id
                == asset.id,

                AlertRule.metric
                == item["metric"],

                AlertRule.operator
                == item["operator"],

                AlertRule.value
                == item["value"],
            )
        )

        if existing:
            continue

        rule = AlertRule(
            user_id=user.id,
            asset_id=asset.id,
            metric=item["metric"],
            operator=item["operator"],
            value=item["value"],
            reset_buffer=item[
                "reset_buffer"
            ],
            cooldown_seconds=item[
                "cooldown_seconds"
            ],
            enabled=True,
        )

        session.add(rule)

        print(
            f"✅ 创建规则："
            f"{asset.name} | "
            f"{item['metric']} | "
            f"{item['operator']} | "
            f"{item['value']}"
        )


def main():

    create_tables()

    with SessionLocal() as session:

        user = create_default_user(
            session
        )

        create_assets(
            session
        )

        session.flush()

        create_default_rules(
            session,
            user,
        )

        session.commit()

    print()
    print("✅ 数据库初始化完成")


if __name__ == "__main__":
    main()