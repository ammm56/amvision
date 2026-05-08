# WorkflowPreviewRun 接口文档

## 文档目的

本文档说明当前已经公开的 WorkflowPreviewRun REST API、状态语义和稳定返回字段。

本文档只描述当前真实实现的 preview run 行为，不展开未落代码的扩展接口。

## 当前公开范围

- POST /api/v1/workflows/preview-runs
- GET /api/v1/workflows/preview-runs/{preview_run_id}
- saved application 引用执行
- inline application + template snapshot 执行

## 资源定位

- WorkflowPreviewRun 用于节点编辑器里的快速试跑、联调和隔离执行。
- 每次 create 请求都会先固定 application snapshot 和 template snapshot，再在独立子进程里执行。
- preview run 是短期调试资源，不进入长期 runtime worker 的实例管理。
- 第一阶段只支持同步等待结果，不公开 async preview、events 和 cancel。
- WorkflowPreviewRun 返回的是持久化记录视图；如果节点图里出现 inline base64 图片或 memory image-ref，资源返回会自动脱敏，不直接回显原始图片内容或 image_handle。

## 接口入口

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：/api/v1/workflows/preview-runs
- 稳定合同：amvision.workflow-preview-run.v1

## 鉴权规则

- POST /api/v1/workflows/preview-runs 需要 workflows:write
- GET /api/v1/workflows/preview-runs/{preview_run_id} 需要 workflows:read

## 状态语义

| 状态 | 说明 |
| --- | --- |
| created | 记录已创建，子进程尚未开始执行 |
| running | 子进程正在执行固定 snapshot |
| succeeded | 同步执行成功结束 |
| failed | 执行失败 |
| timed_out | 同步等待超时 |

补充说明：

- create 接口是同步接口，正常调用方通常直接拿到 succeeded、failed 或 timed_out。
- 当 create 请求尚未返回时，其他查询方可能会通过 GET 看到 running。

## 稳定字段

| 字段 | 说明 |
| --- | --- |
| format_id | 固定为 amvision.workflow-preview-run.v1 |
| preview_run_id | preview 资源 id |
| project_id | 所属 Project id |
| application_id | 实际执行的 FlowApplication id |
| source_kind | 来源类型，当前为 saved-application 或 inline-snapshot |
| application_snapshot_object_key | 固定 application snapshot 的 object key |
| template_snapshot_object_key | 固定 template snapshot 的 object key |
| state | 当前 preview run 状态 |
| created_at | 记录创建时间 |
| started_at | 子进程开始执行时间，可为空 |
| finished_at | 子进程结束时间，可为空 |
| created_by | 创建主体 id，可为空 |
| timeout_seconds | 本次同步等待超时秒数 |
| outputs | 按 application output binding_id 组织的输出；inline base64 图片会改写为 redacted 标记 |
| template_outputs | 按 template output id 组织的底层输出；inline base64 图片会改写为 redacted 标记 |
| node_records | 节点执行记录列表；当前包含 inputs 和 outputs 的脱敏快照 |
| error_message | 失败或超时时的摘要信息，可为空 |
| retention_until | 建议清理时间，可为空 |
| metadata | 调用附加元数据；接口层会补写 created_by；当绑定 execution policy 时还会补写 metadata.execution_policy 摘要 |

补充说明：

- 对 image_base64、preview_image_base64 一类大字段，记录资源会返回对应的 _redacted 标记，不保留原始 base64 文本。
- 对 memory image-ref，记录资源会保留 transport_kind、media_type、width、height 等摘要字段，但不会返回 image_handle。

## POST /api/v1/workflows/preview-runs

- Content-Type：application/json
- 成功状态码：201 Created
- 返回完整 WorkflowPreviewRun 合同

### 请求体字段

