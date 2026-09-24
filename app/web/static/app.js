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

const assetSearchResults =
    document.getElementById(
        "asset-search-results"
    );

let selectedAssetSearchResult =
    null;

let assetSearchTimer =
    null;

const assetFormMessage =
    document.getElementById("asset-form-message");


const marketData = new Map();

const watchlistData = new Map();

const disabledAssetsList =
    document.getElementById(
        "disabled-assets-list"
    );

const refreshDisabledAssetsButton =
    document.getElementById(
        "refresh-disabled-assets"
    );

const alertModeSelect =
    document.getElementById(
        "alert-mode"
    );

const alertOperatorField =
    document.getElementById(
        "alert-operator-field"
    );

const alertValueLabel =
    document.getElementById(
        "alert-value-label"
    );

const alertValueHelp =
    document.getElementById(
        "alert-value-help"
    );

const alertRuleForm =
    document.getElementById(
        "alert-rule-form"
    );

const alertAssetSelect =
    document.getElementById(
        "alert-asset"
    );

const alertMetricSelect =
    document.getElementById(
        "alert-metric"
    );

const alertOperatorSelect =
    document.getElementById(
        "alert-operator"
    );

const alertValueInput =
    document.getElementById(
        "alert-value"
    );

const alertStepAnchorField =
    document.getElementById(
        "alert-step-anchor-field"
    );

const alertStepAnchorInput =
    document.getElementById(
        "alert-step-anchor"
    );

const alertResetBufferInput =
    document.getElementById(
        "alert-reset-buffer"
    );

const alertCooldownInput =
    document.getElementById(
        "alert-cooldown"
    );

const alertResetUnit =
    document.getElementById(
        "alert-reset-unit"
    );

const alertResetHelp =
    document.getElementById(
        "alert-reset-help"
    );

const alertRuleMessage =
    document.getElementById(
        "alert-rule-message"
    );

const alertRulesList =
    document.getElementById(
        "alert-rules-list"
    );

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

