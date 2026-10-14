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
15 分钟是 MIRAO 的展示提醒阈值，不是币安公布的刷新间隔。本阶段不启用 Telegram 自动信号。

## 本阶段接入范围

登录后打开 Binance USDT 合约资产详情 → “币安聪明钱” → “查看聪明钱快照”。
新增 `GET /api/assets/{asset_id}/smart-money`，账户验证沿用现有 Session。
Spot、其他平台、停用资产与不存在的资产不能调用；前端不会随着行情刷新自动请求。
缺失或非法数字显示“未提供”，真实零值正常显示 0，不把读取失败当成没有巨鲸。

进程内所有用户共享每合约 10 分钟缓存，实际源请求全局至少间隔 15 秒，结果与错误缓存有容量上限。
不接受前端绕过缓存的参数，不自动重试；403/202/地区限制停止请求并等待，418/429 遵守完整 Retry-After（秒数或 HTTP 日期），不截短数小时封禁。
已有数据刷新失败时保留旧快照和原抓取时间，同时显示错误；不会把缓存命中伪装成新的源更新。
访问币安无需登录 Cookie、API Key、私钥或交易权限，不引入付费服务、Gemini 调用或新数据库表；MIRAO 页面仍要求登录。

## MIRAO VPS 更新

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

后续需确认 VPS 可读性、源时间语义及长期更新情况，再设计按用户配置的**群体变化**推送。
人数或持仓数量的净变化可能包含样本成员变化，不等同于某个巨鲸的买卖，不能替换现有地址级事件。

## 验证

在 `app/` 运行 `python -m pytest tests/test_binance_smart_money.py tests/test_mobile_api.py -q`，
仓库根运行 `node --test app/tests/smart-money.test.mjs app/tests/service-worker.test.mjs app/tests/mobile-core.test.mjs`。
真实 Chrome 的 390/1280px 验证使用 `python app/tests/browser_smart_money.py`，需 Playwright/Chrome。
测试为隔离数据库和合成快照，不调用币安、Telegram、Gemini 或线上服务。
本地/代码验证与 VPS 部署、长期采集验证是不同状态，不把已推送代码表述为已部署。
