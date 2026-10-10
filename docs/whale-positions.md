# 自动发现股票／ETF 永续巨鲸 · 第一阶段

## 已实现的范围

PWA「提醒 → 链上巨鲸仓位」独立于原有 Binance 聚合成交提醒。无需填写钱包地址；用户选择市场、最低仓位名义价值和同地址同市场提醒间隔，并可暂停、删除。默认阈值为 100 万美元，可从 1000 美元起设置。没有订阅时不监听公开成交、不轮询钱包。

第一阶段限定 Hyperliquid 的 `xyz` 部署市场：`xyz:KORU`、`xyz:SKHY`、`xyz:NVDA`、`xyz:TSLA`。服务启动及每小时读取官方 metadata，只提供当前存在且未退市的市场。不会假设整个 xyz 目录都是股票，也不会将这些合约当成 Binance 同名 USDT 合约。仓位价值沿用官方 `positionValue` 的美元名义价值，不代表实际保证金。

一条公开 WebSocket 监听已订阅市场的 trades，读取 `users` 中买卖双方的公开地址；所有有效成交均可发现候选，不限定单笔成交金额，因此拆单也有机会被发现。候选保存在数据库，REST `clearinghouseState`（`dex=xyz`）核验签名数量、平均开仓价、当前杠杆设置及名义价值。不需要账户 API Key、钱包私钥或交易权限。

事件包括新发现已有仓位、新开仓、加仓、减仓、平仓和反向开仓。首次快照只记为「新发现已有仓位」；之后按两次快照的**签名数量**比较，不根据价格造成的市值涨跌推断加减仓。反向开仓标为净反向，无法推断期间是否经过多次交易。新开仓表示上次核验为零、本次非零，不表示精确成交时间。推送中的均价和杠杆为**当前仓位快照值**，不是历史订单杠杆或本次成交价。平仓不编造已不存在的当前均价或杠杆。

通知统一保存在账户通知中心，发给该用户已验证绑定的 Telegram；只有旧 `default` 账户可沿用部署接收目标。首行直接显示市场、事件、方向及当前名义价值。每用户每事件持久去重；同地址同市场冷却，不会让另一地址的事件被误抑制。显式发送失败最多重试两次；投递前重新检查订阅。进程意外停止后已标为 pending 的投递不自动重发，避免重复；Telegram 请求超时本身存在「已接收但未返回」的不确定性。

## 覆盖和运行边界

- **不是全网全历史索引**，不提供 Binance 等中心化交易所用户仓位。未接入其他链上交易场所，也未购买历史数据。
- 从监听成交及持久候选池发现地址；启动前已有但此后不成交的静默钱包可能遗漏。第一次订阅也会收到公开成交源的最近成交快照，从中发现地址，但不把旧成交当作刚开仓。
- 大仓位目标每 60 秒核验，普通候选目标每 5 分钟；观察到新成交可提前排队，但同地址不快于 30 秒。两次核验间开仓又平仓的短暂持仓可能完全遗漏。
- 最多约两次顺序仓位查询／秒（单次权重 2）；每小时一次市场目录查询。排队、网络故障、限流会延迟，不能保证每个地址都按目标频率更新。使用同一出口 IP 的其他程序也消耗上游额度。
- 默认候选池容量 2000，可通过 `WHALE_POSITION_ADDRESS_CAP` 设置为 100–10000。达到容量会记录跳过次数，页面提示覆盖不完整；仅清理超过一天未成交且已核验空仓的候选，不静默淘汰已知持仓。计数表示新候选被跳过的次数，并非唯一遗漏地址数。
- 页面显示服务心跳、成交连接、实际订阅市场、最近成交、核验时间、排队数及异常。超过三分钟未更新的仓位标为过期。网络异常、缺失字段、重复／过期源快照不会生成虚假平仓。
- 公共事件保留七天；账户通知继续沿用原有通知保存策略。页面每次最多显示 50 个大仓位及 50 条事件。阈值调整不补发历史事件。已提交但未派发的事件可在一小时内恢复派发，超时不再推送旧消息。
- **只运行一个 `whale_position_worker` 实例**。目前使用现有共享 SQLite；要水平扩容需增加跨进程任务领取／协调机制。