function formatSessionTime(
    value,
) {

    if (!value) {
        return "";
    }

    const date =
        parseServerTime(
            value
        );

    if (!date) {
        return "";
    }

    return date.toLocaleTimeString(
        "zh-CN",
        {
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        }
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


    // =============================================
    // 不同市场使用不同的新鲜度标准
    // =============================================

    let activeThreshold = 60;
    let staleThreshold = 300;


    // Crypto
    if (
        asset.venue ===
        "BINANCE"
    ) {

        activeThreshold = 15;
        staleThreshold = 60;
    }


    // US / HK
    if (
        asset.venue === "US" ||
        asset.venue === "HKEX"
    ) {

        activeThreshold = 30;

        // 3 分钟以内没有新行情，
        // 不认为连接异常。
        staleThreshold = 180;
    }


    // Korea
    if (
        asset.venue ===
        "KRX"
    ) {

        activeThreshold = 120;
        staleThreshold = 600;
    }


    // =============================================
    // 行情活跃
    // =============================================

    if (
        age <=
        activeThreshold
    ) {

        return {
            text: "● 行情活跃",
            className:
                "status-live",
        };
    }


    // =============================================
    // 数据源仍可用，
    // 但该股票最近没有新价格变化
    // =============================================

    if (
        age <=
        staleThreshold
    ) {

        return {
            text: "● 暂无新行情",
            className:
                "status-idle",
        };
    }


    // =============================================
    // 很久没收到行情
    // =============================================

    return {
        text: "○ 行情较旧",
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


    function buildSessionItem(
        label,
        price,
        updatedAt,
    ) {

        const time =
            formatSessionTime(
                updatedAt
            );

        return `
            <div class="us-session-item">

                <span class="us-session-label">
                    ${label}
                </span>

                <div class="us-session-value">

                    <strong>
                        ${formatSessionPrice(
                            asset,
                            price
                        )}
                    </strong>

                    ${
                        time
                            ? `
                                <small class="us-session-time">
                                    ${time}
                                </small>
                            `
                            : ""
                    }

                </div>

            </div>
        `;
    }


    return `
        <div class="us-session-panel">

            <div class="us-current-session">

                当前阶段：

                <strong>
                    ${sessionName}
                </strong>

            </div>


            <div class="us-session-grid">

                ${buildSessionItem(
                    "收盘",
                    asset.regular_price,
                    asset.regular_updated_at
                )}

                ${buildSessionItem(
                    "盘前",
                    asset.pre_price,
                    asset.pre_updated_at
                )}

                ${buildSessionItem(
                    "盘后",
                    asset.after_price,
                    asset.after_updated_at
                )}

                ${buildSessionItem(
                    "夜盘",
                    asset.overnight_price,
                    asset.overnight_updated_at
                )}

            </div>

        </div>
    `;
}


// =========================================================
// Watchlist
// =========================================================

async function loadWatchlist() {

    const response =
        await fetch(
            "/api/watchlist"
        );

    if (!response.ok) {

        throw new Error(
            `HTTP ${response.status}`
        );
    }

    const items =
        await response.json();

    watchlistData.clear();

    for (const item of items) {

        watchlistData.set(
            Number(item.asset_id),
            item
        );
    }
}


async function followAsset(
    assetId,
) {

    const response =
        await fetch(
            "/api/watchlist",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body: JSON.stringify(
                    {
                        asset_id:
                            assetId,

                        news_enabled:
                            true,

                        price_alerts_enabled:
                            true,
                    }
                ),
            }
        );

    const data =
        await response.json();

    if (!response.ok) {

        throw new Error(
            data.detail
            || "关注失败"
        );
    }

    watchlistData.set(
        Number(assetId),
        data
    );

    return data;
}


async function unfollowAsset(
    assetId,
) {

    const response =
        await fetch(
            `/api/watchlist/${assetId}`,
            {
                method:
                    "DELETE",
            }
        );

    const data =
        await response.json();

    if (!response.ok) {

        throw new Error(
            data.detail
            || "取消关注失败"
        );
    }

    watchlistData.delete(
        Number(assetId)
    );

    return data;
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

    const watchItem =
        watchlistData.get(
            Number(
                asset.asset_id
            )
        );

    const isFollowed =
        Boolean(
            watchItem
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


        <div class="market-card-actions">

        <button
    class="
        asset-watch-button
        ${isFollowed ? "is-followed" : ""}
    "
    data-asset-id="${asset.asset_id}"
    type="button"
>
    ${isFollowed ? "★ 已关注" : "☆ 关注"}
</button>

            <span
                class="
                    market-status
                    ${realtimeStatus.className}
                "
            >
                ${realtimeStatus.text}
            </span>

            <button
                class="asset-remove-button"
                data-asset-id="${asset.asset_id}"
                type="button"
                title="移除 ${asset.symbol}"
            >
                ×
            </button>

        </div>

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


const watchButton =
    card.querySelector(
        ".asset-watch-button"
    );

if (watchButton) {

    watchButton.onclick =
        async () => {

            watchButton.disabled =
                true;

            try {

                if (isFollowed) {

                    await unfollowAsset(
                        asset.asset_id
                    );

                } else {

                    await followAsset(
                        asset.asset_id
                    );
                }

                renderAsset(
                    asset
                );

                loadAlertAssetOptions();

            } catch (error) {

                alert(
                    error.message
                );

            } finally {

                watchButton.disabled =
                    false;
            }
        };
}

const removeButton =
    card.querySelector(
        ".asset-remove-button"
    );

if (removeButton) {

    removeButton.onclick =
        async () => {

            const confirmed =
                window.confirm(
                    `确定移除 ${asset.symbol} 吗？`
                );

            if (!confirmed) {
                return;
            }

            try {

                await disableAsset(
                    asset.asset_id
                );

                marketData.delete(
                    asset.asset_id
                );

                card.remove();

                await loadDisabledAssets();

            } catch (error) {

                alert(
                    `删除失败：${error.message}`
                );
            }
        };
}
loadAlertAssetOptions();

}


// =========================================================
// REST Initial Load
// =========================================================

async function loadInitialMarket() {

    try {

        await loadWatchlist();

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

async function disableAsset(
    assetId,
) {

    const response =
        await fetch(
            `/api/assets/${assetId}`,
            {
                method: "DELETE",
            }
        );

    if (!response.ok) {

        const data =
            await response.json();

        throw new Error(
            data.detail
            || "删除失败"
        );
    }

    return true;
}

async function restoreAsset(
    assetId,
) {

    const response =
        await fetch(
            `/api/assets/${assetId}`,
            {
                method: "PATCH",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body:
                    JSON.stringify(
                        {
                            enabled: true,
                        }
                    ),
            }
        );

    const data =
        await response.json();

    if (!response.ok) {

        throw new Error(
            data.detail
            || "恢复失败"
        );
    }

    return data;
}

// =========================================================
// Alert Rules
// =========================================================

function getSelectedAlertAsset() {

    if (!alertAssetSelect) {
        return null;
    }

    const assetId =
        Number(
            alertAssetSelect.value
        );

    if (!assetId) {
        return null;
    }

    return (
        marketData.get(assetId)
        || null
    );
}


function updateAlertModeUI() {

    if (!alertModeSelect) {
        return;
    }

    const mode =
        alertModeSelect.value;


    if (mode === "step") {

        // 第一期 Step 只做价格步长
        alertMetricSelect.value =
            "price";

        alertMetricSelect.disabled =
            true;


        if (alertOperatorField) {

            alertOperatorField.style.display =
                "none";
        }


        if (alertStepAnchorField) {

            alertStepAnchorField.style.display =
                "";
        }


        if (alertStepAnchorInput) {

            alertStepAnchorInput.required =
                true;
        }


        if (alertValueLabel) {

            alertValueLabel.textContent =
                "每变化多少价格提醒";
        }


        if (alertValueInput) {

            alertValueInput.placeholder =
                "例如 100";
        }


        if (alertValueHelp) {

            alertValueHelp.textContent =
                "填写固定步长。例如初始锚点 21.10，步长 0.30，则下一次上涨 21.40、下跌 20.80 时提醒。";
        }


        // Step 自带锚点机制，
        // 不需要 reset_buffer / cooldown
        alertResetBufferInput.disabled =
            true;

        alertCooldownInput.disabled =
            true;

        return;
    }


    // ================================================
    // 普通指定阈值模式
    // ================================================

    alertMetricSelect.disabled =
        false;


    if (alertStepAnchorField) {

        alertStepAnchorField.style.display =
            "none";
    }


    if (alertStepAnchorInput) {

        alertStepAnchorInput.required =
            false;
    }


    if (alertOperatorField) {

        alertOperatorField.style.display =
            "";
    }


    if (alertValueLabel) {

        alertValueLabel.textContent =
            "触发值";
    }


    if (alertValueInput) {

        alertValueInput.placeholder =
            "阈值";
    }


    if (alertValueHelp) {

        alertValueHelp.textContent =
            "达到指定阈值时提醒";
    }


    alertResetBufferInput.disabled =
        false;

    alertCooldownInput.disabled =
        false;


    updateAlertResetHelp();
}

function updateAlertResetHelp() {

    if (
        !alertMetricSelect
        || !alertResetUnit
        || !alertResetHelp
    ) {
        return;
    }

    const metric =
        alertMetricSelect.value;

    const asset =
        getSelectedAlertAsset();

    const currency =
        asset?.currency || "";


    if (
        metric === "change_pct"
    ) {

        alertResetUnit.textContent =
            "%";

        alertResetHelp.textContent =
            "例如阈值 +5%，重新激活距离 0.5%，需要先回落到 +4.5% 才允许再次提醒。";

        return;
    }


    if (
        metric === "price"
    ) {

        alertResetUnit.textContent =
            currency || "价格";

        alertResetHelp.textContent =
            "例如 BTC 阈值 86,250，距离 100，则触发后需先回落到 86,150 才重新激活。";

        return;
    }


    if (
        metric === "price_change"
    ) {

        alertResetUnit.textContent =
            currency || "价格";

        alertResetHelp.textContent =
            "价格变动需要先离开触发值一定距离，才允许下一次提醒。";

        return;
    }


    alertResetUnit.textContent =
        "—";
}

function getMetricName(
    metric,
) {

    const names = {
        price:
            "价格",

        change_pct:
            "涨跌幅",

        price_change:
            "价格变动",
    };

    return (
        names[metric]
        || metric
    );
}


function getOperatorName(
    operator,
) {

    const names = {

        crossing_up:
            "向上突破",

        crossing_down:
            "向下跌破",

        step:
            "固定步长",
    };

    return (
        names[operator]
        || operator
    );
}


function formatRuleValue(
    rule,
) {

    const value =
        Number(
            rule.value
        );

    if (
        rule.metric
        === "change_pct"
    ) {

        return `${value}%`;
    }

    return value.toLocaleString(
        undefined,
        {
            maximumFractionDigits:
                8,
        }
    );
}


function loadAlertAssetOptions() {

    if (!alertAssetSelect) {
        return;
    }

    const currentValue =
        alertAssetSelect.value;

    const assets =
    Array.from(
        marketData.values()
    )
    .filter(
        asset => {

            const watchItem =
                watchlistData.get(
                    Number(
                        asset.asset_id
                    )
                );

            return (
                watchItem
                &&
                watchItem
                    .price_alerts_enabled
            );
        }
    );

    assets.sort(
        (a, b) => {

            const venueCompare =
                String(
                    a.venue || ""
                ).localeCompare(
                    String(
                        b.venue || ""
                    )
                );

            if (
                venueCompare !== 0
            ) {

                return venueCompare;
            }

            return String(
                a.symbol || ""
            ).localeCompare(
                String(
                    b.symbol || ""
                )
            );
        }
    );


    alertAssetSelect.innerHTML = `
        <option value="">
            选择资产
        </option>
    `;


    for (
        const asset
        of assets
    ) {

        const option =
            document.createElement(
                "option"
            );

        option.value =
            asset.asset_id;

        option.textContent =
            `${asset.symbol} · ${asset.venue}`;

        alertAssetSelect.appendChild(
            option
        );
    }


    if (
        currentValue
        && assets.some(
            asset =>
                String(
                    asset.asset_id
                )
                ===
                String(
                    currentValue
                )
        )
    ) {

        alertAssetSelect.value =
            currentValue;
    }
}


async function createAlertRule(
    payload,
) {

    const response =
        await fetch(
            "/api/alert-rules",
            {
                method:
                    "POST",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body:
                    JSON.stringify(
                        payload
                    ),
            }
        );


    const data =
        await response.json();


    if (!response.ok) {

        throw new Error(
            data.detail
            || "创建提醒失败"
        );
    }

    return data;
}


async function updateAlertRule(
    ruleId,
    payload,
) {

    const response =
        await fetch(
            `/api/alert-rules/${ruleId}`,
            {
                method:
                    "PATCH",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body:
                    JSON.stringify(
                        payload
                    ),
            }
        );


    const data =
        await response.json();


    if (!response.ok) {

        throw new Error(
            data.detail
            || "修改提醒失败"
        );
    }

    return data;
}


async function deleteAlertRule(
    ruleId,
) {

    const response =
        await fetch(
            `/api/alert-rules/${ruleId}`,
            {
                method: "DELETE",
            }
        );

    if (!response.ok) {

        const text =
            await response.text();

        let message =
            "删除提醒失败";

        if (text) {

            try {

                const data =
                    JSON.parse(text);

                message =
                    data.detail
                    || message;

            } catch {

                message =
                    text;
            }
        }

        throw new Error(
            message
        );
    }

    return true;
}


function renderAlertRule(
    rule,
) {

    const item =
        document.createElement(
            "div"
        );

    item.className =
        "alert-rule-item";


    let conditionHtml;

if (
    rule.operator
    === "step"
) {

    const currency =
        rule.asset.currency
        || "";

    const anchorText =
        Number.isFinite(
            Number(
                rule.step_anchor
            )
        )
            ? Number(
                rule.step_anchor
            ).toLocaleString()
            : "--";

    conditionHtml = `
        初始锚点
        <strong>
            ${anchorText}
            ${currency}
        </strong>

        · 每变化

        <strong>
            ${Number(rule.value).toLocaleString()}
            ${currency}
        </strong>

        提醒一次
    `;

} else {

    conditionHtml = `
        ${getMetricName(
            rule.metric
        )}

        ·

        ${getOperatorName(
            rule.operator
        )}

        <strong>
            ${formatRuleValue(
                rule
            )}
        </strong>
    `;
}

    const enabledText =
        rule.enabled
            ? "已启用"
            : "已停用";

    const enabledClass =
        rule.enabled
            ? "alert-enabled"
            : "alert-disabled";


    item.innerHTML = `

        <div class="alert-rule-main">

            <div class="alert-rule-symbol">

                ${rule.asset.symbol}

                <span>
                    ${rule.asset.venue || ""}
                </span>

            </div>


            <div class="alert-rule-condition">

    ${conditionHtml}

</div>


            <div class="alert-rule-details">

    ${
        rule.operator === "step"

            ? "双向监控 · 触发后以实际触发价格移动锚点"

            : `
                重新激活距离：
                ${rule.reset_buffer}

                ·

                最短间隔：
                ${
                    rule.cooldown_seconds >= 60
                        ? `${rule.cooldown_seconds / 60} 分钟`
                        : `${rule.cooldown_seconds} 秒`
                }
            `
    }

</div>

        </div>


        <div class="alert-rule-actions">

            <span
                class="
                    alert-rule-status
                    ${enabledClass}
                "
            >
                ${enabledText}
            </span>


            <button
                type="button"
                class="alert-toggle-button"
            >
                ${
                    rule.enabled
                        ? "停用"
                        : "启用"
                }
            </button>


            <button
                type="button"
                class="alert-delete-button"
            >
                删除
            </button>

        </div>
    `;


    const toggleButton =
        item.querySelector(
            ".alert-toggle-button"
        );

    const deleteButton =
        item.querySelector(
            ".alert-delete-button"
        );


    toggleButton.onclick =
        async () => {

            toggleButton.disabled =
                true;

            try {

                await updateAlertRule(
                    rule.id,
                    {
                        enabled:
                            !rule.enabled,
                    }
                );

                await loadAlertRules();

            } catch (error) {

                alert(
                    `修改失败：${error.message}`
                );

                toggleButton.disabled =
                    false;
            }
        };


    deleteButton.onclick =
        async () => {

            const confirmed =
                window.confirm(
                    `确定删除 ${rule.asset.symbol} 的这条提醒吗？`
                );

            if (!confirmed) {
                return;
            }

            try {

                await deleteAlertRule(
                    rule.id
                );

                await loadAlertRules();

            } catch (error) {

                alert(
                    `删除失败：${error.message}`
                );
            }
        };


    return item;
}


async function loadAlertRules() {

    if (!alertRulesList) {
        return;
    }

    try {

        const response =
            await fetch(
                "/api/alert-rules"
            );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );
        }


        const rules =
            await response.json();


        alertRulesList.innerHTML =
            "";


        if (
            rules.length === 0
        ) {

            alertRulesList.innerHTML = `
                <div class="alert-rules-empty">
                    暂无提醒规则
                </div>
            `;

            return;
        }


        for (
            const rule
            of rules
        ) {

            alertRulesList.appendChild(
                renderAlertRule(
                    rule
                )
            );
        }

    } catch (error) {

        console.error(
            "Load alert rules failed:",
            error
        );

        alertRulesList.innerHTML = `
            <div class="alert-rules-empty">
                提醒规则加载失败
            </div>
        `;
    }
}


async function loadDisabledAssets() {

    if (!disabledAssetsList) {
        return;
    }

    try {

        const response =
            await fetch(
                "/api/disabled-assets"
            );

        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );
        }

        const assets =
            await response.json();

        disabledAssetsList.innerHTML =
            "";

        if (
            assets.length === 0
        ) {

            disabledAssetsList.innerHTML = `
                <div class="disabled-assets-empty">
                    暂无已移除资产
                </div>
            `;

            return;
        }


        for (
            const asset
            of assets
        ) {

            const item =
                document.createElement(
                    "div"
                );

            item.className =
                "disabled-asset-item";

            item.innerHTML = `

                <div class="disabled-asset-info">

                    <strong>
                        ${asset.symbol}
                    </strong>

                    <span>
                        ${asset.name || ""}
                    </span>

                    <small>
                        ${asset.venue}
                    </small>

                </div>


                <button
                    class="asset-restore-button"
                    type="button"
                >
                    恢复
                </button>
            `;


            const restoreButton =
                item.querySelector(
                    ".asset-restore-button"
                );


            restoreButton.onclick =
                async () => {

                    restoreButton.disabled =
                        true;

                    restoreButton.textContent =
                        "恢复中...";

                    try {

                        await restoreAsset(
                            asset.asset_id
                        );

                        item.remove();

                        // 重新读取最新行情。
                        // Worker 重新订阅后，
                        // WebSocket 也会继续更新。
                        await loadInitialMarket();

                        await loadDisabledAssets();

                    } catch (error) {

                        restoreButton.disabled =
                            false;

                        restoreButton.textContent =
                            "恢复";

                        alert(
                            `恢复失败：${error.message}`
                        );
                    }
                };


            disabledAssetsList
                .appendChild(
                    item
                );
        }

    } catch (error) {

        console.error(
            "Load disabled assets failed:",
            error
        );

        disabledAssetsList.innerHTML = `
            <div class="disabled-assets-empty">
                加载失败
            </div>
        `;
    }
}

