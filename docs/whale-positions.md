# 自动发现 trade.xyz 永续巨鲸

## 已实现的范围

PWA「提醒 → 链上巨鲸仓位」独立于原有 Binance 聚合成交提醒。无需填写钱包地址；用户选择市场、最低仓位名义价值、同地址同市场提醒间隔、调仓门槛和累计窗口，并可暂停、删除。默认仓位阈值为 100 万美元，可从 1000 美元起设置。没有订阅时不监听公开成交、不轮询钱包。

支持 Hyperliquid 的 `xyz` 部署市场，服务启动及每小时读取官方 metadata，提供目录中全部当前存在且未退市的合约，不再受 KORU、SKHY、NVDA、TSLA 四个市场的白名单限制。页面可按名称搜索；新增市场须通过最新目录核验，不能凭空输入代码创建。目录涵盖股票、ETF 及其他品种，未知品种沿用官方符号与中性的“永续合约”名称，不猜测股票分类。2026-10-11 开发核验时官方返回 114 个未退市市场；该数量会随上游目录变化，并非固定承诺。只监听用户已开启的市场，不会自动订阅全部目录。

这些合约不是 Binance 同名 USDT 合约。仓位价值沿用官方 `positionValue` 的美元名义价值，不代表实际保证金。已有四个市场的订阅、阈值、通知和候选数据继续保留；退市或目录过期时仍可暂停或删除已有订阅。

一条公开 WebSocket 监听已订阅市场的 trades，读取 `users` 中买卖双方的公开地址；所有有效成交均可发现候选，不限定单笔成交金额，因此拆单也有机会被发现。候选保存在数据库，REST `clearinghouseState`（`dex=xyz`）核验签名数量、平均开仓价、当前杠杆设置及名义价值。不需要账户 API Key、钱包私钥或交易权限。

事件包括新发现已有仓位、新开仓、加仓、减仓、平仓和反向开仓。首次快照只记为「新发现已有仓位」；之后按两次快照的**签名数量**比较，不根据价格造成的市值涨跌推断加减仓。反向开仓标为净反向，无法推断期间是否经过多次交易。新开仓表示上次核验为零、本次非零，不表示精确成交时间。推送中的均价和杠杆为**当前仓位快照值**，不是历史订单杠杆或本次成交价。平仓不编造已不存在的当前均价或杠杆。

Telegram 与仓位页面显示官方快照 `unrealizedPnl` 的**当前未实现盈亏**，正负号区分浮盈和浮亏，真实零值显示 `$0.00`。字段缺失或无效、尚未重新核验的旧记录显示“未提供”，不自行估算。盈亏变化本身不触发开仓／加减仓事件；当前仓位页面随正常核验更新，历史事件中的盈亏保留事件核验时的快照。已平仓事件不把浮盈亏或零持仓冒充已实现收益；已实现净利润需要另外获取成交和结算记录。本次仅扩展 JSON 快照字段，无数据库迁移，不补发历史 Telegram 消息。

通知统一保存在账户通知中心，发给该用户已验证绑定的 Telegram；只有旧 `default` 账户可沿用部署接收目标。新推送通常为七行：首行显示品种与动作，加减仓同时显示数量净变化；随后显示本次动作价格、仓位价值（万／亿美元）、均价及杠杆、浮动盈亏、短地址、`trade.xyz` 与北京时间。加减仓的金额明确为“剩余仓位”；首次核验标为“新发现已有多／空单”；平仓显示上次仓位及“已实现盈亏：未提供”，不冒充平仓收益。完整地址、源名称和前后快照继续保存在事件数据；网页保留完整地址和仓位变化详情。旧 Telegram 和已生成的通知不改写。

动作价格来自官方 `userFillsByTime`，分别显示“开仓价格”“加仓价格”“减仓价格”“平仓价格”，反向开仓分别显示旧仓平仓价与新仓开仓价。只在两次仓位核验间隔不超过一小时、对应市场成交能按 `startPosition` 完整连接前后签名数量、且期间没有混合买卖时提供价格。多笔成交按数量加权，标注“成交均价”；跨越零仓位的成交按关闭旧仓和开启新仓的数量拆分。同毫秒成交按仓位链排序，不依赖成交 ID 的大小。首次发现、旧记录、成交缺失／异常、响应达到 2000 条上限、数量不一致或期间先买后卖等情况显示“未提供”，不会拿持仓均价、标记价或最新市场价代替。平仓价不等于已实现收益。

