"""An unavailable stock gateway must not stall or terminate crypto quote processing."""
import asyncio
import threading
import time

import market_worker
import providers.moomoo as moomoo


def test_disconnected_opend_does_not_block_crypto_ticks(monkeypatch):
    closed = threading.Event()
    querying = threading.Event()
    release = threading.Event()

    class DisconnectedContext:
        def __init__(self, host, port, is_async_connect=False):
            # Model the installed SDK's blocking reconnect constructor, bounded for tests.
            if not is_async_connect:
                time.sleep(.3)

        def set_handler(self, handler):
            pass

        def set_sync_query_connect_timeout(self, timeout):
            pass

        def subscribe(self, *args, **kwargs):
            querying.set()
            release.wait(timeout=.5)
            return -1, 'OpenD unavailable'

        def close(self):
            closed.set()

    monkeypatch.setattr(moomoo, 'OpenQuoteContext', DisconnectedContext)

    async def scenario():
        provider = moomoo.MoomooRealtimeProvider()
        stream = provider.stream_markets_dynamic(lambda: {'US.TEST'}, refresh_seconds=1)
        task = asyncio.create_task(anext(stream))
        started = time.monotonic()
        ticks = []
        try:
            # Represents a healthy Binance stream running in the same event loop.
            for price in (100, 101, 102):
                await asyncio.sleep(.01)
                ticks.append(price)
            assert querying.is_set()
            assert ticks == [100, 101, 102]
            assert time.monotonic() - started < .2
            assert not task.done()
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await stream.aclose()
        assert closed.is_set()

    asyncio.run(scenario())


def test_source_failure_and_empty_asset_list_do_not_stop_other_sources(monkeypatch):
    async def scenario():
        attempts = 0
        ticks = []

        async def failing_stock_source():
            nonlocal attempts
            attempts += 1
            raise ConnectionError('OpenD unavailable')

        async def crypto_source():
            ticks.append(len(ticks) + 1)
            await asyncio.sleep(.01)
            # Returning also models a source which initially has no configured assets.

        async def empty_source():
            return

        supervise = market_worker.supervise_provider
        monkeypatch.setattr(market_worker, 'supervise_provider',
                            lambda name, runner: supervise(name, runner, .005))
        monkeypatch.setattr(market_worker, 'run_moomoo_realtime', failing_stock_source)
        monkeypatch.setattr(market_worker, 'run_binance_batch', empty_source)
        monkeypatch.setattr(market_worker, 'run_binance_futures_batch', crypto_source)
        tasks = [asyncio.create_task(market_worker.main())]
        try:
            await asyncio.sleep(.07)
            assert attempts >= 2
            assert len(ticks) >= 2
            assert not any(task.done() for task in tasks)
        finally:
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert all(isinstance(result, asyncio.CancelledError) for result in results)

    asyncio.run(scenario())
