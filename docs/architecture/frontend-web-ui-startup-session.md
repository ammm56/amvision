# 浏览器前端启动和会话规划

## 文档目的

本文档用于定义浏览器前端 Web UI 的启动、默认本地用户、长期 user token、登录页出现条件、退出语义和会话状态管理，为后续实现 `app/bootstrap.ts`、`session.store.ts`、`platform/auth` 和 `AuthShell` 提供规则。

[local-auth.md](../api/local-auth.md) 说明后端本地用户、登录会话、refresh token 和长期调用 token 接口。[frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md) 说明 runtime config、存储策略、权限映射、测试和发布接入的开工检查。本文档只说明前端如何使用鉴权能力。

## 适用范围

- standalone、workstation 和 edge 本地部署形态的默认登录体验
- 前端首屏启动和后端连接检查
- 默认 `amvar` 用户与长期 user token 的前端使用方式
- 登录页、退出、重新进入和 token 失效处理
- session store、auth guard、HTTP client 和 WebSocket client 的鉴权接入
- 后续在线账号 provider 的预留边界

## 设计结论

- 本地部署默认不显示登录页，启动后应直接进入 Workbench。
- 默认本地用户是 `amvar`，后端空库首次启动会自动写入该用户、默认密码和默认长期 user token。
- 前端本地部署默认使用长期 user token 建立工作台会话，不强制先走用户名密码登录。
- 只有用户明确执行退出、默认 token 缺失、默认 token 被撤销、后端不再接受默认 token，或当前 auth mode 不支持自动进入时，才显示登录页。
- 显式退出不会撤销长期 user token。退出只清理前端当前凭据和本机浏览器状态，并记录“需要手动登录”的本地标记。
- 用户在登录页使用 `amvar` 和密码登录成功后，前端使用短期 session token 和 refresh token 维持人工会话。
- 长期 user token 适合本地工作站自动进入、外部系统调用、WebSocket 和 SDK；短期 session token 适合人工登录后的管理操作。

## 默认本地用户体验

真实本地生产环境中，默认用户和默认长期 user token 仍存在。前端启动体验按下面规则处理：

1. 打开 Web UI。
2. 显示 `StartupView`，进行后端连接检查和 bootstrap 读取。
3. 如果本地没有“已退出”标记，前端读取本地部署提供的默认 user token。
4. 前端用该 token 调用 `GET /api/v1/system/bootstrap` 或 `GET /api/v1/system/me`。
5. 如果返回主体有效，且用户名为 `amvar` 或符合当前环境配置，直接进入 Workbench。
6. 如果 token 无效、后端不可用或权限不足，进入 AuthShell。
7. 用户明确退出后，再次打开 Web UI 时进入 AuthShell，不再自动使用默认 user token。

这条规则的目标是让现场工作站像本地软件一样开箱即用，同时保留退出后的人工登录路径。

## 默认 token 来源

前端代码仓库不应把长期 user token 写死在业务源码里。默认 token 应通过部署时运行配置注入，例如：

- standalone launcher 生成的前端 runtime config。
- backend-service 随静态资源一起提供的本地 runtime config。
- 发布包内仅本机可读的配置文件，由启动器复制到前端静态目录。

建议前端读取顺序：

1. 浏览器本地保存的短期 session token。
2. 浏览器本地保存的长期 user token。
3. 本地 runtime config 提供的默认 user token。
4. 无可用凭据时进入登录页。

默认 token 只作为本地部署初始体验。若现场修改或撤销默认 token，前端应自动退回登录页，不提示使用旧 token。

## 启动状态机

```text
app start
  ↓
load runtime config
  ↓
GET /api/v1/system/bootstrap without token
  ↓
choose credential
  ↓
GET /api/v1/system/me or bootstrap with Bearer token
  ↓
valid credential ───────→ WorkbenchShell
  ↓ invalid
AuthShell
```

### StartupView

`StartupView` 只负责启动检查，不承担登录表单。

显示内容：

