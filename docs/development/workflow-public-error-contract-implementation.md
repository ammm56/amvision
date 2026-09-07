# Workflow 公开错误契约实施基线

状态：已完成设计，尚未实现。本文是本次跨后端、前端、Trigger 和 .NET SDK 修复的唯一实施基线；完成后把稳定规则合并到 API 与架构专题，并删除本文。

## 目标

Workflow App 输入校验、Runtime、Preview、Runtime 显示、ZeroMQ Trigger、本机共享内存 Trigger 和 .NET SDK 当前存在多种公开错误表示：

- HTTP 使用 `error.code`、`error.message` 和 `error.details`；
- WorkflowRun 使用 `error_message` 和 `metadata.error_details`；
- App Result 失败响应使用 `error_message` 和 `error_details`；
- TriggerResult 使用 `error_message`、`metadata.error_code` 和 `metadata.error_details`；
- Runtime 显示使用字符串形式的 `error_message` 和 `display_error`；
- JSON Schema 校验直接公开 `jsonschema.ValidationError.message`，其中可能包含输入值；
- FastAPI/Pydantic 请求校验详情除 `bytes` 外仍可能公开原始 `input`。

本次修复建立一个公开错误对象，使相同错误通过不同调用方式返回相同的 code、message、details 层级，同时阻止输入值、Base64、文件内容、异常堆栈和内部异常类型进入公开响应。

本次修复不增加队列、缓存、重试、结果重放或逐节点进度，不改变 Workflow、Runtime 与 Trigger 的职责边界。

## 实施范围

纳入本次整体迁移：

- FastAPI 的 `ServiceError` 和 `RequestValidationError` 公开响应；
- Workflow App JSON、multipart、Preview 和 Trigger 输入校验；
- HTTP Runtime 同步调用、异步 WorkflowRun 创建和查询；
- Workflow Preview 创建、查询、摘要和公开事件；
- WorkflowRun 公开事件及 WebSocket replay/live 消息；
- Runtime 监视和 App Mode 的公开显示帧；
- `amvision.workflow-trigger-result.v1`；
- ZeroMQ 和本机共享内存 Trigger；
- 前端 Workflow 编辑、Runtime 监视和 App Mode；
- .NET SDK 的 HTTP、ZeroMQ 和本机共享内存调用；
- OpenAPI、Fixture、Postman、文档示例和自动化测试。

本次不重构以下内部表示：

- Worker 进程 IPC 的 `error_message`、`error_details`；
- `WorkflowRun`、`WorkflowPreviewRun` 领域对象；
- SQLite 和其他 DatabaseBackend 中已有的错误字段；
- Runtime 内部 metadata 与 health 的 `last_error`；
- mailbox header 中用于快速状态判断的数字错误码；
- 训练、转换、数据集和普通 Task 的持久化错误字段。

内部表示在公开边界统一转换。因此本次不需要 Alembic migration，也不需要删除历史 WorkflowRun；已有记录仍通过同一响应构造器生成新错误对象。

## 公开错误对象

新增通用只读契约 `ErrorContract`：

```json
{
  "code": "workflow_input_payload_schema_invalid",
  "message": "Workflow 输入不符合公开 schema",
  "details": {
    "binding_id": "request_json",
    "payload_path": ["value", "station"],
    "schema_path": ["properties", "station", "type"],
    "reason": "JSON Schema type 校验失败"
  }
}
```

字段规则：

- `code`：必填、非空、稳定的机器错误码；
- `message`：必填、非空、可直接显示的错误摘要；
- `details`：必填 object，无附加信息时为 `{}`；
- 禁止额外字段；
- 不携带 HTTP `status_code`；
- 不携带 `request_id`、`event_id` 或 `workflow_run_id`；
- 不携带 `error_type`、堆栈、异常类名或原始异常字符串。

HTTP 状态属于传输层。请求、Run 和 Trigger 标识保留在 HTTP Header 或结果外层，不能改变错误对象结构。

## 公开结果规则

包含执行状态的公开结果固定携带：

```json
{
  "error": null
}
```

或：

```json
{
  "error": {
    "code": "operation_timeout",
    "message": "Workflow 执行超时",
    "details": {}
  }
}
```

不得继续公开以下平行表示：

- `error_message`；
- `error_code`；
- `error_details`；
- `metadata.error_code`；
- `metadata.error_details`。