async function searchAssets(
    market,
    query,
) {

    const response =
        await fetch(
            "/api/assets/search"
            + `?market=${encodeURIComponent(market)}`
            + `&q=${encodeURIComponent(query)}`
        );

    const data =
        await response.json();

    if (!response.ok) {

        throw new Error(
            data.detail
            || "搜索失败"
        );
    }

    return data.data || [];
}


function clearAssetSearchResults() {

    if (
        !assetSearchResults
    ) {
        return;
    }

    assetSearchResults.innerHTML =
        "";
}


function renderAssetSearchResults(
    results,
) {

    clearAssetSearchResults();

    if (
        !assetSearchResults
    ) {
        return;
    }

    if (!results.length) {

        const empty =
            document.createElement(
                "div"
            );

        empty.className =
            "asset-search-empty";

        empty.textContent =
            "没有找到匹配资产";

        assetSearchResults.appendChild(
            empty
        );

        return;
    }

    for (
        const item
        of results
    ) {

        const button =
            document.createElement(
                "button"
            );

        button.type =
            "button";

        button.className =
            "asset-search-item";

        const title =
            document.createElement(
                "div"
            );

        title.className =
            "asset-search-symbol";

        title.textContent =
            item.symbol;

        const meta =
            document.createElement(
                "div"
            );

        meta.className =
            "asset-search-meta";

        let marketLabel = "";

if (
    item.venue === "BINANCE"
) {

    marketLabel =
        item.segment === "FUTURES"
            ? "Binance 永续"
            : "Binance 现货";

} else if (
    item.venue === "US"
) {

    marketLabel =
        "美股";

} else if (
    item.venue === "HKEX"
) {

    marketLabel =
        "港股";

} else {

    marketLabel =
        item.venue || "";
}

meta.textContent =
    `${item.name} · ${marketLabel}`;

        button.appendChild(
            title
        );

        button.appendChild(
            meta
        );

        button.addEventListener(
            "click",
            () => {

                selectedAssetSearchResult =
                    item;

                assetSymbol.value =
                    item.symbol;

                assetName.value =
                    item.name;

                clearAssetSearchResults();

                let selectedLabel = "";

if (
    item.venue === "BINANCE"
) {

    selectedLabel =
        item.segment === "FUTURES"
            ? "Binance 永续"
            : "Binance 现货";

} else if (
    item.venue === "US"
) {

    selectedLabel =
        "美股";

} else if (
    item.venue === "HKEX"
) {

    selectedLabel =
        "港股";

} else {

    selectedLabel =
        item.venue || "";
}

assetFormMessage
    .textContent =
    `已选择 ${item.symbol} · ${selectedLabel}`;
            }
        );

        assetSearchResults.appendChild(
            button
        );
    }
}

