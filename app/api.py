import asyncio
import json
import os
import time

from news_notification_service import (
    maybe_send_news_notification,
)

from hybrid_news_analyzer import HybridNewsAnalyzer

from providers.google_news import (
    GoogleNewsProvider,
)

from urllib.request import (
    ProxyHandler,
    Request,
    build_opener,
    urlopen,
)
from contextlib import suppress

from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import date
from datetime import datetime, timezone



from database import Base, SessionLocal, engine as database_engine
from auth_api import authenticated_websocket, current_user_id, install_auth
from models import (
    Notification,
    DailyPrice,
    AlertRule,
    AlertState,
    AlertSubscription,
    Asset,
    User,
    UserCredential,
    UserSession,
    UserHiddenAsset,
    TelegramChallenge,
    MarketQuote,
    NewsItem,
    NewsImpact,
    WatchlistItem,
)
from schemas import (
    AlertRuleCreate,
    AlertRuleUpdate,
    SubscriptionUpsert,
    AssetCreate,
    AssetQuickCreate,
    AssetUpdate,
    NewsTestCreate,
    WatchlistCreate,
)




# =========================================================
# Realtime WebSocket Connections
# =========================================================

class ConnectionManager:

    def __init__(self):

        self.active_connections: list[WebSocket] = []

    def add(
        self,
        websocket: WebSocket,
    ):

        self.active_connections.append(
            websocket
        )

    def disconnect(
        self,
        websocket: WebSocket,
    ):

        if websocket in self.active_connections:

            self.active_connections.remove(
                websocket
            )

    async def broadcast_json(
        self,
        data,
    ):

        disconnected = []

        for websocket in self.active_connections:

            try:

                await websocket.send_json(
                    data
                )

            except Exception:

                disconnected.append(
                    websocket
                )

        for websocket in disconnected:

            self.disconnect(
                websocket
            )


manager = ConnectionManager()


# =========================================================
# FastAPI
# =========================================================

app = FastAPI(
    title="Market Radar API",
    description=(
        "Market Radar Web / App Backend API"
    ),
    version="0.3.0",
)

BASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
)

WEB_DIR = (
    BASE_DIR
    / "web"
)

STATIC_DIR = (
    WEB_DIR
    / "static"
)


app.mount(
    "/static",
    StaticFiles(
        directory=STATIC_DIR
    ),
    name="static",
)

from mobile_api import install_mobile_routes
from subscription_service import initialize_subscription_tables, supports_subscription, subscription_config


@app.on_event(
    "startup"
)
async def start_market_broadcaster():

    Base.metadata.create_all(database_engine, tables=[UserCredential.__table__, UserSession.__table__,
                                                     UserHiddenAsset.__table__, TelegramChallenge.__table__], checkfirst=True)
    initialize_subscription_tables(database_engine)

    app.state.market_broadcast_task = (
        asyncio.create_task(
            market_broadcast_loop()
        )
    )


@app.on_event(
    "shutdown"
)
async def stop_market_broadcaster():

    task = getattr(
        app.state,
        "market_broadcast_task",
        None,
    )

    if task is None:

        return

    task.cancel()

    with suppress(
        asyncio.CancelledError
    ):

        await task


# =========================================================
# Database Session
# =========================================================

def get_db():

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


# =========================================================
# Helpers
# =========================================================

# =========================================================
# Asset Search Cache
# =========================================================

_binance_asset_catalog_cache = {
    "loaded_at": 0.0,
    "data": [],
}

BINANCE_ASSET_CATALOG_TTL = 300

_moomoo_asset_catalog_cache = {
    "US": {
        "loaded_at": 0.0,
        "data": [],
    },

    "HK": {
        "loaded_at": 0.0,
        "data": [],
    },
}

MOOMOO_ASSET_CATALOG_TTL = 300


def create_moomoo_provider():
    # The SDK creates log files on import. Load it only for Moomoo requests,
    # so the web client and other markets can start without an OpenD setup.
    from providers.moomoo import MoomooRealtimeProvider

    return MoomooRealtimeProvider()


def load_moomoo_asset_catalog(
    market: str,
):

    market = (
        market.strip()
        .upper()
    )

    cache_key = (
        "HK"
        if market in {
            "HK",
            "HKEX",
        }
        else
        market
    )

    if cache_key not in (
        _moomoo_asset_catalog_cache
    ):

        raise ValueError(
            f"Unsupported market: "
            f"{market}"
        )

    now = time.monotonic()

    cache = (
        _moomoo_asset_catalog_cache[
            cache_key
        ]
    )

    if (
        cache["data"]
        and
        now - cache["loaded_at"]
        < MOOMOO_ASSET_CATALOG_TTL
    ):

        return cache["data"]

    provider = (
        create_moomoo_provider()
    )

    data = (
        provider.load_stock_catalog(
            cache_key
        )
    )

    cache["loaded_at"] = now
    cache["data"] = data

    return data


def _binance_read_json(
    url: str,
):


    request = Request(
        url,
        headers={
            "User-Agent":
                "Market-Radar/1.0",
        },
    )

    proxy_url = os.getenv(
        "BINANCE_PROXY_URL"
    )

    if proxy_url:

        opener = build_opener(
            ProxyHandler(
                {
                    "http":
                        proxy_url,

                    "https":
                        proxy_url,
                }
            )
        )

        with opener.open(
            request,
            timeout=15,
        ) as response:

            return json.loads(
                response
                .read()
                .decode("utf-8")
            )

    with urlopen(
        request,
        timeout=15,
    ) as response:

        return json.loads(
            response
            .read()
            .decode("utf-8")
        )


def load_binance_asset_catalog():

    now = time.monotonic()

    cached_data = (
        _binance_asset_catalog_cache[
            "data"
        ]
    )

    loaded_at = (
        _binance_asset_catalog_cache[
            "loaded_at"
        ]
    )

    if (
        cached_data
        and
        now - loaded_at
        < BINANCE_ASSET_CATALOG_TTL
    ):

        return cached_data

    results = []

    # =====================================================
    # Binance Spot
    # =====================================================

    spot_data = _binance_read_json(
        "https://api.binance.com"
        "/api/v3/exchangeInfo"
    )

    for item in spot_data.get(
        "symbols",
        [],
    ):

        if (
            item.get("status")
            != "TRADING"
        ):

            continue

        symbol = item.get(
            "symbol",
            "",
        ).upper()

        base_asset = item.get(
            "baseAsset",
            "",
        ).upper()

        quote_asset = item.get(
            "quoteAsset",
            "",
        ).upper()

        # 当前 Market Radar
        # Crypto 主要监控 USDT 交易对
        if quote_asset != "USDT":

            continue

        results.append(
            {
                "market":
                    "CRYPTO",

                "symbol":
                    symbol,

                "name":
                    (
                        f"{base_asset} / "
                        f"{quote_asset}"
                    ),

                "asset_type":
                    "crypto",

                "venue":
                    "BINANCE",

                "segment":
                    "SPOT",

                "currency":
                    quote_asset,

                "provider":
                    "BINANCE",

                "instrument_type":
                    "spot",

                "display_label":
                    (
                        f"{symbol} · "
                        f"Binance 现货"
                    ),
            }
        )

    # =====================================================
    # Binance USD-M Futures
    # =====================================================

    futures_data = _binance_read_json(
        "https://fapi.binance.com"
        "/fapi/v1/exchangeInfo"
    )

    for item in futures_data.get(
        "symbols",
        [],
    ):

        if (
            item.get("status")
            != "TRADING"
        ):

            continue

        contract_type = (
            item.get(
                "contractType",
                ""
            )
            .strip()
            .upper()
        )

        if contract_type not in {
            "PERPETUAL",
            "TRADIFI_PERPETUAL",
        }:
            continue

        symbol = item.get(
            "symbol",
            "",
        ).upper()

        base_asset = item.get(
            "baseAsset",
            "",
        ).upper()

        quote_asset = item.get(
            "quoteAsset",
            "",
        ).upper()

        if quote_asset != "USDT":

            continue

        results.append(
            {
                "market":
                    "CRYPTO",

                "symbol":
                    symbol,

                "name":
                    (
                        f"{base_asset} / "
                        f"{quote_asset}"
                    ),

                "asset_type":
                    "crypto",

                "venue":
                    "BINANCE",

                "segment":
                    "FUTURES",

                "currency":
                    quote_asset,

                "provider":
                    "BINANCE",

                "instrument_type":
                    "perpetual",

                "display_label":
                    (
                        f"{symbol} · "
                        f"Binance 永续"
                    ),
            }
        )

    _binance_asset_catalog_cache[
        "loaded_at"
    ] = now

    _binance_asset_catalog_cache[
        "data"
    ] = results

    return results


