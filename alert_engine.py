from datetime import datetime


class AlertEngine:
    """
    纯 Alert Engine。

    它不负责数据库、
    不负责 Telegram、
    不负责文件。

    它只负责：

    Rule + State + Market Data
                ↓
           判断是否触发
    """

    # =====================================================
    # 获取规则字段
    # =====================================================

    @staticmethod
    def _rule_value(
        rule,
        key,
        default=None,
    ):
        return rule.get(
            key,
            default,
        )

    # =====================================================
    # 获取指标值
    # =====================================================

    def _get_metric_value(
        self,
        rule,
        market_data,
    ):

        metric = self._rule_value(
            rule,
            "metric",
        )

        if metric == "price":

            return float(
                market_data["price"]
            )

        if metric == "change_pct":

            return float(
                market_data["change_pct"]
            )

        if metric == "price_change":

            reference_price = (
                market_data.get(
                    "reference_price"
                )
            )

            # =================================================
            # 兼容以前韩国股票测试
            #
            # 以前使用 previous_close
            # =================================================

            if reference_price is None:
                reference_price = (
                    market_data.get(
                        "previous_close"
                    )
                )

            if reference_price is None:
                raise ValueError(
                    "price_change "
                    "缺少 reference_price"
                )

            return float(
                market_data["price"]
                - reference_price
            )

        raise ValueError(
            f"暂不支持指标：{metric}"
        )

    # =====================================================
    # 冷却时间判断
    # =====================================================

    @staticmethod
    def _cooldown_finished(
        state,
        cooldown_seconds,
        now,
    ):

        last_triggered = state.get(
            "last_triggered_at"
        )

        if not last_triggered:
            return True

        if isinstance(
            last_triggered,
            str,
        ):
            last_triggered = (
                datetime.fromisoformat(
                    last_triggered
                )
            )

        # SQLite 有时返回无时区 datetime，
        # 做兼容处理
        if (
            now.tzinfo is not None
            and
            last_triggered.tzinfo is None
        ):
            last_triggered = (
                last_triggered.replace(
                    tzinfo=now.tzinfo
                )
            )

        elif (
            now.tzinfo is None
            and
            last_triggered.tzinfo is not None
        ):
            now = now.replace(
                tzinfo=last_triggered.tzinfo
            )

        elapsed = (
            now
            - last_triggered
        ).total_seconds()

        return (
            elapsed
            >= cooldown_seconds
        )

    # =====================================================
    # 核心判断
    # =====================================================

    def evaluate(
        self,
        rule,
        state,
        market_data,
        now=None,
    ):

        if now is None:
            now = datetime.now()

        # 做副本，避免直接修改外部对象
        new_state = {
            "armed": state.get(
                "armed",
                True,
            ),
            "last_value": state.get(
                "last_value"
            ),
            "last_triggered_at": (
                state.get(
                    "last_triggered_at"
                )
            ),
            "trigger_count": state.get(
                "trigger_count",
                0,
            ),
        }

        if not self._rule_value(
            rule,
            "enabled",
            True,
        ):

            return {
                "status": "disabled",
                "state": new_state,
            }

        threshold = float(
            self._rule_value(
                rule,
                "value",
            )
        )

        reset_buffer = float(
            self._rule_value(
                rule,
                "reset_buffer",
                0,
            )
        )

        cooldown_seconds = int(
            self._rule_value(
                rule,
                "cooldown_seconds",
                0,
            )
        )

        operator = self._rule_value(
            rule,
            "operator",
        )

        current_value = (
            self._get_metric_value(
                rule,
                market_data,
            )
        )

        previous_value = (
            new_state["last_value"]
        )

        # =================================================
        # 第一次获得数据
        # =================================================

        if previous_value is None:

            new_state[
                "last_value"
            ] = current_value

            return {
                "status": "initialized",
                "current_value": current_value,
                "state": new_state,
            }

        status = "none"

        # =================================================
        # 向上突破
        # =================================================

        if operator == "crossing_up":

            # ---------------------------------------------
            # 重新武装
            # ---------------------------------------------

            if not new_state["armed"]:

                reset_level = (
                    threshold
                    - reset_buffer
                )

                if (
                    current_value
                    <= reset_level
                ):

                    new_state[
                        "armed"
                    ] = True

                    status = "rearmed"

            # ---------------------------------------------
            # 向上突破
            # ---------------------------------------------

            if new_state["armed"]:

                crossed = (
                    previous_value
                    < threshold
                    and
                    current_value
                    >= threshold
                )

                if crossed:

                    new_state[
                        "armed"
                    ] = False

                    cooldown_ok = (
                        self._cooldown_finished(
                            new_state,
                            cooldown_seconds,
                            now,
                        )
                    )

                    if cooldown_ok:

                        new_state[
                            "last_triggered_at"
                        ] = now

                        new_state[
                            "trigger_count"
                        ] += 1

                        status = "triggered"

                    else:

                        status = (
                            "suppressed_cooldown"
                        )

        # =================================================
        # 向下跌破
        # =================================================

        elif operator == "crossing_down":

            # ---------------------------------------------
            # 重新武装
            # ---------------------------------------------

            if not new_state["armed"]:

                reset_level = (
                    threshold
                    + reset_buffer
                )

                if (
                    current_value
                    >= reset_level
                ):

                    new_state[
                        "armed"
                    ] = True

                    status = "rearmed"

            # ---------------------------------------------
            # 向下跌破
            # ---------------------------------------------

            if new_state["armed"]:

                crossed = (
                    previous_value
                    > threshold
                    and
                    current_value
                    <= threshold
                )

                if crossed:

                    new_state[
                        "armed"
                    ] = False

                    cooldown_ok = (
                        self._cooldown_finished(
                            new_state,
                            cooldown_seconds,
                            now,
                        )
                    )

                    if cooldown_ok:

                        new_state[
                            "last_triggered_at"
                        ] = now

                        new_state[
                            "trigger_count"
                        ] += 1

                        status = "triggered"

                    else:

                        status = (
                            "suppressed_cooldown"
                        )

        else:

            raise ValueError(
                f"暂不支持操作符："
                f"{operator}"
            )

        # =================================================
        # 保存当前值
        # =================================================

        new_state[
            "last_value"
        ] = current_value

        return {
            "status": status,
            "previous_value": previous_value,
            "current_value": current_value,
            "threshold": threshold,
            "state": new_state,
        }