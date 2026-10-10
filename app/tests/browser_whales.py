"""Real API browser acceptance with explicitly synthetic, in-memory whale data.

Run from the repository root: python app/tests/browser_whales.py
Requires Node Playwright and Chromium; respects the same browser env as the
subscriptions smoke test. Never starts providers or sends Telegram messages.
"""
from pathlib import Path
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import api
from database import Base
from hyperliquid_whales import milliseconds, position_event
from whale_models import WhaleAddress, WhalePositionEvent, WhaleRuntime


def main():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    lock = threading.Lock()
    address = "0x" + "a" * 40
    position = {"qty":"100000", "notional_usd":"2000000", "entry_price":"19.5",
                "leverage":"10", "leverage_type":"isolated", "snapshot_ms":milliseconds()-240000}
    with sessions() as db:
        db.add(WhaleRuntime(id=1, data={"catalog_ms":milliseconds(),"heartbeat_ms":milliseconds(),
            "started_ms":milliseconds(),"connected":True,"subscribed_coins":["xyz:KORU"],
            "markets":[{"coin":"xyz:KORU","name":"Synthetic browser test market","max_leverage":10},
                       {"coin":"xyz:GOLD","name":"Synthetic browser test non-equity market","max_leverage":10}]}))
        db.add(WhaleAddress(address=address,discovered_ms=1,last_trade_ms=1,
            checked_ms=milliseconds(),snapshot_ms=position["snapshot_ms"],positions={"xyz:KORU":position}))
        db.commit()

    def get_db():
        with lock, sessions() as db:
            yield db

    @api.app.post("/__fixture__/whale-event")
    def add_fixture():
        with lock, sessions() as db:
            payload = position_event(address, "xyz:KORU", None, position, milliseconds())
            db.add(WhalePositionEvent(event_key=payload["event_key"],address=address,coin="xyz:KORU",
                kind="discovered",qualifying_usd=2000000,observed_ms=milliseconds(),payload=payload))
            db.commit()
        return {"synthetic_test_fixture":True}

    api.app.dependency_overrides[api.get_db] = get_db
    api.app.state.auth_session_factory = sessions
    api.app.state.auth_insecure_local_cookie = True
    api.load_realtime_market_quotes = lambda: []
    listener = socket.socket()
    listener.bind(("127.0.0.1",0))
    port = listener.getsockname()[1]
    os.environ["RADAR_PUBLIC_ORIGIN"] = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(api.app,log_level="error",lifespan="off"))
    thread = threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
    thread.start()
    deadline = time.monotonic()+10
    try:
        while not server.started:
            if time.monotonic()>deadline:
                raise RuntimeError("Fixture server did not start")
            time.sleep(.05)
        env = {**os.environ,"RADAR_TEST_BASE_URL":f"http://127.0.0.1:{port}"}
        node = env.get("NODE_EXECUTABLE") or shutil.which("node")
        if not node:
            raise RuntimeError("Node.js is required for browser tests")
        script=os.environ.get("RADAR_BROWSER_SCRIPT","whales.browser.cjs")
        return subprocess.run([node,str(Path(__file__).with_name(script))],env=env,check=False,timeout=120).returncode
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        api.app.dependency_overrides.clear()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
