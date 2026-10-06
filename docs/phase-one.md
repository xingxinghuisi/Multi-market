# 第一阶段：浅色移动端与 PWA

这是第一阶段的历史记录；后续真实合约指标见 [pwa-data-phase-two.md](pwa-data-phase-two.md)。

## 仓库审计

- 当前 GitHub `main` 有根目录和 `app/` 两套代码，`app/` 包含较新的新闻 API、采集与分析功能。本次仅扩展 `app/`，根目录历史实现保留。
- API 为 FastAPI，模型为 SQLAlchemy，当前数据库为 `app/data/market_radar.db`（SQLite），并非 PostgreSQL。
- 前端为原生 HTML / CSS / JavaScript，无需 Node 构建。旧页面是同屏工作台。
- Binance Spot / Futures、Moomoo、KRX provider、价格提醒与 Telegram 服务已经存在。韩股快速新增接口明确返回不可用，故新版仅支持关注库内韩股。
- 关注与提醒创建使用 `username=default`；没有登录、注册、密码或 session 接口。现有提醒列表也未按用户隔离。
- 当前仓库未发现 crypto metrics API / 数据模型。不会按示意图补造资金费率、OI、多空比、财务估值或指数报价。
- `Notification` 模型存在，但原来没有通知列表接口。

## 本次实现

- 新默认首页 `app/web/mobile.html`；原 `index.html`、`app.js`、`style.css` 原样保留，经 `/legacy` 访问。
- 浅色卡片、玻璃底部导航、手机安全区、宽屏双栏、键盘焦点、减少透明度 / 动画偏好兼容。不将网页玻璃效果声称为原生 iOS API。
- 页面进入时的轻柔位移与层次渐现、底部玻璃选中块的弹性滑动、按钮按压回弹、提示浮现及真实历史曲线首次绘制。实时行情刷新不重复播放页面入场动画；系统选择减少动态效果时禁用这些动画。
- 首次进入 / 账户能力说明、市场总览、关注、资产详情、添加资产、创建提醒、提醒管理、通知、新闻、设置及个人中心。
- 资产使用 ID 和 `venue + segment + symbol` 区分，Spot 与 Futures 不合并。
- 图表只绘制后端提供的日收盘价；范围明确为最近 30 个交易日，提供可访问的数据表。没有分钟 K 线时不提供虚假的 1D / 1W 切换。
- 详情显示报价时间、涨跌基准与时区，股票展示已有盘前 / 常规 / 盘后 / 隔夜字段。数据缺失用破折号或说明呈现，零值正常显示。
- 原 WebSocket 首次快照和增量行情都可读取；定时 HTTP 刷新兜底。可保存 15 / 30 / 60 秒刷新偏好；失败、空列表和离线状态有提示。
- 关注增删、价格突破 / 下破 / Step 提醒创建、暂停 / 启用 / 删除使用原有接口。取消关注不悄悄删除现有提醒规则。
- 新闻外链限制 HTTP(S)，外部文本转义后显示；表单保存期间阻止重复提交。
- PWA manifest、192 / 512 图标、Service Worker。仅缓存公开页面和静态资源，不缓存 API、行情、通知、账户信息或写请求；不支持离线写入或原生推送。

## 接口映射

| 页面 | 接口 |
| --- | --- |
| 首页 / 关注 | `GET /api/assets`, `/api/market/latest`, `/api/watchlist`; `/ws/market` |
| 关注操作 | `POST /api/watchlist`, `DELETE /api/watchlist/{asset_id}` |
| 详情 | `/api/assets/{id}`, `/api/market/latest/assets/{id}`, `/api/market/history/assets/{id}`, `/api/assets/{id}/news` |
| 资产搜索 / 添加 | `/api/assets/search`, `POST /api/assets/quick` |
| 提醒管理 | `/api/alert-rules`, `PATCH / DELETE /api/alert-rules/{id}` |
| 新闻 | `/api/news`，显示现有分析来源，不推测情绪 |
| 通知 | 新增只读 `GET /api/notifications?limit=100&before_id=...`，筛选默认用户，最多 200 条 |
| 账户 / 设置 | 新增只读 `GET /api/client-profile`，返回能力与 Telegram 接收目标配置状态，不返回 chat ID 或密钥 |

没有迁移数据库，没有修改行情采集、新闻分析、提醒引擎或 Telegram 发送流程。新增路由集中在 `app/mobile_api.py`。

Moomoo SDK 调整为按需导入，仍使用原 provider。其导入时会创建日志文件，按需加载避免没有 OpenD 本机环境时连带阻断其他市场与网页启动。

## 验证记录

- Python 测试：10 项通过（既有引擎 / provider 测试及新增 API 契约测试）；使用独立内存数据库。
- 前端：9 项通过，包括核心格式化、资产类型、提醒参数、时间解析，以及 Service Worker 缓存范围与离线回退。
- 手机浏览器：390 × 844，检查总览、关注、新闻、提醒、通知、个人中心、账户说明、添加资产、股票与 Spot 详情，无横向溢出；实测关注 → Step 提醒创建 → 暂停，以及刷新设置保存后重新加载。
- 桌面浏览器：1280 px 宽度检查市场双栏、底部导航和横向溢出；没有发现溢出。
- 自动 Playwright 脚本保留供本机 / CI 复跑；本环境的子进程管道权限阻止了它启动浏览器，因此实际交互改用应用内浏览器验证，不将整套脚本标注为已通过。
- 仍有原 FastAPI `on_event` 和测试客户端依赖的弃用警告；本轮不扩大后端生命周期改造范围。
- 生产行情源、新闻 worker、Telegram 送达、iPhone 真机安装和后台推送不在本机验证结果内。

## 当前边界和下一阶段

1. **开放少量用户前必做**：认证、会话安全、所有读写接口的用户隔离（包括 WebSocket）、接口权限、限流与部署访问控制。仅添加登录 UI 不能解决这些问题。
2. 找回 / 合并用户提到的 crypto metrics 实现，再以真实 schema 接入资金费率、OI、多空比。本阶段明确说明不可用。
3. 在已有运行环境验证真实 Binance / Moomoo / KRX 连接、新闻采集和 Telegram 送达；API 本机验证不能替代上游授权与网络测试。
4. 评估通知已读状态、分页 UI、用户自助绑定 Telegram、PWA 推送；这些都需要新增服务端能力。
5. 整理两套代码的部署入口，后续再清理历史副本，避免与第一阶段 UI 变更一起大规模迁移。

源文件和测试可提交；`.env`、数据库、日志、虚拟环境、测试输出和临时安装文件均应留在忽略列表内。
