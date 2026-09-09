from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import date



from database import SessionLocal
from models import (
    DailyPrice,
    AlertRule,
    AlertState,
    Asset,
    User,
    MarketQuote,
)
from schemas import (
    AlertRuleCreate,
    AlertRuleUpdate,
    AssetCreate,
    AssetUpdate,
)


# =========================================================
# FastAPI
# =========================================================

app = FastAPI(
    title="Market Radar API",
    description=(
        "Market Radar Web / App Backend API"
    ),
    version="0.3.0",
)


# =========================================================
# Database Session
# =========================================================

def get_db():

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


# =========================================================
# Helpers
# =========================================================

def get_default_user(
    db: Session,
):

    user = db.scalar(
        select(User).where(
            User.username == "default"
        )
    )

    if not user:

        raise HTTPException(
            status_code=500,
            detail=(
                "Default user does not exist. "
                "Please run init_db.py first."
            ),
        )

    return user
def serialize_daily_price(
    daily_price: DailyPrice,
):

    return {
        "date": daily_price.date,
        "open": daily_price.open,
        "high": daily_price.high,
        "low": daily_price.low,
        "close": daily_price.close,
        "volume": daily_price.volume,
        "change_pct": daily_price.change_pct,
    }

def serialize_market_quote(
    quote: MarketQuote,
    asset: Asset,
):

    return {
        "asset_id": asset.id,
        "symbol": asset.symbol,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "venue": asset.venue,
        "segment": asset.segment,
        "currency": asset.currency,
        "provider": asset.provider,

        "price": quote.price,
        "reference_price": quote.reference_price,
        "change_amount": quote.change_amount,
        "change_pct": quote.change_pct,

        "open": quote.open,
        "high": quote.high,
        "low": quote.low,
        "volume": quote.volume,
        "quote_volume": quote.quote_volume,

        "event_time": quote.event_time,
        "session_date": quote.session_date,

        "reference_type": quote.reference_type,
        "reference_timezone": quote.reference_timezone,

        "updated_at": quote.updated_at,
    }

def serialize_asset(
    asset: Asset,
):

    return {
        "id": asset.id,
        "symbol": asset.symbol,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "venue": asset.venue,
        "segment": asset.segment,
        "currency": asset.currency,
        "provider": asset.provider,
        "enabled": asset.enabled,
        "created_at": asset.created_at,
    }

def get_asset_or_404(
    db: Session,
    asset_id: int,
):

    asset = db.get(
        Asset,
        asset_id,
    )

    if not asset:

        raise HTTPException(
            status_code=404,
            detail="Asset not found",
        )

    return asset


def get_rule_or_404(
    db: Session,
    rule_id: int,
):

    rule = db.get(
        AlertRule,
        rule_id,
    )

    if not rule:

        raise HTTPException(
            status_code=404,
            detail="Alert rule not found",
        )

    return rule


def reset_alert_state(
    db: Session,
    rule_id: int,
):
    """
    修改规则以后必须清除旧状态。

    例如：
    原规则 +3%
    改成 +5%

    旧 last_value / armed 状态
    不应该继续沿用。
    """

    state_model = db.scalar(
        select(AlertState).where(
            AlertState.rule_id
            == rule_id
        )
    )

    if state_model:

        db.delete(
            state_model
        )


def serialize_rule(
    rule,
    asset,
    user,
):

    return {
        "id": rule.id,

        "user": {
            "id": user.id,
            "username": user.username,
        },

        "asset": {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
            "provider": asset.provider,
        },

        "metric": rule.metric,
        "operator": rule.operator,
        "value": rule.value,

        "reset_buffer":
            rule.reset_buffer,

        "cooldown_seconds":
            rule.cooldown_seconds,

        "enabled":
            rule.enabled,

        "created_at":
            rule.created_at,
    }


# =========================================================
# Root
# =========================================================

