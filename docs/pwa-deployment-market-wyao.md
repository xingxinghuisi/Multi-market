# market.wyao.cc 的 PWA 上线准备

此文档适用于现有 Docker Compose 服务和已经配置 HTTPS 的 Nginx。它是部署操作清单，不会自动修改服务器或现有数据库。先在服务器备份 `app/data/market_radar.db` 与现有环境配置，再更新镜像。

## 1. 环境配置

在服务器的仓库根目录现有 `.env.production` 中增加或确认以下变量。不要把该文件提交到 Git：

```dotenv
RADAR_PUBLIC_ORIGIN=https://market.wyao.cc
RADAR_WORKER_TOKEN=<用安全随机数生成的长字符串>
```

正式环境不要设置 `RADAR_ALLOW_HTTP_LOCAL=1`。`RADAR_PUBLIC_ORIGIN` 必须与用户实际打开的页面 Origin 完全一致，不带结尾斜杠。`RADAR_WORKER_TOKEN` 需要由 API 和新闻 worker 共享；现有 Compose 的两项服务都读取同一 `.env.production`。新闻 worker 在 Compose 中固定访问 `http://api:8000`，不会误连自己的 `localhost`。

保留现有行情、Telegram、Groq、Moomoo 等变量。Compose 的 `${MOOMOO_LOGIN_ACCOUNT}` 是在读取 Compose 文件时展开的，因此执行 Compose 命令时必须加 `--env-file .env.production`，或通过服务器已有方式提供它。

## 2. Nginx

在 `market.wyao.cc` **现有的 HTTPS server 块**中，让以下 location 指向宿主机的本地端口。请与现有 location 合并，不要替换证书、其他站点或全局配置：

```nginx
location /ws/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}

location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

公开注册之前，在 Nginx 的 `http` 上下文添加独立限流区（如果现有配置已有等效限流，可沿用）：

```nginx
limit_req_zone $binary_remote_addr zone=radar_register:10m rate=2r/m;
limit_req_zone $binary_remote_addr zone=radar_login:10m rate=10r/m;
```

在同一 HTTPS server 块添加精确路径规则。精确规则会覆盖上面的通用 `location /`，因此必须各自转发到 API：

```nginx
limit_req_status 429;

location = /api/auth/register {
    limit_req zone=radar_register burst=4 nodelay;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
}

location = /api/auth/login {
    limit_req zone=radar_login burst=10 nodelay;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
}
```

应用内已有每进程限流，服务重启会清空计数，因此不能替代边缘限流。若已有全局反向代理规则，先确认它们不会覆盖 WebSocket Upgrade、Host 和 HTTPS 转发头。运行 `nginx -t` 通过后再 reload。

## 3. 构建与启动

在服务器仓库根目录执行，沿用现有数据卷：

```sh
docker build -f Dockerfile.app -t korea-market-radar-app:latest app
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production run --rm --no-deps api python deployment_preflight.py
docker compose --env-file .env.production up -d api market_worker crypto_metrics_worker whale_print_worker news_worker
```

`app/.dockerignore` 会把本机数据库排除在镜像构建上下文之外。Compose 仍挂载 `./app/data:/app/data`，已有数据库会保留。新认证表在 API 启动时单独创建；请先完成备份。既有 `default` 账户不会自动分配给任何新注册者。如果需要继续访问原有关注和提醒，备份后在服务器交互式执行 `docker compose --env-file .env.production exec api python claim_default_account.py` 为它设置密码。

多空/巨鲸订阅升级还会自动新增 `alert_subscriptions` 与 `subscription_deliveries` 表，保留原有账户、行情、价格规则和通知。API 与两个订阅 worker 必须一起更新并使用相同的 `RADAR_WORKER_TOKEN`。详细操作与投递边界见 [推送订阅说明](push-subscriptions.md)。不要重新初始化生产数据库。

## 4. 上线验收

1. 在手机 Safari 打开 `https://market.wyao.cc/`，确认没有证书警告，注册新账户后可退出并重新登录。
2. 确认关注、提醒、通知只出现在各自账户；无 Telegram 绑定的新账户只收站内通知。
3. 观察行情时间戳、新闻更新时间以及合约指标；没有数据时页面应显示不可用状态，不能把目录资产当作实时价格。
4. 检查浏览器中的市场 WebSocket 已连接，Nginx/API/worker 日志无连接或鉴权错误。
5. 在 Safari 使用“添加到主屏幕”，从图标启动后检查导航、登录保留和页面安全区域。

尚未完成密码找回、Telegram 自助绑定、边缘限流的实际配置和 iPhone 真机验收。在这些完成前，先不要向公众宣布开放。
