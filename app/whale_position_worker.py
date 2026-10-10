"""Discover public wallets automatically, then verify xyz perpetual positions.

One public market socket; no user-specific socket subscriptions and no keys.
REST is intentionally bounded. Run ONE replica with the shared SQLite volume.
"""
import asyncio
from contextlib import suppress
import json
import os
import time

from dotenv import load_dotenv
from sqlalchemy import delete, func, select
import websockets
from websockets_proxy import Proxy, proxy_connect

from database import SessionLocal, engine
import models  # Register the existing referenced tables; never recreate their data.
from hyperliquid_whales import PublicAPIError, PublicClient, WS_URL, address_value, decimal, milliseconds, parse_positions, position_event
from whale_models import (WhaleAddress, WhalePositionDelivery, WhalePositionEvent, WhaleRuntime,
                          WhaleSubscription, initialize_whale_tables)
from whale_position_service import deliver_pending

load_dotenv()


def log(message):
    print(f"[WHALE POSITIONS] {message}", flush=True)


def remember_trades(trades, coins, cap):
    """All valid counterparties are candidates, including small/split fills."""
    now = milliseconds()
    candidates = {}
    for trade in trades:
        if not isinstance(trade, dict) or trade.get("coin") not in coins:
            continue
        try:
            stamp = int(trade["time"])
            if not 0 < stamp <= now + 60000 or decimal(trade["px"]) <= 0 or decimal(trade["sz"]) <= 0:
                continue
            users = trade["users"]
            if not isinstance(users, list) or len(users) != 2:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        for value in users:
            address = address_value(value)
            if address:
                candidates[address] = max(candidates.get(address, 0), stamp)
    dropped = 0
    with SessionLocal() as db:
        count = db.scalar(select(func.count()).select_from(WhaleAddress))
        for address, stamp in candidates.items():
            row = db.get(WhaleAddress, address)
            if row is None:
                if count >= cap:
                    dropped += 1
                    continue
                row = WhaleAddress(address=address, discovered_ms=now, last_trade_ms=stamp,
                                   positions={}, next_check_ms=0)
                db.add(row)
                count += 1
            elif stamp > row.last_trade_ms:
                row.last_trade_ms = stamp
                # Keep hot wallets responsive, but never query the same one faster than 30s.
                row.next_check_ms = min(row.next_check_ms, max(now, row.checked_ms + 30000))
        db.commit()
    return dropped, max(candidates.values(), default=0)


def scan_one(client, floors):
    """Advance state and record changes in the same transaction, only on valid snapshots."""
    now = milliseconds()
    with SessionLocal() as db:
        row = db.scalar(select(WhaleAddress).where(WhaleAddress.next_check_ms <= now)
                        .order_by(WhaleAddress.next_check_ms, WhaleAddress.discovered_ms).limit(1))
        if row is None or not floors:
            return None
        address = row.address
        try:
            stamp, positions = parse_positions(client.positions(address), floors)
            if stamp <= row.snapshot_ms or now - stamp > 120000:
                raise ValueError("Stale snapshot")
            previous = row.positions or {}
            active = False
            for coin, current in positions.items():
                active = active or decimal(current["notional_usd"]) >= floors[coin]
                payload = position_event(row.address, coin, previous.get(coin), current, stamp)
                if payload and decimal(payload["qualifying_usd"]) >= floors[coin]:
                    if db.get(WhalePositionEvent, payload["event_key"]) is None:
                        db.add(WhalePositionEvent(event_key=payload["event_key"], address=row.address,
                            coin=coin, kind=payload["kind"], qualifying_usd=float(payload["qualifying_usd"]),
                            observed_ms=now, payload=payload))
            row.positions = {**previous, **positions}
            row.snapshot_ms = stamp
            row.checked_ms = now
            row.next_check_ms = now + (60000 if active else 300000)
            db.commit()
            return {"last_scan_ms": now, "last_scan_error": None}
        except Exception as error:
            # Network failure cannot overwrite the last good position or produce a close.
            db.rollback()
            row = db.get(WhaleAddress, address)
            row.next_check_ms = now + 60000
            db.commit()
            label = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
            retry_ms = now + (error.retry_seconds * 1000 if isinstance(error, PublicAPIError) and
                             (error.status == 429 or error.status >= 500) else 10000)
            return {"last_scan_error": label[:100], "last_scan_failure_ms": now,
                    "scan_retry_ms": retry_ms}


def config_and_heartbeat(runtime):
    with SessionLocal() as db:
        floors = dict(db.execute(select(WhaleSubscription.coin, func.min(WhaleSubscription.min_position_usd))
            .where(WhaleSubscription.enabled.is_(True)).group_by(WhaleSubscription.coin)).all())
        row = db.get(WhaleRuntime, 1)
        if row is None:
            row = WhaleRuntime(id=1, data={})
            db.add(row)
        data = {**runtime, "heartbeat_ms": milliseconds()}
        row.data = data
        db.commit()
        return floors


def housekeeping():
    with SessionLocal() as db:
        cutoff = milliseconds() - 7 * 86400000
        old_keys = select(WhalePositionEvent.event_key).where(WhalePositionEvent.observed_ms < cutoff)
        db.execute(delete(WhalePositionDelivery).where(WhalePositionDelivery.event_key.in_(old_keys)))
        db.execute(delete(WhalePositionEvent).where(WhalePositionEvent.observed_ms < cutoff))
        # Reclaim cold, verified-empty candidates only. Never evict a known open position.
        cold = db.scalars(select(WhaleAddress).where(WhaleAddress.last_trade_ms < milliseconds() - 86400000,
                                                   WhaleAddress.checked_ms > 0)).all()
        for row in cold:
            if all(decimal(p["qty"]) == 0 for p in row.positions.values()):
                db.delete(row)
        db.commit()


