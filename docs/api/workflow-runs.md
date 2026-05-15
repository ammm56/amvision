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
- WorkflowRun 返回的是持久化记录视图；如果输入或输出里出现 inline base64 图片或 memory image-ref，资源返回会自动脱敏，不直接回显原始图片内容或 image_handle。

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
- 稳定合同：amvision.workflow-run.v1

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
| outputs | 按 application output binding_id 组织的输出；inline base64 图片会改写为 redacted 标记 |
| template_outputs | 按 template output id 组织的底层输出；inline base64 图片会改写为 redacted 标记 |
| node_records | 节点执行记录列表；当前包含 inputs 和 outputs 的脱敏快照 |
| error_message | 失败或超时时的摘要信息，可为空 |
| metadata | 调用附加元数据；当 runtime 绑定 execution policy 时会补充 metadata.execution_policy；失败时会补充 error_details，取消时会补充 cancel_requested_at 和 cancelled_by |

补充说明：

- 对 image_base64、preview_image_base64 一类大字段，记录资源会返回对应的 _redacted 标记，不保留原始 base64 文本。
- 对 memory image-ref，记录资源会保留 transport_kind、media_type、width、height 等摘要字段，但不会返回 image_handle。

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs

- Content-Type：application/json
- 成功状态码：201 Created
- 仅支持已经处于 running 的 WorkflowAppRuntime
- 当前仍采用单实例串行执行；如果前一条 run 仍在执行，新建 run 会先进入 queued
- 返回完整 WorkflowRun 合同

### 请求体字段

- input_bindings：可选，按 application input binding_id 组织的输入 payload
- execution_metadata：可选，执行元数据；接口层会补写 created_by，服务层会补写 trigger_source=async-invoke
- timeout_seconds：可选，覆盖 runtime 默认 request_timeout_seconds；若省略且 runtime 已绑定 execution policy，则取 policy.default_timeout_seconds；显式值必须大于 0

### 最小请求 JSON

```json
{
  "input_bindings": {
    "request_image": {
      "object_key": "projects/project-1/files/demo/input/sample-1.jpg"
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
- 当前 multipart 文件上传只支持 `dataset-package.v1` 输入绑定，不支持把图片文件直接作为 `request_image` 上传
- 返回完整 WorkflowRun 合同

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
    "request_image": {
      "object_key": "projects/project-1/files/demo/input/sample-1.jpg"
    }
  },
  "outputs": {},
  "template_outputs": {},
  "node_records": [],
  "error_message": null,
  "metadata": {
    "trigger_source": "async-invoke",
    "created_by": "operator-1",
    "execution_policy": {
      "execution_policy_id": "runtime-default-policy",
      "policy_kind": "runtime-default",
      "trace_level": "node-summary",
      "retain_node_records_enabled": true,
      "retain_trace_enabled": true,
      "snapshot_object_key": "workflows/runtime/app-runtimes/workflow-runtime-1/execution-policy.snapshot.json"
    }
  }
}
```

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke

- Content-Type：application/json
- 成功状态码：200 OK
- 仅支持 observed_state=running 的 WorkflowAppRuntime
- 返回完整 WorkflowRun 合同

### 请求体字段

- input_bindings：可选，按 application input binding_id 组织的输入 payload
- execution_metadata：可选，执行元数据；接口层会补写 created_by
- timeout_seconds：可选，覆盖 runtime 默认 request_timeout_seconds；若省略且 runtime 已绑定 execution policy，则取 policy.default_timeout_seconds；显式值必须大于 0

### 最小请求 JSON

```json
{
  "input_bindings": {
    "request_image": {
      "object_key": "projects/project-1/files/demo/input/sample-1.jpg"
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
- 当前 multipart 文件上传只支持 `dataset-package.v1` 输入绑定，不支持把图片文件直接作为 `request_image` 上传
- 返回完整 WorkflowRun 合同

### 最小响应 JSON

```json
{
  "format_id": "amvision.workflow-run.v1",
  "workflow_run_id": "workflow-run-1",
  "workflow_runtime_id": "workflow-runtime-1",
  "project_id": "project-1",
  "application_id": "inspection-app",
  "state": "succeeded",
  "created_at": "2026-05-08T12:03:00Z",
  "started_at": "2026-05-08T12:03:00Z",
  "finished_at": "2026-05-08T12:03:02Z",
  "created_by": "operator-1",
  "requested_timeout_seconds": 60,
  "assigned_process_id": 12345,
  "input_payload": {
    "request_image": {
      "object_key": "projects/project-1/files/demo/input/sample-1.jpg"
    }
  },
  "outputs": {
    "api-return": {
      "status_code": 200,
      "body": {
        "ok": true
      }
    }
  },
  "template_outputs": {
    "inspection_response": {
      "ok": true
    }
  },
  "node_records": [],
  "error_message": null,
  "metadata": {
    "trigger_source": "sync-api",
    "created_by": "operator-1",
    "execution_policy": {
      "execution_policy_id": "runtime-default-policy",
      "policy_kind": "runtime-default",
      "trace_level": "node-summary",
      "retain_node_records_enabled": true,
      "retain_trace_enabled": true,
      "snapshot_object_key": "workflows/runtime/app-runtimes/workflow-runtime-1/execution-policy.snapshot.json"
    }
  }
}
```

### 失败返回规则

- worker 执行失败时，state 返回 failed，error_message 返回摘要信息。
- worker 返回的详细错误会写入 metadata.error_details，例如 node_id、node_type_id、runtime_kind、error_type 和 error_message。
- worker 等待超时时，state 返回 timed_out，error_message 返回超时摘要。
- async run 在 queued 或 running 期间被取消时，state 返回 cancelled，error_message 返回 workflow run 已取消。

## GET /api/v1/workflows/runs/{workflow_run_id}

- 返回单条 WorkflowRun 的当前持久化结果
- 适合回查输入、输出、node_records、assigned_process_id、error_message 和 metadata.error_details

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
- [docs/api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/app-runtime.invoke.request.json](examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/app-runtime.invoke.request.json)
- [docs/api/postman/workflow-runtime.postman_collection.json](postman/workflow-runtime.postman_collection.json)
- [docs/architecture/workflow-runtime-phase1.md](../architecture/workflow-runtime-phase1.md)