from datetime import datetime

from sqlalchemy import select

from alert_engine import AlertEngine
from models import (
    AlertRule,
    AlertState,
)


engine = AlertEngine()


# =========================================================
# SQLAlchemy Rule → Alert Engine Rule
# =========================================================

def rule_to_dict(
    rule,
):

    return {
        "id": rule.id,
        "metric": rule.metric,
        "operator": rule.operator,
        "value": rule.value,
        "reset_buffer": (
            rule.reset_buffer
        ),
        "cooldown_seconds": (
            rule.cooldown_seconds
        ),
        "enabled": rule.enabled,
    }


# =========================================================
# AlertState → dict
# =========================================================

def state_to_dict(
    state,
):

    if state is None:

        return {
            "armed": True,
            "last_value": None,
            "last_triggered_at": None,
            "trigger_count": 0,
        }

    return {
        "armed": state.armed,
        "last_value": state.last_value,
        "last_triggered_at": (
            state.last_triggered_at
        ),
        "trigger_count": (
            state.trigger_count
        ),
    }


# =========================================================
# 获取 / 创建 State
# =========================================================

def get_or_create_state(
    session,
    rule,
):

    state = session.scalar(
        select(AlertState).where(
            AlertState.rule_id
            == rule.id
        )
    )

    if state:
        return state

    state = AlertState(
        rule_id=rule.id,
        armed=True,
        last_value=None,
        trigger_count=0,
    )

    session.add(state)

    session.flush()

    return state


# =========================================================
# 把 Engine 返回状态写回数据库
# =========================================================

def update_state_model(
    state_model,
    state_data,
):

    state_model.armed = (
        state_data["armed"]
    )

    state_model.last_value = (
        state_data["last_value"]
    )

    state_model.last_triggered_at = (
        state_data[
            "last_triggered_at"
        ]
    )

    state_model.trigger_count = (
        state_data[
            "trigger_count"
        ]
    )


# =========================================================
# 执行一条规则
# =========================================================

def process_rule(
    session,
    rule,
    market_data,
    now=None,
):

    if now is None:
        now = datetime.now()

    state_model = (
        get_or_create_state(
            session,
            rule,
        )
    )

    rule_data = rule_to_dict(
        rule
    )

    state_data = state_to_dict(
        state_model
    )

    result = engine.evaluate(
        rule_data,
        state_data,
        market_data,
        now=now,
    )

    update_state_model(
        state_model,
        result["state"],
    )

    session.flush()

    return {
        "rule_id": rule.id,
        "metric": rule.metric,
        "operator": rule.operator,
        "value": rule.value,
        **result,
    }


# =========================================================
# 执行某股票所有已启用规则
# =========================================================

def process_asset_rules(
    session,
    asset_id,
    market_data,
    now=None,
):

    rules = session.scalars(
        select(AlertRule).where(
            AlertRule.asset_id
            == asset_id,

            AlertRule.enabled
            == True,
        )
    ).all()

    results = []

    for rule in rules:

        result = process_rule(
            session,
            rule,
            market_data,
            now=now,
        )

        results.append(result)

    return results