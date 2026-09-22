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
        # 固定步长提醒
        #
        # 例：
        # anchor = 86100
        # step   = 100
        #
        # 86200 -> 提醒
        # 86300 -> 再提醒
        #
        # 86000 -> 向下提醒
        # =================================================

        if operator == "step":

            step_size = threshold

            if step_size <= 0:

                raise ValueError(
                    "step 模式的步长必须大于 0"
                )

            anchor_value = (
                previous_value
            )

            difference = (
                current_value
                - anchor_value
            )

            absolute_difference = (
                abs(
                    difference
                )
            )

            # ---------------------------------------------
            # 还没有跨越一个完整步长
            #
            # 注意：
            # step 模式不能把 last_value 更新成当前价格，
            # 因为 last_value 在这里代表“锚点”。
            # ---------------------------------------------

            if (
                absolute_difference
                < step_size
            ):

                return {
                    "status": "none",

                    "previous_value":
                        anchor_value,

                    "current_value":
                        current_value,

                    "threshold":
                        step_size,

                    "step_size":
                        step_size,

                    "step_count":
                        0,

                    "state":
                        new_state,
                }


            # ---------------------------------------------
            # 一次可能跨越多个档位
            #
            # 86100 -> 86450
            #
            # 共跨：
            # 86200
            # 86300
            # 86400
            #
            # 只发送一次通知
            # ---------------------------------------------

            step_count = int(
                absolute_difference
                // step_size
            )


            if difference > 0:

                direction = "up"

                new_anchor = (
                    anchor_value
                    + (
                        step_count
                        * step_size
                    )
                )

            else:

                direction = "down"

                new_anchor = (
                    anchor_value
                    - (
                        step_count
                        * step_size
                    )
                )


            # ---------------------------------------------
            # 更新锚点
            # ---------------------------------------------

            new_state[
                "last_value"
            ] = new_anchor

            new_state[
                "last_triggered_at"
            ] = now

            new_state[
                "trigger_count"
            ] += 1


            return {
                "status":
                    "triggered",

                "previous_value":
                    anchor_value,

                "current_value":
                    current_value,

                "threshold":
                    step_size,

                "step_size":
                    step_size,

                "step_count":
                    step_count,

                "direction":
                    direction,

                "anchor_before":
                    anchor_value,

                "anchor_after":
                    new_anchor,

                "state":
                    new_state,
            }


        # =================================================
        # 向上突破
        # =================================================

        elif operator == "crossing_up":
        # =================================================
        # 向上突破
        # =================================================

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