const cryptoList = document.getElementById("crypto-list");
const krxList = document.getElementById("krx-list");
const connectionStatus = document.getElementById("connection-status");

const marketData = new Map();


function formatPrice(asset) {

    const price = Number(asset.price);

    if (!Number.isFinite(price)) {
        return "--";
    }

    if (asset.currency === "KRW") {

        return price.toLocaleString(
            "zh-CN",
            {
                maximumFractionDigits: 0,
            }
        );
    }

    return price.toLocaleString(
        "zh-CN",
        {
            maximumFractionDigits: 8,
        }
    );
}


function formatChange(changePct) {

    const value = Number(changePct);

    if (!Number.isFinite(value)) {
        return "--";
    }

    const prefix =
        value > 0
            ? "+"
            : "";

    return (
        prefix +
        value.toFixed(2) +
        "%"
    );
}


function getChangeClass(changePct) {

    const value = Number(changePct);

    if (!Number.isFinite(value)) {
        return "neutral";
    }

    if (value > 0) {
        return "positive";
    }

    if (value < 0) {
        return "negative";
    }

    return "neutral";
}


// =========================================================
// 数据库 updated_at 当前保存的是 UTC 时间
//
// 如果 API 返回：
// 2026-09-10T06:17:49.869200
//
// 浏览器默认可能把它误认为本地时间。
// 所以没有时区信息时，主动按照 UTC 解析。
// =========================================================

function parseServerTime(value) {

    if (!value) {
        return null;
    }

    let text = String(value);

    const hasTimezone =
        text.endsWith("Z") ||
        /[+-]\d{2}:\d{2}$/.test(text);

    if (!hasTimezone) {
        text += "Z";
    }

    const date = new Date(text);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return null;
    }

    return date;
}


function formatUpdatedTime(value) {

    const date =
        parseServerTime(value);

    if (!date) {
        return "更新时间未知";
    }

    return (
        "最后更新：" +
        date.toLocaleString(
            "zh-CN",
            {
                hour12: false,
            }
        )
    );
}


function getAgeSeconds(value) {

    const date =
        parseServerTime(value);

    if (!date) {
        return null;
    }

    return Math.max(
        0,
        (
            Date.now() -
            date.getTime()
        ) / 1000
    );
}


function formatAge(value) {

    const seconds =
        getAgeSeconds(value);

    if (seconds === null) {
        return "";
    }

    if (seconds < 10) {
        return "刚刚";
    }

    if (seconds < 60) {

        return (
            Math.floor(seconds) +
            " 秒前"
        );
    }

    if (seconds < 3600) {

        return (
            Math.floor(
                seconds / 60
            ) +
            " 分钟前"
        );
    }

    if (seconds < 86400) {

        return (
            Math.floor(
                seconds / 3600
            ) +
            " 小时前"
        );
    }

    return (
        Math.floor(
            seconds / 86400
        ) +
        " 天前"
    );
}


// =========================================================
// 判断行情是否“新鲜”
//
// Binance：15 秒以内
// KRX：120 秒以内
//
// KRX 某只股票可能短时间没有成交，
// 所以不能设置得和 Crypto 一样严格。
// =========================================================

function getRealtimeStatus(asset) {

    const age =
        getAgeSeconds(
            asset.updated_at
        );

    if (age === null) {

        return {
            text: "状态未知",
            className: "status-stale",
        };
    }

    let threshold = 60;

    if (
        asset.venue === "BINANCE"
    ) {
        threshold = 15;
    }

    if (
        asset.venue === "KRX"
    ) {
        threshold = 120;
    }

    if (age <= threshold) {

        return {
            text: "● 实时",
            className: "status-live",
        };
    }

    return {
        text: "○ 最近行情",
        className: "status-stale",
    };
}


function getRealtimeSource(asset) {

    if (
        asset.venue === "BINANCE"
    ) {
        return "Binance WebSocket";
    }

    if (
        asset.venue === "KRX"
    ) {
        return "Infoway WebSocket";
    }

    return "Realtime Feed";
}


