# 技术信号与 Gemini / Technical signals and Gemini

本轮增加 Binance USDT 合约技术信号、Gemini 解读和每月 **$8.50** Telegram 费用提醒。现有价格提醒、新闻、多空、巨鲸和账户不重建。Gemini 默认关闭，需要 Google Cloud 项目与身份凭据后启用。没有凭据时，技术信号仍能发送，消息会说明 AI 尚未配置。

## 页面与信号

「提醒 → 技术信号与 Gemini 解读」新增或编辑合约订阅；使用现有个人订阅 API。每个账户最多 10 个合约，每个合约一组可编辑周期。支持 15m、1h、4h、1d；默认 1h。Telegram 发给订阅用户绑定的目标，未绑定时保留站内通知。

- RSI 14：Wilder 平滑，上穿或下穿用户配置的上下限。
- MACD：EMA 12/26，DEA 9，DIF/DEA 金叉与死叉。
- MA / EMA：用户选择算法和短长周期，默认 EMA 9/21。
- KDJ：9/3/3，K/D 金叉与死叉；K、D 从 50 起算。
- 成交额异动：本根 USDT 成交额 / 前 20 根均值，从下方达到用户配置倍数时触发。
- 斐波那契：用户明确填写波段高低点和方向；接近、突破、跌破 0.382/0.5/0.618。不能代替用户猜测波段锚点。
- RSI 顶/底背离：严格价格高低点，与 RSI 对比，右侧 3 根收盘确认；不是零延迟背离，也没有实现所有指标的背离。

只使用 Binance 官方 `/fapi/v1/klines` 已收盘、连续、最近完整周期的数据。至少 150 根有效 K 线，最多请求 400 根；数据缺失、过旧、断档、无效 OHLC 时不调用 AI、不推造假信号。首次开启或改变配置建立基线，从下一根收盘检测；暂停/重启不追发全部历史信号。每分钟检查，受上游出数时间影响。

同根多个信号合并。AI 只解释确定性计算结果，返回偏多/偏空/中性、依据和风险；有可用的高一档完整周期时附带背景，没有时明确缺失。永续合约没有股票流通股本换手率，使用真实成交额及相对成交额，不能把两种换手率混为一谈。不自动交易。

## Google Cloud 准备

