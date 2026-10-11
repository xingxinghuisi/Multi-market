# Lighter 主网巨鲸 / Lighter mainnet whales

## 已完成

PWA「提醒 → 链上巨鲸仓位」新增平台筛选，可搜索、添加、暂停和删除 Lighter 主网永续市场。自动从公开成交发现买卖双方账户索引，核验公开仓位与 L1 地址，复用现有个人仓位门槛、调仓金额／比例、累计窗口、冷却、通知中心及 Telegram。无需手动添加巨鲸地址，也不需要 API Key、钱包私钥或交易权限。

市场由官方 `orderBookDetails` 动态核验，只提供 active、非隐藏的永续目录；排除现货和停用记录。仅减仓、冻结以及 24h 无成交会标示。2026-10-11 开发实测得到 213 个有效永续市场，数量会变化。**KORU（market_id=226）虽然 active，但当时仅减仓、24h 成交量为零**；不能因为有目录就承诺一定发现活跃巨鲸。不能把 inactive 的 SKHYNIX 与 SKHYNIXUSD 合并。

只接 **Lighter 主部署**，不含 Robinhood。市场键 `lighter:mainnet:<market_id>`、账户键 `lighter:mainnet:<account_index>` 与 trade.xyz 独立；同名合约、同一 L1 地址的多个子账户不会合并。公开 L1 地址为空或零地址时只显示真实账户索引，不编造钱包。

## 数据口径

- 数量为 `position × sign`，名义价值取 `position_value` 绝对值；均价及未实现盈亏直接取公开账户仓位字段。缺失可选字段显示未提供。
- 账户 REST 的 `initial_margin_fraction` 为**百分数**，例如 `5.00` 折算 `20x`，不同于目录中的基点单位。页面及 Telegram 明确标注“初始保证金率折算”，不称为实际资金杠杆或历史订单设置。
- 快照时间为本服务成功读取时的 UTC 时间，保存 `snapshot_basis=observed_at`；不是账户最后交易的微秒时间，也不是准确开仓时间。首次核验仅称“新发现已有仓位”。
- 仅完整成功、账户 ID 一致的仓位响应推进快照。缺页、异常数量、重复持仓、超时或接口失败保留旧仓位，不生成假平仓。
- 动作价格使用公开 `trades?account_index=...`。按本账户买卖方及 maker/taker 角色读取 `*_position_size_before`，成交链必须完整连接前后签名数量。多笔取 VWAP，反向开仓分段；最多 3 页、每页 100 条。分页截断、乱序、身份不符、缺字段、鉴权拒绝或数量不一致时显示未提供，不以持仓均价或标记价代替。
- 与现有实现一致，只比较核验间净数量变化；短暂开平仓、混合方向成交不保证逐笔发现。静默历史账户、重连期间和候选池溢出可能遗漏，不是全网历史全量索引。

## 运行与限流

新增 `lighter_whales.py` 只读适配器及 `lighter_position_worker.py` 采集进程，**不添加投递循环**。`whale_position_worker` 是两平台唯一投递协调进程，避免同时抢投导致重复；各运行一个副本，即使只订阅 Lighter 也必须保留原协调进程。API 和两个进程共享原 `./app/data:/app/data` 卷，无新增运行时依赖或旧表结构修改。

公开 REST 目录、账户及成交历史共享至少 1.2 秒间隔（约 50 次/分钟）；405／429／5xx 遵守退避，长冷却不阻塞心跳。WebSocket 控制消息至少间隔 0.4 秒、最多 20 个订阅待确认，小批量发送并持续读消息；暂停市场后重连所需订阅。候选池默认每平台 2000，分别限量；大仓位目标约 60 秒核验，普通候选约 5 分钟，实际随队列和限流延迟。页面分别展示两平台心跳、连接、候选和异常，并提示共享投递服务离线。

无需新增必填环境变量。可选 `WHALE_LIGHTER_ADDRESS_CAP` 为 100–10000；`LIGHTER_PROXY` 用于公开 REST 与 WebSocket。不要提交真实 `.env` 或代理凭据。

## 升级和验收

先使用 [备份与部署命令](whale-positions.md#本地与-docker) 更新 API 和两个巨鲸进程。该命令适用于已有正确 Git checkout 的 `/opt/korea-market-radar`；`git pull` 本身不更新运行中的容器。其他行情、新闻与 OpenD 无需重建或重新登录。

部署后在「提醒 → 链上巨鲸仓位 → 添加市场」选择 Lighter 主网，并选择目录中有成交的市场、小范围开启测试。确认 Lighter 公开成交连接、候选账户及核验时间推进，同时确认共享推送服务在线。真实推送继续受个人仓位及调仓门槛筛选。KORU 当时无成交，不能用它作为“必须马上发现地址”的验收样本。

本地完整 Python 测试 182 项通过、前端测试 24 项通过；浏览器覆盖双平台同名市场增删、设置重载、320–1440px 和浅色／夜间。隔离测试涵盖单位换算、账户／市场隔离、坏响应保留仓位、成交角色与完整链、分页和速率上限、持久去重及 API 认证。开发还通过新适配器验证了无鉴权账户成交历史；35 秒真实公开采集链路在隔离数据库中发现 144 个候选、核验 21 个、保存 10 条仓位事件与 10 条站内通知。未下单、未发 Telegram、未修改生产数据。这不替代 VPS 持续运行和真实接收验收。

## English

Lighter mainnet is an additive public whale source alongside trade.xyz. Active, non-hidden perpetual markets are discovered from official metadata, with reduce-only, frozen and zero-volume states labeled. Public trade counterparties yield account indices; complete account responses verify positions and public L1 addresses. Deployment-qualified market/account identities keep venues and subaccounts separate. Robinhood is excluded.

Quantity, notional, entry and unrealized P&L use public source fields. Account initial margin is a percentage: 5.00% implies 20x, explicitly labeled as margin-derived rather than actual effective leverage. Snapshot timestamps denote observation time. Exact, complete own-account fill chains support action-specific VWAP; incomplete, denied or capped history remains unavailable. REST and WebSocket pacing, bounded candidate pools and retries preserve source limits and heartbeat visibility.

Existing account policies, aggregation, durable delivery claims and notification history are reused. Run one Lighter discovery replica and one existing whale-position coordinator; only the latter delivers both venues. Upgrade API and both workers after the linked SQLite backup procedure. Local tests and read-only upstream validation do not imply VPS deployment or a historical whole-network index.

## 官方依据

- [Public WebSocket and trade account indices](https://apidocs.lighter.xyz/docs/websocket-reference)
- [REST and WebSocket limits](https://apidocs.lighter.xyz/docs/rate-limits)
- [Official Account API](https://github.com/elliottech/lighter-python/blob/main/docs/AccountApi.md)
- [Official AccountPosition fields](https://github.com/elliottech/lighter-python/blob/main/docs/AccountPosition.md)
- [Official Order/trades API](https://github.com/elliottech/lighter-python/blob/main/docs/OrderApi.md)
- [Official SDK margin-mode constants](https://github.com/elliottech/lighter-python/blob/main/lighter/signer_client.py)
