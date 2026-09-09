from datetime import (
    date,
    datetime,
    timezone,
)

from providers.binance import (
    BinanceSpotProvider,
)


def test_binance_snapshot_change_pct():

    snapshot = (
        BinanceSpotProvider
        .build_snapshot(

            symbol="BTCUSDT",

            price=102000,

            day_open=100000,

            day_high=103000,

            day_low=99000,

            volume=100,

            quote_volume=10000000,

            event_time=datetime(
                2026,
                9,
                9,
                12,
                0,
                tzinfo=timezone.utc,
            ),

            session_date=date(
                2026,
                9,
                9,
            ),
        )
    )

    assert (
        snapshot.symbol
        == "BTCUSDT"
    )

    assert (
        snapshot.price
        == 102000
    )

    assert (
        snapshot.reference_price
        == 100000
    )

    assert (
        snapshot.change_amount
        == 2000
    )

    assert (
        snapshot.change_pct
        == 2.0
    )

    assert (
        snapshot.reference_type
        == "utc8_day_open"
    )

    assert (
        snapshot.reference_timezone
        == "UTC+08:00"
    )