@app.get("/")
def root():

    return {
        "app": "Market Radar",
        "api_version": "0.3.0",
        "status": "running",
    }


# =========================================================
# Health
# =========================================================

@app.get("/api/health")
def health():

    return {
        "status": "ok",
    }


# =========================================================
# Assets
# =========================================================

@app.get("/api/assets")
def get_assets(
    symbol: str | None = None,
    venue: str | None = None,
    asset_type: str | None = None,
    enabled: bool | None = None,
    db: Session = Depends(get_db),
):
    statement = select(
        Asset
    )

    if enabled is not None:
        statement = (
            statement.where(
                Asset.enabled
                == enabled
            )
        )

    if symbol:
        statement = statement.where(
            Asset.symbol == symbol.upper()
        )

    if venue:
        statement = statement.where(
            Asset.venue == venue.upper()
        )

    if asset_type:
        statement = statement.where(
            Asset.asset_type
            == asset_type.lower()
        )

    statement = statement.order_by(
        Asset.id
    )

    assets = db.scalars(
        statement
    ).all()

    return [
        {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
            "provider": asset.provider,
            "enabled": asset.enabled,
        }
        for asset in assets
    ]

@app.get(
    "/api/assets/{asset_id}"
)
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        asset_id,
    )

    return serialize_asset(
        asset
    )

@app.get(
    "/api/market/latest"
)
def get_latest_market_quotes(
    venue: str | None = None,
    asset_type: str | None = None,
    symbol: str | None = None,
    db: Session = Depends(get_db),
):

    statement = (
        select(
            MarketQuote,
            Asset,
        )
        .join(
            Asset,
            MarketQuote.asset_id
            == Asset.id,
        )
        .where(
            Asset.enabled == True
        )
    )

    if venue:

        statement = statement.where(
            Asset.venue
            == venue.strip().upper()
        )

    if asset_type:

        statement = statement.where(
            Asset.asset_type
            == asset_type.strip().lower()
        )

    if symbol:

        statement = statement.where(
            Asset.symbol
            == symbol.strip().upper()
        )

    statement = statement.order_by(
        Asset.id
    )

    rows = db.execute(
        statement
    ).all()

    return [
        serialize_market_quote(
            quote,
            asset,
        )
        for quote, asset in rows
    ]

@app.get(
    "/api/market/latest/assets/{asset_id}"
)
def get_latest_market_quote_by_asset(
    asset_id: int,
    db: Session = Depends(get_db),
):

    row = db.execute(
        select(
            MarketQuote,
            Asset,
        )
        .join(
            Asset,
            MarketQuote.asset_id
            == Asset.id,
        )
        .where(
            Asset.id == asset_id
        )
    ).first()

    if row is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Latest market quote "
                "not found"
            ),
        )

    quote, asset = row

    return serialize_market_quote(
        quote,
        asset,
    )

@app.get(
    "/api/market/history/assets/{asset_id}"
)
def get_market_history(
    asset_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):

    asset = db.get(
        Asset,
        asset_id,
    )

    if asset is None:

        raise HTTPException(
            status_code=404,
            detail="Asset not found",
        )

    if limit < 1 or limit > 1000:

        raise HTTPException(
            status_code=400,
            detail=(
                "limit must be "
                "between 1 and 1000"
            ),
        )

    statement = (
        select(
            DailyPrice
        )
        .where(
            DailyPrice.asset_id
            == asset_id
        )
    )

    if start_date is not None:

        statement = statement.where(
            DailyPrice.date
            >= start_date
        )

    if end_date is not None:

        statement = statement.where(
            DailyPrice.date
            <= end_date
        )

    statement = (
        statement
        .order_by(
            DailyPrice.date.desc()
        )
        .limit(
            limit
        )
    )

    rows = db.scalars(
        statement
    ).all()

    return {
        "asset": {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "venue": asset.venue,
            "currency": asset.currency,
        },

        "count": len(
            rows
        ),

        "data": [
            serialize_daily_price(
                row
            )
            for row in rows
        ],
    }

