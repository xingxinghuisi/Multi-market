# 第三阶段：开放注册和账户隔离

## 本轮完成

- 开放用户名 / 密码注册，支持登录和退出。用户名规范化为小写，密码要求 12–128 个字符；密码用带独立随机盐的 scrypt 哈希存储，不保存明文。
- 会话令牌由服务端随机生成，数据库只保存其 SHA-256 摘要；浏览器使用 HttpOnly、SameSite=Strict Cookie，正式域名启用 Secure。写操作需要会话内的 CSRF 值。账户接口返回 `Cache-Control: no-store`。
- 注册与失败登录按来源地址设置基础的进程内尝试限制。正式部署还需要反向代理 / 网关层的跨进程限流。
- 关注、提醒、通知与资料以当前会话用户为准；其他用户的提醒 ID 查询、修改、删除返回 404。WebSocket 行情连接也验证会话。系统级资产与新闻修改接口只允许带服务令牌的可信后台调用。
- 新闻 worker 通过受服务令牌保护的接口获取所有用户已启用新闻的资产，并去重后采集。新闻和价格通知按用户归属保存；新用户没有 Telegram 接收目标时只生成站内记录，绝不发往旧的全局 Telegram 目标。旧 `default` 用户可继续使用原全局目标。
- 旧 `default` 工作区不会被注册者自动领取。仓库新增交互式 `claim_default_account.py`，由运维在核对数据库备份后运行并输入密码；此脚本本轮未在真实数据库上执行。
- 认证表是独立新增的 `user_credentials` 与 `user_sessions`。应用正常启动时只对这两张表执行 `create_all(checkfirst=True)`；不修改既有表字段。内存预览关闭生命周期并单独建表，不写业务数据库。

## 部署配置

- **必须 HTTPS**：生产 Cookie 始终 Secure；`RADAR_ALLOW_HTTP_LOCAL=1` 只供本机 HTTP 调试，正式环境不得设置。
- `RADAR_PUBLIC_ORIGIN`：若反向代理使应用识别到的外部 Origin 不正确，可设置为实际 HTTPS Origin，例如 `https://radar.example.com`。不要填带路径的地址。
- `RADAR_WORKER_TOKEN`：API 与 `news_worker` 使用同一个高熵随机值，通过部署环境注入，不提交到 Git。缺少它时新闻 worker 受保护的调用会被拒绝；这比匿名运行后台修改接口安全。
- 既有生产数据库首次升级前备份。不要重新运行仅供首次初始化的 `init_db.py`；正常启动会添加认证表。需要领取旧工作区时再单独运行领取脚本。

## 尚未具备的上线条件

- 密码找回 / 邮箱验证 / 自助修改密码、Telegram 用户自助绑定和 iOS Web Push 未实现。当前只开放用户名注册，因此用户忘记密码需要人工运维流程。
- 进程内限流不覆盖多实例；开放公网前需在入口层限制注册、登录及资产快速添加请求，并配置访问日志、备份和恢复演练。
- 还需在实际部署环境验证新闻 worker 服务令牌、Binance / Moomoo / KRX 行情、Telegram 送达、HTTPS Cookie、WebSocket，以及 iPhone Safari 安装与弱网恢复。
- 本轮仅在隔离内存数据库验证两账户隔离、CSRF、服务令牌及新用户通知不会误发给旧 Telegram。没有推送 GitHub 或发布公网实例。