if (assetSymbol) {

    assetSymbol.addEventListener(
        "input",
        () => {

            selectedAssetSearchResult =
                null;

            clearTimeout(
                assetSearchTimer
            );

            const query =
                assetSymbol.value
                    .trim();

            const market =
                assetMarket.value;

            clearAssetSearchResults();

            if (
    ![
        "CRYPTO",
        "US",
        "HK",
    ].includes(
        market
    )
) {
    return;
}

            if (
                query.length < 1
            ) {
                return;
            }

            assetSearchTimer =
                setTimeout(
                    async () => {

                        try {

                            const results =
                                await searchAssets(
                                    market,
                                    query,
                                );

                            renderAssetSearchResults(
                                results
                            );

                        } catch (error) {

                            assetFormMessage
                                .textContent =
                                `搜索失败：${error.message}`;
                        }

                    },
                    500,
                );
        }
    );
}


if (assetMarket) {

    assetMarket.addEventListener(
        "change",
        () => {

            selectedAssetSearchResult =
                null;

            clearAssetSearchResults();

            assetSymbol.value =
                "";

            assetName.value =
                "";
        }
    );
}

async function createAsset(
    market,
    symbol,
    name,
    segment = null,
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

                            segment:
                                segment || null,
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

            // =========================================
            // Crypto 必须从搜索结果选择
            // =========================================

            if (
    [
        "CRYPTO",
        "US",
        "HK",
    ].includes(
        market
    )
    &&
    !selectedAssetSearchResult
) {

    assetFormMessage
        .textContent =
        "请从搜索结果中选择资产";

    return;
}

            const segment =
                selectedAssetSearchResult
                    ?.segment
                || null;

            assetFormMessage
                .textContent =
                "正在添加...";

            try {

                const asset =
                    await createAsset(
                        market,
                        symbol,
                        name,
                        segment,
                    );

                assetFormMessage
                    .textContent =
                    `已添加 ${asset.symbol} · ${asset.segment}`;

                assetSymbol.value =
                    "";

                assetName.value =
                    "";

                selectedAssetSearchResult =
                    null;

                clearAssetSearchResults();

                // =====================================
                // 自动刷新
                // =====================================

                setTimeout(
                    () => {
                        loadInitialMarket();
                    },
                    1000,
                );

                setTimeout(
                    () => {
                        loadInitialMarket();
                    },
                    6000,
                );

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

if (
    refreshDisabledAssetsButton
) {

    refreshDisabledAssetsButton
        .addEventListener(
            "click",
            loadDisabledAssets
        );
}
if (
    alertMetricSelect
) {

    alertMetricSelect.addEventListener(
        "change",
        updateAlertResetHelp
    );
}

if (
    alertModeSelect
) {

    alertModeSelect.addEventListener(
        "change",
        updateAlertModeUI
    );
}


if (
    alertAssetSelect
) {

    alertAssetSelect.addEventListener(
        "change",
        updateAlertResetHelp
    );
}
if (
    alertRuleForm
) {

    alertRuleForm.addEventListener(
        "submit",
        async event => {

            event.preventDefault();


            const assetId =
                Number(
                    alertAssetSelect.value
                );

            const value =
                Number(
                    alertValueInput.value
                );

            const resetBuffer =
                Number(
                    alertResetBufferInput.value
                );

            const cooldownMinutes =
                Number(
                    alertCooldownInput.value
                );

            const cooldownSeconds =
                Math.round(
                    cooldownMinutes * 60
                );


            const isStepMode =
                alertModeSelect
                && alertModeSelect.value
                    === "step";


            const stepAnchor =
                alertStepAnchorInput
                    ? Number(
                        alertStepAnchorInput.value
                    )
                    : NaN;


            if (!assetId) {

                alertRuleMessage.textContent =
                    "请选择资产";

                return;
            }


            if (
                !Number.isFinite(
                    value
                )
            ) {

                alertRuleMessage.textContent =
                    "请输入正确的阈值";

                return;
            }


            if (
                isStepMode
                &&
                (
                    !Number.isFinite(
                        stepAnchor
                    )
                    ||
                    stepAnchor <= 0
                )
            ) {

                alertRuleMessage.textContent =
                    "请输入正确的初始锚点";

                return;
            }


            if (
                isStepMode
                &&
                value <= 0
            ) {

                alertRuleMessage.textContent =
                    "固定步长必须大于 0";

                return;
            }


            alertRuleMessage.textContent =
                "正在创建...";


            try {

await createAlertRule(
    {
        asset_id:
            assetId,

        metric:
            isStepMode
                ? "price"
                : alertMetricSelect.value,

        operator:
            isStepMode
                ? "step"
                : alertOperatorSelect.value,

        value,

        step_anchor:
            isStepMode
                ? stepAnchor
                : null,

        reset_buffer:
            isStepMode
                ? 0
                : resetBuffer,

        cooldown_seconds:
            isStepMode
                ? 0
                : cooldownSeconds,

        enabled:
            true,
    }
);


                alertRuleMessage.textContent =
                    "提醒已创建";


                alertValueInput.value =
                    "";

                if (
                    alertStepAnchorInput
                ) {

                    alertStepAnchorInput.value =
                        "";
                }


                await loadAlertRules();


            } catch (error) {

                alertRuleMessage.textContent =
                    `创建失败：${error.message}`;
            }
        }
    );
}

async function start() {

    await loadInitialMarket();

    loadAlertAssetOptions();

    updateAlertModeUI();

    updateAlertResetHelp();

    await loadDisabledAssets();

    await loadAlertRules();

    connectWebSocket();
}


start();