class Worker:
    def __init__(self):
        self.client = PublicClient()
        self.coins = set()
        self.cap = max(100, min(10000, int(os.getenv("WHALE_POSITION_ADDRESS_CAP", "2000"))))
        self.runtime = {"started_ms": milliseconds(), "markets": [], "connected": False,
            "subscribed_coins": [], "address_cap": self.cap, "capacity_skips": 0,
            "poll_seconds": 60, "candidate_poll_seconds": 300,
            "scope": "Hyperliquid / trade.xyz", "history_imported": False}

    async def stream(self):
        backoff = 2
        while True:
            if not self.coins:
                self.runtime["connected"] = False
                self.runtime["subscribed_coins"] = []
                await asyncio.sleep(2)
                continue
            try:
                proxy_url = os.getenv("HYPERLIQUID_PROXY") or os.getenv("HTTPS_PROXY")
                options = {"ping_interval": 20, "ping_timeout": 20, "open_timeout": 15,
                           "max_size": 2 ** 22, "max_queue": 64}
                connection = proxy_connect(WS_URL, proxy=Proxy.from_url(proxy_url), **options) if proxy_url else websockets.connect(WS_URL, **options)
                async with connection as ws:
                    subscribed = set()
                    acknowledged = set()
                    last_ping = time.monotonic()
                    self.runtime["connected"] = True
                    self.runtime["last_connect_ms"] = milliseconds()
                    self.runtime["stream_error"] = None
                    backoff = 2
                    while self.coins:
                        for coin in subscribed - self.coins:
                            await ws.send(json.dumps({"method": "unsubscribe", "subscription": {"type": "trades", "coin": coin}}))
                            acknowledged.discard(coin)
                        for coin in self.coins - subscribed:
                            await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}))
                        subscribed = self.coins.copy()
                        if time.monotonic() - last_ping >= 20:
                            await ws.send('{"method":"ping"}')
                            last_ping = time.monotonic()
                        try:
                            packet = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                        except asyncio.TimeoutError:
                            continue
                        self.runtime["last_message_ms"] = milliseconds()
                        if packet.get("channel") == "subscriptionResponse":
                            sub = packet.get("data", {}).get("subscription", {})
                            if packet.get("data", {}).get("method") == "subscribe" and sub.get("coin") in subscribed:
                                acknowledged.add(sub["coin"])
                            self.runtime["subscribed_coins"] = sorted(acknowledged)
                        elif packet.get("channel") == "error":
                            raise ValueError("Market subscription rejected")
                        elif packet.get("channel") == "trades" and isinstance(packet.get("data"), list):
                            dropped, stamp = await asyncio.to_thread(remember_trades, packet["data"], subscribed, self.cap)
                            self.runtime["capacity_skips"] += dropped
                            if stamp:
                                self.runtime["last_trade_ms"] = max(stamp, self.runtime.get("last_trade_ms", 0))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.runtime["stream_error"] = type(error).__name__
                log(f"Public stream reconnecting: {type(error).__name__}")
            finally:
                self.runtime["connected"] = False
                self.runtime["subscribed_coins"] = []
                self.runtime["disconnected_ms"] = milliseconds()
            await asyncio.sleep(backoff)
            backoff = min(60, backoff * 2)

    async def deliveries(self):
        while True:
            try:
                await asyncio.to_thread(self.deliver)
                self.runtime["delivery_error"] = None
            except Exception as error:
                self.runtime["delivery_error"] = type(error).__name__
                log(f"Delivery retry scheduled: {type(error).__name__}")
            await asyncio.sleep(10)

    @staticmethod
    def deliver():
        with SessionLocal() as db:
            deliver_pending(db)

    async def run(self):
        initialize_whale_tables(engine)
        log("Automatic wallet discovery started (xyz stocks/ETF perpetuals; no historical import)")
        tasks = [asyncio.create_task(self.stream()), asyncio.create_task(self.deliveries())]
        next_config = next_catalog = next_cleanup = 0
        floors = {}
        try:
            while True:
                now = time.monotonic()
                if now >= next_catalog:
                    try:
                        self.runtime["markets"] = await asyncio.to_thread(self.client.markets)
                        self.runtime["catalog_ms"] = milliseconds()
                        self.runtime["catalog_error"] = None
                        next_catalog = now + 3600
                    except Exception as error:
                        self.runtime["catalog_error"] = type(error).__name__
                        log(f"Market catalog retry scheduled: {type(error).__name__}")
                        next_catalog = now + 60
                if now >= next_config:
                    floors = await asyncio.to_thread(config_and_heartbeat, self.runtime.copy())
                    available = {m["coin"] for m in self.runtime["markets"]}
                    if milliseconds() - self.runtime.get("catalog_ms", 0) > 86400000:
                        available = set()
                    floors = {coin: value for coin, value in floors.items() if coin in available}
                    self.coins = set(floors)
                    next_config = now + 10
                if now >= next_cleanup:
                    await asyncio.to_thread(housekeeping)
                    next_cleanup = now + 3600
                if floors and milliseconds() >= self.runtime.get("scan_retry_ms", 0):
                    result = await asyncio.to_thread(scan_one, self.client, floors.copy())
                    if result:
                        self.runtime.update(result)
                # At most two sequential position requests/sec (weight 2 each).
                await asyncio.sleep(.6)
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task


if __name__ == "__main__":
    try:
        asyncio.run(Worker().run())
    except KeyboardInterrupt:
        log("Stopped")
