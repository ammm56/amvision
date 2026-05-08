# WorkflowRun 接口文档

## 文档目的

本文档说明当前已经公开的 WorkflowRun REST API、状态语义和稳定返回字段。

本文档只描述 workflow runtime 第一阶段已经实现的行为，不展开未落代码的扩展接口。

## 当前公开范围

- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke
- GET /api/v1/workflows/runs/{workflow_run_id}
- sync invoke 对应的 WorkflowRun 持久化记录

## 资源定位

- WorkflowRun 表示已发布应用的一次正式调用。
- 第一阶段只支持 sync invoke，不公开异步 runs 创建接口。
- invoke 请求返回前，WorkflowRun 会先写入数据库，再落到 succeeded、failed 或 timed_out。
- WorkflowRun 与 WorkflowPreviewRun 分开建模：前者面向已发布 runtime 的正式调用，后者面向编辑器里的快速试跑。

## 接口入口

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：
  - /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke
  - /api/v1/workflows/runs/{workflow_run_id}
- 稳定合同：amvision.workflow-run.v1

## 鉴权规则

- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke 需要 workflows:write
- GET /api/v1/workflows/runs/{workflow_run_id} 需要 workflows:read

## 状态语义

| 状态 | 说明 |
| --- | --- |
| created | 记录已创建 |
| dispatching | runtime 已收到请求，正在转给 worker |
| running | worker 正在执行固定 snapshot |
| succeeded | 同步调用成功结束 |
| failed | 调用失败 |
| timed_out | 调用超时 |

补充说明：

- invoke 是同步接口，调用方通常直接拿到 succeeded、failed 或 timed_out。
- 在 invoke 请求执行期间，其他查询方可能会通过 GET 看到 dispatching 或 running。
- 当 invoke 结果为 failed 或 timed_out 时，HTTP 响应仍返回 200，并通过 WorkflowRun.state 表达执行结果。

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
| requested_timeout_seconds | 本次同步调用的超时秒数 |
| assigned_process_id | 执行该 run 的 worker 进程 id，可为空 |
| input_payload | 本次 invoke 的输入 payload |
| outputs | 按 application output binding_id 组织的输出 |
| template_outputs | 按 template output id 组织的底层输出 |
| node_records | 节点执行记录列表 |
| error_message | 失败或超时时的摘要信息，可为空 |
| metadata | 调用附加元数据；失败时会补充 error_details |

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke

- Content-Type：application/json
- 成功状态码：200 OK
- 仅支持 observed_state=running 的 WorkflowAppRuntime
- 返回完整 WorkflowRun 合同

### 请求体字段

- input_bindings：可选，按 application input binding_id 组织的输入 payload
- execution_metadata：可选，执行元数据；接口层会补写 created_by
- timeout_seconds：可选，覆盖 runtime 默认 request_timeout_seconds，必须大于 0

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
  },
  "timeout_seconds": 60
}
```

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
    "created_by": "operator-1"
  }
}
```

### 失败返回规则

- worker 执行失败时，state 返回 failed，error_message 返回摘要信息。
- worker 返回的详细错误会写入 metadata.error_details，例如 node_id、node_type_id、runtime_kind、error_type 和 error_message。
- worker 等待超时时，state 返回 timed_out，error_message 返回超时摘要。

## GET /api/v1/workflows/runs/{workflow_run_id}

- 返回单条 WorkflowRun 的当前持久化结果
- 适合回查输入、输出、node_records、assigned_process_id、error_message 和 metadata.error_details

## 当前不公开的扩展项

- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs
- GET /api/v1/workflows/runs/{workflow_run_id}/events
- POST /api/v1/workflows/runs/{workflow_run_id}/cancel
- schedule、integration trigger_source 的对外创建接口

## 与其他资源的关系

- WorkflowRun 依附于 [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md) 创建和执行。
- 编辑态试跑结果见 [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)。
- template/application 的保存和校验入口见 [docs/api/workflows.md](workflows.md)。

## 相关文档

- [docs/api/current-api.md](current-api.md)
- [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md)
- [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)
- [docs/api/workflows.md](workflows.md)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.invoke.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.invoke.request.json)
- [docs/api/postman/workflow-runtime.postman_collection.json](postman/workflow-runtime.postman_collection.json)
- [docs/architecture/workflow-runtime-phase1.md](../architecture/workflow-runtime-phase1.md)