## 本地与 Docker

在已初始化的 `app/` 环境启动 API 后，运行 `python whale_position_worker.py`。API 和 worker 都只新增五张表，不修改现有用户、资产、提醒或数据库文件路径。默认无需增加环境变量；若服务器不能直连，可配置 `HYPERLIQUID_PROXY=http://...`，勿在 Git 中提交带凭据的代理地址。

服务器升级前先备份现有数据库及 `.env.production`。已有正确 Git checkout 时，正常流程是 `git pull --ff-only origin main`，然后：

```sh
cd /opt/korea-market-radar
docker build -f Dockerfile.app -t korea-market-radar-app:latest app
docker run --rm --env-file .env.production korea-market-radar-app:latest python deployment_preflight.py
docker compose --env-file .env.production up -d --no-deps --force-recreate api
docker compose --env-file .env.production up -d --no-deps whale_position_worker
docker compose --env-file .env.production ps api whale_position_worker
docker compose --env-file .env.production logs --since=5m --tail=30 whale_position_worker
```

这两个服务应使用相同 `./app/data:/app/data` 卷。其他行情、新闻、原 Binance 巨鲸及 OpenD 服务不需要随本次变更重建或重新登录。先等待 API healthy，进入提醒中心开启一个市场，再确认页面连接、核验及事件；Telegram 真实接收需在 VPS 部署后验收。PWA 版本已更新，沿用现有自动更新机制。

`git pull` 只下载已推送代码，本身不会更新运行中的镜像。本文件的代码准备及本地测试不代表已部署到 VPS。

## 验证

从仓库根目录：

```sh
python -m pytest app/tests -q
node --test app/tests/mobile-core.test.mjs app/tests/service-worker.test.mjs app/tests/whales.test.mjs
node --check app/web/static/mobile.js
node --check app/web/static/whales.js
```

隔离测试覆盖候选发现、容量、签名数量变化、缺失／过期快照、持久去重、失败重试、用户权限、CSRF、阈值和过期目录。浏览器测试 `app/tests/browser_whales.py` 使用内存数据库和明确的合成测试仓位；不发消息、不启动真实 worker。

开发时另以只读请求核验过官方实时 metadata、trades 的双地址字段和 clearinghouseState 仓位字段，并用隔离数据库运行 35 秒完整链路：发现 63 个公开地址、核验 33 个地址、生成真实来源的仓位事件及隔离站内通知，未发 Telegram、未修改生产数据。这不等同于 VPS 网络或持续推送验收。

## English

The first release automatically discovers public wallets from both counterparties of all observed trades in selected Hyperliquid / trade.xyz stock-linked perpetuals. Users configure markets, position-value thresholds and wallet/market cooldowns without entering addresses. The initial scope is `xyz:KORU`, `xyz:SKHY`, `xyz:NVDA` and `xyz:TSLA`, validated against live venue metadata. These are distinct from Binance instruments.

Persistent candidate wallets are verified through public clearinghouse snapshots. Initial holdings are labeled discoveries; subsequent signed-quantity changes produce net opening, increase, reduction, closure or reversal events. Price-only valuation changes do not imply new trades. Entry price and leverage represent the current position snapshot, not an individual fill or historical leverage setting. Events reuse account notification history and verified Telegram recipients with durable delivery claims and bounded explicit-failure retries.

Coverage begins with observed public trades and the persisted candidate pool; this is not a complete historical or cross-exchange index. Quiet pre-existing wallets, short-lived positions between polls, pool overflow, reconnection gaps and throttling may cause omissions. The UI exposes source scope, heartbeat, subscription acknowledgments, timestamps, queue depth, errors and stale positions. Run one worker replica with the existing SQLite volume. Upgrade the API and new worker after backing up production data; pulling source does not rebuild running containers.

## 官方数据依据 / Official references

- [WebSocket subscriptions and WsTrade counterparty addresses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)
- [Perpetual metadata and clearinghouse state](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals)
- [API rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)
- [Historical data and its separate access requirements](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data)