@app.post(
    "/api/assets",
    status_code=status.HTTP_201_CREATED,
)
def create_asset(
    payload: AssetCreate,
    db: Session = Depends(get_db),
):

    # =====================================================
    # 标准化输入
    # =====================================================

    symbol = (
        payload.symbol
        .strip()
        .upper()
    )

    venue = (
        payload.venue
        .strip()
        .upper()
    )

    segment = (
        payload.segment
        .strip()
        .upper()
    )

    provider = (
        payload.provider
        .strip()
        .upper()
    )

    currency = (
        payload.currency
        .strip()
        .upper()
    )

    asset_type = (
        payload.asset_type
        .strip()
        .lower()
    )

    name = (
        payload.name
        .strip()
    )

    # =====================================================
    # 检查重复
    #
    # 唯一键：
    # venue + segment + symbol
    # =====================================================

    existing = db.scalar(
        select(Asset).where(
            Asset.symbol == symbol,
            Asset.venue == venue,
            Asset.segment == segment,
        )
    )

    if existing:

        raise HTTPException(
            status_code=409,
            detail=(
                "Asset already exists: "
                f"{venue}/"
                f"{segment}/"
                f"{symbol}"
            ),
        )

    # =====================================================
    # 创建
    # =====================================================

    asset = Asset(

        symbol=symbol,

        name=name,

        asset_type=asset_type,

        venue=venue,

        segment=segment,

        currency=currency,

        provider=provider,

        enabled=payload.enabled,
    )

    db.add(
        asset
    )

    try:

        db.commit()

    except IntegrityError:

        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="Asset already exists",
        )

    db.refresh(
        asset
    )

    return serialize_asset(
        asset
    )

@app.patch(
    "/api/assets/{asset_id}"
)
def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        asset_id,
    )

    updates = payload.model_dump(
        exclude_unset=True
    )

    if not updates:

        raise HTTPException(
            status_code=400,
            detail="No fields to update",
        )

    # =====================================================
    # 标准化字段
    # =====================================================

    upper_fields = {
        "symbol",
        "venue",
        "segment",
        "currency",
        "provider",
    }

    for key, value in (
        updates.items()
    ):

        if (
            isinstance(
                value,
                str,
            )
        ):

            value = (
                value.strip()
            )

            if (
                key
                in upper_fields
            ):

                value = (
                    value.upper()
                )

            elif (
                key
                == "asset_type"
            ):

                value = (
                    value.lower()
                )

        setattr(
            asset,
            key,
            value,
        )

    # =====================================================
    # 保存
    # =====================================================

    try:

        db.commit()

    except IntegrityError:

        db.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                "Asset with the same "
                "venue / segment / symbol "
                "already exists"
            ),
        )

    db.refresh(
        asset
    )

    return serialize_asset(
        asset
    )

@app.delete(
    "/api/assets/{asset_id}"
)
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        asset_id,
    )

    # =====================================================
    # V0.11 使用软删除
    #
    # 保留历史 Alert / Notification 数据
    # =====================================================

    asset.enabled = False

    db.commit()

    db.refresh(
        asset
    )

    return {
        "deleted": True,
        "soft_delete": True,
        "asset": serialize_asset(
            asset
        ),
    }

# =========================================================
# Stocks
# =========================================================

@app.get("/api/stocks")
def get_stocks(
    db: Session = Depends(get_db),
):

    assets = db.scalars(
        select(Asset)
        .where(
            Asset.enabled == True,
            Asset.asset_type == "stock",
        )
        .order_by(
            Asset.id
        )
    ).all()

    return [
        {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
            "provider": asset.provider,
            "enabled": asset.enabled,
        }
        for asset in assets
    ]


# =========================================================
# Crypto
# =========================================================

