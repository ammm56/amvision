# 本地用户与登录接口文档

## 文档目的

本文档说明当前已经公开的本地用户、权限管理、登录会话、refresh token 和长期调用 token 接口。

当前阶段已经把本地用户、权限范围、登录会话、refresh token、长期调用 token 和实时审计收敛为稳定基线。

本文档只描述本地实现，不展开未来在线账号提供方的扩展设计；在线版本后续会在本项目稳定基线之上继续扩展。

## 当前公开范围

- GET /api/v1/auth/providers
- POST /api/v1/auth/bootstrap-admin
- POST /api/v1/auth/login
- POST /api/v1/auth/refresh
- POST /api/v1/auth/logout
- GET /api/v1/auth/users
- POST /api/v1/auth/users
- PATCH /api/v1/auth/users/{user_id}
- DELETE /api/v1/auth/users/{user_id}
- POST /api/v1/auth/users/{user_id}/reset-password
- GET /api/v1/auth/users/{user_id}/tokens
- POST /api/v1/auth/users/{user_id}/tokens
- DELETE /api/v1/auth/users/{user_id}/tokens/{token_id}
- GET /api/v1/system/me
- /ws/v1/auth/events

## 设计边界

- 当前阶段以本地用户与权限管理闭环为目标；`local` 是当前唯一完整可用的账号 provider。
- 当前本地用户、登录会话、refresh token 和长期调用 token 都保存在服务数据库中。
- 当前可以通过 provider 目录公开 local 和已配置的在线账号 provider；在线 provider 目前只提供发现抽象，不在本阶段实现回调登录流程，也不是当前前端或集成接入的前提。
- 登录返回的是短期会话凭据：`access_token` + `refresh_token`。
- 长期调用 token 由用户管理接口签发，供 REST、WebSocket、workflow app 或其他集成调用方长期使用。
- 长期调用 token 默认永久有效；只有在创建时显式提供 `ttl_hours` 或 `expires_at` 才会设置过期时间。
- `logout` 只撤销登录会话，不撤销长期调用 token。
- 当前权限模型继续复用既有 `scopes` 和 `project_ids` 语义，不额外引入第二套角色系统。
- `project_ids` 为空时，表示不按 Project 做可见性裁剪。
- 当本地用户表为空且启用自动初始化时，服务会在启动阶段写入默认本地用户和长期调用 token；这组初始化数据由启动期初始化器维护，不通过 backend-service.json 暴露。
- `bootstrap-admin` 只适用于本地用户表为空且关闭默认本地用户自动初始化的场景。

## 鉴权模式说明

- `mode=local`：只接受本地登录会话 token 和本地长期调用 token；仓库默认配置使用该模式。
- `mode=static-bearer`：只接受静态 Bearer token。

## 默认本地用户初始化

- 空库首次启动时，服务会自动写入一组默认本地用户数据。
- 初始化逻辑定义在 [backend/service/application/auth/default_local_auth_seeder.py](../../backend/service/application/auth/default_local_auth_seeder.py)。
- backend-service.json 只保留是否启用自动初始化的开关，不保存默认用户名、密码或 token 明文。
- Postman、Swagger 和业务接口示例统一填写当前环境实际 Bearer token，不把默认 token 当成固定联调值。

## 当前公开 scope

- `auth:read`
- `auth:write`

说明：

- 本地管理员 bootstrap 默认授予 `*`。
- 普通本地用户的接口权限由 `scopes` 决定。
- 资源可见性仍由 `project_ids` 控制。

## GET /api/v1/auth/providers

- 成功状态码：200 OK
- 用于登录页、工作站或外部集成读取当前可用的账号 provider 目录
- 当前应把 `provider_id=local` 视为唯一完整可用的 provider；其他已配置目录项只用于后续在线版本扩展预留
- 当前返回字段：
  - `provider_id`
  - `provider_kind`
  - `display_name`
  - `enabled`
  - `login_mode`
  - `supports_password_login`
  - `supports_refresh`
  - `supports_bootstrap_admin`
  - `supports_user_management`
  - `supports_long_lived_tokens`
  - `issuer_url`
  - `metadata`

## 会话 token 与长期调用 token

### 登录会话 token

- 来源：`POST /api/v1/auth/bootstrap-admin`、`POST /api/v1/auth/login`、`POST /api/v1/auth/refresh`
- 字段：`session_id`、`access_token`、`refresh_token`
- 用途：管理台登录、人工操作、短期会话续期
- 过期：默认按 local auth 配置里的会话 TTL 生效
- 撤销：`POST /api/v1/auth/logout` 或 refresh 轮换后旧会话自动失效

### 长期调用 token

- 来源：`POST /api/v1/auth/users` 的默认 `initial_user_token`，或 `POST /api/v1/auth/users/{user_id}/tokens`
- 字段：`token_id`、`token_name`、`token`
- 用途：接口集成、WebSocket、workflow app、工作站、边车或其他自动化调用方
- 过期：默认永久有效；仅在签发时显式指定 `ttl_hours` 或 `expires_at` 才设置过期时间
- 撤销：`DELETE /api/v1/auth/users/{user_id}/tokens/{token_id}`

