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

# =========================================================
# Asset
# =========================================================


class AssetCreate(BaseModel):

    symbol: str = Field(
        min_length=1,
        max_length=50,
    )

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    asset_type: str = Field(
        min_length=1,
        max_length=30,
    )

    venue: str = Field(
        min_length=1,
        max_length=30,
    )

    segment: str = Field(
        min_length=1,
        max_length=50,
    )

    currency: str = Field(
        min_length=1,
        max_length=20,
    )

    provider: str = Field(
        min_length=1,
        max_length=50,
    )

    enabled: bool = True


class AssetUpdate(BaseModel):

    symbol: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )

    asset_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
    )

    venue: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
    )

    segment: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )

    currency: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
    )

    provider: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )

    enabled: bool | None = None