function renderAsset(asset) {

    if (
        !asset ||
        !asset.asset_id
    ) {
        return;
    }

    marketData.set(
        asset.asset_id,
        asset
    );

    let card =
        document.getElementById(
            `asset-${asset.asset_id}`
        );

    if (!card) {

        card =
            document.createElement(
                "div"
            );

        card.id =
            `asset-${asset.asset_id}`;

        card.className =
            "market-card";

        if (
            asset.venue ===
            "BINANCE"
        ) {

            cryptoList.appendChild(
                card
            );

        } else if (
            asset.venue ===
            "KRX"
        ) {

            krxList.appendChild(
                card
            );
        }
    }

    const changeClass =
        getChangeClass(
            asset.change_pct
        );

    const status =
        getRealtimeStatus(
            asset
        );

    const ageText =
        formatAge(
            asset.updated_at
        );

    const source =
        getRealtimeSource(
            asset
        );

    card.innerHTML = `
        <div class="market-card-header">

            <div>
                <div class="market-symbol">
                    ${asset.symbol}
                </div>

                <div class="market-name">
                    ${asset.name || ""}
                </div>
            </div>

            <span class="market-status ${status.className}">
                ${status.text}
            </span>

        </div>

        <div class="market-price">
            ${formatPrice(asset)}
            <span class="market-currency">
                ${asset.currency || ""}
            </span>
        </div>

        <div class="market-change ${changeClass}">
            ${formatChange(asset.change_pct)}
        </div>

        <div class="market-meta">
            ${source}
        </div>

        <div class="market-updated">
            ${formatUpdatedTime(asset.updated_at)}
            ${ageText ? ` · ${ageText}` : ""}
        </div>
    `;
}


// =========================================================
// 初始 REST 数据
// =========================================================

async function loadInitialMarket() {

    try {

        const response =
            await fetch(
                "/api/market/latest"
            );

        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );
        }

        const data =
            await response.json();

        for (
            const asset
            of data
        ) {

            renderAsset(
                asset
            );
        }

    } catch (error) {

        console.error(
            "Initial market load failed:",
            error
        );
    }
}


// =========================================================
// WebSocket
// =========================================================

function connectWebSocket() {

    const protocol =
        window.location.protocol
        === "https:"
            ? "wss:"
            : "ws:";

    const ws =
        new WebSocket(
            `${protocol}//${window.location.host}/ws/market`
        );

    ws.onopen = () => {

        console.log(
            "WebSocket connected"
        );

        if (connectionStatus) {

            connectionStatus.textContent =
                "● 实时连接";

            connectionStatus.className =
                "connection-live";
        }
    };


    ws.onmessage = event => {

        const message =
            JSON.parse(
                event.data
            );

        if (
            message.type ===
            "market_snapshot"
        ) {

            for (
                const asset
                of message.data
            ) {

                renderAsset(
                    asset
                );
            }

            return;
        }

        if (
            message.type ===
            "market_update"
        ) {

            renderAsset(
                message.data
            );
        }
    };


    ws.onclose = () => {

        console.log(
            "WebSocket disconnected"
        );

        if (connectionStatus) {

            connectionStatus.textContent =
                "○ 正在重新连接";

            connectionStatus.className =
                "connection-offline";
        }

        setTimeout(
            connectWebSocket,
            2000
        );
    };


    ws.onerror = error => {

        console.error(
            "WebSocket error:",
            error
        );

        ws.close();
    };
}


// =========================================================
// 每秒更新一次：
// “刚刚 / 10 秒前 / 5 分钟前”
//
// 即使行情休市没有推送，
// 状态也会自动从实时变成最近行情。
// =========================================================

setInterval(
    () => {

        for (
            const asset
            of marketData.values()
        ) {

            renderAsset(
                asset
            );
        }

    },
    1000
);


async function start() {

    await loadInitialMarket();

    connectWebSocket();
}


start();