def get_default_user(
    db: Session,
):

    user_id = current_user_id()
    user = db.get(User, user_id) if user_id is not None else None

    if not user:

        raise HTTPException(
            status_code=401,
            detail="请先登录",
        )

    return user
def serialize_daily_price(
    daily_price: DailyPrice,
):

    return {
        "date": daily_price.date,
        "open": daily_price.open,
        "high": daily_price.high,
        "low": daily_price.low,
        "close": daily_price.close,
        "volume": daily_price.volume,
        "change_pct": daily_price.change_pct,
    }

def serialize_market_quote(
    quote: MarketQuote,
    asset: Asset,
):

    return {
        "asset_id": asset.id,
        "symbol": asset.symbol,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "venue": asset.venue,
        "segment": asset.segment,
        "currency": asset.currency,
        "provider": asset.provider,

        "price": quote.price,
        "reference_price": quote.reference_price,
        "change_amount": quote.change_amount,
        "change_pct": quote.change_pct,

        "open": quote.open,
        "high": quote.high,
        "low": quote.low,
        "volume": quote.volume,
        "quote_volume": quote.quote_volume,

        "event_time": quote.event_time,
        "session_date": quote.session_date,

        "reference_type": quote.reference_type,
        "reference_timezone": quote.reference_timezone,

        "regular_price":
            quote.regular_price,

        "pre_price":
            quote.pre_price,

        "after_price":
            quote.after_price,

        "overnight_price":
            quote.overnight_price,

        "market_session":
            quote.market_session,

        "updated_at": quote.updated_at,

        "regular_updated_at": (
            quote.regular_updated_at.isoformat()
            if quote.regular_updated_at
            else None
        ),

        "pre_updated_at": (
            quote.pre_updated_at.isoformat()
            if quote.pre_updated_at
            else None
        ),

        "after_updated_at": (
            quote.after_updated_at.isoformat()
            if quote.after_updated_at
            else None
        ),

        "overnight_updated_at": (
            quote.overnight_updated_at.isoformat()
            if quote.overnight_updated_at
            else None
        ),
    }

def load_realtime_market_quotes():

    with SessionLocal() as db:

        rows = db.execute(
            select(
                MarketQuote,
                Asset,
            )
            .join(
                Asset,
                MarketQuote.asset_id
                == Asset.id,
            )
            .where(
                Asset.enabled == True
            )
            .order_by(
                Asset.id
            )
        ).all()

        data = []

        for quote, asset in rows:

            data.append(
                {
                    "type": "market_update",

                    "asset_id": asset.id,
                    "symbol": asset.symbol,
                    "name": asset.name,

                    "asset_type": asset.asset_type,
                    "venue": asset.venue,
                    "currency": asset.currency,

                    "price": quote.price,

                    "reference_price":
                        quote.reference_price,

                    "change_amount":
                        quote.change_amount,

                    "change_pct":
                        quote.change_pct,

                    "open": quote.open,
                    "high": quote.high,
                    "low": quote.low,

                    "volume": quote.volume,
                    "quote_volume":
                        quote.quote_volume,

                    "session_date":
                        quote.session_date,

                    "reference_type":
                        quote.reference_type,

                    "reference_timezone":
                        quote.reference_timezone,

                    "regular_price":
                        quote.regular_price,

                    "pre_price":
                        quote.pre_price,

                    "after_price":
                        quote.after_price,

                    "overnight_price":
                        quote.overnight_price,

                    "market_session":
                        quote.market_session,

                    "event_time": (
                        quote.event_time.isoformat()
                        if quote.event_time
                        else None
                    ),

                    "updated_at": (
                        quote.updated_at.isoformat()
                        if quote.updated_at
                        else None
                    ),

                    "regular_updated_at": (
                        quote.regular_updated_at.isoformat()
                        if quote.regular_updated_at
                        else None
                    ),

                    "pre_updated_at": (
                        quote.pre_updated_at.isoformat()
                        if quote.pre_updated_at
                        else None
                    ),

                    "after_updated_at": (
                        quote.after_updated_at.isoformat()
                        if quote.after_updated_at
                        else None
                    ),

                    "overnight_updated_at": (
                        quote.overnight_updated_at.isoformat()
                        if quote.overnight_updated_at
                        else None
                    ),
                }
            )

        return data

async def market_broadcast_loop():

    last_versions = {}

    while True:

        try:

            quotes = await asyncio.to_thread(
                load_realtime_market_quotes
            )

            current_asset_ids = set()

            for quote in quotes:

                asset_id = quote[
                    "asset_id"
                ]

                current_asset_ids.add(
                    asset_id
                )

                version = (
                    quote["price"],
                    quote["change_pct"],
                    quote["high"],
                    quote["low"],
                    quote["volume"],
                    quote["session_date"],

                    quote.get(
                        "regular_price"
                    ),

                    quote.get(
                        "pre_price"
                    ),

                    quote.get(
                        "after_price"
                    ),

                    quote.get(
                        "overnight_price"
                    ),

                    quote.get(
                        "market_session"
                    ),

                    quote.get(
                        "regular_updated_at"
                    ),

                    quote.get(
                        "pre_updated_at"
                    ),

                    quote.get(
                        "after_updated_at"
                    ),

                    quote.get(
                        "overnight_updated_at"
                    ),
                )

                previous_version = (
                    last_versions.get(
                        asset_id
                    )
                )

                if (
                    previous_version
                    != version
                ):

                    await manager.broadcast_json(
                        quote
                    )

                    last_versions[
                        asset_id
                    ] = version

            # =============================================
            # 清理已经 disabled / 删除的 Asset 状态
            # =============================================

            removed_asset_ids = (
                set(last_versions.keys())
                - current_asset_ids
            )

            for asset_id in removed_asset_ids:

                last_versions.pop(
                    asset_id,
                    None,
                )

        except asyncio.CancelledError:

            raise

        except Exception as error:

            print(
                f"[WEBSOCKET ERROR] "
                f"{error}"
            )

        await asyncio.sleep(
            0.5
        )

def serialize_asset(
    asset: Asset,
):

    return {
        "id": asset.id,
        "symbol": asset.symbol,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "venue": asset.venue,
        "segment": asset.segment,
        "currency": asset.currency,
        "provider": asset.provider,
        "enabled": asset.enabled,
        "created_at": asset.created_at,
    }

def get_asset_or_404(
    db: Session,
    asset_id: int,
):

    asset = db.get(
        Asset,
        asset_id,
    )

    if not asset:

        raise HTTPException(
            status_code=404,
            detail="Asset not found",
        )

    return asset


def build_asset_news_query(
    asset: Asset,
):

    symbol = (
        asset.symbol
        or ""
    ).strip().upper()

    name = (
        asset.name
        or ""
    ).strip()

    venue = (
        asset.venue
        or ""
    ).strip().upper()

    # =====================================================
    # Binance
    # =====================================================
    if (
        venue == "BINANCE"
        and symbol.endswith("USDT")
    ):

        base = symbol[:-4]

        # 常见加密资产使用正式名称，
        # 防止 ticker 本身产生大量无关新闻。
        crypto_aliases = {
            "BTC": "Bitcoin",
            "ETH": "Ethereum",
            "SOL": "Solana",
            "DOGE": "Dogecoin",
            "XRP": "XRP",
            "BNB": "BNB",
            "ADA": "Cardano",
            "AVAX": "Avalanche",
            "LINK": "Chainlink",
        }

        if base in crypto_aliases:
            full_name = crypto_aliases[base]

            return (
                f'"{full_name}" OR '
                f'"{base}" cryptocurrency'
            )

        # 特殊股票 / ETF 型 Binance 标的。
        # 这些 ticker 本身可能是普通英文单词，
        # 必须加入金融语义减少误匹配。
        finance_aliases = {
            "KORU": (
                '"KORU" '
                '("ETF" OR "Direxion" OR "South Korea")'
            ),
            "SKHY": (
                '"SK Hynix" OR "SK hynix"'
            ),
        }

        if base in finance_aliases:
            return finance_aliases[base]

        # 未知 Binance 标的：
        # 不再直接裸搜 ticker。
        return (
            f'"{base}" '
            '(finance OR market OR crypto OR stock OR ETF)'
        )

    # =====================================================
    # 非 Binance 资产
    # =====================================================
    if (
        name
        and name.upper() != symbol
    ):
        return (
            f'"{name}" OR '
            f'"{symbol}"'
        )

    return f'"{symbol}"'


