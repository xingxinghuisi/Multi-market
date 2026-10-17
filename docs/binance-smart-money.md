# Binance Futures Smart Signal · 只读快照接入

2026-10-14 实测：KORUUSDT 和 BTCUSDT 的网页汇总接口均可匿名读取 JSON，HTTP 200、业务码 `000000`、`success=true`。
这是币安网页使用的接口，**未找到它对应的正式开发者 API 文档或更新频率承诺**；一次可读不代表所有 VPS、地区或未来版本都可读。

来源：[币安合约聪明钱说明](https://www.binance.com/zh-CN/support/faq/detail/197ed63fbca34124bae53d8e6d4c9d29)，
[官方开发者目录](https://developers.binance.com/en/docs/llms.txt)。
实测端点为 `GET https://www.binance.com/bapi/futures/v1/public/future/smart-money/signal/overview?symbol=KORUUSDT`。
本地匿名采样 JSON 位于已忽略的 `.local-tmp/binance-smart-money/`，不提交原始样本、运行数据库或凭据。

## 当前可验证的字段

| 上游字段 | 展示含义 |
| --- | --- |
| `symbol` | 必须与请求的 Binance USDT 合约完全一致 |
| `totalPositions` | 群体总持仓名义价值（USD），不是保证金 |
| `totalTraders` | 币安选定的交易员总数 |
| `longShortRatio` | 接口原始群体多空比 |
| `longTraders` / `shortTraders` | 多/空交易员人数 |
| `longTradersQty` / `shortTradersQty` | 多/空持仓数量，合约基础单位，不能当成 USDT |
| `longTradersAvgEntryPrice` / `shortTradersAvgEntryPrice` | 对应群体的平均开仓价 |
| `longWhales` / `shortWhales` | 多/空巨鲸人数 |
| `longWhalesQty` / `shortWhalesQty` | 巨鲸群体持仓数量 |
| `longWhalesAvgEntryPrice` / `shortWhalesAvgEntryPrice` | 巨鲸群体平均开仓价 |
| `longProfitTraders` / `shortProfitTraders` | 盈利交易员人数，不是盈亏金额 |
| `longProfitWhales` / `shortProfitWhales` | 盈利巨鲸人数，不是盈亏金额 |
| `updateTime` | 源返回的毫秒时间字段，具体刷新语义仍待核实 |

官方“巨鲸”按近 30 天盈利超过 10 万美元且总盈亏为正筛选，与 MIRAO 链上巨鲸的仓位金额门槛不同。
该汇总响应没有个人账户/钱包地址、杠杆、个人未实现盈亏金额或逐笔开平仓；不据此生成虚构的钱包事件。
`binance:usdm:KORUUSDT`、`xyz:KORU`、`lighter:mainnet:226` 分别代表不同市场，不能合并仓位。

## 时间字段的实测发现

第一次 KORU 采样时间为 **2026-10-14 14:34:30 UTC**：多头巨鲸 74、空头巨鲸 98。
第二次为 **14:45:20 UTC**：多头巨鲸 76、空头巨鲸 95，数值已变化。
两次 `updateTime` 都为 `1791959444739`（**06:30:44.739 UTC**）；BTC 对照样本也返回同一时间字段。

因此确认了约 11 分钟的两次采样之间数值发生变化，**没有确认每 11 分钟更新，也不能断定全部数据已停更八小时**。
该字段的含义、是否固定基准时间、是否存在时区实现问题都未得到官方定义，不自行加八小时修正。

API 分别返回源时间、最近成功抓取时间、源时间字段的滞后秒数、数据指纹和 `freshness_confirmed=false`。
页面显示“源时间口径待核实”；原始时间落后超过 15 分钟时提醒时间字段较旧，但不冒充已确认的数据过期。
15 分钟是 MIRAO 的展示提醒阈值，不是币安公布的刷新间隔。快照本身不自动推送；群体变化订阅需用户单独开启。

2026-10-17 VPS 四次采样（14:34:49–15:04:50 UTC）全部 `DATA_OK`，三次相邻比较的指纹均变化。
多头巨鲸人数为 65 → 62 → 65 → 64，空头为 166 → 169 → 166 → 167；交易员总数 378 → 378 → 379 → 379。
四次源时间字段均为 `06:05:32.203 UTC`。这证明该 VPS 在这半小时内能够持续读取变化，不能证明固定更新频率，仍不能把源时间当成实际成交或快照刷新时间。

## 可配置的群体变化订阅（2026.10.17.1）

在合约详情点击「设置群体变化提醒」，或在「提醒 → 推送订阅」展开币种卡片。
默认关闭，需要勾选「开启群体变化提醒」并点击「保存聪明钱订阅」。这不会开启大额聚合成交、1H 播报或链上钱包订阅。

- 可选监控巨鲸人数、巨鲸持仓数量，至少选一项；各自可设门槛。
- 默认人数净变化 5 人、数量相对变化 5%、最短提醒间隔 3600 秒（可设 600–86400 秒）。用户可以修改这些值。
- 多头/空头任一所选指标达到其门槛即可触发，按相邻成功读取快照比较。
- 数量百分比 =（本次数量 − 上次数量）/ 上次数量 × 100%；上次数量为 0、字段缺失或非法时不计算该项，不生成零值或无穷百分比。
- 不使用价格涨跌导致的名义价值变化作为调仓依据。群体数量/人数变化也可能来自币安样本成员变化，不等同于个人开平仓。
- 首次开启、重新开启、修改实际配置，以及两次成功读取间隔超过 30 分钟时，只建立对照快照，不推送已有状态。
- 状态和对照快照保存在新增的 `smart_money_states` 表，重启后沿用；不重建任何旧表。
- 每次有效新采样都推进对照，包括未达门槛、提醒间隔内和投递失败的区间；这些变化不累计、不事后补发。
- 抓取失败、被限制、缓存回退、过旧的抓取时间或市场标识不匹配不推进对照，也不生成变化通知。原始源时间较旧不会被伪装成已核实的新源时间。
- 由每用户订阅解析 Telegram 接收目标；未绑定时只保存站内通知。只有旧 default 账户保留既有部署目标兼容。
- 投递使用订阅和观察时间组成的持久化事件键。发送前记录 pending，结果未知时不自动重发；失败写入 failed，后续不会补发这段历史变化。
- 页面显示最近检查、最近成功读取和未达门槛/提醒间隔/发送失败/数据源不可用等状态。

新 `smart_money_worker` 只做调度，每 30 秒顺序选择一个已订阅资产，请求内部 API。
数据仍由同一个 API 进程中的客户端读取，所有账户及页面共享每合约 10 分钟缓存、全局请求间隔和上游限流等待。
多个币种顺序轮转，大量币种可能延长观察间隔；这不是币安承诺的刷新频率。没有开启的订阅时不会主动访问币安。
源时间语义和数据实际新鲜度仍未确认，因此消息明确称为「观察快照净变化」，附两次实际读取时间，不称为实时成交、刚开仓或确定的多空交易建议。
不调用 Gemini，不消耗 Google 额度，不创建钱包地址、杠杆或个人盈亏等不存在的字段。

示例（合成数据，仅说明格式）：

```text
🐋 KORUUSDT 聪明钱群体变化
多头巨鲸：65 → 62（-3 人）
空头巨鲸：166 → 169（+3 人）
观察：10/17 22:34 → 10/17 22:44 北京时间
币安汇总快照净变化，可能含样本成员变动；不是个人成交。源时间含义待核实。
```

该例在用户人数门槛设为 3 或更低时才触发，不会绕过默认 5 人门槛。

## 群体浮动盈亏与均价（2026.10.18.1）

2026-10-17 检查币安实际页面加载的[前端脚本](https://bin.bnbstatic.com/static/chunks/page-1f6e.4bdd9ec8.js)：
总览的浮动盈亏由 `at` / `br` 组件计算；巨鲸标签传入 `longWhalesQty` / `shortWhalesQty` 和对应 `AvgEntryPrice`。
价格来自 `ge` 使用的最新聚合成交，缺失时回退行情价格。未实现盈亏不是 overview 响应中的独立金额字段。
MIRAO 复用现有同一资产 ID 的 Binance USDT 合约成交行情，用相同方向公式计算：

- 多头：（最新成交价 − 群体平均开仓价）× 群体数量。
- 空头：（群体平均开仓价 − 最新成交价）× 群体数量。

分别计算交易员、巨鲸两个群体；交易员包含巨鲸，不把两者相加。
结果标记为「浮盈亏（计算，USDT）」/ `pnl.basis=latest_trade`，不冒充币安账户结算或标记价格口径。
不额外调用币安数据接口，不调用 Gemini。报价与持仓快照来自各自的采集时刻，页面和消息分别展示两者时间；按异步快照持仓计算的金额不保证与币安此刻页面逐分逐毫一致。

- 行情必须来自相同 Binance 合约资产 ID，不能借用同名 Spot、Hyperliquid、Lighter 或股票价格。
- 最新成交时间超过 120 秒、持仓成功读取时间超过 900 秒、明显未来时间或上游回退错误时不显示当前金额，并说明原因。
- 缺失/非法数量或均价显示「未提供」；已知仓位数量为 0 或计算结果恰为 0 时正常显示 0。
- 不使用价格涨跌比例、杠杆倍数或盈利人数来替代真实的数量与成本字段。
- 页面接收现有行情推送时只更新金额和价格时间，不重新请求聪明钱接口、不重建整个页面。
- Telegram 原有群体变化通知附带多空巨鲸开仓均价、计算浮盈亏及参考成交价；人数/数量门槛和冷却仍决定是否推送。
- 新采样的估值和前后差额保存在现有状态 JSON 中；旧状态没有估值时，首次新采样只记录当前金额，后续有效采样才有差额。
- 两次成功观察必须同市场、同价格口径、向前且间隔不超过 30 分钟才比较。共用缓存的重复读取不覆盖上次采样比较。
- 差额包含行情价格、持仓数量/均价与群体成员变化的共同影响，不能解释为这段时间已实现盈利、开平仓收益或资金流入。
- 不含手续费和资金费，也不反推已实现盈亏。它们仍未从本条公共汇总数据链路核实到。

新增 API `pnl` 是 MIRAO 的派生字段；原始汇总缓存不被估值修改。
`GET /api/subscriptions` 的个人 `monitoring.pnl_comparison` 返回最近两次监控快照的差额与时间，保持账户隔离。
本次沿用现有 `smart_money_states.snapshot` JSON，不添加数据库列、不覆盖旧通知、不改变订阅开关。

以下为合成数据示例（不是实时市场行情）：

```text
🐋 KORUUSDT 聪明钱群体变化
多头巨鲸：65 → 68（+3 人）
多头巨鲸持仓数量：100 → 110（+10.00%）
多头巨鲸开仓均价：$14｜浮盈亏：-$110.00
空头巨鲸开仓均价：$19｜浮盈亏：+$900.00
较上次采样：多头 +$90.00｜空头 -$150.00
参考成交价：$13（10/18 08:10:00 北京时间）
观察：10/18 08:00 → 10/18 08:10 北京时间
浮盈亏为快照计算值，含价格/样本变化，不含费用；非已实现收益、不是个人成交。源时间含义待核实。
```

### 部署群体变化订阅

将 `REVIEWED_COMMIT_SHA` 替换为本次提供的完整提交号，在 MIRAO VPS 运行：

```bash
cd /opt/korea-market-radar &&
git fetch origin main &&
git show REVIEWED_COMMIT_SHA:scripts/deploy-smart-money-alerts.sh > /root/mirao-deploy-smart-money-alerts.sh &&
bash /root/mirao-deploy-smart-money-alerts.sh REVIEWED_COMMIT_SHA
```

脚本在线备份 SQLite、保留旧 API 镜像，在隔离备份上检查增量建表与原有核心记录数量，再更新 API 并启动新调度 worker。
不会重启行情、新闻、技术信号、OpenD、Hyperliquid 或 Lighter 服务。激活失败时尝试恢复旧 API/调度 worker 镜像；保留增量表和新 Git 源码，避免覆盖部署期间其他服务产生的新数据。
部署完成不会自动给已有账户开启新订阅。排查使用 `docker compose --env-file .env.production logs --tail=20 smart_money_worker`。

## 本阶段接入范围

登录后打开 Binance USDT 合约资产详情 → “币安聪明钱” → “查看聪明钱快照”。
新增 `GET /api/assets/{asset_id}/smart-money`，账户验证沿用现有 Session。
Spot、其他平台、停用资产与不存在的资产不能调用；前端不会随着行情刷新自动请求。
缺失或非法数字显示“未提供”，真实零值正常显示 0，不把读取失败当成没有巨鲸。

进程内所有用户共享每合约 10 分钟缓存，实际源请求全局至少间隔 15 秒，结果与错误缓存有容量上限。
不接受前端绕过缓存的参数，不自动重试；403/202/地区限制停止请求并等待，418/429 遵守完整 Retry-After（秒数或 HTTP 日期），不截短数小时封禁。
已有数据刷新失败时保留旧快照和原抓取时间，同时显示错误；不会把缓存命中伪装成新的源更新。
访问币安无需登录 Cookie、API Key、私钥或交易权限，不引入付费服务、Gemini 调用或新数据库表；MIRAO 页面仍要求登录。

## 初期只读快照部署（历史记录）

当前版本请使用上方「部署群体变化订阅」流程，它同时包含快照、订阅和浮盈亏功能。以下保留为最初快照版的部署记录。

代码推送后，在 **MIRAO VPS `/opt/korea-market-radar`** 运行，不是在语屿或音频生成服务器。
把下方 `REVIEWED_COMMIT_SHA` 替换为本次给出的完整提交号。

```bash
cd /opt/korea-market-radar &&
git fetch origin main &&
git show REVIEWED_COMMIT_SHA:scripts/deploy-smart-money.sh > /root/mirao-deploy-smart-money.sh &&
bash /root/mirao-deploy-smart-money.sh REVIEWED_COMMIT_SHA
```

脚本检查来源工作区、锁定指定的 main 提交，保留上一 API 镜像和代码号；构建及预检成功后只重建 API。
检查 API 健康、客户端版本 `2026.10.14.1` 与新路由。失败时尝试恢复之前的 API 镜像，Git 源码仍保留新提交。
不重启市场、新闻、Gemini、OpenD、Hyperliquid、Lighter worker，不更改订阅或 Telegram。
无数据库结构迁移，`.env.production` 与数据库不进入 Git、备份输出或部署命令日志。

## VPS 低频探测

部署完成后先运行一次：

```bash
docker exec korea-radar-api python -u verify_binance_smart_money.py --symbol KORUUSDT --samples 1
```

连续四次、每十分钟一次（约半小时），可以在后台运行：

```bash
mkdir -p /opt/korea-market-radar/.local-tmp
nohup docker exec korea-radar-api python -u verify_binance_smart_money.py \
  --symbol KORUUSDT --samples 4 --interval 600 \
  > /opt/korea-market-radar/.local-tmp/smart-money-probe.log 2>&1 < /dev/null &
tail -n 10 /opt/korea-market-radar/.local-tmp/smart-money-probe.log
```

探测器同时记录 `source_time_changed` 与 `data_changed`，不会把时间字段不变等同于数值不更新。
遇到限流或访问限制立即结束，不重试、不切换地区/IP，也不读用户数据库或发送 Telegram。
短窗口的变化仅约束该窗口内的观察，不能证明长期固定更新频率。

长期更新稳定性与源时间语义仍需持续核实；当前订阅仅比较成功读取的**群体快照变化**。
人数或持仓数量的净变化可能包含样本成员变化，不等同于某个巨鲸的买卖，不能替换现有地址级事件。

## 验证

在 `app/` 运行 `python -m pytest tests/test_binance_smart_money.py tests/test_smart_money_pnl.py tests/test_smart_money_subscriptions.py tests/test_subscriptions.py tests/test_mobile_api.py -q`，
仓库根运行 `node --test app/tests/smart-money.test.mjs app/tests/service-worker.test.mjs app/tests/mobile-core.test.mjs`。
真实 Chrome 的 390/1280px 验证使用 `python app/tests/browser_smart_money.py`，需 Playwright/Chrome。
测试为隔离数据库和合成快照，不调用币安、Telegram、Gemini 或线上服务。
本地/代码验证与 VPS 部署、长期采集验证是不同状态，不把已推送代码表述为已部署。
