import argparse
from datetime import date, timedelta

from backfill_service import (
    backfill_enabled_assets,
)


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Market Radar "
            "Historical Backfill"
        )
    )

    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help=(
            "How many calendar days "
            "to backfill"
        ),
    )

    args = parser.parse_args()

    if args.days < 1:

        raise ValueError(
            "--days must be >= 1"
        )

    end_date = date.today()

    start_date = (
        end_date
        - timedelta(
            days=args.days - 1
        )
    )

    print()
    print(
        "=" * 80
    )

    print(
        "Market Radar "
        "Historical Backfill"
    )

    print(
        "=" * 80
    )

    print(
        f"Range: "
        f"{start_date} -> {end_date}"
    )

    results = (
        backfill_enabled_assets(
            start_date=start_date,
            end_date=end_date,
        )
    )

    print()
    print(
        "=" * 80
    )

    print(
        "Backfill Completed"
    )

    print(
        "=" * 80
    )

    for result in results:

        print(
            f"{result['symbol']} | "
            f"Fetched="
            f"{result['fetched']} | "
            f"Inserted="
            f"{result['inserted']} | "
            f"Updated="
            f"{result['updated']}"
        )


if __name__ == "__main__":

    main()