def get_news_locale(
    asset: Asset,
):

    venue = (
        asset.venue
        or ""
    ).upper()

    if venue in {
        "KR",
        "KRX",
    }:

        return {
            "hl": "ko",
            "gl": "KR",
            "ceid": "KR:ko",
        }

    if venue == "HKEX":

        return {
            "hl": "zh-HK",
            "gl": "HK",
            "ceid": "HK:zh-Hant",
        }

    return {
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }

# =========================================================
# Watchlist
# =========================================================

@app.get("/api/watchlist")
def get_watchlist(
    db: Session = Depends(get_db),
):

    user = get_default_user(
        db
    )

    rows = db.execute(
        select(
            WatchlistItem,
            Asset,
        )
        .join(
            Asset,
            WatchlistItem.asset_id
            == Asset.id,
        )
        .where(
            WatchlistItem.user_id
            == user.id
        )
        .order_by(
            WatchlistItem.id
        )
    ).all()

    return [
        {
            "id":
                item.id,

            "user_id":
                item.user_id,

            "asset_id":
                asset.id,

            "symbol":
                asset.symbol,

            "name":
                asset.name,

            "asset_type":
                asset.asset_type,

            "venue":
                asset.venue,

            "segment":
                asset.segment,

            "provider":
                asset.provider,

            "enabled":
                asset.enabled,

            "news_enabled":
                item.news_enabled,

            "price_alerts_enabled":
                item.price_alerts_enabled,

            "created_at":
                item.created_at,
        }

        for item, asset
        in rows
    ]


@app.post("/api/watchlist")
def add_watchlist_item(
    payload: WatchlistCreate,
    db: Session = Depends(get_db),
):

    user = get_default_user(
        db
    )

    asset = db.get(
        Asset,
        payload.asset_id,
    )

    if asset is None:

        raise HTTPException(
            status_code=404,
            detail="Asset not found",
        )

    if not asset.enabled:

        raise HTTPException(
            status_code=400,
            detail="Asset is disabled",
        )

    existing = db.scalar(
        select(
            WatchlistItem
        )
        .where(
            WatchlistItem.user_id
            == user.id,

            WatchlistItem.asset_id
            == asset.id,
        )
    )

    if existing is not None:

        existing.news_enabled = (
            payload.news_enabled
        )

        existing.price_alerts_enabled = (
            payload.price_alerts_enabled
        )

        db.commit()

        db.refresh(
            existing
        )

        return {
            "status":
                "already_followed",

            "id":
                existing.id,

            "asset_id":
                asset.id,

            "symbol":
                asset.symbol,

            "news_enabled":
                existing.news_enabled,

            "price_alerts_enabled":
                existing.price_alerts_enabled,
        }

    item = WatchlistItem(
        user_id=user.id,
        asset_id=asset.id,

        news_enabled=(
            payload.news_enabled
        ),

        price_alerts_enabled=(
            payload.price_alerts_enabled
        ),
    )

    db.add(
        item
    )

    db.commit()

    db.refresh(
        item
    )

    return {
        "status":
            "followed",

        "id":
            item.id,

        "asset_id":
            asset.id,

        "symbol":
            asset.symbol,

        "news_enabled":
            item.news_enabled,

        "price_alerts_enabled":
            item.price_alerts_enabled,
    }


@app.delete(
    "/api/watchlist/{asset_id}"
)
def remove_watchlist_item(
    asset_id: int,
    db: Session = Depends(get_db),
):

    user = get_default_user(
        db
    )

    item = db.scalar(
        select(
            WatchlistItem
        )
        .where(
            WatchlistItem.user_id
            == user.id,

            WatchlistItem.asset_id
            == asset_id,
        )
    )

    if item is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Asset is not in watchlist"
            ),
        )

    db.delete(
        item
    )

    db.commit()

    return {
        "status":
            "unfollowed",

        "asset_id":
            asset_id,
    }



def apply_news_analysis(
    impact,
    analysis,
):

    source = analysis.get(
        "analysis_source",
        "rule",
    )

    impact.sentiment = (
        analysis["sentiment"]
    )

    impact.impact_score = (
        analysis["impact_score"]
    )

    impact.relevance_score = (
        analysis.get(
            "relevance_score"
        )
    )

    impact.analysis_source = (
        source
    )

    impact.reason = (
        f"[{source.upper()}] "
        f"{analysis['reason']}"
    )

    impact.analyzed_at = (
        datetime.now(
            timezone.utc
        )
    )

    return source


# =========================================================
# News
# =========================================================

def serialize_news(
    news: NewsItem,
    impact: NewsImpact,
    asset: Asset,
):

    return {
        "news_id":
            news.id,

        "asset_id":
            asset.id,

        "symbol":
            asset.symbol,

        "name":
            asset.name,

        "venue":
            asset.venue,

        "source":
            news.source,

        "title":
            news.title,

        "summary":
            news.summary,

        "url":
            news.url,

        "published_at":
            news.published_at,

        "sentiment":
    impact.sentiment,

"impact_score":
    impact.impact_score,

"relevance_score":
    impact.relevance_score,

"analysis_source":
    impact.analysis_source,

"analyzed_at":
    impact.analyzed_at,

"reason":
    impact.reason,
    }


@app.post("/api/news/test")
def create_test_news(
    payload: NewsTestCreate,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        payload.asset_id,
    )

    sentiment = (
        payload.sentiment
        .strip()
        .lower()
    )

    if sentiment not in {
        "positive",
        "negative",
        "neutral",
    }:

        raise HTTPException(
            status_code=400,
            detail=(
                "sentiment must be "
                "positive, negative or neutral"
            ),
        )

    news = NewsItem(
        source="TEST",
        url=(
            "test://news/"
            f"{asset.id}/"
            f"{time.time_ns()}"
        ),
        title=payload.title.strip(),
        summary=None,
    )

    db.add(news)
    db.flush()

    impact = NewsImpact(
        news_id=news.id,
        asset_id=asset.id,
        sentiment=sentiment,
        impact_score=payload.impact_score,
        reason=(
            payload.reason.strip()
            if payload.reason
            else None
        ),
    )

    db.add(impact)

    db.commit()

    db.refresh(news)
    db.refresh(impact)

    return serialize_news(
        news,
        impact,
        asset,
    )


@app.get("/api/news")
def get_news(
    limit: int = 50,
    db: Session = Depends(get_db),
):

    limit = max(
        1,
        min(
            limit,
            200,
        ),
    )

    rows = db.execute(
        select(
            NewsItem,
            NewsImpact,
            Asset,
        )
        .join(
            NewsImpact,
            NewsImpact.news_id
            == NewsItem.id,
        )
        .join(
            Asset,
            Asset.id
            == NewsImpact.asset_id,
        )
        .order_by(
            NewsItem.id.desc()
        )
        .limit(limit)
    ).all()

    return [
        serialize_news(
            news,
            impact,
            asset,
        )

        for (
            news,
            impact,
            asset,
        ) in rows
    ]


@app.get(
    "/api/assets/{asset_id}/news"
)
def get_asset_news(
    asset_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        asset_id,
    )

    limit = max(
        1,
        min(
            limit,
            200,
        ),
    )

    rows = db.execute(
        select(
            NewsItem,
            NewsImpact,
        )
        .join(
            NewsImpact,
            NewsImpact.news_id
            == NewsItem.id,
        )
        .where(
            NewsImpact.asset_id
            == asset_id
        )
        .order_by(
            NewsItem.id.desc()
        )
        .limit(limit)
    ).all()

    return [
        serialize_news(
            news,
            impact,
            asset,
        )

        for (
            news,
            impact,
        ) in rows
    ]

