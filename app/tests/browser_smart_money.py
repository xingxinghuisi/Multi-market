"""Real browser/API with synthetic snapshots and an isolated database. Never calls Binance."""
import os
from pathlib import Path
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
import mobile_api
from binance_smart_money import parse_overview, SmartMoneyUnavailable
from database import Base
from models import Asset


def main():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    lock = threading.Lock()
    with sessions() as db:
        db.add(Asset(symbol='KORUUSDT', name='Synthetic browser fixture', asset_type='crypto',
                     venue='BINANCE', segment='FUTURES', currency='USDT', provider='BINANCE_FUTURES'))
        db.commit()

    def get_db():
        with lock, sessions() as db:
            yield db

    state = {'calls': 0, 'fail': False}
    def snapshot(symbol):
        state['calls'] += 1
        if state['fail']:
            state['fail'] = False
            raise SmartMoneyUnavailable('access_restricted', 1800)
        return parse_overview({'code': '000000', 'success': True, 'data': {
            'symbol': symbol, 'updateTime': int((time.time()-8*3600)*1000),
            'totalPositions': 1000000, 'totalTraders': 20, 'longShortRatio': .5,
            'longTraders': 10, 'shortTraders': 10, 'longWhales': 3, 'shortWhales': 4,
            'longWhalesAvgEntryPrice': 14, 'shortWhalesAvgEntryPrice': 19,
            'longProfitWhales': 0,
        }}, symbol)

    def no_external(_url):
        raise OSError('External data disabled in browser tests')

    @api.app.get('/__fixture__/smart-money')
    def fixture_status():
        return state

    @api.app.post('/__fixture__/smart-money-fail')
    def fail_next():
        state['fail'] = True
        return {'synthetic_fixture': True}

    api.app.dependency_overrides[api.get_db] = get_db
    api.app.state.auth_session_factory = sessions
    api.app.state.auth_insecure_local_cookie = True
    api._binance_read_json = no_external
    mobile_api.smart_money_client.get = snapshot
    api.load_realtime_market_quotes = lambda: []
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    os.environ['RADAR_PUBLIC_ORIGIN'] = base
    server = uvicorn.Server(uvicorn.Config(api.app, log_level='error', lifespan='off'))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError('Browser fixture server did not start')
        time.sleep(.05)
    try:
        result = subprocess.run(['node', str(Path(__file__).with_name('smart-money.browser.cjs'))],
                                env={**os.environ, 'RADAR_TEST_BASE_URL': base}, timeout=90)
        return result.returncode
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        api.app.dependency_overrides.clear()
        engine.dispose()


if __name__ == '__main__':
    sys.exit(main())
