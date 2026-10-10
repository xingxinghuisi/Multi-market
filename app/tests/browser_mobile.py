"""Browser smoke tests against the real API with isolated, explicitly synthetic fixtures.

Run from app/: python tests/browser_mobile.py
Requires playwright + an installed Chromium browser. Never runs market/news workers.
"""
import socket
import os
import sys
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api
from database import Base
from models import Asset, DailyPrice, MarketQuote, Notification, User


def main():
    preview = "--preview" in sys.argv
    requested_port = next((int(arg.split("=", 1)[1]) for arg in sys.argv if arg.startswith("--port=")), 0)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    database_lock = threading.Lock()
    with sessions() as db:
        user = User(username="default")
        db.add(user)
        db.flush()
        if preview:
            from init_db import ASSETS
            db.add_all([Asset(**asset) for asset in ASSETS])
            db.add(Asset(symbol="BTCUSDT", name="Bitcoin / USDT Perpetual", asset_type="crypto",
                         venue="BINANCE", segment="FUTURES", currency="USDT", provider="BINANCE"))
        for segment in (() if preview else ("SPOT", "FUTURES")):
            asset = Asset(symbol="TESTUSDT", name="Browser test fixture", asset_type="crypto", venue="BINANCE", segment=segment, currency="USDT", provider="BINANCE")
            db.add(asset)
            db.flush()
            db.add(MarketQuote(asset_id=asset.id, price=100, change_pct=0, event_time=datetime.now(timezone.utc)))
            db.add(DailyPrice(asset_id=asset.id, date=date(2026, 9, 1), open=99, high=101, low=98, close=100, volume=0, change_pct=0))
        if not preview:
            db.add(Notification(user_id=user.id, category="price", title="Synthetic browser test notification", message="Test only", channel="telegram", status="pending"))
        db.commit()

    def get_db():
        # StaticPool shares one SQLite connection; serialize the preview sessions.
        with database_lock, sessions() as db:
            yield db

    api.app.dependency_overrides[api.get_db] = get_db
    api.app.state.auth_session_factory = sessions
    api.app.state.auth_insecure_local_cookie = True
    if preview:
        # An in-memory UI preview must never suggest that seeded catalog rows are live market data.
        def no_external_metrics(_url):
            raise OSError("External market data is disabled in the local preview")
        api._binance_read_json = no_external_metrics
    # Avoid the production database in the websocket snapshot as well.
    def snapshot():
        with database_lock, sessions() as db:
            return api.get_latest_market_quotes(db=db)

    api.load_realtime_market_quotes = snapshot
    listener = socket.socket()
    listener.bind(("127.0.0.1", requested_port))
    port = listener.getsockname()[1]
    # Tests/previews use this local origin even when the host has production env configured.
    os.environ["RADAR_PUBLIC_ORIGIN"] = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(api.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Test server did not start")
        time.sleep(.05)
    output = Path("../test-results")
    output.mkdir(exist_ok=True)
    try:
        if preview:
            print(f"In-memory preview: http://127.0.0.1:{port} (no stored quotes, no workers, no database writes)", flush=True)
            while thread.is_alive():
                thread.join(timeout=1)
            return
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            base = f"http://127.0.0.1:{port}"
            page.goto(base)
            page.get_by_role("heading", name="登录", exact=True).wait_for()
            assert page.locator("#register-form").count() == 0
            page.get_by_role("link", name="创建账户").click()
            page.get_by_role("heading", name="创建账户", exact=True).wait_for()
            assert page.locator("#login-form").count() == 0
            page.locator('#register-form [name="username"]').fill("browser_test")
            page.locator('#register-form [name="password"]').fill("browser-test-password")
            page.get_by_role("button", name="注册并进入").click()
            page.get_by_role("heading", name="市场，尽在掌握").wait_for()
            page.get_by_role("link", name="查看资产目录").click()
            page.get_by_role("heading", name="资产目录", exact=True).wait_for()
            page.goto(base + "/#home")
            page.get_by_role("link", name="查看我的关注").click()
            page.get_by_role("heading", name="我的关注", exact=True).wait_for()
            page.goto(base + "/#home")
            page.locator('a[href="#asset/1"]').first.wait_for()
            assert page.locator(".asset-row").count() == 2
            page.goto(base + "/#asset/2")
            page.get_by_role("heading", name="TESTUSDT", exact=True).wait_for()
            page.get_by_role("button", name="☆ 关注").click()
            page.get_by_role("button", name="★ 已关注").wait_for()
            page.get_by_role("link", name="创建价格提醒", exact=True).click()
            page.locator('[name="operator"]').select_option("step")
            page.locator('[name="value"]').fill("10")
            page.locator('[name="step_anchor"]').fill("100")
            page.get_by_role("button", name="创建提醒", exact=True).click()
            page.get_by_role("button", name="暂停", exact=True).click()
            page.get_by_role("button", name="启用", exact=True).wait_for()
            page.goto(base + "/#watchlist")
            page.get_by_role("button", name="移除关注 TESTUSDT").click()
            page.get_by_role("heading", name="我的关注", exact=True).wait_for()
            assert page.locator('.row-follow[aria-pressed="true"]').count() == 0
            page.goto(base + "/#alerts")
            page.get_by_role("button", name="暂停", exact=True).wait_for()
            page.goto(base + "/#catalog")
            page.once("dialog", lambda dialog: dialog.accept())
            page.get_by_role("button", name="从我的资产目录删除 TESTUSDT").first.click()
            page.get_by_role("heading", name="资产目录", exact=True).wait_for()
            assert page.locator(".asset-row").count() == 1
            for route in ("home", "catalog", "watchlist", "news", "alerts", "notifications", "profile", "settings", "login", "register", "add", "asset/1", "asset/2"):
                page.goto(base + "/#" + route)
                page.locator("h1").wait_for()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), route
            page.goto(base + "/#asset/2")
            assert page.locator(".candle-chart .candle").count() == 1
            page.get_by_text("查看历史数据", exact=True).click()
            assert page.locator(".chart-table tbody tr").count() == 1
            page.goto(base + "/#settings")
            page.get_by_role("button", name="夜间", exact=True).click()
            assert page.locator("html").get_attribute("data-theme") == "dark"
            page.reload()
            page.get_by_role("button", name="夜间", exact=True).wait_for()
            assert page.get_by_role("button", name="夜间", exact=True).get_attribute("aria-pressed") == "true"
            page.get_by_role("button", name="浅色", exact=True).click()
            assert page.locator("html").get_attribute("data-theme") == "light"
            page.locator('[name="refresh"]').select_option("60")
            page.get_by_role("button", name="保存设置").click()
            page.reload()
            page.locator('[name="refresh"]').wait_for()
            assert page.locator('[name="refresh"]').input_value() == "60"
            page.goto(base + "/#home")
            page.get_by_role("heading", name="市场，尽在掌握").wait_for()
            row = page.locator(".asset-row").first
            before = row.bounding_box()
            row.hover()
            page.wait_for_timeout(700)
            after = row.bounding_box()
            assert abs(before["x"] - after["x"]) < 1
            page.screenshot(path=str(output / "mobile-test-fixtures.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(output / "desktop-test-fixtures.png"), full_page=True)
            page.evaluate("navigator.serviceWorker.ready")
            keys = page.evaluate("caches.keys().then(async keys => (await Promise.all(keys.map(async key => (await (await caches.open(key)).keys()).map(r=>new URL(r.url).pathname)))).flat())")
            assert "/" in keys and not any(key.startswith("/api/") for key in keys)
            context.set_offline(True)
            page.reload(wait_until="domcontentloaded")
            page.get_by_text("当前离线。", exact=False).wait_for()
            page.get_by_role("heading", name="市场，尽在掌握").wait_for()
            assert not errors, errors
            print("Browser checks passed: mobile/desktop routes, futures follow, Step alert, pause, history, settings, shell cache, offline.")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        api.app.dependency_overrides.clear()
        engine.dispose()


if __name__ == "__main__":
    main()