@app.post(
    "/api/news/fetch/{asset_id}"
)
def fetch_asset_news(
    asset_id: int,
    limit: int = 10,
    max_analyze: int | None = None,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        asset_id,
    )

    limit = max(
        1,
        min(
            limit,
            50,
        ),
    )

    if max_analyze is not None:
        max_analyze = max(
            0,
            min(
                max_analyze,
                limit,
            ),
        )

    query = build_asset_news_query(
        asset
    )

    locale = get_news_locale(
        asset
    )

    provider = GoogleNewsProvider()

    analyzer = HybridNewsAnalyzer()

    try:

        items = provider.search(
            query=query,
            limit=limit,
            time_range="1d",
            **locale,
        )

    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "News fetch failed: "
                f"{error}"
            ),
        ) from error

    # =====================================================
    # 第一层去重：
    # Google News 本次返回的数据内部可能存在重复 URL
    # =====================================================

    raw_fetched = len(items)

    unique_items = []

    seen_urls = set()

    for item in items:

        url = (
            item.get("url")
            or ""
        ).strip()

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(
            url
        )

        unique_items.append(
            item
        )

    items = unique_items

    # =====================================================
    # 第二层去重：
    # 当前 Asset 已经关联过哪些 news_id
    # =====================================================

    linked_news_ids = set(
        db.scalars(
            select(
                NewsImpact.news_id
            )
            .where(
                NewsImpact.asset_id
                == asset.id
            )
        ).all()
    )

    created_news = 0
    reused_news = 0
    created_links = 0
    analyzed_news = 0
    queued_news = 0

    for item in items:

        news = db.scalar(
            select(
                NewsItem
            )
            .where(
                NewsItem.url
                == item["url"]
            )
        )

        # =============================================
        # 新闻不存在：创建
        # =============================================

        if news is None:

            news = NewsItem(
                source=(
                    item.get(
                        "source"
                    )
                    or "Google News"
                )[:100],

                url=item[
                    "url"
                ],

                title=item[
                    "title"
                ],

                summary=item.get(
                    "summary"
                ),

                published_at=item.get(
                    "published_at"
                ),
            )

            db.add(
                news
            )

            # 必须先 flush
            # 才能拿到 news.id
            db.flush()

            created_news += 1

        # =============================================
        # 新闻已经存在
        # =============================================

        else:

            reused_news += 1

            # 老新闻没有 summary，
            # 新抓取结果有 summary 时补进去
            if (
                not news.summary
                and item.get(
                    "summary"
                )
            ):

                news.summary = item[
                    "summary"
                ]

        # =============================================
        # 这个 Asset 已经关联过该新闻
        # 直接跳过
        # =============================================

        if news.id in linked_news_ids:

            continue

        # =============================================
        # 自动分析
        # =============================================

        should_analyze = (
                max_analyze is None
                or analyzed_news
                < max_analyze
        )

        if should_analyze:

            analysis = analyzer.analyze(
                title=news.title,
                summary=news.summary,
                symbol=asset.symbol,
                name=asset.name,
                asset_type=asset.asset_type,
                venue=asset.venue,
                segment=asset.segment,
                provider=asset.provider,
            )

            impact = NewsImpact(
                news_id=news.id,
                asset_id=asset.id,

                sentiment="neutral",
                impact_score=0,
            )

            source = apply_news_analysis(
                impact,
                analysis,
            )

            notification_result = (
                maybe_send_news_notification(
                    db=db,
                    asset=asset,
                    news=news,
                    impact=impact,
                )
            )

            analyzed_news += 1

        else:

            impact = NewsImpact(
                news_id=news.id,
                asset_id=asset.id,

                sentiment="neutral",

                impact_score=0,

                reason=(
                    "Imported from Google News RSS; "
                    "not analyzed yet."
                ),
            )

            queued_news += 1

        db.add(
            impact
        )

        # 关键：
        # 马上记住当前事务已经创建了这组关联
        # 即使数据库还没 commit，也不会再次创建
        linked_news_ids.add(
            news.id
        )

        created_links += 1

    db.commit()

    return {
        "asset_id":
            asset.id,

        "symbol":
            asset.symbol,

        "query":
            query,

        "fetched":
            raw_fetched,

        "unique_fetched":
            len(items),

        "duplicate_results":
            raw_fetched
            - len(items),

        "created_news":
            created_news,

        "reused_news":
            reused_news,

        "created_links":
            created_links,

        "analyzed_news":
            analyzed_news,

        "queued_news":
            queued_news,

        "max_analyze":
            max_analyze,
    }

@app.post(
    "/api/news/analyze/{news_id}"
)
def analyze_news(
    news_id: int,
    db: Session = Depends(get_db),
):

    rows = db.execute(
        select(
            NewsItem,
            NewsImpact,
            Asset,
        )
        .join(
            NewsImpact,
            NewsImpact.news_id
            == NewsItem.id,
        )
        .join(
            Asset,
            Asset.id
            == NewsImpact.asset_id,
        )
        .where(
            NewsItem.id
            == news_id
        )
    ).all()

    if not rows:

        raise HTTPException(
            status_code=404,
            detail="News impact not found",
        )

    analyzer = HybridNewsAnalyzer()

    results = []

    for (
        news,
        impact,
        asset,
    ) in rows:
        analysis = analyzer.analyze(
            title=news.title,
            summary=news.summary,
            symbol=asset.symbol,
            name=asset.name,
            asset_type=asset.asset_type,
            venue=asset.venue,
            segment=asset.segment,
            provider=asset.provider,
        )

        source = apply_news_analysis(
            impact,
            analysis,
        )

        results.append(
            {
                "news_id":
                    news.id,

                "asset_id":
                    asset.id,

                "symbol":
                    asset.symbol,

                "title":
                    news.title,

                "sentiment":
                    impact.sentiment,

                "impact_score":
                    impact.impact_score,

                "reason":
                    impact.reason,

                "analysis_source":
                    analysis.get(
                        "analysis_source"
                    ),

                "fallback_reason":
                    analysis.get(
                        "fallback_reason"
                    ),

                "model":
                    analysis.get(
                        "model"
                    ),

                "relevance_score":
                    analysis.get(
                        "relevance_score"
                    ),
            }
        )

    db.commit()

    return {
        "news_id":
            news_id,

        "analyzed":
            len(results),

        "data":
            results,
    }


@app.post(
    "/api/assets/{asset_id}/news/analyze-all"
)
def analyze_asset_news_all(
    asset_id: int,
    limit: int = 20,
    force: bool = False,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        asset_id,
    )

    limit = max(
        1,
        min(
            limit,
            50,
        ),
    )

    rows = db.execute(
        select(
            NewsItem,
            NewsImpact,
        )
        .join(
            NewsImpact,
            NewsImpact.news_id
            == NewsItem.id,
        )
        .where(
            NewsImpact.asset_id
            == asset.id
        )
        .order_by(
            NewsItem.id.desc()
        )
        .limit(limit)
    ).all()

    analyzer = HybridNewsAnalyzer()

    results = []

    skipped = 0
    analyzed = 0
    groq_count = 0
    rule_count = 0
    error_count = 0

    for (
        news,
        impact,
    ) in rows:

        current_reason = (
            impact.reason
            or ""
        )

        # 已经由 Groq 分析过的新闻，
        # 默认不重复消耗免费额度
        if (
            not force
            and current_reason.startswith(
                "[GROQ]"
            )
        ):

            skipped += 1
            continue

        try:

            analysis = analyzer.analyze(
                title=news.title,
                summary=news.summary,
                symbol=asset.symbol,
                name=asset.name,
                asset_type=asset.asset_type,
                venue=asset.venue,
                segment=asset.segment,
                provider=asset.provider,
            )

            source = analysis.get(
                "analysis_source",
                "rule",
            )

            source = apply_news_analysis(
                impact,
                analysis,
            )

            analyzed += 1

            if source == "groq":

                groq_count += 1

            else:

                rule_count += 1

            results.append(
                {
                    "news_id":
                        news.id,

                    "source":
                        news.source,

                    "title":
                        news.title,

                    "sentiment":
                        impact.sentiment,

                    "impact_score":
                        impact.impact_score,

                    "reason":
                        impact.reason,

                    "analysis_source":
                        source,

                    "fallback_reason":
                        analysis.get(
                            "fallback_reason"
                        ),

                    "model":
                        analysis.get(
                            "model"
                        ),

                    "relevance_score":
                        analysis.get(
                            "relevance_score"
                        ),
                }
            )

        except Exception as error:

            error_count += 1

            results.append(
                {
                    "news_id":
                        news.id,

                    "error":
                        type(error).__name__,

                    "detail":
                        str(error),
                }
            )

    db.commit()

    return {
        "asset_id":
            asset.id,

        "symbol":
            asset.symbol,

        "requested_limit":
            limit,

        "found":
            len(rows),

        "analyzed":
            analyzed,

        "groq":
            groq_count,

        "rule":
            rule_count,

        "skipped":
            skipped,

        "errors":
            error_count,

        "data":
            results,
    }

