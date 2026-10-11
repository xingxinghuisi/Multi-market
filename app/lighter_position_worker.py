"""Discover Lighter accounts from public trades and verify positions, one replica.

Notifications are delivered ONLY by whale_position_worker, for both venues.
"""
import asyncio
from contextlib import suppress
import json
import os
import time

import websockets
from websockets_proxy import Proxy, proxy_connect

from database import engine
from hyperliquid_whales import milliseconds
from lighter_whales import LighterClient, WS_URL, market_key, stream_trades
from whale_models import initialize_whale_tables
from whale_position_worker import config_and_heartbeat, housekeeping, remember_trades, scan_one


def log(message):
    print(f"[LIGHTER POSITIONS] {message}", flush=True)


class Worker:
    def __init__(self):
        self.client = LighterClient()
        self.coins = set()
        self.next_send_at = 0
        self.cap = max(100, min(10000, int(os.getenv("WHALE_LIGHTER_ADDRESS_CAP", "2000"))))
        self.runtime = {"started_ms": milliseconds(), "markets": [], "connected": False,
                        "subscribed_coins": [], "address_cap": self.cap, "capacity_skips": 0,
                        "poll_seconds": 60, "candidate_poll_seconds": 300,
                        "scope": "Lighter 主网", "history_imported": False}

    async def reconcile(self, ws, subscribed, acknowledged):
        # <=150 control messages/min and <=20 subscriptions awaiting ack,
        # below the public 200/min and 50-inflight limits. Drain messages
        # between small batches rather than filling the receive queue at startup.
        room = max(0, 20 - len(subscribed - acknowledged))
        adding = sorted(self.coins - subscribed)[:min(5, room)]
        for coin in adding:
            await asyncio.sleep(max(0, self.next_send_at - time.monotonic()))
            await ws.send(json.dumps({"type": "subscribe", "channel": f"trade/{coin.rsplit(':', 1)[1]}"}))
            self.next_send_at = time.monotonic() + .4
            subscribed.add(coin)

    async def stream(self):
        backoff = 2
        while True:
            if not self.coins:
                self.runtime["connected"] = False
                self.runtime["subscribed_coins"] = []
                await asyncio.sleep(2)
                continue
            try:
                proxy_url = os.getenv("LIGHTER_PROXY") or os.getenv("HTTPS_PROXY")
                options = {"ping_interval": 20, "ping_timeout": 20, "open_timeout": 15,
                           "max_size": 2 ** 22, "max_queue": 64}
                connection = proxy_connect(WS_URL, proxy=Proxy.from_url(proxy_url), **options) if proxy_url else websockets.connect(WS_URL, **options)
                async with connection as ws:
                    subscribed, acknowledged = set(), set()
                    self.runtime.update(connected=True, last_connect_ms=milliseconds(), stream_error=None)
                    backoff = 2
                    while self.coins or subscribed:
                        # Reconnect after removals instead of accumulating unacknowledged
                        # unsubscribe traffic when many users pause markets at once.
                        if subscribed - self.coins:
                            break
                        await self.reconcile(ws, subscribed, acknowledged)
                        self.runtime["subscribed_coins"] = sorted(acknowledged)
                        try:
                            packet = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                        except asyncio.TimeoutError:
                            continue
                        self.runtime["last_message_ms"] = milliseconds()
                        if packet.get("type") == "ping":
                            await ws.send('{"type":"pong"}')
                        elif packet.get("type") == "error" or packet.get("error"):
                            raise ValueError("Public market subscription rejected")
                        elif packet.get("type") in {"subscribed/trade", "update/trade"}:
                            channel = packet.get("channel", "")
                            if not channel.startswith("trade:"):
                                raise ValueError("Invalid trade channel")
                            coin = market_key(channel.split(":", 1)[1])
                            if coin in subscribed:
                                acknowledged.add(coin)
                                self.runtime["subscribed_coins"] = sorted(acknowledged)
                                trades = stream_trades(packet, {coin})
                                dropped, stamp = await asyncio.to_thread(remember_trades, trades, subscribed, self.cap, "lighter")
                                self.runtime["capacity_skips"] += dropped
                                if stamp:
                                    self.runtime["last_trade_ms"] = max(stamp, self.runtime.get("last_trade_ms", 0))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.runtime["stream_error"] = type(error).__name__
                log(f"Public stream reconnecting: {type(error).__name__}")
            finally:
                self.runtime.update(connected=False, subscribed_coins=[], disconnected_ms=milliseconds())
            await asyncio.sleep(backoff)
            backoff = min(60, backoff * 2)

    async def run(self):
        initialize_whale_tables(engine)
        log("Public Lighter mainnet account discovery started; no historical import")
        task = asyncio.create_task(self.stream())
        next_config = next_catalog = next_cleanup = 0
        floors = {}
        try:
            while True:
                now = time.monotonic()
                if now >= next_catalog:
                    try:
                        self.runtime["markets"] = await asyncio.to_thread(self.client.markets)
                        self.runtime.update(catalog_ms=milliseconds(), catalog_error=None)
                        next_catalog = now + 3600
                        log(f"Verified {len(self.runtime['markets'])} active perpetual markets")
                    except Exception as error:
                        self.runtime["catalog_error"] = type(error).__name__
                        next_catalog = now + 60
                        log(f"Catalog retry: {type(error).__name__}")
                if now >= next_config:
                    floors = await asyncio.to_thread(config_and_heartbeat, self.runtime.copy(), "lighter")
                    available = set(self.client.catalog) if milliseconds() - self.runtime.get("catalog_ms", 0) <= 86400000 else set()
                    floors = {coin: value for coin, value in floors.items() if coin in available}
                    self.coins = set(floors)
                    next_config = now + 10
                if now >= next_cleanup:
                    await asyncio.to_thread(housekeeping, "lighter")
                    next_cleanup = now + 3600
                if floors and milliseconds() >= self.runtime.get("scan_retry_ms", 0):
                    result = await asyncio.to_thread(scan_one, self.client, floors.copy(), "lighter")
                    if result:
                        self.runtime.update(result)
                        if result.get("last_scan_error"):
                            log(f"Account check retry: {result['last_scan_error']}")
                await asyncio.sleep(1.2)
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    try:
        asyncio.run(Worker().run())
    except KeyboardInterrupt:
        log("Stopped")