状态与错误对象的约束为：

| 状态 | `error` |
| --- | --- |
| `created`、`queued`、`running`、`accepted`、`succeeded` | 必须为 `null` |
| `failed`、`timed_out`、`cancelled` | 必须为完整错误对象 |

公开契约构造器在内部记录缺少错误码时按状态补齐：

| 内部状态或来源 | 默认公开错误码 |
| --- | --- |
| `timed_out` | `operation_timeout` |
| `cancelled` | `operation_cancelled` |
| `failed` 且没有稳定错误码 | `workflow_execution_failed` |
| Preview 显示容量超限 | `runtime_preview_size_limit` |
| 未处理异常 | `internal_error` |

未处理异常只公开 `internal_error`、通用消息和空 details。异常类型与原始 `str(error)` 只能进入受控日志，而且日志本身不得记录业务输入内容。

## 输入校验脱敏

### JSON Schema

`WorkflowInputValidator._validate_payload_schema()` 和 `_validate_request_schema()` 不得再把 `ValidationError.message` 放入 details。`type`、`enum`、`pattern` 和 `additionalProperties` 等错误文本可能包含原始字符串或用户字段名。

保留的定位信息只有：

- `binding_id`；
- `payload_path`；
- `schema_path`；
- 不含输入值的 `reason`。

`reason` 由校验关键字生成：

```text
JSON Schema <validator> 校验失败
```

禁止公开 `ValidationError.instance`、`validator_value`、`context`、原始 message 或任何输入值的 repr。

### FastAPI/Pydantic

`RequestValidationError` 的单项详情固定为：

```json
{
  "path": ["body", "input_bindings", "request_json"],
  "rule": "string_type",
  "reason": "请求字段校验失败"
}
```

不公开 Pydantic 原始 `input`、`ctx`、可能包含输入内容的 `msg` 或内部文档 URL。错误列表最多返回前 32 项，details 同时携带 `error_count` 和 `returned_error_count`，避免构造型请求生成无界响应。

### 其他输入错误

容量、数量、MIME 和 ObjectStore 引用错误可以返回契约限制、binding id 和受管理对象标识，但不能返回：

- Base64 正文；
- 文件正文；
- JSON/text 原始输入；
- 非受管理本地路径；
- LocalBuffer 内存内容；
- 用户令牌或鉴权 Header。

## 后端实现边界

新增 `backend/contracts/errors.py`，定义 frozen、`extra="forbid"` 的 `ErrorContract`。新增公开错误构造模块，集中完成：

- `ServiceError -> ErrorContract`；
- 内部 `error_message + error_details + state -> ErrorContract`；
- 默认错误码补齐；
- 从公开 details 中移除内部嵌套 `error_code`；
- 未处理异常的通用化。

现有 `serialize_error()` 是持久化诊断工具，不能直接充当公开错误转换器。它的 JSON-safe 处理不等于敏感信息过滤。

全局 FastAPI handler 只负责把已经安全的错误对象放到固定外层：

```json
{
  "error": {
    "code": "request_validation_failed",
    "message": "请求参数校验失败",
    "details": {}
  }
}
```

`x-request-id` 保留在 HTTP Header。全局 handler 不通过字段名猜测敏感信息；具体输入产生处负责构造安全 details。

## Runtime 与 Preview 映射

`WorkflowRunContract`、`WorkflowPreviewRunContract` 和 `WorkflowPreviewRunSummaryContract` 删除公开 `error_message`，统一新增：

```text
error: ErrorContract | null
```

响应构造器从领域对象的 `error_message`、`metadata.error_details` 和 state 构造 error，并在对外 metadata 中删除错误平行字段。内部领域对象与数据库不变。

App Result 成功时继续直接返回 Workflow 的公开输出。失败时固定为：

```json
{
  "workflow_run_id": "workflow-run-<uuid>",
  "state": "failed",
  "error": {
    "code": "workflow_execution_failed",
    "message": "Workflow 执行失败",
    "details": {}
  }
}
```

`run`、`debug` 与默认 `app-result` 不能再分别生成不同错误层级。`debug` 可以保留节点记录和 trace，但仍不能返回未脱敏输入或第二套错误对象。

WorkflowRun 和 PreviewRun 的公开事件 payload 使用同一 error。REST replay 与实时 WebSocket 必须调用同一个公开事件序列化函数，禁止分别拼装。