@app.post(
    "/api/news/analyze-pending"
)
def analyze_pending_news(
    limit: int = 50,
    db: Session = Depends(get_db),
):

    limit = max(
        1,
        min(
            limit,
            200,
        ),
    )

    rows = db.execute(
        select(
            NewsItem,
            NewsImpact,
            Asset,
        )
        .join(
            NewsImpact,
            NewsImpact.news_id
            == NewsItem.id,
        )
        .join(
            Asset,
            Asset.id
            == NewsImpact.asset_id,
        )
        .where(
            NewsImpact.reason.like(
                "%not analyzed yet%"
            ),

            Asset.enabled.is_(
                True
            ),

            Asset.id.in_(select(WatchlistItem.asset_id).where(WatchlistItem.news_enabled.is_(True))),
        )
        .order_by(
            NewsItem.id.desc()
        )
        .limit(limit)
    ).all()

    analyzer = HybridNewsAnalyzer()

    results = []

    for (
        news,
        impact,
        asset,
    ) in rows:
        analysis = analyzer.analyze(
            title=news.title,
            summary=news.summary,
            symbol=asset.symbol,
            name=asset.name,
            asset_type=asset.asset_type,
            venue=asset.venue,
            segment=asset.segment,
            provider=asset.provider,
        )

        source = apply_news_analysis(
            impact,
            analysis,
        )

        notification_result = (
            maybe_send_news_notification(
                db=db,
                asset=asset,
                news=news,
                impact=impact,
            )
        )

        results.append(
            {
                "news_id":
                    news.id,

                "asset_id":
                    asset.id,

                "symbol":
                    asset.symbol,

                "title":
                    news.title,

                "sentiment":
                    impact.sentiment,

                "impact_score":
                    impact.impact_score,

                "reason":
                    impact.reason,

                "analysis_source":
                    analysis.get(
                        "analysis_source"
                    ),

                "fallback_reason":
                    analysis.get(
                        "fallback_reason"
                    ),

                "model":
                    analysis.get(
                        "model"
                    ),

                "relevance_score":
                    analysis.get(
                        "relevance_score"
                    ),
            }
        )

    db.commit()

    return {
        "analyzed":
            len(results),

        "data":
            results,
    }

def get_rule_or_404(
    db: Session,
    rule_id: int,
):

    rule = db.get(
        AlertRule,
        rule_id,
    )

    if not rule or rule.user_id != get_default_user(db).id:

        raise HTTPException(
            status_code=404,
            detail="Alert rule not found",
        )

    return rule


def reset_alert_state(
    db: Session,
    rule_id: int,
):
    """
    修改规则以后必须清除旧状态。

    例如：
    原规则 +3%
    改成 +5%

    旧 last_value / armed 状态
    不应该继续沿用。
    """

    state_model = db.scalar(
        select(AlertState).where(
            AlertState.rule_id
            == rule_id
        )
    )

    if state_model:

        db.delete(
            state_model
        )


def serialize_rule(
    rule,
    asset,
    user,
):

    return {
        "id": rule.id,

        "user": {
            "id": user.id,
            "username": user.username,
        },

        "asset": {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
            "provider": asset.provider,
        },

        "metric": rule.metric,
        "operator": rule.operator,
        "value": rule.value,

        "step_anchor":
            rule.step_anchor,

        "reset_buffer":
            rule.reset_buffer,

        "cooldown_seconds":
            rule.cooldown_seconds,

        "enabled":
            rule.enabled,

        "created_at":
            rule.created_at,
    }


# =========================================================
# Root
# =========================================================

@app.get("/")
def root():

    return FileResponse(
        WEB_DIR
        / "mobile.html"
    )

# =========================================================
# Health
# =========================================================

@app.get("/api/health")
def health():

    return {
        "status": "ok",
    }


# =========================================================
# Assets
# =========================================================


@app.get("/api/disabled-assets")
def get_disabled_assets(
    db: Session = Depends(get_db),
):

    assets = db.scalars(
        select(
            Asset
        )
        .where(
            Asset.enabled.is_(False)
        )
        .order_by(
            Asset.venue,
            Asset.symbol,
        )
    ).all()

    return [
        {
            "asset_id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
            "provider": asset.provider,
            "enabled": asset.enabled,
        }

        for asset
        in assets
    ]


@app.get("/api/assets")
def get_assets(
    symbol: str | None = None,
    venue: str | None = None,
    asset_type: str | None = None,
    enabled: bool | None = True,
    db: Session = Depends(get_db),
):
    statement = select(
        Asset
    )

    if enabled is not None:
        statement = (
            statement.where(
                Asset.enabled
                == enabled
            )
        )

    if symbol:
        statement = statement.where(
            Asset.symbol == symbol.upper()
        )

    if venue:
        statement = statement.where(
            Asset.venue == venue.upper()
        )

    if asset_type:
        statement = statement.where(
            Asset.asset_type
            == asset_type.lower()
        )

    statement = statement.order_by(
        Asset.id
    )

    assets = db.scalars(
        statement
    ).all()

    return [
        {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
            "provider": asset.provider,
            "enabled": asset.enabled,
        }
        for asset in assets
    ]

@app.get(
    "/api/assets/search"
)
def search_assets(
    q: str,
    market: str = "CRYPTO",
):

    query = (
        q.strip()
        .upper()
    )

    selected_market = (
        market.strip()
        .upper()
    )

    if len(query) < 1:

        return {
            "count": 0,
            "data": [],
        }

    try:

        if selected_market in {
            "CRYPTO",
            "BINANCE",
        }:

            catalog = (
                load_binance_asset_catalog()
            )


        elif selected_market in {

            "US",

            "USA",

        }:

            provider = (

                create_moomoo_provider()

            )

            matched = (

                provider

                .search_stock_assets(

                    "US",

                    query,

                    20,

                )

            )

            return {

                "count":

                    len(matched),

                "data":

                    matched,

            }


        elif selected_market in {

            "HK",

            "HKEX",

        }:

            provider = (

                create_moomoo_provider()

            )

            matched = (

                provider

                .search_stock_assets(

                    "HK",

                    query,

                    20,

                )

            )

            return {

                "count":

                    len(matched),

                "data":

                    matched,

            }

        else:

            return {
                "count": 0,
                "data": [],
            }

    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "Asset search failed: "
                f"{error}"
            ),
        )

    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "Binance asset search "
                f"failed: {error}"
            ),
        )

    matched = []

    for item in catalog:

        symbol = (
            item["symbol"]
        )

        name = (
            item["name"]
        )

        if (
            query in symbol
            or
            query in name.upper()
        ):

            matched.append(
                item
            )

    # 完全匹配优先，
    # 其次 symbol 前缀，
    # 最后普通包含
    matched.sort(
        key=lambda item: (
            0
            if item["symbol"] == query
            else
            1
            if item["symbol"].startswith(
                query
            )
            else
            2,

            len(
                item["symbol"]
            ),

            item["symbol"],

            0
            if item["segment"] in {
                "SPOT",
                "STOCK",
            }
            else
            1
        )
    )

    matched = matched[:20]

    return {
        "count": len(
            matched
        ),
        "data": matched,
    }