1. 打开 [项目设置](https://console.cloud.google.com/iam-admin/settings)，或在控制台顶部的项目选择器查看 **项目 ID**；项目名称不是 ID。
2. 将该项目关联到 Developer Program 月度代金券所在的结算账号。核对 [代金券余额](https://console.cloud.google.com/billing/credits)。
3. 为项目启用 Vertex AI / Gemini 对应服务 `aiplatform.googleapis.com`。
4. 为 VPS 准备 Google Application Default Credentials（ADC）。可使用 Workload Identity Federation，或有 `roles/aiplatform.user` 权限的专用服务账号凭据。不要发送密钥到聊天，不放 Git，不复制到镜像。
5. 外部 VPS 使用 JSON 凭据时，将文件安全存放在仓库外，例如 `/opt/mirao-secrets/google-adc.json`，仅允许运行服务的管理员读取。使用下面的只读挂载覆盖配置。

当前项目为 `api-test-510819`，可直接使用以下入口：

- [启用 Vertex AI API](https://console.cloud.google.com/apis/library/aiplatform.googleapis.com?project=api-test-510819)。
- [创建服务账号](https://console.cloud.google.com/iam-admin/serviceaccounts?project=api-test-510819)：名称可用 `mirao-signals`，为此账号授予 **Vertex AI User**。新版页面可能显示为 **Agent Platform User**，认准角色 ID `roles/aiplatform.user`。[官方角色说明](https://docs.cloud.google.com/iam/docs/roles-permissions/aiplatform)
- 如果使用 JSON 密钥，在该服务账号的「密钥 → 添加密钥 → 创建新密钥」中选 JSON，下载后通过自己的 VPS 工具安全上传到上述仓库外路径。将文件权限设为仅管理员可读（例如 `chmod 600 /opt/mirao-secrets/google-adc.json`）。不要粘贴文件内容或把它上传至聊天/GitHub。如果组织禁止服务账号密钥，不绕过策略，使用 Workload Identity Federation。

参考：[Cloud 认证](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/gcp-auth)、[额度适用范围](https://developers.google.com/profile/help/benefits?hl=en)。

在 VPS 原有 `.env.production` 中追加配置，保留原有所有值：

```dotenv
GEMINI_ENABLED=1
GOOGLE_CLOUD_PROJECT=api-test-510819
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_MONTHLY_WARNING_USD=8.5
GEMINI_BUDGET_USERNAME=xingxinghuisi
GEMINI_MAX_CALLS_PER_DAY=100
GEMINI_CREDENTIALS_FILE=/opt/mirao-secrets/google-adc.json
```

`GEMINI_BUDGET_USERNAME` 必须是**已经存在并绑定 Telegram 的 MIRAO 账户**；这里的 `xingxinghuisi` 是当前部署操作示例。其他用户不会收到站主的费用提醒。凭据文件不通过网页上传；API 容器不需要读取它，只有信号 worker 挂载。

### 当前 VPS 首次启用

已上传到 `/opt/mirao-secrets/google-adc.upload.json` 的凭据，可以配合 `scripts/deploy-gemini.sh <已审阅的完整提交 SHA>` 首次启用。脚本适用于现有 `/opt/korea-market-radar` 的干净 `main` checkout：严格校验远端提交，备份配置和 SQLite，核对凭据项目与账号，构建候选镜像并验证数据库副本。

切换 API 前，脚本执行 `gemini_check.py --symbol KORUUSDT`，使用真实已收盘 K 线做一次 Gemini 连通性测试，并将返回用量记入原数据库。不会建立订阅或发送测试 Telegram。如果 Google 权限、结算或行情源失败，原 API 继续运行；相同快照不会自动重复付费测试。成功后只重建 API、启动信号 worker，现有行情、新闻、巨鲸与 OpenD 进程继续运行。切换失败会尝试恢复原 API 镜像和配置，保留实时数据库和费用记录。

脚本将本部署的费用接收账号设为 `xingxinghuisi`；必须已绑定 Telegram。检测到本地源码修改或已存在信号容器时会停止，避免覆盖。不要为绕过检查执行 `git reset --hard`。之后的日常更新使用下面的 Compose 命令。

取得当前新版代码、备份原数据库和部署配置后，在仓库根目录执行：

```sh
docker build -f Dockerfile.app -t korea-market-radar-app:latest app
docker compose --env-file .env.production -f compose.yaml -f compose.gemini.yaml config --quiet
docker compose --env-file .env.production -f compose.yaml -f compose.gemini.yaml run --rm --no-deps api python deployment_preflight.py
docker compose --env-file .env.production -f compose.yaml -f compose.gemini.yaml up -d --no-deps --force-recreate api signal_worker
docker compose --env-file .env.production -f compose.yaml -f compose.gemini.yaml logs --since=5m --tail=30 signal_worker
```

此后更新 `signal_worker` 时始终带 `-f compose.gemini.yaml`，否则只读凭据挂载会丢失。API 启动只新增 `technical_signal_states`、`gemini_analyses`、`ai_budget_notices`，不修改旧表。不运行 `init_db.py`。

## 费用与 8.5 美元提醒

**本项目即时估算**：每次返回的 `usageMetadata` 记录输入、缓存输入、输出与思考 Token，按当时支持模型的公开标准 Global 文本单价计算，保存整数纳美元。默认 Gemini 3.1 Flash-Lite 单价为每百万输入 $0.25、输出含思考 $1.50；缓存输入 $0.025，核对日期 2026-10-12。新增模型必须更新单价表，不能无价格地继续调用。3.8 Flash 使用促销抵扣前标准价，避免假设额外返券能与月度赠额叠加。[官方价格](https://cloud.google.com/vertex-ai/generative-ai/pricing)

- 按美国太平洋时间的自然月统计，与 Google Cloud 月度预算对应；界面写明月份口径。
- 达到或超过 $8.50，发给费用负责人一次 Telegram 提醒，并保留站内通知；失败的发送下轮重试，重启不重复正常已发送的提醒。下月独立计算。
- **8.5 美元是提醒线，不是停机线。** 提醒后继续服务。全体用户共用默认每天 100 次 AI 请求上限；达到后只发送确定性技术信号，避免无限付费调用。
- 相同公开快照复用分析，先持久化请求键再调用。模型超时、断线或崩溃造成结果不明时，不自动重试付费请求；UI 显示未核实请求数，费用不明不能显示为已确认免费。
- 截断或解析失败但返回用量的请求仍记费。纯文本调用，不启用搜索、地图、工具、显式缓存存储等额外收费能力。
- 估算不是实际账单或代金券余额，只覆盖本项目；其它应用/Cloud 服务消费、税费、结算币种转换和抵扣差异不在其中。
- Telegram 发送超时后可能出现结果不明；已提交的 pending 不自动重发，避免重复。这与现有通知的幂等边界一致。

**Google 实际账单通知（可选连接，建议同样设置）**：

1. 在 [Cloud Billing 预算](https://console.cloud.google.com/billing/budgets) 创建 USD 月度预算，金额 $10，实际用量阈值 85%。
2. 选择该项目和 Vertex AI 服务；如果要监控整笔共享赠额的所有 Cloud 消费，则改为整个结算账号。选择**不计入抵扣额度（排除所有 credits）**，否则 $10 赠额抵扣后，净账单 $0 会掩盖额度消耗。
3. 将预算通知发到 Pub/Sub topic，创建 pull subscription，只给信号服务账号该订阅的 `roles/pubsub.subscriber`。
4. 配置以下两项并重建 `signal_worker`：

```dotenv
GEMINI_BILLING_SUBSCRIPTION=projects/api-test-510819/subscriptions/mirao-billing
GEMINI_BILLING_BUDGET_ID=the-budget-uuid
```

worker 使用 Google OAuth 拉取，严格匹配预算 UUID、USD、本月 `costIntervalStart`，按实际 `costAmount >= 8.5` 发 Telegram，忽略纯预测告警和其他预算。无需开放接收账单的公共 webhook。成功投递才 ack，失败由 Pub/Sub 重投并由数据库去重。实际账单与 Token 估算各自标明来源，每月每个来源最多一次正常提醒。Google 账单可能延迟，预算提醒也不是硬性消费上限。[官方预算通知格式](https://docs.cloud.google.com/billing/docs/how-to/budgets-programmatic-notifications)

## English

Adds account-owned Binance USD-M closed-candle technical subscriptions, optional Gemini interpretation through Google Cloud, and a persistent $8.50/month Telegram usage warning. Existing price/news/whale workflows remain compatible. Supported signals include RSI, MACD, configurable MA/EMA, KDJ, relative quote volume, user-anchored Fibonacci levels, and confirmed RSI divergence.

AI is opt-in. Configure a billed Cloud project, ADC credentials mounted read-only, and the existing MIRAO account receiving budget warnings. Paid requests are reserved before generation, shared by identical public snapshots, and never automatically retried after ambiguous failures. Usage estimates include thinking tokens and survive restarts. The warning does not stop service; a separate shared daily request cap preserves deterministic signals when exhausted.

An optional authenticated Pub/Sub pull integration forwards actual Cloud Budget cost reports. Configure a USD monthly budget excluding credits, the intended project/service or billing-account scope, and the expected budget UUID. Estimates, actual billed usage, and remaining promotional credit are distinct. No production credentials or live paid requests are included in automated tests.