## Runtime 显示映射

Runtime 监视和 App Mode 显示帧保留两个明确边界：

- `error`：Workflow 执行错误；
- `display_error`：Preview 数据提取、容量或显示通道错误。

两个字段均为 `ErrorContract | null`。Workflow 成功但显示数据超过容量时，只设置 `display_error`；Workflow 执行失败时设置 `error`，不能用显示错误覆盖业务根因。

本次不增加逐节点进度、强制终止终态、离线缓存或广播队列。Runtime 没有监视客户端时仍不构造或发送显示数据。

## Trigger 映射

`TriggerResultContract` 删除 `error_message`，新增 `error: ErrorContract | null`。失败 manifest 为：

```json
{
  "format_id": "amvision.workflow-trigger-result.v1",
  "trigger_source_id": "zeromq-workflow-runtime-<uuid>",
  "event_id": "trigger-event-<uuid>",
  "state": "failed",
  "workflow_run_id": "workflow-run-<uuid>",
  "response_payload": {},
  "error": {
    "code": "workflow_input_payload_schema_invalid",
    "message": "Workflow 输入不符合公开 schema",
    "details": {}
  },
  "metadata": {
    "workflow_runtime_id": "workflow-runtime-<uuid>",
    "workflow_state": "failed",
    "ack_policy": "ack-after-run-finished",
    "result_mode": "sync-reply"
  }
}
```

Trigger metadata 只保存调用方式和执行上下文，不再保存 error code/details。错误分类直接读取 `result.error.code`。

ZeroMQ Frame 0 与本机共享内存 mailbox JSON 必须序列化同一个 `TriggerResultContract`。mailbox header 的数字错误码继续用于快速状态判断，但由 `result.error.code` 映射，不能形成第二个 JSON 错误协议。

本次不改变 attachment、physical payload、Frame、LocalBuffer lease、reader guard、ACK 或 transport tracker 生命周期。

## .NET SDK

新增一个公共错误 DTO，字段固定映射 `code`、`message`、`details`。HTTP WorkflowRun、Preview 和 TriggerResult 统一引用该 DTO。

删除 SDK 对以下旧公开路径的读取：

- `ErrorMessage`；
- `Metadata["error_code"]`；
- `Metadata["error_details"]`；
- root `error_code` 和 root `error_message` fallback。

SDK OperationResult 外层继续保留 `data`、`http_response`、`exception`：

- 后端业务失败进入 `data.error`；
- HTTP 非 2xx 从响应根部读取 `error`；
- 网络、反序列化和本地资源访问失败进入 `exception`；
- 同一个业务错误不能同时复制到 `data.error` 和 `exception`。

ZeroMQ 与本机共享内存必须返回同一个 TriggerResult DTO，不因传输方式增加 Result 包装或改变错误层级。

## 前端

前端新增统一 `ErrorContract` TypeScript 类型。Workflow 编辑 Preview、Runtime 监视、App Mode、Workflow 详情和 Trigger 结果只读取：

```text
result.error?.code
result.error?.message
result.error?.details
```

Runtime 显示额外读取 `frame.display_error`。前端只使用稳定 code 执行特殊逻辑；message 是默认摘要，四语言显示可以按 code 映射本地化文本。

旧 `error_message`、`metadata.error_details` 和字符串 `display_error` 类型、解析与测试 Fixture 必须在同一迁移中删除。

## 版本和迁移

当前 Workflow Trigger result mapping 明确属于发布前开发契约。本次按开发态 v1 整体收敛：

- 保持现有 `amvision.workflow-run.v1`、`amvision.workflow-preview-run.v1` 和 `amvision.workflow-trigger-result.v1`；
- 后端、前端、.NET SDK、Fixture、Postman 和文档同时更新；
- 不增加 v2；
- 不保留公开协议双读、fallback 或兼容分支；
- 发布说明明确记录 v1 错误对象重置，外部调用端必须同步 SDK。

内部数据库仍使用当前字段，公开转换器同时覆盖历史和新记录。这是内部到公开契约的单向映射，不是两套公开协议并存。

## 实施顺序

### 1. 契约与脱敏