@app.get("/api/crypto")
def get_crypto_assets(
    db: Session = Depends(get_db),
):

    assets = db.scalars(
        select(Asset)
        .where(
            Asset.enabled == True,
            Asset.asset_type == "crypto",
        )
        .order_by(
            Asset.id
        )
    ).all()

    return [
        {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
            "provider": asset.provider,
            "enabled": asset.enabled,
        }
        for asset in assets
    ]


# =========================================================
# 获取所有 Alert Rules
# =========================================================

@app.get("/api/alert-rules")
def get_alert_rules(
    db: Session = Depends(get_db),
):

    statement = (
        select(
            AlertRule,
            Asset,
            User,
        )
        .join(
            Asset,
            AlertRule.asset_id
            == Asset.id,
        )
        .join(
            User,
            AlertRule.user_id
            == User.id,
        )
        .order_by(
            AlertRule.id
        )
    )

    rows = db.execute(
        statement
    ).all()

    return [
        serialize_rule(
            rule,
            asset,
            user,
        )
        for (
            rule,
            asset,
            user,
        ) in rows
    ]


# =========================================================
# 获取单条 Alert Rule
# =========================================================

@app.get(
    "/api/alert-rules/{rule_id}"
)
def get_alert_rule(
    rule_id: int,
    db: Session = Depends(get_db),
):

    rule = get_rule_or_404(
        db,
        rule_id,
    )

    asset = get_asset_or_404(
        db,
        rule.asset_id,
    )

    user = db.get(
        User,
        rule.user_id,
    )

    return serialize_rule(
        rule,
        asset,
        user,
    )


# =========================================================
# 创建 Alert Rule
# =========================================================

@app.post(
    "/api/alert-rules",
    status_code=status.HTTP_201_CREATED,
)
def create_alert_rule(
    payload: AlertRuleCreate,
    db: Session = Depends(get_db),
):

    user = get_default_user(
        db
    )

    asset = get_asset_or_404(
        db,
        payload.asset_id,
    )

    rule = AlertRule(
        user_id=user.id,

        asset_id=asset.id,

        metric=payload.metric,

        operator=payload.operator,

        value=payload.value,

        reset_buffer=(
            payload.reset_buffer
        ),

        cooldown_seconds=(
            payload.cooldown_seconds
        ),

        enabled=payload.enabled,
    )

    db.add(rule)

    db.commit()

    db.refresh(rule)

    return serialize_rule(
        rule,
        asset,
        user,
    )


# =========================================================
# 修改 Alert Rule
# =========================================================

@app.patch(
    "/api/alert-rules/{rule_id}"
)
def update_alert_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    db: Session = Depends(get_db),
):

    rule = get_rule_or_404(
        db,
        rule_id,
    )

    updates = payload.model_dump(
        exclude_unset=True
    )

    if not updates:

        raise HTTPException(
            status_code=400,
            detail="No fields to update",
        )

    # ---------------------------------------------
    # 修改规则参数
    # ---------------------------------------------

    for key, value in updates.items():

        setattr(
            rule,
            key,
            value,
        )

    # ---------------------------------------------
    # 规则改变以后：
    # 清除旧 AlertState
    # ---------------------------------------------

    reset_alert_state(
        db,
        rule.id,
    )

    db.commit()

    db.refresh(rule)

    asset = get_asset_or_404(
        db,
        rule.asset_id,
    )

    user = db.get(
        User,
        rule.user_id,
    )

    return serialize_rule(
        rule,
        asset,
        user,
    )


# =========================================================
# 删除 Alert Rule
# =========================================================

@app.delete(
    "/api/alert-rules/{rule_id}"
)
def delete_alert_rule(
    rule_id: int,
    db: Session = Depends(get_db),
):

    rule = get_rule_or_404(
        db,
        rule_id,
    )

    # 删除关联 AlertState
    reset_alert_state(
        db,
        rule.id,
    )

    db.delete(
        rule
    )

    db.commit()

    return {
        "deleted": True,
        "rule_id": rule_id,
    }