@app.get(
    "/api/assets/{asset_id}"
)
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        asset_id,
    )

    return serialize_asset(
        asset
    )

@app.websocket(
    "/ws/market"
)
async def websocket_market(
    websocket: WebSocket,
):

    if not authenticated_websocket(websocket):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    try:

        # =================================================
        # 新客户端连接后
        # 先立即发送完整市场快照
        # =================================================

        initial_quotes = (
            await asyncio.to_thread(
                load_realtime_market_quotes
            )
        )

        await websocket.send_json(
            {
                "type": "market_snapshot",
                "count": len(
                    initial_quotes
                ),
                "data": initial_quotes,
            }
        )

        manager.add(
            websocket
        )

        # =================================================
        # 保持连接
        #
        # 客户端不需要主动持续发送数据
        # =================================================

        while True:

            await websocket.receive_text()

    except WebSocketDisconnect:

        manager.disconnect(
            websocket
        )

    except Exception:

        manager.disconnect(
            websocket
        )

@app.get(
    "/api/market/latest"
)

def get_latest_market_quotes(
    venue: str | None = None,
    asset_type: str | None = None,
    symbol: str | None = None,
    db: Session = Depends(get_db),
):

    statement = (
        select(
            MarketQuote,
            Asset,
        )
        .join(
            Asset,
            MarketQuote.asset_id
            == Asset.id,
        )
        .where(
            Asset.enabled == True
        )
    )

    if venue:

        statement = statement.where(
            Asset.venue
            == venue.strip().upper()
        )

    if asset_type:

        statement = statement.where(
            Asset.asset_type
            == asset_type.strip().lower()
        )

    if symbol:

        statement = statement.where(
            Asset.symbol
            == symbol.strip().upper()
        )

    statement = statement.order_by(
        Asset.id
    )

    rows = db.execute(
        statement
    ).all()

    return [
        serialize_market_quote(
            quote,
            asset,
        )
        for quote, asset in rows
    ]

@app.get(
    "/api/market/latest/assets/{asset_id}"
)
def get_latest_market_quote_by_asset(
    asset_id: int,
    db: Session = Depends(get_db),
):

    row = db.execute(
        select(
            MarketQuote,
            Asset,
        )
        .join(
            Asset,
            MarketQuote.asset_id
            == Asset.id,
        )
        .where(
            Asset.id == asset_id
        )
    ).first()

    if row is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Latest market quote "
                "not found"
            ),
        )

    quote, asset = row

    return serialize_market_quote(
        quote,
        asset,
    )

@app.get(
    "/api/market/history/assets/{asset_id}"
)
def get_market_history(
    asset_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):

    asset = db.get(
        Asset,
        asset_id,
    )

    if asset is None:

        raise HTTPException(
            status_code=404,
            detail="Asset not found",
        )

    if limit < 1 or limit > 1000:

        raise HTTPException(
            status_code=400,
            detail=(
                "limit must be "
                "between 1 and 1000"
            ),
        )

    statement = (
        select(
            DailyPrice
        )
        .where(
            DailyPrice.asset_id
            == asset_id
        )
    )

    if start_date is not None:

        statement = statement.where(
            DailyPrice.date
            >= start_date
        )

    if end_date is not None:

        statement = statement.where(
            DailyPrice.date
            <= end_date
        )

    statement = (
        statement
        .order_by(
            DailyPrice.date.desc()
        )
        .limit(
            limit
        )
    )

    rows = db.scalars(
        statement
    ).all()

    return {
        "asset": {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "venue": asset.venue,
            "currency": asset.currency,
        },

        "count": len(
            rows
        ),

        "data": [
            serialize_daily_price(
                row
            )
            for row in rows
        ],
    }

@app.post(
    "/api/assets",
    status_code=status.HTTP_201_CREATED,
)
def create_asset(
    payload: AssetCreate,
    db: Session = Depends(get_db),
):

    # =====================================================
    # 标准化输入
    # =====================================================

    symbol = (
        payload.symbol
        .strip()
        .upper()
    )

    venue = (
        payload.venue
        .strip()
        .upper()
    )

    segment = (
        payload.segment
        .strip()
        .upper()
    )

    provider = (
        payload.provider
        .strip()
        .upper()
    )

    currency = (
        payload.currency
        .strip()
        .upper()
    )

    asset_type = (
        payload.asset_type
        .strip()
        .lower()
    )

    name = (
        payload.name
        .strip()
    )

    # =====================================================
    # 检查重复
    #
    # 唯一键：
    # venue + segment + symbol
    # =====================================================

    existing = db.scalar(
        select(Asset).where(
            Asset.symbol == symbol,
            Asset.venue == venue,
            Asset.segment == segment,
        )
    )

    if existing:

        # =====================================================
        # 已存在并且仍然启用
        # =====================================================

        if existing.enabled:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Asset already exists: "
                    f"{venue}/"
                    f"{segment}/"
                    f"{symbol}"
                ),
            )

        # =====================================================
        # 已经被软删除
        # 直接恢复原 Asset
        # =====================================================

        existing.name = name
        existing.asset_type = asset_type
        existing.currency = currency
        existing.provider = provider
        existing.enabled = True

        db.commit()

        db.refresh(
            existing
        )

        return serialize_asset(
            existing
        )

    # =====================================================
    # 创建
    # =====================================================

    asset = Asset(

        symbol=symbol,

        name=name,

        asset_type=asset_type,

        venue=venue,

        segment=segment,

        currency=currency,

        provider=provider,

        enabled=payload.enabled,
    )

    db.add(
        asset
    )

    try:

        db.commit()

    except IntegrityError:

        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="Asset already exists",
        )

    db.refresh(
        asset
    )

    return serialize_asset(
        asset
    )

