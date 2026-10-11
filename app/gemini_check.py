"""Explicit setup check using real closed candles; no Telegram or subscription changes."""
import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from database import SessionLocal, engine
from gemini_service import analyze, budget_owner, configuration, usage_summary
from models import Asset
from signal_models import initialize_signal_tables
from signal_worker import fetch_candles
from technical_indicators import TechnicalConfig, closed_candles, evaluate


def check(db, symbol, reader=fetch_candles, generator=None, now=None):
    if not configuration()["configured"]:
        raise ValueError("Gemini project/model configuration is incomplete")
    owner = budget_owner(db)
    if owner is None or not owner.telegram_chat_id:
        raise ValueError("Budget owner must exist and have Telegram configured")
    asset = db.scalar(select(Asset).where(Asset.symbol == symbol, Asset.venue == "BINANCE",
                                         Asset.segment == "FUTURES", Asset.enabled.is_(True)))
    if asset is None:
        raise ValueError("Choose an enabled Binance futures asset")
    now = now or datetime.now(timezone.utc)
    candles = closed_candles(reader(symbol, "1h"), "1h", int(now.timestamp() * 1000))
    snapshot = evaluate(candles, TechnicalConfig())
    snapshot.update(symbol=symbol, purpose="explicit_connection_check")
    result, _ = analyze(db, snapshot, generator=generator, now=now)
    return result, usage_summary(db, now)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="KORUUSDT")
    args = parser.parse_args()
    try:
        initialize_signal_tables(engine)
        with SessionLocal() as db:
            result, usage = check(db, args.symbol)
        if result is None:
            print("GEMINI_CHECK_FAILED: check billing, model access, and service account permissions; no automatic paid retry.", file=sys.stderr)
            return 1
        print(f"GEMINI_CHECK_OK: bias={result['bias']}; month_estimate_usd={usage['estimated_usd']:.6f}; unverified_calls={usage['unverified_calls']}")
        return 0
    except Exception as error:
        print(f"GEMINI_CHECK_FAILED: {type(error).__name__}; no credentials or response bodies shown.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
