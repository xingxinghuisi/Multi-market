from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal
from models import (
    AlertRule,
    AlertState,
    Asset,
    User,
)
from schemas import (
    AlertRuleCreate,
    AlertRuleUpdate,
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
    db: Session = Depends(get_db),
):

    statement = select(Asset).where(
        Asset.enabled == True
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