@app.post(
    "/api/assets/quick",
    status_code=status.HTTP_201_CREATED,
)
def create_asset_quick(
    payload: AssetQuickCreate,
    db: Session = Depends(get_db),
):

    market = (
        payload.market
        .strip()
        .upper()
    )

    symbol = (
        payload.symbol
        .strip()
        .upper()
    )

    # =====================================================
    # Crypto
    # =====================================================

    if market in {
        "CRYPTO",
        "BINANCE",
    }:

        # =============================================
        # 读取 Binance 当前真实产品目录
        # =============================================

        try:

            catalog = (
                load_binance_asset_catalog()
            )

        except Exception as error:

            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to load "
                    "Binance asset catalog: "
                    f"{error}"
                ),
            )

        # =============================================
        # segment
        #
        # 搜索结果点击时：
        # SPOT / FUTURES 会一起提交
        # =============================================

        segment = None

        if payload.segment:

            segment = (
                payload.segment
                .strip()
                .upper()
            )

            if segment not in {
                "SPOT",
                "FUTURES",
            }:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Unsupported Binance "
                        "segment"
                    ),
                )

        # =============================================
        # 找到 Binance 中匹配的产品
        # =============================================

        matches = [
            item

            for item
            in catalog

            if (
                item["symbol"]
                == symbol
                and
                (
                    segment is None
                    or
                    item["segment"]
                    == segment
                )
            )
        ]

        if not matches:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Binance product "
                    "not found: "
                    f"{symbol}"
                    + (
                        f" / {segment}"
                        if segment
                        else ""
                    )
                ),
            )

        # =============================================
        # 没传 segment 时
        #
        # 如果同一个 symbol 同时有
        # Spot + Futures
        # 必须让用户从搜索结果中选择
        # =============================================

        if segment is None:

            available_segments = {
                item["segment"]
                for item
                in matches
            }

            if (
                len(
                    available_segments
                )
                > 1
            ):

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{symbol} exists in "
                        "multiple Binance products. "
                        "Please select Spot "
                        "or Futures."
                    ),
                )

            segment = (
                matches[0][
                    "segment"
                ]
            )

        selected_product = (
            matches[0]
        )

        # =============================================
        # 创建 Asset
        # =============================================

        full_payload = AssetCreate(

            symbol=symbol,

            name=(
                payload.name.strip()
                if payload.name
                else
                selected_product[
                    "name"
                ]
            ),

            asset_type="crypto",

            venue="BINANCE",

            segment=segment,

            currency=(
                selected_product[
                    "currency"
                ]
            ),

            provider="BINANCE",

            enabled=payload.enabled,
        )

    # =====================================================
    # US stocks
    # =====================================================

    elif market in {

        "US",

        "USA",

    }:

        # =============================================

        # 使用 Moomoo 验证真实美股代码

        # =============================================

        try:

            provider = (

                create_moomoo_provider()

            )

            matches = (

                provider

                .search_stock_assets(

                    "US",

                    symbol,

                    20,

                )

            )


        except Exception as error:

            raise HTTPException(

                status_code=502,

                detail=(

                    "Moomoo asset validation "

                    f"failed: {error}"

                ),

            )

        selected_product = next(

            (

                item

                for item in matches

                if item["symbol"] == symbol

            ),

            None,

        )

        if selected_product is None:
            raise HTTPException(

                status_code=400,

                detail=(

                    "US stock not found: "

                    f"{symbol}"

                ),

            )

        full_payload = AssetCreate(

            symbol=

            selected_product[

                "symbol"

            ],

            name=(

                payload.name.strip()

                if payload.name

                else

                selected_product[

                    "name"

                ]

            ),

            asset_type=

            selected_product[

                "asset_type"

            ],

            venue=

            selected_product[

                "venue"

            ],

            segment=

            selected_product[

                "segment"

            ],

            currency=

            selected_product[

                "currency"

            ],

            provider=

            selected_product[

                "provider"

            ],

            enabled=

            payload.enabled,

        )

    # =====================================================
    # Hong Kong stocks
    # =====================================================

    elif market in {

        "HK",

        "HKEX",

    }:

        # 700 -> 00700

        if symbol.isdigit():
            symbol = (

                symbol.zfill(5)

            )

        # =============================================

        # 使用 Moomoo 验证真实港股代码

        # =============================================

        try:

            provider = (

                create_moomoo_provider()

            )

            matches = (

                provider

                .search_stock_assets(

                    "HK",

                    symbol,

                    20,

                )

            )


        except Exception as error:

            raise HTTPException(

                status_code=502,

                detail=(

                    "Moomoo asset validation "

                    f"failed: {error}"

                ),

            )

        selected_product = next(

            (

                item

                for item in matches

                if (

                    item["symbol"]

                    == symbol

            )

            ),

            None,

        )

        if selected_product is None:
            raise HTTPException(

                status_code=400,

                detail=(

                    "HK stock not found: "

                    f"{symbol}"

                ),

            )

        full_payload = AssetCreate(

            symbol=

            selected_product[

                "symbol"

            ],

            name=(

                payload.name.strip()

                if payload.name

                else

                selected_product[

                    "name"

                ]

            ),

            asset_type=

            selected_product[

                "asset_type"

            ],

            venue=

            selected_product[

                "venue"

            ],

            segment=

            selected_product[

                "segment"

            ],

            currency=

            selected_product[

                "currency"

            ],

            provider=

            selected_product[

                "provider"

            ],

            enabled=

            payload.enabled,

        )

    # =====================================================
    # Korea 暂时不开放用户新增
    # =====================================================

    elif market in {
        "KR",
        "KRX",
        "KOREA",
    }:

        raise HTTPException(
            status_code=400,
            detail=(
                "Korean realtime provider "
                "is currently unavailable"
            ),
        )

    else:

        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported market. "
                "Supported: CRYPTO, US, HK"
            ),
        )

    # 复用原来的完整创建逻辑：
    # 标准化、重复检查、数据库提交等
    return create_asset(
        payload=full_payload,
        db=db,
    )

@app.patch(
    "/api/assets/{asset_id}"
)
def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        asset_id,
    )

    updates = payload.model_dump(
        exclude_unset=True
    )

    if not updates:

        raise HTTPException(
            status_code=400,
            detail="No fields to update",
        )

    # =====================================================
    # 标准化字段
    # =====================================================

    upper_fields = {
        "symbol",
        "venue",
        "segment",
        "currency",
        "provider",
    }

    for key, value in (
        updates.items()
    ):

        if (
            isinstance(
                value,
                str,
            )
        ):

            value = (
                value.strip()
            )

            if (
                key
                in upper_fields
            ):

                value = (
                    value.upper()
                )

            elif (
                key
                == "asset_type"
            ):

                value = (
                    value.lower()
                )

        setattr(
            asset,
            key,
            value,
        )

    # =====================================================
    # 保存
    # =====================================================

    try:

        db.commit()

    except IntegrityError:

        db.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                "Asset with the same "
                "venue / segment / symbol "
                "already exists"
            ),
        )

    db.refresh(
        asset
    )

    return serialize_asset(
        asset
    )

@app.delete(
    "/api/assets/{asset_id}"
)
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
):

    asset = get_asset_or_404(
        db,
        asset_id,
    )

    # =====================================================
    # V0.11 使用软删除
    #
    # 保留历史 Alert / Notification 数据
    # =====================================================

    asset.enabled = False

    db.commit()

    db.refresh(
        asset
    )

    return {
        "deleted": True,
        "soft_delete": True,
        "asset": serialize_asset(
            asset
        ),
    }

# =========================================================
# Stocks
# =========================================================

@app.get("/api/stocks")
def get_stocks(
    db: Session = Depends(get_db),
):

    assets = db.scalars(
        select(Asset)
        .where(
            Asset.enabled == True,
            Asset.asset_type == "stock",
        )
        .order_by(
            Asset.id
        )
    ).all()

    return [
        {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
            "provider": asset.provider,
            "enabled": asset.enabled,
        }
        for asset in assets
    ]


# =========================================================
# Crypto
# =========================================================

@app.get("/api/crypto")
def get_crypto_assets(
    db: Session = Depends(get_db),
):

    assets = db.scalars(
        select(Asset)
        .where(
            Asset.enabled == True,
            Asset.asset_type == "crypto",
        )
        .order_by(
            Asset.id
        )
    ).all()

    return [
        {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
            "provider": asset.provider,
            "enabled": asset.enabled,
        }
        for asset in assets
    ]


# =========================================================
# 获取所有 Alert Rules
# =========================================================

@app.get("/api/alert-rules")
def get_alert_rules(
    db: Session = Depends(get_db),
):

    user = get_default_user(db)

    statement = (
        select(
            AlertRule,
            Asset,
            User,
        )
        .join(
            Asset,
            AlertRule.asset_id
            == Asset.id,
        )
        .join(
            User,
            AlertRule.user_id
            == User.id,
        )
        .where(AlertRule.user_id == user.id)
        .order_by(
            AlertRule.id
        )
    )

    rows = db.execute(
        statement
    ).all()

    return [
        serialize_rule(
            rule,
            asset,
            user,
        )
        for (
            rule,
            asset,
            user,
        ) in rows
    ]


# =========================================================
# 获取单条 Alert Rule
# =========================================================

@app.get(
    "/api/alert-rules/{rule_id}"
)
def get_alert_rule(
    rule_id: int,
    db: Session = Depends(get_db),
):

    rule = get_rule_or_404(
        db,
        rule_id,
    )

    asset = get_asset_or_404(
        db,
        rule.asset_id,
    )

    user = db.get(
        User,
        rule.user_id,
    )

    return serialize_rule(
        rule,
        asset,
        user,
    )


# =========================================================
# 创建 Alert Rule
# =========================================================