- project_id：必填，所属 Project id
- application_ref：可选，引用已保存 FlowApplication；当前只支持 application_id
- execution_policy_id：可选，引用一条已保存 WorkflowExecutionPolicy
- application：可选，inline FlowApplication snapshot
- template：可选，inline WorkflowGraphTemplate snapshot
- input_bindings：可选，按 application input binding_id 组织的输入 payload
- execution_metadata：可选，执行元数据；接口层会补写 created_by
- timeout_seconds：可选；未提供且存在 execution policy 时取 policy.default_timeout_seconds，否则默认 30

### 输入约束

- application_ref 与 inline application/template 二选一。
- 如果未提供 application_ref，则必须同时提供 application 和 template。
- 当前不公开 wait_mode 或 async query_path。

### 最小请求 JSON

```json
{
  "project_id": "project-1",
  "execution_policy_id": "preview-default-policy",
  "application_ref": {
    "application_id": "inspection-demo-app"
  },
  "input_bindings": {
    "request_image": {
      "object_key": "projects/project-1/files/demo/input/sample-1.jpg"
    }
  },
  "execution_metadata": {
    "trigger_source": "editor-preview"
  }
}
```

### 最小响应 JSON

```json
{
  "format_id": "amvision.workflow-preview-run.v1",
  "preview_run_id": "preview-run-1",
  "project_id": "project-1",
  "application_id": "inspection-demo-app",
  "source_kind": "saved-application",
  "application_snapshot_object_key": "workflows/runtime/preview-runs/preview-run-1/application.snapshot.json",
  "template_snapshot_object_key": "workflows/runtime/preview-runs/preview-run-1/template.snapshot.json",
  "state": "succeeded",
  "created_at": "2026-05-08T12:00:00Z",
  "started_at": "2026-05-08T12:00:00Z",
  "finished_at": "2026-05-08T12:00:02Z",
  "created_by": "editor-user",
  "timeout_seconds": 30,
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
  "retention_until": "2026-05-09T12:00:00Z",
  "metadata": {
    "trigger_source": "editor-preview",
    "created_by": "editor-user",
    "execution_policy": {
      "execution_policy_id": "preview-default-policy",
      "policy_kind": "preview-default",
      "trace_level": "summary",
      "retain_node_records_enabled": true,
      "retain_trace_enabled": true,
      "snapshot_object_key": "workflows/runtime/preview-runs/preview-run-1/execution-policy.snapshot.json"
    }
  }
}
```

## GET /api/v1/workflows/preview-runs/{preview_run_id}

- 返回单条 WorkflowPreviewRun 的当前持久化结果
- 返回字段与 create 接口一致
- 典型用途：在 create 请求执行期间回查 running，或在返回后再次读取 outputs、node_records 和 error_message

## 当前不公开的扩展项

- GET /api/v1/workflows/preview-runs/{preview_run_id}/events
- POST /api/v1/workflows/preview-runs/{preview_run_id}/cancel
- async preview create

## 与其他资源的关系

- WorkflowPreviewRun 与 WorkflowRun 分开建模：前者用于编辑器试跑，后者用于已发布 runtime 的正式调用。
- WorkflowPreviewRun 当前可以引用 [docs/api/workflow-execution-policies.md](workflow-execution-policies.md) 中的 execution_policy_id；接口返回会把应用到本次执行的策略摘要写入 metadata.execution_policy。
- preview run 不替代 [docs/api/workflows.md](workflows.md) 里的 template/application validate、save、get 接口。
- 已发布应用的长期运行和同步调用见 [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md) 与 [docs/api/workflow-runs.md](workflow-runs.md)。

## 相关文档

- [docs/api/current-api.md](current-api.md)
- [docs/api/workflows.md](workflows.md)
- [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md)
- [docs/api/workflow-runs.md](workflow-runs.md)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.preview-run.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.preview-run.request.json)
- [docs/api/postman/workflow-runtime.postman_collection.json](postman/workflow-runtime.postman_collection.json)
- [docs/architecture/workflow-runtime-phase1.md](../architecture/workflow-runtime-phase1.md)