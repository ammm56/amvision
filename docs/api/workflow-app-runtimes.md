# WorkflowAppRuntime 接口文档

## 文档目的

本文档说明当前已经公开的 WorkflowAppRuntime REST API、状态语义和稳定返回字段。

本文档描述当前已经公开的 WorkflowAppRuntime 行为，包括第一阶段最小运行面，以及第二阶段已经落地的 restart、instances 和 execution policy 最小接入。

## 当前公开范围

- POST /api/v1/workflows/app-runtimes
- GET /api/v1/workflows/app-runtimes
- GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/start
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart
- GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health
- GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/instances

## 资源定位

- WorkflowAppRuntime 表示一份已发布应用的长期运行单元。
- runtime 创建时会固定 application snapshot 和 template snapshot；如果提供 execution_policy_id，还会额外固定 execution policy snapshot。
- 当前仍采用单 runtime 单实例单进程模型，已经公开 restart 和 instances，但不公开 scale。
- runtime worker 提供 start、stop、health 和执行宿主能力；sync invoke 与 async WorkflowRun 都复用同一份固定 snapshot。

## 接口入口

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：/api/v1/workflows/app-runtimes
- 稳定合同：amvision.workflow-app-runtime.v1

## 鉴权规则

- create、start、stop、restart 需要 workflows:write
- list、get、health、instances 需要 workflows:read

## 状态语义

### desired_state

- stopped：期望 runtime 未运行
- running：期望 runtime 已运行

### observed_state

- stopped：当前没有活动 worker 进程
- running：worker 已启动并完成 snapshot 装载
- failed：worker 启动失败、健康检查失败或最近一次 invoke 让 worker 进入失败态

补充说明：

- 领域状态机内部允许 starting 和 stopping，但第一阶段 HTTP start/stop 是同步接口，接口返回时通常已经落到 running、stopped 或 failed。
- health 接口会刷新 observed_state、heartbeat_at、worker_process_id 和 loaded_snapshot_fingerprint。

## 稳定字段

| 字段 | 说明 |
| --- | --- |
| format_id | 固定为 amvision.workflow-app-runtime.v1 |
| workflow_runtime_id | runtime 资源 id |
| project_id | 所属 Project id |
| application_id | 来源 FlowApplication id |
| display_name | 展示名称 |
| application_snapshot_object_key | 固定 application snapshot 的 object key |
| template_snapshot_object_key | 固定 template snapshot 的 object key |
| execution_policy_snapshot_object_key | 固定 execution policy snapshot 的 object key，可为空 |
| desired_state | 当前期望状态 |
| observed_state | 当前观测状态 |
| request_timeout_seconds | 默认同步调用超时秒数 |
| created_at | 记录创建时间 |
| updated_at | 最近一次状态更新或健康刷新时间 |
| created_by | 创建主体 id，可为空 |
| last_started_at | 最近一次成功 start 时间，可为空 |
| last_stopped_at | 最近一次 stop 时间，可为空 |
| heartbeat_at | 最近一次 worker 心跳时间，可为空 |
| worker_process_id | 当前 worker 进程 id，可为空 |
| loaded_snapshot_fingerprint | 当前 worker 已装载的 snapshot 指纹，可为空 |
| last_error | 最近一次错误摘要，可为空 |
| health_summary | 健康附加信息；当前至少包含 mode |
| metadata | 创建时附加元数据；当绑定 execution policy 时还会补写 metadata.execution_policy 摘要 |

## POST /api/v1/workflows/app-runtimes

- Content-Type：application/json
- 成功状态码：201 Created
- 返回完整 WorkflowAppRuntime 合同

### 请求体字段

- project_id：必填，所属 Project id
- application_id：必填，已保存 FlowApplication id
- execution_policy_id：可选，引用一条已保存 WorkflowExecutionPolicy
- display_name：可选，展示名称
- request_timeout_seconds：可选；未提供且存在 execution policy 时取 policy.default_timeout_seconds，否则默认 60
- metadata：可选，附加元数据

### 最小请求 JSON

```json
{
  "project_id": "project-1",
  "application_id": "inspection-app",
  "execution_policy_id": "runtime-default-policy",
  "display_name": "Inspection Runtime",
  "metadata": {
    "line_id": "line-1"
  }
}
```

### 最小响应 JSON

