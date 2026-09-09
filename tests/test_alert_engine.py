from alert_engine import AlertEngine


def create_state():

    return {
        "armed": True,
        "last_value": None,
        "last_triggered_at": None,
        "trigger_count": 0,
    }


def make_market_data(
    price,
    previous_close,
    change_pct,
):

    return {
        "price": price,
        "previous_close": previous_close,
        "change_pct": change_pct,
    }


def evaluate(
    engine,
    rule,
    state,
    market_data,
):

    result = engine.evaluate(
        rule,
        state,
        market_data,
    )

    return (
        result,
        result["state"],
    )


# =========================================================
# 1. 上涨突破 +3%
# =========================================================

def test_change_pct_crossing_up():

    engine = AlertEngine()

    state = create_state()

    rule = {
        "id": 1,
        "metric": "change_pct",
        "operator": "crossing_up",
        "value": 3.0,
        "reset_buffer": 0.2,
        "cooldown_seconds": 0,
        "enabled": True,
    }

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1840000,
            1793000,
            2.5,
        ),
    )

    assert (
        result["status"]
        == "initialized"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1850000,
            1793000,
            3.2,
        ),
    )

    assert (
        result["status"]
        == "triggered"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1860000,
            1793000,
            3.8,
        ),
    )

    assert (
        result["status"]
        == "none"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1840000,
            1793000,
            2.7,
        ),
    )

    assert (
        result["status"]
        == "rearmed"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1850000,
            1793000,
            3.1,
        ),
    )

    assert (
        result["status"]
        == "triggered"
    )


# =========================================================
# 2. 下跌跌破 -3%
# =========================================================

def test_change_pct_crossing_down():

    engine = AlertEngine()

    state = create_state()

    rule = {
        "id": 2,
        "metric": "change_pct",
        "operator": "crossing_down",
        "value": -3.0,
        "reset_buffer": 0.2,
        "cooldown_seconds": 0,
        "enabled": True,
    }

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1750000,
            1793000,
            -2.5,
        ),
    )

    assert (
        result["status"]
        == "initialized"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1730000,
            1793000,
            -3.2,
        ),
    )

    assert (
        result["status"]
        == "triggered"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1700000,
            1793000,
            -4.5,
        ),
    )

    assert (
        result["status"]
        == "none"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1750000,
            1793000,
            -2.7,
        ),
    )

    assert (
        result["status"]
        == "rearmed"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1730000,
            1793000,
            -3.1,
        ),
    )

    assert (
        result["status"]
        == "triggered"
    )


# =========================================================
# 3. 指定价格
# =========================================================

def test_price_crossing_up():

    engine = AlertEngine()

    state = create_state()

    rule = {
        "id": 3,
        "metric": "price",
        "operator": "crossing_up",
        "value": 1900000,
        "reset_buffer": 10000,
        "cooldown_seconds": 0,
        "enabled": True,
    }

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1880000,
            1793000,
            4.8,
        ),
    )

    assert (
        result["status"]
        == "initialized"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1910000,
            1793000,
            6.5,
        ),
    )

    assert (
        result["status"]
        == "triggered"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1950000,
            1793000,
            8.8,
        ),
    )

    assert (
        result["status"]
        == "none"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1885000,
            1793000,
            5.1,
        ),
    )

    assert (
        result["status"]
        == "rearmed"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1910000,
            1793000,
            6.5,
        ),
    )

    assert (
        result["status"]
        == "triggered"
    )


# =========================================================
# 4. 上涨固定金额
# =========================================================

def test_price_change_crossing_up():

    engine = AlertEngine()

    state = create_state()

    rule = {
        "id": 4,
        "metric": "price_change",
        "operator": "crossing_up",
        "value": 50000,
        "reset_buffer": 10000,
        "cooldown_seconds": 0,
        "enabled": True,
    }

    previous_close = 1800000

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1830000,
            previous_close,
            1.67,
        ),
    )

    assert (
        result["status"]
        == "initialized"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1860000,
            previous_close,
            3.33,
        ),
    )

    assert (
        result["status"]
        == "triggered"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1880000,
            previous_close,
            4.44,
        ),
    )

    assert (
        result["status"]
        == "none"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1830000,
            previous_close,
            1.67,
        ),
    )

    assert (
        result["status"]
        == "rearmed"
    )

    result, state = evaluate(
        engine,
        rule,
        state,
        make_market_data(
            1860000,
            previous_close,
            3.33,
        ),
    )

    assert (
        result["status"]
        == "triggered"
    )