只有达到仓位阈值并产生变化的地址才增加一次成交查询，同一地址多个变动市场共享这次响应；首次发现与价格／盈亏变化不请求成交记录。价格查询失败仍保存有效仓位和事件、照常发送价格未提供的提醒；遇到 429 或服务器错误遵守退避，不无限追查历史或补发旧通知。价格及核验依据保存在事件 JSON；网页原有仓位均价字段保持原含义。当前可配置过滤升级需同时更新 API 和 worker，见下方部署步骤。

每用户每事件持久去重；同地址同市场冷却，不会让另一地址的事件被误抑制。显式发送失败最多重试两次；投递前重新检查订阅及设置更新时间，配置变化后取消旧失败重试。进程意外停止后已标为 pending 的投递不自动重发，避免重复；Telegram 请求超时本身存在「已接收但未返回」的不确定性。

## 每个账户、每个市场的推送设置

| 设置 | 默认值 | 规则 |
| --- | --- | --- |
| 巨鲸仓位门槛 | $1,000,000 | 前后快照中较大的仓位规模；最小 $1,000 |
| 最小调仓金额 | $5,000 | 加仓／减仓数量 × 对应价格；0 关闭此限制 |
| 最小数量变化 | 原仓位的 0.5% | 数量净变化绝对值 ÷ 原数量绝对值；0 关闭此限制 |
| 累计窗口 | 300 秒 | 0–3600 秒；0 关闭累计、逐次判断 |
| 提醒间隔 | 300 秒 | 同一账户、地址、市场；0 关闭 |
| 重要动作优先 | 开启 | 新开仓、平仓、反向开仓跳过提醒间隔 |

普通加减仓需**同时**满足金额与比例门槛；这些值由用户在订阅卡片设置，并非固定阈值。金额优先使用完整核验的成交均价；缺失时按本次仓位价值除以数量估算当前价格，仅用于过滤，推送的动作价格仍为“未提供”。不使用持仓开仓均价冒充成交价。默认对已存在且未配置新字段的订阅也生效；把金额、比例及累计窗口均设为 0 可恢复逐次调仓判断。

窗口从第一条待累计变化开始，连续同方向的加仓／减仓在同账户、地址、市场内合并，数量相接才可累计；不混合加仓与减仓，不在不同地址／市场／账户间合并。中途无数量变化的核验不打断累计。累计达到两个门槛即尝试提醒，无需等满窗口；仍在冷却中则保留至间隔结束，最晚窗口到期再判断，仍受冷却或未达标就过滤。窗口过后不和下一窗口相加，事件过旧（一小时）不补发。新开仓、平仓、反向开仓取消旧累计，按重要动作设置处理；首次发现不受调仓门槛限制，但仍受仓位门槛与普通间隔约束。重要动作仍逐事件去重，不保证核验间的每笔开平仓都被发现。

累计消息标题为“累计加仓／累计减仓”，时间为核验范围；所有成员均有完整成交价格时才显示按数量加权的成交均价，任一缺失则不编造累计成交价。改变订阅设置、暂停或删除订阅会取消未推送累计；后续核验数量已变化但未产生合格事件（例如仓位降到门槛以下后平仓）时，也取消过时累计。已经发送的通知不改写。站内事件流继续显示达到仓位门槛的变化，并显示个人推送判断，故网页事件数可能多于 Telegram 消息数。

覆盖区分共享候选池和每市场的已知地址、已核验地址、待首次核验、符合个人仓位门槛的持仓及过期数量。市场关联来自升级后的真实成交和已保存的非零持仓，不推测所有候选都交易所有市场，也不冒充全网历史地址总数。近 24 小时判断只统计当前账户，显示等待累计、调仓未达标、间隔抑制、已并入累计、发送成功／失败等状态；升级前未记录的判断不反推。

新增四张独立表：`whale_push_policies`、`whale_adjustment_batches`、`whale_event_decisions`、`whale_market_addresses`。API／worker 启动幂等建表，保留原订阅表结构及数据；无需手工 ALTER。旧客户端未提供新字段时不会覆盖已保存的新设置。累计记录可跨 worker 重启恢复；个人判断随公共事件保留七天。

## 覆盖和运行边界