@app.post(
    "/api/alert-rules",
    status_code=status.HTTP_201_CREATED,
)
def create_alert_rule(
    payload: AlertRuleCreate,
    db: Session = Depends(get_db),
):

    user = get_default_user(
        db
    )

    asset = get_asset_or_404(
        db,
        payload.asset_id,
    )

    # =========================================================
    # Price Alert 必须基于已关注资产
    # =========================================================

    if not asset.enabled:
        raise HTTPException(
            status_code=400,
            detail="Asset is disabled",
        )

    watchlist_item = db.scalar(
        select(
            WatchlistItem
        )
        .where(
            WatchlistItem.user_id
            == user.id,

            WatchlistItem.asset_id
            == asset.id,
        )
    )

    if watchlist_item is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Asset must be followed "
                "before creating price alerts"
            ),
        )

    if not watchlist_item.price_alerts_enabled:
        raise HTTPException(
            status_code=400,
            detail=(
                "Price alerts are disabled "
                "for this watched asset"
            ),
        )

    # =====================================================
    # Step 模式
    #
    # value       = 每次变化多少
    # step_anchor = 用户指定的初始锚点
    # =====================================================

    step_anchor = None

    if payload.operator == "step":

        if payload.metric != "price":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Step alert only supports "
                    "price metric"
                ),
            )

        if payload.value <= 0:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Step size must be greater than 0"
                ),
            )

        if payload.step_anchor is None:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Step alert requires "
                    "an initial anchor price"
                ),
            )

        if payload.step_anchor <= 0:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Step anchor must be "
                    "greater than 0"
                ),
            )

        step_anchor = float(
            payload.step_anchor
        )

    rule = AlertRule(
        user_id=user.id,

        asset_id=asset.id,

        metric=payload.metric,

        operator=payload.operator,

        value=payload.value,

        step_anchor=(
            step_anchor
        ),

        reset_buffer=(
            payload.reset_buffer
        ),

        cooldown_seconds=(
            payload.cooldown_seconds
        ),

        enabled=payload.enabled,
    )

    db.add(rule)

    db.commit()

    db.refresh(rule)

    return serialize_rule(
        rule,
        asset,
        user,
    )


# =========================================================
# 修改 Alert Rule
# =========================================================

@app.patch(
    "/api/alert-rules/{rule_id}"
)
def update_alert_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    db: Session = Depends(get_db),
):

    rule = get_rule_or_404(
        db,
        rule_id,
    )

    updates = payload.model_dump(
        exclude_unset=True
    )

    if not updates:

        raise HTTPException(
            status_code=400,
            detail="No fields to update",
        )

    # ---------------------------------------------
    # 修改规则参数
    # ---------------------------------------------

    for key, value in updates.items():

        setattr(
            rule,
            key,
            value,
        )

    # =====================================================
    # 更新后的完整规则校验
    # =====================================================

    if rule.operator == "step":

        if rule.metric != "price":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Step alert only supports "
                    "price metric"
                ),
            )

        if rule.value <= 0:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Step size must be greater than 0"
                ),
            )

        if (
            rule.step_anchor is None
            or
            rule.step_anchor <= 0
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Step alert requires "
                    "an initial anchor price"
                ),
            )

    else:

        # 非 Step 模式不保留 Step 初始锚点
        rule.step_anchor = None


    # =====================================================
    # 只有真正影响提醒计算的参数发生变化，
    # 才重置 AlertState。
    #
    # 单纯 enabled true / false 不重置动态锚点。
    # =====================================================

    state_affecting_fields = {
        "metric",
        "operator",
        "value",
        "step_anchor",
        "reset_buffer",
        "cooldown_seconds",
    }

    if (
        state_affecting_fields
        .intersection(
            updates.keys()
        )
    ):

        reset_alert_state(
            db,
            rule.id,
        )

    db.commit()

    db.refresh(rule)

    asset = get_asset_or_404(
        db,
        rule.asset_id,
    )

    user = db.get(
        User,
        rule.user_id,
    )

    return serialize_rule(
        rule,
        asset,
        user,
    )


# =========================================================
# 删除 Alert Rule
# =========================================================

@app.delete(
    "/api/alert-rules/{rule_id}"
)
def delete_alert_rule(
    rule_id: int,
    db: Session = Depends(get_db),
):

    rule = get_rule_or_404(
        db,
        rule_id,
    )

    # =====================================================
    # 1. 先停用规则
    #
    # 防止 Worker 在删除过程中继续触发新 Notification
    # =====================================================

    rule.enabled = False

    db.flush()


    # =====================================================
    # 2. 保留历史 Notification
    #
    # 只解除 Notification -> AlertRule 外键
    # =====================================================

    notifications = db.scalars(
        select(
            Notification
        ).where(
            Notification.rule_id
            == rule.id
        )
    ).all()

    for notification in notifications:

        notification.rule_id = None

    # 关键：
    # 先真正 UPDATE 数据库，
    # 再继续删除 AlertRule
    db.flush()


    # =====================================================
    # 3. 删除 AlertState
    # =====================================================

    reset_alert_state(
        db,
        rule.id,
    )

    # 关键：
    # 先真正 DELETE AlertState
    db.flush()


    # =====================================================
    # 4. 删除 AlertRule
    # =====================================================

    db.delete(
        rule
    )

    db.commit()


    return {
        "deleted": True,
        "rule_id": rule_id,
    }


# =========================================================
# 推送订阅
#
# 用户 × 币种 × 提醒类型 的订阅开关。
# alert_type: longshort_digest / whale_print
# =========================================================

def serialize_subscription(
    subscription,
    asset,
):

    try:
        config = subscription_config(subscription)
        config_valid = True
    except ValueError:
        config = {"whale_min_usd": 50000, "cooldown_seconds": 300}
        config_valid = False

    return {
        "id": subscription.id,

        "asset": {
            "id": asset.id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "venue": asset.venue,
            "segment": asset.segment,
            "currency": asset.currency,
        },

        "alert_type": subscription.alert_type,
        "enabled": subscription.enabled,
        "config": config,
        "config_valid": config_valid,
        "created_at": subscription.created_at,
    }


def get_subscription_or_404(
    db,
    user_id,
    subscription_id,
):

    subscription = db.get(
        AlertSubscription,
        subscription_id,
    )

    if (
        subscription is None
        or subscription.user_id != user_id
    ):

        raise HTTPException(
            status_code=404,
            detail="Subscription not found",
        )

    return subscription


# =========================================================
# 获取当前用户全部订阅
# =========================================================

@app.get("/api/subscriptions")
def get_subscriptions(
    db: Session = Depends(get_db),
):

    user = get_default_user(db)

    statement = (
        select(
            AlertSubscription,
            Asset,
        )
        .join(
            Asset,
            AlertSubscription.asset_id
            == Asset.id,
        )
        .where(
            AlertSubscription.user_id
            == user.id
        )
        .order_by(
            AlertSubscription.id
        )
    )

    rows = db.execute(
        statement
    ).all()

    return [
        serialize_subscription(
            subscription,
            asset,
        )
        for (
            subscription,
            asset,
        ) in rows
    ]


# =========================================================
# 新增 / 更新订阅（upsert）
# =========================================================

@app.put("/api/subscriptions")
def upsert_subscription(
    payload: SubscriptionUpsert,
    db: Session = Depends(get_db),
):

    user = get_default_user(db)

    asset = get_asset_or_404(
        db,
        payload.asset_id,
    )

    if not supports_subscription(asset):
        raise HTTPException(status_code=400, detail="推送订阅目前仅支持 Binance USDT 合约")

    subscription = db.scalar(
        select(
            AlertSubscription
        ).where(
            AlertSubscription.user_id
            == user.id,
            AlertSubscription.asset_id
            == payload.asset_id,
            AlertSubscription.alert_type
            == payload.alert_type,
        )
    )

    if subscription is None:

        subscription = AlertSubscription(
            user_id=user.id,
            asset_id=payload.asset_id,
            alert_type=payload.alert_type,
            enabled=payload.enabled,
            config=payload.config,
        )

        db.add(subscription)

    else:

        subscription.enabled = payload.enabled

        if payload.config is not None:
            subscription.config = payload.config

    db.commit()
    db.refresh(subscription)

    return serialize_subscription(
        subscription,
        asset,
    )


# =========================================================
# 删除单条订阅
# =========================================================

@app.delete(
    "/api/subscriptions/{subscription_id}"
)
def delete_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
):

    user = get_default_user(db)

    subscription = get_subscription_or_404(
        db,
        user.id,
        subscription_id,
    )

    db.delete(subscription)
    db.commit()

    return {
        "deleted": True,
        "subscription_id": subscription_id,
    }


install_mobile_routes(app, get_db, get_default_user, lambda url: _binance_read_json(url))
install_auth(app, get_db)
