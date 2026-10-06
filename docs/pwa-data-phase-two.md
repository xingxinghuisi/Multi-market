# PWA 第二阶段：真实合约指标与数据状态

这是第二阶段的历史记录；后续登录与账户隔离见 [pwa-accounts-phase-three.md](pwa-accounts-phase-three.md)。

用户选择先发布 iPhone 主屏幕 PWA，之后再评估 App Store 包装。本阶段仍是本地可运行版本，尚未对外发布。

## 已接入

- Binance USD-M 合约详情新增 `GET /api/assets/{asset_id}/crypto-metrics`。仅接受数据库中已启用的 Binance 合约资产；Spot 与股票返回 404。
- 从 Binance 官方公开接口读取标记价格、指数价格、最新资金费率、下一次资金费时间和当前未平仓量。每组指标保留 Binance 返回的时间。该值直接取自 `lastFundingRate` 字段，不自行推算。
- 上游请求沿用已有 `BINANCE_PROXY_URL` 配置。正常结果缓存 20 秒；部分失败缓存 5 秒。上游失败或字段无效时返回 `null`/“—”，页面保留其他可用字段。没有增加数据库表、私钥或历史假数据。
- 市场页没有报价时显示“等待行情”，资产目录数量不再被称为正在实时跟踪数量。合约指标只在合约详情显示，现货和股票仍使用各自现有字段。
- 提醒列表及按 ID 查询、修改、删除限定到现有默认用户，避免数据库中其他用户的规则误出现在单用户工作区。这不是多人认证。

数据源：[Binance USD-M Futures Market Data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)。相关接口为 `/fapi/v1/premiumIndex` 与 `/fapi/v1/openInterest`。多空比目前不接入：当前官方文档将相关接口标为需 API Key，部署中也未提供对应授权，页面不会捏造该指标。

## 运行与验证边界

- 本机 `--preview` 使用独立内存数据库，加载已有资产目录和一条 BTCUSDT 合约目录项来检查页面；没有实时行情、新闻 worker 或真实通知，合约指标也禁用外网读取。预览中的空值不代表线上数据源故障。
- 实际部署仍须运行现有 `market_worker.py` 与 `news_worker.py`，并确认 Binance / Moomoo / KRX 网络与授权、报价新鲜度和 Telegram 发送。只启动 API 不会自动产生行情或新闻。
- iPhone PWA 安装需要 HTTPS 或 localhost 开发环境。真实 iPhone Safari 的安装、返回前台刷新及弱网恢复仍需真机测试。
- 对外给少量用户使用前，必须完成注册 / 登录、会话安全、所有私有接口和 WebSocket 的用户隔离、限流以及部署权限；现有“登录 / 注册”页仍明确显示未开放。不要直接把当前单用户实例公开到互联网。
- 设备推送尚未接入。Apple 支持主屏幕 Web App 的 Web Push，但需要用户授权、订阅保存、服务端 VAPID 与推送发送链路。当前通知中心仅显示数据库中的发送记录。

## 验证

Python 内存数据库契约测试覆盖真实源字段映射、Spot/合约区分、部分上游失败、短时缓存和跨用户提醒规则防护；前端核心与 Service Worker 测试保持通过。本机预览没有执行真实外网行情调用。
