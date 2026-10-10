# 多空播报与巨鲸订阅 / Push subscriptions

## 使用方法

1. 在「提醒 → 推送订阅 → 添加币种」选择资产目录中的 Binance USDT 合约。
2. 每个币种分别开启「1H 多空播报」「巨鲸大单」。价格步进继续使用原有「价格提醒」页面。
3. 巨鲸阈值按 USDT 名义成交额计算，可设置每个币种的独立提醒间隔（0–86400 秒；默认 300 秒）。
4. 在「设置 → Telegram」绑定个人接收目标。未绑定时，消息保存在「通知中心」，不会发到其他账户的 Telegram。
5. 合约详情的「1H 多空数据」显示完整周期的账户、持仓、主动买卖比及上期值。上游缺失或不可用时显示明确错误，不生成模拟数据。

订阅开关不会修改共享资产的采集开关，也不要求加入关注列表。从个人资产目录删除币种会暂停该币种的个人价格规则及推送订阅；恢复资产不会自动重新开启。删除订阅保留历史通知。

## 数据和投递

- 仅支持 Binance USD-M / USDT 合约；Spot、股票、币本位合约不接入本轮订阅。
- 1H 播报复用现有完整小时数据计算，默认每小时第 2 分钟运行；沿用 `CRYPTO_METRICS_PUSH_MINUTE` 配置。相同币种每轮只请求一次源数据，再逐个投递给订阅用户。
- 巨鲸监听读取 Binance `aggTrade` 聚合成交，按用户独立阈值和冷却判断。它只能识别大额聚合成交，不能识别真实钱包，也不将主动买卖差额当作资金净流入。
- 监听每 15 秒刷新订阅，市场没有成交时也会刷新。API 在投递时再次检查最新开关、阈值和数据库冷却；取消或提高阈值无需等待 worker 缓存刷新才生效。
- 接收目标只在 API 内解析。只有旧 `default` 账户保留服务器默认 Chat ID 的兼容行为。
- 通知状态：`sent` 已发送、`in_app` 站内记录、`failed` 发送失败、`pending` 正在投递或结果尚未确认。站内通知和 Telegram 消息使用同一份事件内容。
- `subscription_deliveries` 持久化订阅与事件键，避免正常请求重试、重连或重复执行同一小时造成重复发送。已失败的同一事件可再次提交；失败不占用成功冷却。投递过程中崩溃留下的 pending 不会自动重发，防止结果不明时重复发送。Telegram 本身没有幂等发送键，因此网络超时的极端情况仍不能保证端到端恰好一次。
- 当前 Compose 采用单 API 进程和每种一个 worker。扩展为多个 API 进程前，需要把进程内冷却互斥改为跨进程数据库锁/队列；事件唯一约束仍由数据库维护。

## 现有数据库升级

API 正常启动时只增加 `alert_subscriptions`、`subscription_deliveries`，不重建旧表，不覆盖旧数据，也不需要运行初始化脚本。

如果首次升级时订阅表尚不存在，会把旧 default 用户已关注、启用的 USDT 合约迁移成 1H 订阅，延续原播报选择。已存在订阅表时保留所有手动配置；重启不重新开启已关闭的订阅。巨鲸提醒需由用户主动开启。

## 部署

代码包/分支更新后，按 [现有部署文档](pwa-deployment-market-wyao.md) 备份数据库和部署配置。在仓库根目录构建并一起更新 API、1H worker 和巨鲸 worker：

```sh
docker build -f Dockerfile.app -t korea-market-radar-app:latest app
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production run --rm --no-deps api python deployment_preflight.py
docker compose --env-file .env.production up -d --force-recreate api crypto_metrics_worker whale_print_worker
docker compose --env-file .env.production ps
```

沿用现有 `.env.production`、`RADAR_WORKER_TOKEN` 和 `app/data` 挂载。Nginx 和域名不需要新增路径配置。只运行 API 可以管理订阅和读取公开多空数据；持续播报与实时大单监听需要对应 worker 运行。

验收时使用两个账户订阅同一币种，检查独立阈值、各自 Telegram 与通知记录；关闭其中一个账户的订阅后，另一个账户应继续工作。PWA 资源版本已更新，会沿用现有自动更新流程。

## 验证

### OpenD 不可用时的行情隔离

行情 worker 的 Moomoo 连接使用 SDK 异步连接，并为同步订阅请求设置连接等待上限。OpenD 停止、未登录或正在等待登录限流解除时，不应阻塞 Binance Spot/Futures 行情。各行情源独立重试；启动时没有资产的源也会定期重新检查新增资产。SDK 连接到 OpenD 的重试不等于重新登录 Moomoo 账户。

若旧版在停止 OpenD 后加密行情不再更新，拉取本修复、重建镜像，并只重建 `market_worker`；无需在 Moomoo 限流期间重启 OpenD。通过 worker 的 `[LIVE]` 行和数据库 `market_quotes.event_time` 的推进验证恢复。对应回归测试为 `tests/test_market_isolation.py`。

从 `app/` 执行：

```sh
python -m pytest tests -q
node --test tests/mobile-core.test.mjs tests/service-worker.test.mjs
node --check web/static/mobile.js
```

API/数据库测试使用隔离内存数据库，行情与 Telegram 通过模拟对象验证。浏览器界面验收使用内存预览，检查添加/删除、两种开关、阈值和间隔保存、合约详情入口、夜间模式与 320–1440px 布局。实际 VPS 网络连通性、真实 Binance 成交与真实 Telegram 接收需部署后验收。

可重复的浏览器测试在 `app/tests/subscriptions.browser.cjs`，需要 Node Playwright 与 Chromium。先在 `app/` 启动 `python tests/browser_mobile.py --preview --port=60439`，再从仓库根目录执行 `node app/tests/subscriptions.browser.cjs`。可通过 `RADAR_TEST_BASE_URL` 指定其他内存预览端口，或用 `PLAYWRIGHT_EXECUTABLE_PATH` 指定已安装的 Chrome。测试还会模拟保存过程中发生 PWA 更新，确认写入不会被刷新打断，并检查缓存不包含私有 API。

## English

MIRAO now manages hourly long/short reports and large aggregated-trade alerts as account-owned subscriptions. Users configure symbols, independent switches, USDT thresholds and cooldowns in the PWA. Futures details expose the existing completed-hour ratios, and both alert types appear in notification history.

Workers collect data and submit stable event keys to the authenticated internal API. The API rechecks current settings, resolves the account's Telegram recipient, applies persistent cooldowns and records delivery status. Unbound accounts receive in-app records; the deployment chat fallback is limited to the legacy default account.

Startup adds subscription and delivery tables without replacing existing data. A first-time upgrade preserves the legacy owner's hourly selection only when no subscription table exists. Existing subscriptions and disabled settings remain intact.

Deploy the API and both subscription workers together using the existing Docker Compose environment and data volume. Aggregated trades do not identify individual whales or wallets. The current deployment assumes one API process; multi-process cooldown coordination requires a shared lock or queue.

The market worker uses the Moomoo SDK's asynchronous connection mode so an unavailable OpenD cannot block Binance streams. Each source retries independently, including sources with no assets at startup. Deploy this isolation fix by rebuilding the app image and recreating only `market_worker`; leave OpenD stopped while account login is rate-limited.
