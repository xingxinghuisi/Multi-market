const cryptoList =
    document.getElementById("crypto-list");

const usList =
    document.getElementById("us-list");

const hkList =
    document.getElementById("hk-list");

const krxList =
    document.getElementById("krx-list");

const connectionStatus =
    document.getElementById("connection-status");

const assetForm =
    document.getElementById("asset-form");

const assetMarket =
    document.getElementById("asset-market");

const assetSymbol =
    document.getElementById("asset-symbol");

const assetName =
    document.getElementById("asset-name");

const assetFormMessage =
    document.getElementById("asset-form-message");


const marketData = new Map();


// =========================================================
// Price
// =========================================================

function formatNumber(
    value,
    currency,
) {

    const number =
        Number(value);

    if (!Number.isFinite(number)) {
        return "--";
    }

    if (currency === "KRW") {

        return number.toLocaleString(
            "zh-CN",
            {
                maximumFractionDigits: 0,
            }
        );
    }

    return number.toLocaleString(
        "zh-CN",
        {
            minimumFractionDigits: 2,
            maximumFractionDigits: 4,
        }
    );
}


function formatPrice(asset) {

    return formatNumber(
        asset.price,
        asset.currency,
    );
}


function formatSessionPrice(
    asset,
    value,
) {

    if (
        value === null ||
        value === undefined
    ) {
        return "--";
    }

    return formatNumber(
        value,
        asset.currency,
    );
}


// =========================================================
// Change
// =========================================================

