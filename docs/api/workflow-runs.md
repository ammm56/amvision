# WorkflowRun 接口文档

## 文档目的

本文档说明当前已经公开的 WorkflowRun REST API、状态语义和稳定返回字段。

本文档描述当前已经公开的 WorkflowRun 行为，包括同步 invoke、multipart invoke、异步 run create、multipart run create、结果回查、事件读取和取消。

## 当前公开范围

- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs/upload
- GET /api/v1/workflows/runs/{workflow_run_id}
- GET /api/v1/workflows/runs/{workflow_run_id}/events
- POST /api/v1/workflows/runs/{workflow_run_id}/cancel
- /ws/v1/workflows/runs/events
- sync invoke 和 async run 共用的 WorkflowRun 持久化记录

## 资源定位

- WorkflowRun 表示已发布应用的一次正式调用。
- WorkflowRun 同时承接 sync invoke 和 async run 两种调用方式。
- invoke 或 runs 请求都会先写入 WorkflowRun，再推进到终态。
- WorkflowRun 与 WorkflowPreviewRun 分开建模：前者面向已发布 runtime 的正式调用，后者面向编辑器里的快速试跑。
- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke` 和 `.../invoke/upload` 默认只返回公开 App Result；如需平台运行回执或完整调试 trace，必须显式传 `response_mode=run` 或 `response_mode=debug`。
- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs` 创建异步 run，只返回运行回执。异步 run 完成后，`GET /api/v1/workflows/runs/{workflow_run_id}` 默认返回公开 App Result；如需平台运行回执或完整调试 trace，必须显式传 `response_mode=run` 或 `response_mode=debug`。
- `response_mode=run` 和 `response_mode=debug` 如果输入或输出里出现 inline base64 图片或 memory image-ref，资源返回会自动脱敏，不直接回显原始图片内容或 image_handle。

## Sync / Async 边界说明

- WorkflowRun 表示一条已发布 WorkflowAppRuntime 的正式执行记录。当前正式执行支持 sync invoke 和 async runs 两种提交方式，两者共享同一套 snapshot 和节点图。
- sync invoke 在当前请求内等待执行结束，适合低时延、短链路和高频交互。
- async runs 在创建时先返回 workflow_run_id，调用方再通过 GET 查询结果，必要时可发起 cancel，适合长时间执行、后台提交、排队和后续回查。
- WorkflowPreviewRun 只用于编辑态试跑。生产态正式执行统一落在 WorkflowRun，不再为不同触发方式引入另一类正式执行资源。
- 当前公开入口是 HTTP API；后续如果通过 PLC、ZeroMQ、MQTT、gRPC、IO 变化或其他集成方式触发 workflow，仍应统一映射为 WorkflowRun。
- 多 runtime 实例仍用于吞吐和隔离。async runs 解决的是长时间执行、排队、取消和回查，不承担扩容职责。

## 接口入口

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：
  - /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke
  - /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload
  - /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs
  - /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs/upload
  - /api/v1/workflows/runs/{workflow_run_id}
  - /api/v1/workflows/runs/{workflow_run_id}/events
  - /api/v1/workflows/runs/{workflow_run_id}/cancel
- 实时资源流：/ws/v1/workflows/runs/events
- 稳定规则：amvision.workflow-run.v1

## 鉴权规则

- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke 需要 workflows:write
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload 需要 workflows:write
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs 需要 workflows:write
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs/upload 需要 workflows:write
- GET /api/v1/workflows/runs/{workflow_run_id} 需要 workflows:read
- GET /api/v1/workflows/runs/{workflow_run_id}/events 需要 workflows:read
- POST /api/v1/workflows/runs/{workflow_run_id}/cancel 需要 workflows:write
- /ws/v1/workflows/runs/events 需要 workflows:read

## 状态语义

| 状态 | 说明 |
| --- | --- |
| created | 记录已创建 |
| queued | 异步 run 已入队，尚未占用 worker |
| dispatching | runtime 已收到请求，正在转给 worker |
| running | worker 正在执行固定 snapshot |
| succeeded | 同步调用成功结束 |
| failed | 调用失败 |
| cancelled | 调用已取消 |
| timed_out | 调用超时 |

补充说明：

