# API 通用约定

本文只定义所有公开 API 共享的调用规则。完整 endpoint 和 schema 由 backend-service 的 `/openapi.json` 生成，资源流程进入各专题文档。

## 地址与版本

- REST 根路径：`/api/v1`
- OpenAPI：`/openapi.json`
- Swagger UI：`/docs`
- 破坏性 contract 变化必须使用新版本，不在现有字段上静默改变语义。

## 鉴权

业务接口使用：

```http
Authorization: Bearer <token>
```

Bearer token 可以是登录会话 access token 或长期 user token。用户、session、refresh、token 与 scope 的完整语义见 [本地鉴权](local-auth.md)。客户端不得依赖仓库示例中的默认用户名、密码或 token 作为生产凭据。

## Project 边界

- Project 级资源必须携带路径、查询或请求 schema 要求的 `project_id`。
- 详情、输出、下载和控制动作也要校验资源归属；知道资源 id 不代表可以跨 Project 访问。
- SDK 或长期集成保存稳定资源 id，不从页面显示名称推导 id。

## 请求标识

客户端可以发送 `x-request-id`；未发送时服务生成 UUID。服务在响应头回传 `x-request-id`，统一错误体也包含 `request_id`。日志、Task、Run 和外部调用排障应优先记录该值。

## 列表分页

主要列表使用：

- `offset`：默认 `0`
- `limit`：默认 `100`，上限以 OpenAPI 为准

分页信息位于响应头：

- `x-offset`
- `x-limit`
- `x-total-count`
- `x-has-more`
- `x-next-offset`（仍有下一页时）

客户端必须处理分页；不能先取项目前 100 条，再在本地过滤特定 Runtime、Trigger 或版本。

## 错误

统一 HTTP 错误结构：

```json
{
  "error": {
    "code": "resource_conflict",
    "message": "资源状态不允许当前操作",
    "details": {},
    "request_id": "..."
  }
}
```

- `code` 是稳定分支依据。
- `message` 用于展示，不用于程序判断。
- `details` 提供 generation、当前状态、占用资源或字段错误等上下文。
- 409 表示资源状态、CAS generation 或生命周期冲突；客户端应刷新资源，而不是无限重试。
- 422 表示请求 schema 校验失败。

## 并发与幂等

- 控制面使用资源状态与 expected generation/expected state 做条件更新。
- 冲突立即返回，不隐式排队、不无限重试。
- Workflow 切版固定为新的 revision 和更大的 generation；rollback 也不会倒退 generation。
- 同步/异步 Run 成功后记录固定版本、revision、generation、fingerprint 和 worker instance，不因后续切版被改写。

## 时间与状态

- 时间字段使用带时区的 ISO 8601 字符串。
- Task、Run、Deployment、Runtime 和 Trigger 各有独立状态机；客户端只使用专题文档和 OpenAPI 中公开的值。
- WebSocket 是增量通知，不是资源最终状态；断线或游标失效后先重新读取 REST 快照。

## 文件和图片

- ObjectStore 相对位置由服务端命名空间管理。
- 明确支持磁盘路径的字段可以使用本机绝对路径；普通 `object_key` 不能因此自动获得磁盘访问语义。
- `image-ref.v1` 显式区分 ObjectStore、LocalBuffer 和磁盘绝对路径来源。
- 大图主链路使用 `image-ref.v1`、LocalBuffer/mmap；Base64 JSON 只适合小型兼容输入。
- 下载使用服务返回的 `content_url`、`download_url` 或 file id，不拼接内部磁盘目录。

## API 专题

- [Project](projects.md)
- [DatasetImport](datasets-imports.md) / [DatasetExport](datasets-exports.md)
- [模型接口](detection-training.md)
- [Workflow](workflows.md)
- [Workflow App Version](workflow-app-versions.md)
- [Workflow App Runtime](workflow-app-runtimes.md)
- [Workflow Run](workflow-runs.md)
- [Trigger Source](workflow-trigger-sources.md)
- [WebSocket](websocket-usage.md)