- 后端连接状态
- 当前 auth mode
- Project bootstrap 状态
- 默认自动进入是否可用
- 失败原因摘要

进入 Workbench 后，StartupView 不应长期保留。

### AuthShell

`AuthShell` 只在需要人工介入时出现。

出现条件：

- 用户明确点击退出。
- 当前浏览器记录了 `manual_login_required=true`。
- 默认 user token 不存在或校验失败。
- 后端返回 401 或 403，且 refresh 无法恢复。
- 后端 `auth_mode` 不是前端支持的自动进入模式。
- 当前环境禁用了默认用户自动进入。

登录页默认填入用户名 `amvar`，但不应默认填入密码。密码字段保持空白。

### WorkbenchShell

`WorkbenchShell` 是正常首屏。进入后顶部栏显示：

- 当前 Project
- 后端连接状态
- 当前用户显示名或 username
- 凭据类型：session 或 user-token
- 退出入口

默认 user token 进入时，顶部栏可以显示“本地默认用户”一类的中性提示。提示不应阻塞操作。

## 凭据类型和前端行为

| 凭据类型 | 来源 | 前端用途 | 续期方式 | 退出行为 |
| --- | --- | --- | --- | --- |
| session token | login / refresh | 人工登录后的管理会话 | refresh token | 调用 logout，清理 session 和 refresh |
| refresh token | login / refresh | session 续期 | refresh 接口轮换 | 随 session 一起清理 |
| user token | 默认 seed 或用户管理接口 | 本地自动进入、外部调用、WebSocket | 默认不续期 | 不能调用 logout，只清理前端本地引用 |
| static bearer | 特殊配置 | 兼容静态 token 模式 | 无 | 清理前端本地引用 |

重要规则：

- `POST /api/v1/auth/logout` 只接受登录会话 token，不接受长期 user token。
- 当前凭据是 user token 时，前端退出只做本地退出，不调用后端 logout。
- 退出后必须写入本地 `manual_login_required=true`，避免下次启动又自动使用默认 user token。
- 人工登录成功后清除 `manual_login_required`。
- 若用户在设置中选择“恢复本地默认自动进入”，前端可以清除 `manual_login_required`，并重新尝试默认 user token。

## session.store.ts 规划

`session.store.ts` 保存应用级会话摘要，不保存业务资源状态。

建议字段：

- `authMode`
- `bearerAuthEnabled`
- `currentUser`
- `credentialKind`
- `accessToken`
- `refreshToken`
- `tokenExpiresAt`
- `refreshExpiresAt`
- `manualLoginRequired`
- `defaultAutoLoginAvailable`
- `loginState`
- `lastAuthError`

`loginState` 建议取值：

- `checking`
- `auto-authenticated`
- `authenticated`
- `manual-login-required`
- `offline`
- `failed`

本地存储建议：

- session token 和 refresh token 可放入 `sessionStorage` 或受控 local storage，具体策略由 `platform/storage` 统一封装。
- default user token 不复制到多个业务 store。
- `manualLoginRequired` 可以放入 localStorage，使刷新页面和重开浏览器后仍保留退出意图。
- 所有 token 不写入日志、错误上报、URL 和 WebSocket message payload。

## HTTP client 和 WebSocket client

HTTP client：

- 每次请求从 `session.store.ts` 读取当前 access token 或 user token。
- 401 时，如果当前凭据是 session token 且存在 refresh token，先尝试 refresh。
- refresh 成功后重试原请求。
- refresh 失败或当前凭据是 user token 时，清理当前凭据并进入 AuthShell。
- 403 不自动登录，页面显示权限不足。

WebSocket client：

- 默认通过 Authorization header 或后端支持的 query token 传入当前 token。
- token refresh 后应重建连接。
- 401/close 触发会话恢复流程。
- user token 不需要 refresh，但被撤销后应回到 AuthShell。

## 路由守卫

路由守卫只判断前端是否有有效主体和必要权限摘要，不自行判断业务资源是否可操作。