function formatChange(
    changePct,
) {

    const value =
        Number(changePct);

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


function getChangeClass(
    changePct,
) {

    const value =
        Number(changePct);

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
// Time
// =========================================================

function parseServerTime(
    value,
) {

    if (!value) {
        return null;
    }

    let text =
        String(value);

    const hasTimezone =
        text.endsWith("Z") ||
        /[+-]\d{2}:\d{2}$/.test(
            text
        );

    if (!hasTimezone) {
        text += "Z";
    }

    const date =
        new Date(text);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return null;
    }

    return date;
}


function formatUpdatedTime(
    value,
) {

    const date =
        parseServerTime(
            value
        );

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


function getAgeSeconds(
    value,
) {

    const date =
        parseServerTime(
            value
        );

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


function formatAge(
    value,
) {

    const seconds =
        getAgeSeconds(
            value
        );

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
// Realtime Status
// =========================================================

function getRealtimeStatus(
    asset,
) {

    const age =
        getAgeSeconds(
            asset.updated_at
        );

    if (age === null) {

        return {
            text: "状态未知",
            className:
                "status-stale",
        };
    }

    let threshold = 60;

    if (
        asset.venue ===
        "BINANCE"
    ) {
        threshold = 15;
    }

    if (
        asset.venue === "US" ||
        asset.venue === "HKEX"
    ) {
        threshold = 30;
    }

    if (
        asset.venue === "KRX"
    ) {
        threshold = 120;
    }

    if (
        age <= threshold
    ) {

        return {
            text: "● 实时",
            className:
                "status-live",
        };
    }

    return {
        text: "○ 最近行情",
        className:
            "status-stale",
    };
}


// =========================================================
// US Market Session
// =========================================================

function getSessionName(
    session,
) {

    const names = {

        pre:
            "盘前",

        regular:
            "正常盘",

        after:
            "盘后",

        overnight:
            "夜盘",

        closed:
            "休市",
    };

    return (
        names[session]
        || "行情"
    );
}


function getRealtimeSource(
    asset,
) {

    if (
        asset.venue ===
        "BINANCE"
    ) {
        return "Binance WebSocket";
    }

    if (
        asset.venue === "US" ||
        asset.venue === "HKEX"
    ) {
        return "Moomoo OpenD";
    }

    if (
        asset.venue ===
        "KRX"
    ) {
        return "Korea Market";
    }

    return "Realtime Feed";
}


// =========================================================
// Move Card
// =========================================================

function appendCardToMarket(
    card,
    asset,
) {

    if (
        asset.venue ===
        "BINANCE"
    ) {

        cryptoList.appendChild(
            card
        );

        return;
    }

    if (
        asset.venue ===
        "US"
    ) {

        usList.appendChild(
            card
        );

        return;
    }

    if (
        asset.venue ===
        "HKEX"
    ) {

        hkList.appendChild(
            card
        );

        return;
    }

    if (
        asset.venue ===
        "KRX"
    ) {

        krxList.appendChild(
            card
        );
    }
}


// =========================================================
// US Extended Session HTML
// =========================================================

function buildUsSessionHtml(
    asset,
) {

    if (
        asset.venue !== "US"
    ) {
        return "";
    }

    const sessionName =
        getSessionName(
            asset.market_session
        );

    return `
        <div class="us-session-panel">

            <div class="us-current-session">
                当前阶段：
                <strong>
                    ${sessionName}
                </strong>
            </div>

            <div class="us-session-grid">

                <div class="us-session-item">
                    <span>
                        收盘
                    </span>

                    <strong>
                        ${formatSessionPrice(
                            asset,
                            asset.regular_price
                        )}
                    </strong>
                </div>

                <div class="us-session-item">
                    <span>
                        盘前
                    </span>

                    <strong>
                        ${formatSessionPrice(
                            asset,
                            asset.pre_price
                        )}
                    </strong>
                </div>

                <div class="us-session-item">
                    <span>
                        盘后
                    </span>

                    <strong>
                        ${formatSessionPrice(
                            asset,
                            asset.after_price
                        )}
                    </strong>
                </div>

                <div class="us-session-item">
                    <span>
                        夜盘
                    </span>

                    <strong>
                        ${formatSessionPrice(
                            asset,
                            asset.overnight_price
                        )}
                    </strong>
                </div>

            </div>

        </div>
    `;
}


// =========================================================
// Render Asset
// =========================================================

function renderAsset(
    asset,
) {

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

        appendCardToMarket(
            card,
            asset,
        );
    }

    const changeClass =
        getChangeClass(
            asset.change_pct
        );

    const realtimeStatus =
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

    const sessionHtml =
        buildUsSessionHtml(
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

            <span
                class="
                    market-status
                    ${realtimeStatus.className}
                "
            >
                ${realtimeStatus.text}
            </span>

        </div>


        <div class="market-price">

            ${formatPrice(asset)}

            <span class="market-currency">
                ${asset.currency || ""}
            </span>

        </div>


        <div class="market-change ${changeClass}">
            ${formatChange(
                asset.change_pct
            )}
        </div>


        ${sessionHtml}


        <div class="market-meta">
            ${source}
        </div>


        <div class="market-updated">

            ${formatUpdatedTime(
                asset.updated_at
            )}

            ${
                ageText
                    ? ` · ${ageText}`
                    : ""
            }

        </div>
    `;
}


// =========================================================
// REST Initial Load
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
// Create Asset
// =========================================================

async function createAsset(
    market,
    symbol,
    name,
) {

    const response =
        await fetch(
            "/api/assets/quick",
            {
                method:
                    "POST",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body:
                    JSON.stringify(
                        {
                            market,
                            symbol,

                            name:
                                name || null,
                        }
                    ),
            }
        );

    const data =
        await response.json();

    if (!response.ok) {

        throw new Error(
            data.detail
            || "添加失败"
        );
    }

    return data;
}


if (assetForm) {

    assetForm.addEventListener(
        "submit",
        async event => {

            event.preventDefault();

            const market =
                assetMarket.value;

            const symbol =
                assetSymbol
                .value
                .trim();

            const name =
                assetName
                .value
                .trim();

            if (!symbol) {
                return;
            }

            assetFormMessage
                .textContent =
                "正在添加...";

            try {

                const asset =
                    await createAsset(
                        market,
                        symbol,
                        name,
                    );

                assetFormMessage
                    .textContent =
                    `已添加 ${asset.symbol}`;

                assetSymbol.value =
                    "";

                assetName.value =
                    "";

            } catch (error) {

                assetFormMessage
                    .textContent =
                    `添加失败：${error.message}`;
            }
        }
    );
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

        if (
            connectionStatus
        ) {

            connectionStatus
                .textContent =
                "● 实时连接";

            connectionStatus
                .className =
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

            // 兼容两种后端格式
            renderAsset(
                message.data
                || message
            );

            return;
        }
    };


    ws.onclose = () => {

        console.log(
            "WebSocket disconnected"
        );

        if (
            connectionStatus
        ) {

            connectionStatus
                .textContent =
                "○ 正在重新连接";

            connectionStatus
                .className =
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
// Refresh relative time every second
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


// =========================================================
// Start
// =========================================================

async function start() {

    await loadInitialMarket();

    connectWebSocket();
}


start();