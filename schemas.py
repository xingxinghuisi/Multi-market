from typing import Literal

from pydantic import BaseModel, Field


# =========================================================
# 当前支持的提醒指标
#
# 以后可以继续增加：
# volume
# foreign_net
# institution_net
# funding_rate
# open_interest
# ...
# =========================================================

MetricType = Literal[
    "price",
    "change_pct",
    "price_change",
]


OperatorType = Literal[
    "crossing_up",
    "crossing_down",
]


# =========================================================
# 创建提醒
# =========================================================

class AlertRuleCreate(BaseModel):

    asset_id: int

    metric: MetricType

    operator: OperatorType

    value: float

    reset_buffer: float = Field(
        default=0,
        ge=0,
    )

    cooldown_seconds: int = Field(
        default=300,
        ge=0,
    )

    enabled: bool = True


# =========================================================
# 修改提醒
# =========================================================

class AlertRuleUpdate(BaseModel):

    metric: MetricType | None = None

    operator: OperatorType | None = None

    value: float | None = None

    reset_buffer: float | None = Field(
        default=None,
        ge=0,
    )

    cooldown_seconds: int | None = Field(
        default=None,
        ge=0,
    )

    enabled: bool | None = None