1. 新增 `ErrorContract` 和公开错误构造器；
2. 增加状态到默认错误码的唯一映射；
3. 替换两处 JSON Schema raw message；
4. 收紧 Pydantic 请求错误序列化；
5. 验证 `type`、`enum`、`pattern`、`additionalProperties` 和嵌套 request schema 不回显测试标记。

该阶段通过后再修改公开响应，避免各调用面各自实现错误清洗。

### 2. HTTP Runtime 与 Preview

1. 统一全局 HTTP 错误外层；
2. 修改 WorkflowRun 与 PreviewRun 公开契约；
3. 修改 app-result、run、debug 和查询响应构造器；
4. 修改公开事件 replay/live；
5. 清除对外 metadata 中的旧错误字段；
6. 验证历史内部记录仍能生成新 error。

### 3. Trigger

1. 修改 `TriggerResultContract`；
2. 修改 result dispatcher、submitter 和 supervisor；
3. 简化 Trigger 错误分类；
4. 修改 ZeroMQ adapter 错误 reply；
5. 修改本机共享内存 mailbox JSON；
6. 验证两种传输除 source/event id 外返回相同错误对象；
7. 验证二进制错误码、容量统计和超时统计仍正确。

### 4. Runtime 显示和前端

1. 把显示帧错误改成 ErrorContract；
2. 同步 Workflow 编辑 Preview、Runtime 监视和 App Mode；
3. 验证 Runtime 重启后的 WebSocket 重连与错误显示；
4. 验证业务错误和 display error 不互相覆盖；
5. 删除前端旧字段与 fallback。

### 5. .NET SDK

1. 新增统一错误 DTO；
2. 同步 HTTP、ZeroMQ 和本机共享内存结果模型；
3. 删除旧字段与 fallback；
4. 更新 KeyName/ResourceId 示例和 ContractTests；
5. 验证业务失败与 transport exception 边界。

### 6. 文档与完整回归

同步更新 Workflow Run、Preview、Runtime 显示、Trigger、SDK、通信契约和输入契约文档，删除所有旧 JSON 示例。OpenAPI、Postman 和 SDK Fixture 必须与代码同批更新。

## 测试矩阵

至少覆盖：

- 未声明 binding；
- 缺少 required binding；
- payload schema 错误；
- request schema 错误；
- inline、文本、文件和文件数量容量超限；
- MIME 拒绝；
- ObjectStore 引用无效；
- Runtime 未启动；
- Worker 与节点执行失败；
- 执行超时和取消；
- Trigger busy 与容量不足；
- ZeroMQ 协议错误；
- 本机共享内存协议错误；
- Preview 显示容量超限。

每一项检查：

1. `error` 层级固定；
2. `code`、`message`、`details` 完整；
3. 不存在旧公开错误字段；
4. 不包含唯一敏感测试标记；
5. HTTP、ZeroMQ 和本机共享内存使用相同业务错误码；
6. 前端和 .NET SDK 能读取同一结构；
7. 成功输出和 attachment 数据不变。

JSON 对象字段顺序不属于契约，不编写依赖序列化键顺序的测试。

## 性能与稳定性门禁

成功热路径只增加一个 `error=null` 字段，不执行递归脱敏、不复制图片、不访问额外存储。错误对象只在失败路径构造。

完成后至少执行：

- 输入契约和 API 单元测试；
- Workflow Runtime、Preview 和 Trigger 集成测试；
- ZeroMQ 与本机共享内存真实调用；
- .NET ContractTests；
- 前端 typecheck、相关 unit test 和 build；
- 两实例同步部署、两个并发 Workflow 调用回归；
- LocalBuffer lease、reader guard、ACK、handle 和内存基线检查；
- 成功请求修改前后延迟对照。

禁止为了错误统一增加队列、隐藏重试、全局缓存、结果保留线程或大对象深复制。若成功链路出现可测回归，优先调整公开边界的对象构造，不能修改 Runtime/Trigger 调度语义掩盖问题。

## 完成条件

- 所有 Workflow 公开调用面只剩一个错误对象；
- HTTP、ZeroMQ、本机共享内存和 .NET SDK 的业务错误语义一致；
- Schema 与请求校验响应不包含输入值；
- 内部错误表示没有泄漏到公开 metadata；
- 成功结果、图片表示和高性能数据面不变；
- 代码、测试、OpenAPI、SDK、Fixture、Postman 和文档一次性通过；
- 稳定规则已合并到正式专题后删除本文。
