# PWA 自动更新 / Automatic PWA updates

## 本次修复

线上版本接口立即返回新版本，但脚本及 Service Worker 响应曾携带四小时 HTTP 缓存。旧脚本刷新后仍可能拿到旧脚本，原先不限制刷新次数，造成循环跳转。

- HTML 使用 `Cache-Control: no-cache`；入口 CSS、JavaScript、所有模块导入和 SW 注册 URL 均携带同一发布版本号。
- Service Worker 对公开资源重新核验 HTTP 缓存，只缓存精确列入清单的公共资源；API、账户、行情、通知及其他查询参数仍不进入离线缓存。
- 首次接管页面只检查实际版本，不因 `controllerchange` 无条件刷新。
- 同一目标版本最多自动尝试一次；十分钟内跨页面最多两次，防止混合版本后端引发振荡。通过 sessionStorage 持久记录；存储不可用时使用 URL 标记作为备用保护。
- 保存请求、表单操作期间延后更新；持续版本不一致时停止重复刷新并提示，页面仍可使用。返回前台时继续检查版本。

该修复通过旧页面 / 新版本接口的真实浏览器回归，包含首次安装、存储被禁用、保存订阅时更新。上线仍需重建镜像并更新 API；普通 `git pull` 不会替换运行中的容器。仅部署本修复不需要重启行情、Telegram 或 OpenD 服务；若同时升级动态巨鲸目录，还需更新 `whale_position_worker`。

发布新版本时，保持 `web/version.txt`、`mobile.js`、`mobile.html`、模块导入与 `sw.js` 的版本一致，并更新 SW 缓存名称。`app-update.test.mjs` 检查发布版本一致性。

## English

The version API could report a new build while HTTP caches retained an older JavaScript bundle for four hours. Repeated reloads then fetched the same stale bundle. Entry assets, module imports and worker registration now use release-version URLs, the document requests revalidation, and the worker revalidates its explicit public shell cache. Private API responses remain uncached.

Controller changes check the actual build version instead of forcing a reload. Automatic attempts are persisted and bounded: one per target, at most two within ten minutes. URL markers provide a fallback when sessionStorage is unavailable. Updates wait for writes and active forms; persistent mismatches stop refreshing and leave the current page usable. Browser regressions cover first installation, stale bundles, blocked storage and updates during subscription writes.