- **不是全网全历史索引**，不提供 Binance 等中心化交易所用户仓位。未接入其他链上交易场所，也未购买历史数据。
- 从监听成交及持久候选池发现地址；启动前已有但此后不成交的静默钱包可能遗漏。第一次订阅也会收到公开成交源的最近成交快照，从中发现地址，但不把旧成交当作刚开仓。
- 大仓位目标每 60 秒核验，普通候选目标每 5 分钟；观察到新成交可提前排队，但同地址不快于 30 秒。两次核验间开仓又平仓的短暂持仓可能完全遗漏。
- REST 请求顺序执行，间隔不少于 0.6 秒，并按约 900 权重／分钟的目标节流：仓位查询权重 2，目录／成交查询权重 20，成交响应另按每 20 条增加权重。每小时刷新一次目录。排队、网络故障、限流会延迟，不能保证每个地址都按目标频率更新；使用同一出口 IP 的其他程序也消耗上游额度。
- 默认候选池容量 2000，可通过 `WHALE_POSITION_ADDRESS_CAP` 设置为 100–10000。达到容量会记录跳过次数，页面提示覆盖不完整；仅清理超过一天未成交且已核验空仓的候选，不静默淘汰已知持仓。计数表示新候选被跳过的次数，并非唯一遗漏地址数。
- 页面显示服务心跳、成交连接、实际订阅市场、最近成交、核验时间、排队数及异常。超过三分钟未更新的仓位标为过期。网络异常、缺失字段、重复／过期源快照不会生成虚假平仓。
- 公共事件保留七天；账户通知继续沿用原有通知保存策略。页面每次最多显示 50 个大仓位及 50 条事件。阈值调整不补发历史事件。已提交但未派发的事件可在一小时内恢复派发，超时不再推送旧消息。
- **只运行一个 `whale_position_worker` 实例**。目前使用现有共享 SQLite；要水平扩容需增加跨进程任务领取／协调机制。

## 本地与 Docker

在已初始化的 `app/` 环境启动 API 后，运行 `python whale_position_worker.py`。API 和 worker 都只新增五张表，不修改现有用户、资产、提醒或数据库文件路径。默认无需增加环境变量；若服务器不能直连，可配置 `HYPERLIQUID_PROXY=http://...`，勿在 Git 中提交带凭据的代理地址。

服务器升级前先备份 `.env.production`。下方命令使用 SQLite 在线备份保存现有数据库，然后拉取源码、构建和更新服务；适用于已有正确 Git checkout 的部署目录：

```sh
(
set -e
cd /opt/korea-market-radar
docker compose --env-file .env.production exec -T api python - <<'PY'
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
folder = Path('/app/data/backups')
folder.mkdir(exist_ok=True)
target = folder / ('before-whale-policy-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.db')
with sqlite3.connect('file:/app/data/market_radar.db?mode=ro', uri=True) as source:
    with sqlite3.connect(target) as backup:
        source.backup(backup)
print('DATABASE_BACKUP_OK:', target.name)
PY
git pull --ff-only origin main
docker build -f Dockerfile.app -t korea-market-radar-app:latest app
docker run --rm --env-file .env.production korea-market-radar-app:latest python deployment_preflight.py
docker compose --env-file .env.production stop whale_position_worker
docker compose --env-file .env.production up -d --no-deps --force-recreate --wait --wait-timeout 90 api
docker compose --env-file .env.production up -d --no-deps --force-recreate whale_position_worker
docker compose --env-file .env.production ps api whale_position_worker
docker compose --env-file .env.production logs --since=5m --tail=30 whale_position_worker
)
```

这两个服务应使用相同 `./app/data:/app/data` 卷。其他行情、新闻、原 Binance 巨鲸及 OpenD 服务不需要随本次变更重建或重新登录。先等待 API healthy，进入提醒中心开启一个市场，再确认页面连接、核验及事件；Telegram 真实接收需在 VPS 部署后验收。PWA 版本已更新，沿用现有自动更新机制。

`git pull` 只下载已推送代码，本身不会更新运行中的镜像。本文件的代码准备及本地测试不代表已部署到 VPS。

## 验证

从仓库根目录：

```sh
python -m pytest app/tests -q
node --test app/tests/mobile-core.test.mjs app/tests/service-worker.test.mjs app/tests/whales.test.mjs app/tests/app-update.test.mjs
node --check app/web/static/mobile.js
node --check app/web/static/whales.js
```

隔离测试也覆盖两个门槛、零值关闭、累计重启／到期／方向变化、重要动作优先、配置变更取消、旧客户端兼容及账户隔离的覆盖统计。浏览器测试 `app/tests/browser_whales.py` 使用内存数据库和明确的合成测试仓位；不发消息、不启动真实 worker，验证设置保存后重载、手机／桌面及浅色／夜间布局。

开发时另以只读请求核验过官方实时 metadata、trades 的双地址字段和 clearinghouseState 仓位字段，并用隔离数据库运行 35 秒完整链路：发现 63 个公开地址、核验 33 个地址、生成真实来源的仓位事件及隔离站内通知，未发 Telegram、未修改生产数据。这不等同于 VPS 网络或持续推送验收。

## English