规则：

- `/` 默认进入启动流程，成功后跳转默认工作台路由。
- 登录、启动和错误页使用 `BlankShell` 或 `AuthShell`。
- 业务页面都经过 `WorkbenchShell`。
- 未认证访问业务路由时，跳转 AuthShell。
- 已认证访问登录页时，跳转 Workbench。
- 当前用户缺少必要 scope 时，进入权限不足视图或禁用对应入口。

## 退出和重新进入

### 退出流程

1. 用户点击顶部栏退出。
2. 前端检查当前 `credentialKind`。
3. 如果是 `session`，调用 `POST /api/v1/auth/logout`。
4. 如果是 `user-token`，不调用 logout。
5. 清理内存 token、sessionStorage、运行中的 WebSocket 连接和页面查询缓存。
6. 写入 `manualLoginRequired=true`。
7. 跳转 AuthShell。

### 再次进入

- 如果 `manualLoginRequired=true`，直接显示登录页。
- 登录页默认用户名为 `amvar`。
- 登录成功后保存 session token 和 refresh token，清除 `manualLoginRequired`。
- 如果登录失败，保留 AuthShell 并显示错误摘要。

### 恢复自动进入

设置页可提供“恢复本地默认自动进入”动作。该动作只清理前端的 `manualLoginRequired` 标记，不重置后端用户、密码或 token。

## 用户管理页面

第一阶段可以把用户管理放在 Settings 模块。

建议页面：

- 本地用户列表
- 当前用户详情
- 修改密码
- 长期 user token 列表
- 签发新 token
- 撤销 token
- auth events 实时观察

重要边界：

- 长期 user token 明文只在签发时显示一次。
- 删除默认 token 后，当前浏览器可能无法继续自动进入。
- 修改 `amvar` 密码不影响已有长期 user token。
- 撤销当前正在使用的 user token 后，前端应回到 AuthShell。
- 普通操作页不应展示默认 token 明文。

## 本地生产安全提示

本地部署默认开箱即用，但前端实现仍应保留下面能力：

- 支持修改默认密码。
- 支持撤销或轮换默认长期 user token。
- 支持禁用默认自动进入。
- 支持查看当前凭据类型和用户。
- 支持权限不足时清楚提示，而不是反复回到登录页。
- 支持后续在线账号 provider 接入，而不重写整个启动流程。

这些能力不改变默认自动进入体验，只为现场安全加固和后续在线形态预留空间。

## 当前规划缺口

前端真实编码前，还需要补齐下面细节：

- runtime config 文件名、加载路径、字段名和默认 user token 注入规则见 [frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)。
- token 存储策略应在 `platform/storage` 中实现，并与 [frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md) 的 runtime config 字段保持一致。
- `manualLoginRequired` 的 key 名和清理入口。
- `system/bootstrap` 和 `system/me` 的首屏调用顺序。
- HTTP 401 refresh 重试的并发锁，避免多个请求同时 refresh。
- WebSocket token refresh 后的重连策略。
- Settings 中用户管理与 token 管理的第一阶段范围。
- 权限 scope 到导航项、按钮和路由守卫的映射表。
- 自动进入失败时的错误文案和诊断入口。

## 不做事项

- 不在业务源码中散落默认 token 字符串。
- 不把长期 user token 当成可 logout 的登录会话。
- 不在用户明确退出后继续自动进入工作台。
- 不把登录页作为本地生产环境默认首屏。
- 不把在线 provider 作为本地部署前提。
- 不在前端自行创建默认用户或重置默认密码。

## 推荐同步文档

- [frontend-web-ui.md](frontend-web-ui.md)
- [frontend-web-ui-structure.md](frontend-web-ui-structure.md)
- [frontend-web-ui-workflows.md](frontend-web-ui-workflows.md)
- [frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)
- [../api/local-auth.md](../api/local-auth.md)
- [../api/projects.md](../api/projects.md)
- [../api/websocket-usage.md](../api/websocket-usage.md)