- invoke 是同步接口，调用方通常直接拿到 succeeded、failed 或 timed_out。
- runs 是异步接口，创建返回时通常处于 queued；worker 开始执行后会推进到 running，结束后进入 succeeded、failed、cancelled 或 timed_out。
- 在执行期间，其他查询方可能会通过 GET 看到 queued、dispatching 或 running。
- 当 invoke 结果为 failed 或 timed_out 时，HTTP 响应仍返回 200，并通过 WorkflowRun.state 表达执行结果。
- 当异步 run 被取消时，GET 和 cancel 响应都会返回 state=cancelled。

## 稳定字段

| 字段 | 说明 |
| --- | --- |
| format_id | 固定为 amvision.workflow-run.v1 |
| workflow_run_id | WorkflowRun 资源 id |
| workflow_runtime_id | 所属 WorkflowAppRuntime id |
| project_id | 所属 Project id |
| application_id | 运行的 FlowApplication id |
| state | 当前 WorkflowRun 状态 |
| created_at | 记录创建时间 |
| started_at | worker 开始执行时间，可为空 |
| finished_at | worker 结束执行时间，可为空 |
| created_by | 调用主体 id，可为空 |
| requested_timeout_seconds | 本次调用的超时秒数 |
| assigned_process_id | 执行该 run 的 worker 进程 id，可为空 |
| input_payload | 本次调用的输入 payload；inline base64 图片会改写为 redacted 标记 |
| outputs | 按 application output binding_id 组织的公开 App Result；详情接口与 async run 返回持久化脱敏副本 |
| template_outputs | 按 template output id 组织的底层输出，仅用于平台调试、trace 和内部回查 |
| node_records | 节点执行记录列表，仅用于平台调试、trace 和内部回查 |
| error_message | 失败或超时时的摘要信息，可为空 |
| metadata | 调用附加元数据；当 runtime 绑定 execution policy 时会补充 metadata.execution_policy；失败时会补充 error_details，取消时会补充 cancel_requested_at 和 cancelled_by |

补充说明：

- 对 image_base64、preview_image_base64 一类大字段，持久化记录资源会返回对应的 _redacted 标记，不保留原始 base64 文本。
- 对 memory image-ref，记录资源会保留 transport_kind、media_type、width、height 等摘要字段，但不会返回 image_handle。

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs

- Content-Type：application/json
- 成功状态码：201 Created
- 仅支持已经处于 running 的 WorkflowAppRuntime
- 当前仍采用单实例串行执行；如果前一条 run 仍在执行，新建 run 会先进入 queued
- 返回完整 WorkflowRun 规则

### 请求体字段

- input_bindings：可选，按 application input binding_id 组织的输入 payload
- execution_metadata：可选，执行元数据；接口层会补写 created_by，服务层会补写 trigger_source=async-invoke
- timeout_seconds：可选，覆盖 runtime 默认 request_timeout_seconds；若省略且 runtime 已绑定 execution policy，则取 policy.default_timeout_seconds；显式值必须大于 0

### 最小请求 JSON

```json
{
  "input_bindings": {
    "request_image_base64": {
      "image_base64": "<base64 image bytes>",
      "media_type": "image/png"
    }
  },
  "execution_metadata": {
    "trigger_source": "schedule"
  }
}
```

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs/upload

- Content-Type：multipart/form-data
- 成功状态码：201 Created
- 仅支持已经处于 running 的 WorkflowAppRuntime
- 当前 multipart 保留字段：
  - input_bindings_json，可选
  - execution_metadata_json，可选
  - timeout_seconds，可选
- 其他文件字段名必须等于 application 的 input binding_id
- 当前 multipart 文件上传只支持 `dataset-package.v1` 输入绑定，不支持把图片文件直接作为 `request_image_base64` 或 `request_image_ref` 上传
- 返回完整 WorkflowRun 规则

### 最小响应 JSON