The service automatically discovers public wallets from both counterparties of observed trades in subscribed Hyperliquid / trade.xyz perpetuals. Users search the official `xyz` catalog and configure markets, position-value thresholds and wallet/market cooldowns without entering addresses. All currently listed, non-delisted xyz instruments are eligible; the initial four-market allowlist has been removed. Metadata is refreshed at startup and hourly. The catalog includes equities, ETFs and other instruments, so unfamiliar names retain neutral perpetual labels. The live catalog returned 114 markets during development verification on 2026-10-11; availability changes over time. Existing subscriptions are preserved, only enabled markets are monitored, and these are distinct from Binance instruments.

Persistent candidate wallets are verified through public clearinghouse snapshots. Initial holdings are labeled discoveries; subsequent signed-quantity changes produce net opening, increase, reduction, closure or reversal events. Price-only valuation changes do not imply new trades. Entry price and leverage represent the current position snapshot, not an individual fill or historical leverage setting. Events reuse account notification history and verified Telegram recipients with durable delivery claims and bounded explicit-failure retries.

Position cards and Telegram messages display the source snapshot's `unrealizedPnl` as current unrealized P&L, preserving profit, loss and zero. Missing or invalid fields and older records remain unavailable until verified again. P&L-only changes do not generate position-change alerts. Event P&L is historical to that event snapshot, while current holdings update through normal polling. Closure events do not infer realized profit from unrealized P&L or zero position value. Existing JSON snapshots remain compatible without a database migration or historical Telegram replay.

New Telegram messages use concise copy: instrument and action (including net quantity for increases/reductions), remaining position value, entry/leverage, unrealized P&L, shortened wallet address, and trade.xyz with Beijing time. Initial discoveries remain explicitly pre-existing holdings; closure messages retain the previous notional and mark realized P&L unavailable. Full source and snapshot details remain in stored events and the web view. Existing notifications are not rewritten.

Messages now also include action-specific opening, increase, reduction or closing prices from official `userFillsByTime` records. Fills must connect both signed position snapshots exactly through their start positions, within a window of at most one hour, without mixed buy/sell directions. Multiple fills use size-weighted prices and are labeled as an execution average. Reversals split closing and opening quantities/prices at zero; same-millisecond ordering uses position continuity rather than trade IDs. Discoveries, legacy events, incomplete/invalid fills, responses reaching the 2000-fill limit and unreconciled quantities remain unavailable. Entry, mark and latest market prices are never substituted. Closing price does not imply realized profit.

One optional fill lookup is shared by all qualifying changed markets in a wallet scan. Failed lookups preserve valid snapshots and alerts, with unavailable execution prices; HTTP rate limits/server errors trigger backoff. REST pacing accounts for fill-response weights, targeting about 900 weight/minute with at least 0.6 seconds between requests. Existing Telegram messages are not replayed.

Personal per-market settings now include minimum adjustment USD (default 5,000), minimum quantity change as a percentage of the original position (0.5%), aggregation window (300 seconds), cooldown (300 seconds) and priority opening/closure/reversal alerts (enabled). Ordinary increases/reductions must pass both change gates. Zero disables the respective gate or aggregation window. Missing execution prices use a snapshot estimate only for filtering, never as a claimed fill price.

Continuous same-direction adjustments merge durably within each user's wallet/market window and send when qualified and outside cooldown. Expired subthreshold or still-cooled batches are filtered. Opposite changes or important position events supersede old batches; configuration changes, pausing and deletion cancel pending aggregation and obsolete failed retries. Complete member executions yield a size-weighted aggregate price; otherwise it remains unavailable. Initial discovery remains distinct from a new opening. Per-market retained-pool coverage and personal 24-hour decision counts explain why web events can outnumber Telegram messages.

Four additive tables store policies, batches, decisions and market/address associations; startup creates them idempotently without altering legacy subscriptions. Existing clients omitting new fields preserve saved settings. Upgrade both API and worker using the deployment steps above; PWA assets use version `2026.10.11.5`.

Coverage begins with observed public trades and the persisted candidate pool; this is not a complete historical or cross-exchange index. Quiet pre-existing wallets, short-lived positions between polls, pool overflow, reconnection gaps and throttling may cause omissions. The UI exposes source scope, heartbeat, subscription acknowledgments, timestamps, queue depth, errors and stale positions. Run one worker replica with the existing SQLite volume. Upgrade the API and new worker after backing up production data; pulling source does not rebuild running containers.

## 官方数据依据 / Official references

- [WebSocket subscriptions and WsTrade counterparty addresses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)
- [Perpetual metadata and clearinghouse state](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals)
- [API rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)
- [Historical data and its separate access requirements](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data)