```json
{
  "format_id": "amvision.workflow-app-runtime.v1",
  "workflow_runtime_id": "workflow-runtime-1",
  "project_id": "project-1",
  "application_id": "inspection-app",
  "display_name": "Inspection Runtime",
  "application_snapshot_object_key": "workflows/runtime/app-runtimes/workflow-runtime-1/application.snapshot.json",
  "template_snapshot_object_key": "workflows/runtime/app-runtimes/workflow-runtime-1/template.snapshot.json",
  "execution_policy_snapshot_object_key": "workflows/runtime/app-runtimes/workflow-runtime-1/execution-policy.snapshot.json",
  "desired_state": "stopped",
  "observed_state": "stopped",
  "request_timeout_seconds": 60,
  "created_at": "2026-05-08T12:00:00Z",
  "updated_at": "2026-05-08T12:00:00Z",
  "created_by": "operator-1",
  "last_started_at": null,
  "last_stopped_at": null,
  "heartbeat_at": null,
  "worker_process_id": null,
  "loaded_snapshot_fingerprint": null,
  "last_error": null,
  "health_summary": {},
  "metadata": {
    "line_id": "line-1",
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

## GET /api/v1/workflows/app-runtimes

- 需要显式提供查询参数 project_id
- 返回当前 Project 下的 WorkflowAppRuntime 列表
- 第一阶段列表项返回完整 WorkflowAppRuntime 合同，不只返回摘要字段

## GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}

- 返回单条 WorkflowAppRuntime 的当前持久化记录
- 不会主动刷新 worker 健康状态；如果需要最新 process_id、heartbeat_at 或 fingerprint，应调用 health 接口

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/start

- 成功状态码：200 OK
- 返回更新后的 WorkflowAppRuntime 合同
- 接口返回时通常已经落到 observed_state=running 或 observed_state=failed

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop

- 成功状态码：200 OK
- 返回更新后的 WorkflowAppRuntime 合同
- stop 成功后通常会把 worker_process_id 清空，并把 observed_state 落到 stopped

## POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart

- 成功状态码：200 OK
- 返回更新后的 WorkflowAppRuntime 合同
- 当前语义固定为先停止当前单实例 worker，再重新加载同一组固定 snapshot
- restart 后通常会刷新 last_started_at、last_stopped_at、heartbeat_at、worker_process_id 和 loaded_snapshot_fingerprint

## GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health

- 成功状态码：200 OK
- 返回刷新后的 WorkflowAppRuntime 合同
- 当前重点字段：observed_state、heartbeat_at、worker_process_id、loaded_snapshot_fingerprint、last_error、health_summary

## GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/instances

- 成功状态码：200 OK
- 返回当前 runtime 下面可观测的 instance 列表
- 当前单实例模型下，running 或 failed 且 worker 仍存活时通常返回 1 条；stopped 或已经被清理的 worker 返回空列表
- 当前稳定合同：amvision.workflow-app-runtime-instance.v1

### instances 稳定字段

| 字段 | 说明 |
| --- | --- |
| format_id | 固定为 amvision.workflow-app-runtime-instance.v1 |
| instance_id | 当前单实例 runtime 的逻辑实例 id |
| workflow_runtime_id | 所属 WorkflowAppRuntime id |
| state | 当前观测状态 |
| process_id | 当前 worker 进程 id，可为空 |
| current_run_id | 当前正在执行的 WorkflowRun id；当前同步模型下通常为空 |
| started_at | 当前实例最近一次启动时间，可为空 |
| heartbeat_at | 当前实例最近一次心跳时间，可为空 |
| loaded_snapshot_fingerprint | 当前实例已装载 snapshot 指纹，可为空 |
| last_error | 当前实例最近一次错误摘要，可为空 |
| health_summary | 当前健康附加信息；当前至少包含 mode |

## 当前不公开的扩展项

- min/max instance 扩缩容控制
- activation_mode、restart_policy

## 与其他资源的关系

- WorkflowAppRuntime 是 [docs/api/workflow-runs.md](workflow-runs.md) 的宿主资源。
- 当前同步调用入口仍挂在 runtime 下：POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke。
- WorkflowAppRuntime create 当前可以引用 [docs/api/workflow-execution-policies.md](workflow-execution-policies.md) 中的 execution_policy_id，并返回 execution_policy_snapshot_object_key。
- 编辑态试跑见 [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)。

## invoke 输入输出约定

- invoke 请求体中的 `input_bindings` 按 application `binding_id` 组织，而不是按 template `input_id` 或节点 id 组织。
- `image-ref.v1` 常见 JSON 形状是 `{"object_key": "inputs/source.jpg", "media_type": "image/png"}`；如果省略 `transport_kind`，当前实现会按 `object_key` 自动识别为 storage 引用。
- `image-base64.v1` 常见 JSON 形状是 `{"image_base64": "<base64>", "media_type": "image/png"}`；也支持单行 data URL。
- `image-ref.v1` 在本机受控 adapter 或 TriggerSource 场景下也可以携带 `buffer_ref` 或 `frame_ref`，用于复用 LocalBufferBroker 的 direct mmap 数据面；这类引用只在同机短期有效，不作为长期公开文件引用。
- `value.v1` 常见 JSON 形状是 `{"value": {...}}`。
- `dataset-package.v1` 通过 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload` 上传，文件字段名必须等于 binding_id。当前 multipart 上传入口只支持这类 zip 包输入，不支持把图片文件直接作为 `request_image` 上传。
- invoke 返回体是 `WorkflowRunContract`。如果 application 输出绑定是 `workflow-execute-output`，结果会直接出现在 `outputs[binding_id]`；如果输出绑定是 `http-response`，结果会出现在 `outputs[binding_id] = {"status_code": ..., "body": ...}`。

## 相关文档

- [docs/api/current-api.md](current-api.md)
- [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)
- [docs/api/workflow-runs.md](workflow-runs.md)
- [docs/api/workflows.md](workflows.md)
- [docs/api/postman/workflows/README.md](postman/workflows/README.md)
- [docs/api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/app-runtime.create.request.json](examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/app-runtime.create.request.json)
- [docs/api/postman/workflow-runtime.postman_collection.json](postman/workflow-runtime.postman_collection.json)
- [docs/architecture/workflow-runtime-phase1.md](../architecture/workflow-runtime-phase1.md)
- [docs/architecture/workflow-runtime-phase2.md](../architecture/workflow-runtime-phase2.md)