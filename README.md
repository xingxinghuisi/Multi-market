# MIRAO（原 Korea Market Radar）

移动端 / PWA 位于 **`app/`**。根目录还保留一套较旧的 API 和网页；从根目录执行 `uvicorn api:app` 会启动旧版本。当前方向是先在 iPhone 主屏幕发布 PWA，之后再考虑 App Store。

## 本地运行

Python 3.13；建议使用虚拟环境。PowerShell：

```powershell
cd app
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python init_db.py
$env:RADAR_ALLOW_HTTP_LOCAL="1"
.\.venv\Scripts\python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/`。新版为默认首页，旧工作台在 `/legacy`。
`init_db.py` 仅适用于首次初始化；保留现有生产数据库时不要重复初始化或覆盖数据。
初始化包含既有资产与默认提醒，不会生成模拟报价。行情、新闻及 Telegram 发送继续由现有 worker 和服务端配置负责。仅运行 API 时，页面可操作，数据以数据库中已有记录为准；Binance 合约详情的公开指标按需从上游读取。

现在支持开放注册、用户名密码登录、退出，以及关注、提醒、通知的账户隔离。密码以 scrypt 哈希保存；会话使用 HttpOnly、SameSite=Strict Cookie，正式域名只发 Secure Cookie。`RADAR_ALLOW_HTTP_LOCAL=1` 仅用于本机 HTTP 调试，正式部署不要设置。旧数据库中的 `default` 用户不会自动归给新注册者；确认备份后，运行 `python claim_default_account.py`，在交互提示中为旧工作区设置密码，再以 `default` 登录。PWA 的外观可在设置中选择跟随系统、浅色或夜间；导航使用具有降级样式的透明玻璃效果，尊重减少动态效果与减少透明度偏好。

资产目录的“删除资产”只从当前账户移除，并暂停该资产的个人提醒；共享行情资产及其他用户不受影响。可在“添加资产”中重新加入。Telegram 设置支持通过 Chat ID 接收验证码并绑定个人目标，也可发送测试消息；旧 `default` 账户继续显示服务器默认目标。移动端每次回到前台会检查行情与版本，报价原位更新，避免整页闪动。

## 部署上下文

「提醒 → 推送订阅」支持按币种管理 1H 多空播报和巨鲸大额聚合成交提醒，独立设置阈值与间隔。合约详情显示完整周期多空数据，两类事件统一进入个人通知中心与已绑定的 Telegram。订阅不修改行情采集开关。升级方式和数据边界见 [推送订阅说明](docs/push-subscriptions.md)。

现有 `Dockerfile.app` 需要 `requirements.txt`；该文件仅在 `app/` 中存在，因此应用镜像必须使用 `app/` 作为构建上下文。例如：

```powershell
docker build -f Dockerfile.app -t korea-market-radar-app:latest app
```

保留现有 Compose 的环境与数据卷配置。移动 PWA 安装需要 HTTPS；开发时 `localhost` 例外。新闻采集器现在通过服务专用接口聚合各账户关注的资产；API 与 `news_worker` 必须共享环境变量 `RADAR_WORKER_TOKEN`（随机生成、只放进部署环境，不提交仓库）。现有新账户未绑定 Telegram 时，提醒保留为站内记录，不发送到旧的全局 Telegram 目标。

`market.wyao.cc` 已用于现有 Docker / Nginx 部署；每次更新仍应核验线上数据链路、备份与回滚。密码找回、跨进程限流与 iPhone 真机联调仍待完善；开放注册代码完成不等于可以不经验证直接大规模推广。

## 验证

```powershell
cd app
.\.venv\Scripts\python -m pip install pytest httpx
.\.venv\Scripts\python -m pytest tests -q
node --test --test-isolation=none tests/mobile-core.test.mjs
node --test --test-isolation=none tests/service-worker.test.mjs
node --check web/static/mobile.js
node --check web/sw.js
```

前端没有构建步骤或新增运行时框架。浏览器验证脚本在 `app/tests/browser_mobile.py`；需要 Playwright 和 Chromium，使用独立内存测试数据库，不连接实际行情源或发送 Telegram。

不写业务数据库的界面预览（无需 Playwright）：在 `app/` 下运行 `python tests/browser_mobile.py --preview`，打开终端打印的本机地址。可在预览里注册临时账户；此模式加载项目资产目录和一条用于检查合约布局的 BTCUSDT 合约目录项，没有模拟报价，也不读取外网合约指标。账户、关注与提醒都只保存在内存中，退出即清空。

详情与接口清单见 [docs/phase-one.md](docs/phase-one.md)、[docs/pwa-data-phase-two.md](docs/pwa-data-phase-two.md) 和 [docs/pwa-accounts-phase-three.md](docs/pwa-accounts-phase-three.md)。`market.wyao.cc` 的现有 Nginx / Docker 上线步骤见 [docs/pwa-deployment-market-wyao.md](docs/pwa-deployment-market-wyao.md)。
