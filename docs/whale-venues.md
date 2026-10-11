# 下一巨鲸数据源核验 / Next whale venue

用户确定的筛选口径：**永续 DEX、近 30 天成交量前三**，且能公开发现账户并查询他人仓位，不要求用户提供已知巨鲸地址。当前功能仍只接入 Hyperliquid / trade.xyz；本记录是下一阶段的接入依据，不表示已上线第二平台。

## 2026-10-11 核验

按 [DeFiLlama Perps](https://defillama.com/perps) 的 **Reported Volume 30d**、协议合并口径排序；不以页面默认的持仓量排序代替成交量排名，不重复累计父协议与子部署：

| 排名 | 协议 | 近 30 天上报成交量（USD） | 判断 |
| --- | --- | ---: | --- |
| 1 | Hyperliquid | $200.425B | 已接入其 trade.xyz 市场 |
| 2 | Variational | $73.309B | 公开 API 文档目前提供市场统计，未确认可用的任意钱包仓位发现接口 |
| 3 | Lighter | $60.550B | 下一接入候选；已验证公开账户读取与股票合约目录 |
| 4 | Aster | $56.091B | 本次口径不在前三，不列为下一接入对象 |

此处排名来自公开页面及其完整页面数据中的 `protocols / total30d`，是当日快照，会变化；不是本应用实时排名功能。尝试 DeFiLlama derivatives REST overview 返回 HTTP 402，因此未依赖该受限接口。上报成交量与规范化成交量并非同一指标，本记录不据此评定成交质量。

**Lighter 的第三名是合并口径**：Lighter Perps 主部署约 $45.629B，Lighter Robinhood Perps 约 $14.921B，合计约 $60.550B。若改为每个部署单独排名，不能声称 Lighter 主部署单独第三。下一步先接入具备目标股票合约的主部署，再评估第二部署；数据标识须包含平台和部署，不能混淆账户索引及成交。

## 为什么优先 Lighter

[Lighter 官方账户 SDK 文档](https://github.com/elliottech/lighter-python/blob/main/docs/AccountApi.md) 支持按账户索引或 L1 地址查询账户；开发时对主网 `GET /api/v1/account?by=index&value=1` 无密钥读取返回成功，含账户索引、L1 地址和 positions 容器。这个样本无持仓，不能据此冒充已验证某个真实巨鲸；非零仓位、分页完整性和实时成交链仍需下一阶段验收。

[官方 WebSocket 文档](https://apidocs.lighter.xyz/docs/websocket-reference) 的公开成交结构提供买卖双方账户索引，可作为自动发现入口；账户仓位结构包含方向、数量、平均开仓价、仓位价值、未实现盈亏、保证金模式及初始保证金比例。杠杆设置的换算和字段语义需单独核验，不把实际资金杠杆冒充用户设置。

对 [主网官方合约目录](https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails) 的只读查询返回 239 条永续目录记录（含停用市场），其中以下为当前真实状态：

| 符号 | market_id | 状态 |
| --- | ---: | --- |
| KORU | 226 | active |
| NVDA | 110 | active |
| TSLA | 112 | active |
| AAPL | 113 | active |
| SKHYNIXUSD | 161 | active |
| SKHYNIX | 143 | inactive |

接入时动态核验目录，仅提供有效市场；不得把已停用的 SKHYNIX 与 SKHYNIXUSD 静默视作同一合约，也不把 Lighter、trade.xyz、Binance 的同名市场当成同一仓位。

[Variational 当前官方 API 文档](https://docs.variational.io/technical-documentation/api) 提供 `/metadata/stats` 市场统计；文档中的交易 API 尚未开放，未找到满足自动发现任意账户仓位的数据链。故即使排名第二，也不把其统计接口充作巨鲸仓位源；后续若公开能力变化再核验。

## 下一阶段范围

1. 只读验证 Lighter 主部署：有效目录 → 成交对手账户索引 → 账户/L1 地址 → 完整非零仓位；确认分页、时间、限流及断线恢复。
2. 增加独立数据适配器及平台/部署标识，兼容现有 trade.xyz 订阅；复用已完成的个人过滤、累计与通知机制。
3. 前端选择平台、显示准确市场和来源；事件、地址、仓位及去重均按平台/部署隔离。没有完整数据时明确缺失，不推算虚假开仓或成交价格。
4. 隔离测试及小范围部署验收通过后开放；接入前复核近 30 天排名和目录状态。

## English

The agreed scope is perpetual DEXs ranked by trailing 30-day volume, with publicly discoverable accounts and positions. On 2026-10-11, DeFiLlama's reported-volume protocol aggregates place Hyperliquid, Variational and Lighter first through third. Lighter includes its main and Robinhood deployments; its main deployment alone is not third. Parent and child totals must not be double-counted.

Lighter is the next candidate: its public mainnet account endpoint succeeded without credentials, and its current directory includes active KORU, NVDA, TSLA, AAPL and SKHYNIXUSD perpetuals. The tested account was empty; live nonzero position and execution reconciliation still need validation. Variational's current public documentation exposes market statistics but does not establish the required arbitrary-account discovery/position path. No second venue has been integrated by this change.
