from datetime import date

from sqlalchemy import select

from database import SessionLocal
from models import Asset, DailyPrice
from providers.registry import provider_registry


def upsert_daily_price(
    db,
    asset_id: int,
    bar,
):

    row = db.scalar(
        select(
            DailyPrice
        ).where(
            DailyPrice.asset_id == asset_id,
            DailyPrice.date == bar.date,
        )
    )

    if row is None:

        row = DailyPrice(
            asset_id=asset_id,
            date=bar.date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            change_pct=bar.change_pct,
        )

        db.add(
            row
        )

        return "inserted"

    row.open = bar.open
    row.high = bar.high
    row.low = bar.low
    row.close = bar.close
    row.volume = bar.volume
    row.change_pct = bar.change_pct

    return "updated"


def backfill_asset(
    asset_id: int,
    start_date: date,
    end_date: date,
):

    with SessionLocal() as db:

        asset = db.get(
            Asset,
            asset_id,
        )

        if asset is None:

            raise ValueError(
                f"Asset not found: {asset_id}"
            )

        provider = provider_registry.get(
            asset.provider
        )

        if not hasattr(
            provider,
            "get_daily_history",
        ):

            raise ValueError(
                f"Provider does not support history: "
                f"{asset.provider}"
            )

        print()
        print(
            f"[BACKFILL] "
            f"{asset.symbol} "
            f"{asset.venue}"
        )

        print(
            f"Provider: "
            f"{asset.provider}"
        )

        print(
            f"Range: "
            f"{start_date} -> {end_date}"
        )

        bars = provider.get_daily_history(
            symbol=asset.symbol,
            start_date=start_date,
            end_date=end_date,
        )

        inserted = 0
        updated = 0

        for bar in bars:

            status = upsert_daily_price(
                db=db,
                asset_id=asset.id,
                bar=bar,
            )

            if status == "inserted":

                inserted += 1

            else:

                updated += 1

        db.commit()

        print(
            f"Fetched: {len(bars)}"
        )

        print(
            f"Inserted: {inserted}"
        )

        print(
            f"Updated: {updated}"
        )

        return {
            "asset_id": asset.id,
            "symbol": asset.symbol,
            "provider": asset.provider,
            "fetched": len(bars),
            "inserted": inserted,
            "updated": updated,
        }


def backfill_enabled_assets(
    start_date: date,
    end_date: date,
):

    with SessionLocal() as db:

        assets = db.scalars(
            select(
                Asset
            )
            .where(
                Asset.enabled == True
            )
            .order_by(
                Asset.id
            )
        ).all()

        asset_ids = [
            asset.id
            for asset in assets
        ]

    results = []

    for asset_id in asset_ids:

        try:

            result = backfill_asset(
                asset_id=asset_id,
                start_date=start_date,
                end_date=end_date,
            )

            results.append(
                result
            )

        except Exception as error:

            print()
            print(
                f"[BACKFILL ERROR] "
                f"Asset ID={asset_id}"
            )

            print(
                f"Error: {error}"
            )

    return results