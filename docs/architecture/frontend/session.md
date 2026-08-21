# 浏览器前端启动与会话

## 启动顺序

`src/app/bootstrap.ts` 按固定顺序完成：

1. 读取 runtime config。
2. 创建 Vue、Pinia 和 Router。
3. 初始化本地偏好与 i18n。
4. 配置统一 HTTP client 的 token、refresh 和 unauthorized 回调。
5. 注册路由守卫。
6. Router ready 后挂载应用。

开发态 runtime config 位于 `frontend/web-ui/public/`；发行包由 `assemble-release` 复制构建结果并确保 `frontend/runtime-config.json` 存在。

## 会话状态机

`session.store.ts` 使用以下状态：

- `checking`
- `auto-authenticated`
- `authenticated`
- `manual-login-required`
- `offline`
- `failed`

初始化流程：

1. 无凭据读取 `/system/bootstrap`，确认后端与鉴权模式。
2. 存在“需要手工登录”标记时直接进入登录页。
3. 优先恢复浏览器中的 session token 与 refresh token。
4. 恢复失败后，在 runtime config 允许自动登录时尝试 user token。
5. 所有自动方式失败后进入手工登录。

默认本地用户名为 `amvar`。默认 user token 与是否启用自动登录由 runtime config 决定；生产交付应按现场策略替换默认凭据。

## 凭据语义

| 凭据 | 用途 | 浏览器行为 |
| --- | --- | --- |
| session token | 用户名密码登录后的管理会话 | 保存到配置指定的浏览器存储；到期可使用 refresh token |
| refresh token | 刷新 session | 仅随 session 使用 |
| user token | 本地工作站自动进入、SDK 或长期集成 | 不调用 session logout；退出时只清理本地引用 |
| static bearer | 受控部署兼容入口 | 由后端 bootstrap 和 runtime config 决定是否可用 |

HTTP 401 先走统一 refresh；refresh 失败时清理鉴权状态并转到登录流程。WebSocket 只在后端 bootstrap 声明允许时使用 query token。

## 退出

显式退出会：

1. session 凭据存在时调用后端 logout。
2. 清理浏览器保存的 session、refresh 和 user token 引用。
3. 写入“需要手工登录”标记。
4. 返回登录页。

user token 本身不会因为前端退出而被撤销。撤销长期 token 必须通过后端用户/token 管理接口完成。

## 路由守卫

- 无需鉴权的页面：Startup、Login、Forbidden、Offline、NotFound。
- 业务路由默认要求已初始化会话。
- `requiredScopes` 必须全部满足；前端只负责导航门禁，后端负责最终授权。
- 后端离线时显示 Offline，而不是把连接失败误报为未登录。

相关接口见 [本地鉴权 API](../../api/local-auth.md)，启动命令见 [开发环境启动](../../deployment/development-environment.md)。
