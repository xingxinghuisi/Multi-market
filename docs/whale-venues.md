# 下一巨鲸数据源核验 / Next whale venue

用户确定的筛选口径：**永续 DEX、近 30 天成交量前三**，且能公开发现账户并查询他人仓位，不要求用户提供已知巨鲸地址。本记录保留选型时的排名快照；Lighter 主网现已完成代码接入，数据语义、测试及 VPS 升级见 [Lighter 说明](lighter-whales.md)。代码接入不等于 VPS 已更新。

## 2026-10-11 核验

按 [DeFiLlama Perps](https://defillama.com/perps) 的 **Reported Volume 30d**、协议合并口径排序；不以页面默认的持仓量排序代替成交量排名，不重复累计父协议与子部署：

| 排名 | 协议 | 近 30 天上报成交量（USD） | 判断 |
| --- | --- | ---: | --- |
| 1 | Hyperliquid | $200.425B | 已接入其 trade.xyz 市场 |
| 2 | Variational | $73.309B | 公开 API 文档目前提供市场统计，未确认可用的任意钱包仓位发现接口 |
| 3 | Lighter | $60.550B | 已接入主网公开成交与仓位；不含 Robinhood |
| 4 | Aster | $56.091B | 本次口径不在前三，不列为下一接入对象 |

此处排名来自公开页面及其完整页面数据中的 `protocols / total30d`，是当日快照，会变化；不是本应用实时排名功能。尝试 DeFiLlama derivatives REST overview 返回 HTTP 402，因此未依赖该受限接口。上报成交量与规范化成交量并非同一指标，本记录不据此评定成交质量。

**Lighter 的第三名是合并口径**：Lighter Perps 主部署约 $45.629B，Lighter Robinhood Perps 约 $14.921B，合计约 $60.550B。若改为每个部署单独排名，不能声称 Lighter 主部署单独第三。下一步先接入具备目标股票合约的主部署，再评估第二部署；数据标识须包含平台和部署，不能混淆账户索引及成交。

## 为什么优先 Lighter

[Lighter 官方账户 SDK 文档](https://github.com/elliottech/lighter-python/blob/main/docs/AccountApi.md) 支持按账户索引或 L1 地址查询账户。最初无持仓样本仅证明接口可读；本次进一步从真实 BTC 公开成交发现账户，再通过新适配器无密钥核验了非零 BTC 仓位、L1 地址及账户成交历史。分页和身份错误有隔离测试，VPS 持续运行仍待部署验收。

[官方 WebSocket 文档](https://apidocs.lighter.xyz/docs/websocket-reference) 的公开成交结构提供买卖双方账户索引，可作为自动发现入口；账户仓位结构包含方向、数量、平均开仓价、仓位价值、未实现盈亏、保证金模式及初始保证金比例。杠杆设置的换算和字段语义需单独核验，不把实际资金杠杆冒充用户设置。

对 [主网官方合约目录](https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails) 的只读查询返回 239 条永续目录记录（含停用市场），其中以下为当前真实状态：

| 符号 | market_id | 状态 |
| --- | ---: | --- |
| KORU | 226 | active，但 force_reduce_only=true，24h 成交为零 |
| NVDA | 110 | active |
| TSLA | 112 | active |
| AAPL | 113 | active |
| SKHYNIXUSD | 161 | active |
| SKHYNIX | 143 | inactive |

接入时动态核验目录，仅提供有效市场；不得把已停用的 SKHYNIX 与 SKHYNIXUSD 静默视作同一合约，也不把 Lighter、trade.xyz、Binance 的同名市场当成同一仓位。

[Variational 当前官方 API 文档](https://docs.variational.io/technical-documentation/api) 提供 `/metadata/stats` 市场统计；文档中的交易 API 尚未开放，未找到满足自动发现任意账户仓位的数据链。故即使排名第二，也不把其统计接口充作巨鲸仓位源；后续若公开能力变化再核验。

## 本次实现与后续验收

1. 已完成主网只读数据链、独立适配器、平台/部署隔离及个人推送规则复用。
2. 已添加平台选择、真实目录状态、来源与子账户标识、分平台运行状态。
3. 已添加坏响应、分页、时间单位、保证金率、限流、身份与去重测试；成交不完整时价格未提供。
4. 后续在 VPS 小范围开启有成交的市场，检查持续采集、队列与 Telegram 接收。排名与目录会变化，下一平台接入前重新核验。

## English

The agreed scope is perpetual DEXs ranked by trailing 30-day volume, with publicly discoverable accounts and positions. On 2026-10-11, DeFiLlama's reported-volume protocol aggregates place Hyperliquid, Variational and Lighter first through third. Lighter includes its main and Robinhood deployments; its main deployment alone is not third. Parent and child totals must not be double-counted.

Lighter mainnet is now implemented alongside trade.xyz, with public trade-to-account discovery, verified nonzero positions and unauthenticated account fill history. KORU is active but reduce-only with zero recent volume at verification; directory availability does not guarantee active whales. Variational's documentation still does not establish the required arbitrary-account discovery/position path. This code and isolated validation do not imply VPS deployment or Robinhood coverage.