```json
{
  "format_id": "amvision.workflow-run.v1",
  "workflow_run_id": "workflow-run-2",
  "workflow_runtime_id": "workflow-runtime-1",
  "project_id": "project-1",
  "application_id": "inspection-app",
  "state": "queued",
  "created_at": "2026-05-08T12:05:00Z",
  "started_at": null,
  "finished_at": null,
  "created_by": "operator-1",
  "requested_timeout_seconds": 60,
  "assigned_process_id": null,
  "input_payload": {
    "request_image_base64": {
      "image_base64_redacted": true,
      "media_type": "image/png"
    }
  },
  "outputs": {},
  "template_outputs": {},
  "node_records": [],
  "error_message": null,
  "metadata": {
    "trigger_source": "async-invoke",
    "created_by": "operator-1",
    "trace_level": "none",
    "retain_trace_enabled": false,
    "retain_node_records_enabled": false,
    "execution_policy": {
      "execution_policy_id": "runtime-default-policy",
      "policy_kind": "runtime-default",
      "trace_level": "none",
      "retain_node_records_enabled": false,
      "retain_trace_enabled": false,
      "snapshot_object_key": "workflows/runtime/app-runtimes/workflow-runtime-1/execution-policy.snapshot.json"
    }
  }
}
```

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke

- Content-Type：application/json
- 成功状态码：200 OK
- 仅支持 observed_state=running 的 WorkflowAppRuntime
- 默认 `response_mode=app-result`，只返回公开 App Result，不返回 WorkflowRun、template_outputs 或 node_records
- `response_mode=run` 返回 WorkflowRun 运行回执；其中 `outputs` 保留公开 App Result，`template_outputs={}`，`node_records=[]`
- `response_mode=debug` 返回完整 WorkflowRun 调试视图；包含原始 outputs、template_outputs 和 node_records

### 请求体字段

- input_bindings：可选，按 application input binding_id 组织的输入 payload
- execution_metadata：可选，执行元数据；接口层会补写 created_by
- timeout_seconds：可选，覆盖 runtime 默认 request_timeout_seconds；若省略且 runtime 已绑定 execution policy，则取 policy.default_timeout_seconds；显式值必须大于 0

### 响应模式

| response_mode | 用途 | 返回内容 |
| --- | --- | --- |
| app-result | 外部系统和 Postman 正式调用默认值 | 单个 App Result 直接返回；多个 App Result 按 binding_id 返回对象；失败时返回 state、error_message 和 error_details |
| run | 平台前端运行回执 | WorkflowRunContract；只带公开 outputs，不带底层 template_outputs 和 node_records |
| debug | 平台排查问题 | WorkflowRunContract；带完整 outputs、template_outputs 和 node_records |

### 最小请求 JSON

```json
{
  "input_bindings": {
    "request_image_base64": {
      "image_base64": "<base64 image bytes>",
      "media_type": "image/png"
    }
  },
  "execution_metadata": {
    "trigger_source": "sync-api"
  }
}
```

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload

- Content-Type：multipart/form-data
- 成功状态码：200 OK
- 仅支持 observed_state=running 的 WorkflowAppRuntime
- 当前 multipart 保留字段：
  - input_bindings_json，可选
  - execution_metadata_json，可选
  - timeout_seconds，可选
- 其他文件字段名必须等于 application 的 input binding_id
- 当前 multipart 文件上传只支持 `dataset-package.v1` 输入绑定，不支持把图片文件直接作为 `request_image_base64` 或 `request_image_ref` 上传
- 响应模式与 JSON `invoke` 一致，默认只返回公开 App Result；需要运行回执或完整 trace 时显式传 `response_mode=run` 或 `response_mode=debug`

### 默认最小响应 JSON

```json
{
  "status_code": 200,
  "body": {
    "ok": true
  }
}
```

### 失败返回规则

- worker 执行失败时，state 返回 failed，error_message 返回摘要信息。
- worker 返回的详细错误会写入 metadata.error_details，例如 node_id、node_type_id、runtime_kind、error_type 和 error_message。
- worker 等待超时时，state 返回 timed_out，error_message 返回超时摘要。
- async run 在 queued 或 running 期间被取消时，state 返回 cancelled，error_message 返回 workflow run 已取消。

## GET /api/v1/workflows/runs/{workflow_run_id}

- 默认 `response_mode=app-result`，返回公开 App Result，不返回 WorkflowRun、template_outputs 或 node_records
- `response_mode=run` 返回 WorkflowRun 运行回执；其中 `outputs` 保留公开 App Result，`template_outputs={}`，`node_records=[]`
- `response_mode=debug` 返回完整 WorkflowRun 调试视图；包含原始 outputs、template_outputs 和 node_records
- 适合异步 run 完成后获取外部调用结果；平台页面如需状态、assigned_process_id、error_message 和 metadata.error_details，应显式使用 `response_mode=run`

## GET /api/v1/workflows/runs/{workflow_run_id}/events