## POST /api/v1/auth/bootstrap-admin

- 成功状态码：201 Created
- 仅当本地用户表为空时可调用
- 启用默认本地用户自动初始化的环境在空库首次启动后通常不会满足这个条件；常规联调应填写当前环境实际账号或长期调用 token
- 调用成功后会同时创建管理员用户和首个登录会话

### 请求体字段

- `username`：管理员用户名
- `password`：管理员密码
- `display_name`：可选展示名称

### 响应字段

- `session_id`
- `access_token`
- `token_type`，固定为 `bearer`
- `expires_at`
- `refresh_token`
- `refresh_expires_at`
- `user`

## POST /api/v1/auth/login

- 成功状态码：200 OK
- 使用用户名和密码登录当前支持 password 模式的 provider
- 当前支持请求体字段：
  - `provider_id`，默认 `local`
  - `username`
  - `password`
- 用户被禁用或密码错误时返回 401
- 当 provider 只支持外部浏览器登录而不支持 password login 时返回 400
- 返回字段与 bootstrap-admin 一致

## POST /api/v1/auth/refresh

- 成功状态码：200 OK
- 请求体字段：`refresh_token`
- 成功时会签发新的 `session_id`、`access_token` 和 `refresh_token`
- 原 refresh token 与原 access token 会一并失效

## POST /api/v1/auth/logout

- 成功状态码：204 No Content
- 只撤销当前 Bearer token 对应的本地登录会话
- 只接受登录会话 token，不接受长期调用 token 或静态 token

## GET /api/v1/auth/users

- 需要 `auth:read`
- 返回全部本地用户

## POST /api/v1/auth/users

- 需要 `auth:write`
- 当前支持字段：
  - `username`
  - `password`
  - `display_name`
  - `principal_type`
  - `project_ids`
  - `scopes`
  - `metadata`
  - `initial_user_token`
- `initial_user_token` 默认启用，会为新用户签发一个名为 `default` 的长期调用 token
- `initial_user_token` 可选字段：
  - `enabled`
  - `token_name`
  - `ttl_hours`
  - `expires_at`
  - `metadata`
- 返回字段：
  - `user`
  - `initial_user_token`，仅在签发时返回明文 `token`

## PATCH /api/v1/auth/users/{user_id}

- 需要 `auth:write`
- 当前支持字段：
  - `display_name`
  - `password`
  - `project_ids`
  - `scopes`
  - `is_active`
  - `metadata`

## DELETE /api/v1/auth/users/{user_id}

- 需要 `auth:write`
- 删除用户时会一并清理该用户的登录会话、refresh token 和长期调用 token

## POST /api/v1/auth/users/{user_id}/reset-password

- 需要 `auth:write`
- 当前支持字段：
  - `new_password`
  - `revoke_sessions`，默认 `true`
  - `revoke_user_tokens`，默认 `false`
- 当 `revoke_sessions=true` 时，会撤销该用户全部登录会话和 refresh token
- 当 `revoke_user_tokens=true` 时，会额外撤销该用户全部长期调用 token

## GET /api/v1/auth/users/{user_id}/tokens

- 需要 `auth:read`
- 返回指定用户的全部长期调用 token 摘要
- 返回列表不包含 token 明文

## POST /api/v1/auth/users/{user_id}/tokens

- 需要 `auth:write`
- 当前支持字段：
  - `token_name`
  - `ttl_hours`
  - `expires_at`
  - `metadata`
- 成功返回新 token 的一次性明文值

## DELETE /api/v1/auth/users/{user_id}/tokens/{token_id}

- 需要 `auth:write`
- 撤销指定长期调用 token

## GET /api/v1/system/me

当前接口会额外返回本地鉴权相关字段：

- `username`
- `display_name`
- `auth_provider_id`
- `auth_provider_kind`
- `auth_credential_kind`，当前值为 `session` 或 `user-token`
- `auth_credential_id`
- `auth_session_id`
- `auth_token_id`
- `auth_token_name`

## /ws/v1/auth/events

- 需要 `auth:read`
- 用于订阅登录会话和长期调用 token 的实时审计事件
- 当前支持的 query 参数：
  - `event_type`
  - `user_id`
  - `provider_id`
  - `credential_kind`
- 连接成功后会先收到一条 `auth.connected` 控制事件
- 后续当前阶段会推送的主要事件类型：
  - `auth.sessions.issued`
  - `auth.sessions.revoked`
  - `auth.user-tokens.issued`
  - `auth.user-tokens.revoked`
- 当前阶段只提供实时流，不提供通过 WebSocket 的历史回放

## 当前限制

- 当前不公开邮箱验证、忘记密码、自助找回密码、二次认证和在线账号绑定。
- 当前在线 provider 目录只提供发现抽象，不包含浏览器回调、code exchange 和外部 issuer token 校验实现。
- 在线版本会在本项目整体完成后，基于当前本地鉴权和权限模型继续扩展。
- 当前不区分更细的 token 角色类型；仍通过 `scopes` 和 `project_ids` 表达权限范围。
- 当前长期调用 token 只在签发时返回一次明文；后续查询只返回摘要信息。