- 成功状态码：200 OK
- 需要 workflows:read
- 当前支持查询参数 after_sequence 和 limit；只返回 sequence 更大的事件，并按升序截取前 N 条
- 适合断线恢复、历史回看和测试验证

### 当前稳定事件类型

- run.queued
- run.dispatching
- run.started
- run.cancel_requested
- run.succeeded
- run.failed
- run.cancelled
- run.timed_out

### 最小事件语义

- sequence：单条 WorkflowRun 内递增序号，从 1 开始
- event_type：事件类型
- created_at：事件写入时间
- message：面向人读的摘要信息
- payload：结构化摘要；当前至少包含 state 和 workflow_runtime_id，必要时补 assigned_process_id、error_message、started_at、finished_at
- `/ws/v1/workflows/runs/events` 的 replay 和 live 事件与 REST 共用同一套平铺 payload，不再额外包一层 `payload.data`

## /ws/v1/workflows/runs/events

- 需要 workflows:read
- query 参数：workflow_run_id 必填；after_cursor、limit 可选
- after_cursor 当前直接使用 WorkflowRun 事件的 sequence
- 连接成功后先返回 workflows.runs.connected，再按 sequence 持续推送增量事件
- 实时推送走 service_event_bus，历史回放与 REST 事件接口共用同一份 `events.json`
- WorkflowAppRuntime 正式调用默认不返回 diagnostics：`return_timing_metadata_enabled=false`、`return_node_timings_enabled=false`。调用结果默认不包含 `metadata.timings`、`metadata.node_timings`，PublishedInferenceGateway 写入业务输出的 `metadata.timings` 也会被清理。
- WorkflowRun 数据库记录通过 `workflow_run_record_mode` 控制：
  - `full`：保留完整 WorkflowRun 记录、dispatch/final 事件、按 retention 开关保留输入输出和 node_records。
  - `minimal`：同步调用只在完成后写一条最小 WorkflowRun 状态记录，不保留 input_payload、outputs、template_outputs 和 node_records，适合高帧率 Trigger。
  - `none`：同步调用不写 WorkflowRun 数据库记录，只返回当前调用结果；异步 run 不能使用该模式。
- WorkflowAppRuntime 正式调用默认仍使用 `full` 记录模式；ZeroMQ TriggerSource 默认使用 `minimal`。默认执行元数据仍会补齐 `trace_level=none`、`retain_trace_enabled=false`、`retain_node_records_enabled=false`。
- 如需临时排查单次调用，可在 invoke/runs 请求或 TriggerSource `default_execution_metadata` 中显式设置 `return_timing_metadata_enabled=true`、`return_node_timings_enabled=true`；如果还需要历史事件和节点输入输出，再设置 `retain_trace_enabled=true`、`retain_node_records_enabled=true` 和非 `none` 的 `trace_level`。

## POST /api/v1/workflows/runs/{workflow_run_id}/cancel

- 成功状态码：200 OK
- 需要 workflows:write
- 当前只对异步 run 提供稳定语义；如果目标 run 已经处于 succeeded、failed、timed_out 或 cancelled，会直接返回当前结果
- 当目标 run 仍处于 queued 或 running 时，服务会写入取消请求元数据，并把终态推进到 cancelled

### 最小响应语义

- state：cancelled
- error_message：workflow run 已取消
- metadata.cancel_requested_at：取消请求时间
- metadata.cancelled_by：取消主体 id

## 当前不公开的扩展项

- schedule、integration trigger_source 的对外创建接口

## 与其他资源的关系

- WorkflowRun 依附于 [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md) 创建和执行。
- WorkflowRun 返回里的 metadata.execution_policy 摘要来自宿主 WorkflowAppRuntime 固定的 execution policy snapshot。
- 编辑态试跑结果见 [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)。
- template/application 的保存和校验入口见 [docs/api/workflows.md](workflows.md)。

## 相关文档

- [docs/api/current-api.md](current-api.md)
- [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md)
- [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)
- [docs/api/workflows.md](workflows.md)
- [docs/api/examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/app-runtime.invoke.request.json](examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/app-runtime.invoke.request.json)
- [docs/api/postman/workflow-runtime.postman_collection.json](postman/workflow-runtime.postman_collection.json)
- [docs/architecture/workflow-runtime-phase1.md](../architecture/workflow-runtime-phase1.md)
