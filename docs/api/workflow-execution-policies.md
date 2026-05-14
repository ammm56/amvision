# WorkflowExecutionPolicy 接口文档

## 文档目的

本文档用于说明当前已经公开的 WorkflowExecutionPolicy REST API、稳定字段和最小边界。

本文档只描述当前真实实现，不展开 persona、tool policy 或 agent 控制面的后续接口。

## 适用范围

- WorkflowExecutionPolicy 资源定位
- create、list、get 三组接口
- 请求字段、响应字段和最小 JSON 示例
- 与 preview、runtime 的关系

## 当前边界

- WorkflowExecutionPolicy 主要用于表达 preview 和 runtime 的执行默认项。
- 当前已公开 create、list、get 三组接口，并允许 preview create 与 app runtime create 引用 execution_policy_id。
- 当前资源只覆盖 timeout、trace_level、node_records 保留策略和 trace 保留策略。
- 当前资源不负责 PLC、运动控制、传感器接入或结果上报的硬件权限控制。
- 这类硬件或外部系统行为继续由 custom node 或 node pack 本身决定。
- PersonaProfile、ToolPolicy 和 max_agent_steps 仍不进入当前实现范围。

## 接口入口

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：/api/v1/workflows/execution-policies
- 稳定合同：amvision.workflow-execution-policy.v1

## 鉴权规则

- GET /api/v1/workflows/execution-policies 需要 workflows:read
- GET /api/v1/workflows/execution-policies/{execution_policy_id} 需要 workflows:read
- POST /api/v1/workflows/execution-policies 需要 workflows:write

当前阶段不单独拆 execution-policies 专用 scope，避免过早把控制面权限做复杂。

## 稳定字段

- format_id，固定为 amvision.workflow-execution-policy.v1
- execution_policy_id
- project_id
- display_name
- policy_kind，当前取值为 preview-default 或 runtime-default
- default_timeout_seconds
- max_run_timeout_seconds
- trace_level
- retain_node_records_enabled
- retain_trace_enabled
- created_at
- updated_at
- created_by
- metadata

## 接口清单

## POST /api/v1/workflows/execution-policies

- Content-Type：application/json
- 用途：创建一条可复用的 WorkflowExecutionPolicy
- 成功状态码：201 Created

#### 请求字段

- execution_policy_id
- project_id
- display_name
- policy_kind
- default_timeout_seconds
- max_run_timeout_seconds
- trace_level
- retain_node_records_enabled
- retain_trace_enabled
- metadata

#### 响应字段

- execution_policy_id
- project_id
- display_name
- policy_kind
- default_timeout_seconds
- max_run_timeout_seconds
- trace_level
- retain_node_records_enabled
- retain_trace_enabled
- created_at
- updated_at
- created_by
- metadata

#### 最小请求 JSON

```json
{
  "project_id": "project-1",
  "execution_policy_id": "preview-default",
  "display_name": "Preview Default",
  "policy_kind": "preview-default",
  "default_timeout_seconds": 30,
  "max_run_timeout_seconds": 30,
  "trace_level": "node-summary",
  "retain_node_records_enabled": true,
  "retain_trace_enabled": true,
  "metadata": {
    "notes": "用于节点编辑器里的快速试跑"
  }
}
```

#### 最小响应 JSON

```json
{
  "format_id": "amvision.workflow-execution-policy.v1",
  "project_id": "project-1",
  "execution_policy_id": "preview-default",
  "display_name": "Preview Default",
  "policy_kind": "preview-default",
  "default_timeout_seconds": 30,
  "max_run_timeout_seconds": 30,
  "trace_level": "node-summary",
  "retain_node_records_enabled": true,
  "retain_trace_enabled": true,
  "created_at": "2026-05-08T12:00:00Z",
  "updated_at": "2026-05-08T12:00:00Z",
  "created_by": "operator-1",
  "metadata": {
    "notes": "用于节点编辑器里的快速试跑"
  }
}
```

## GET /api/v1/workflows/execution-policies

- 需要显式提供查询参数 project_id
- 用途：列出当前 Project 下可用的 WorkflowExecutionPolicy 摘要

### 列表项稳定字段

- execution_policy_id
- project_id
- display_name
- policy_kind
- default_timeout_seconds
- max_run_timeout_seconds
- trace_level
- retain_node_records_enabled
- retain_trace_enabled
- created_at
- updated_at

## GET /api/v1/workflows/execution-policies/{execution_policy_id}

- 用途：查询单条 WorkflowExecutionPolicy 详情

### 返回字段

- format_id
- execution_policy_id
- project_id
- display_name
- policy_kind
- default_timeout_seconds
- max_run_timeout_seconds
- trace_level
- retain_node_records_enabled
- retain_trace_enabled
- created_at
- updated_at
- created_by
- metadata

## 联调示例

- [docs/api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/preview-execution-policy.create.request.json](examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/preview-execution-policy.create.request.json)
- [docs/api/examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/runtime-execution-policy.create.request.json](examples/workflows/00-short-dev-examples/yolox_deployment_detection_lifecycle_real_path/runtime-execution-policy.create.request.json)
- [docs/api/postman/workflow-runtime.postman_collection.json](postman/workflow-runtime.postman_collection.json)

## 与其他资源的关系

- WorkflowPreviewRun create 可以引用 execution_policy_id；当前响应会把应用到本次执行的策略摘要写入 metadata.execution_policy。
- WorkflowAppRuntime create 可以引用 execution_policy_id；当前响应会返回 execution_policy_snapshot_object_key。
- WorkflowRun 不直接绑定 execution_policy_id，而是沿用宿主 WorkflowAppRuntime 固定的 policy snapshot。
- 该资源不替代 custom node 的节点参数，也不替代 node pack 自己的实现语义。

## 当前不公开的扩展项

- PUT /api/v1/workflows/execution-policies/{execution_policy_id}
- DELETE /api/v1/workflows/execution-policies/{execution_policy_id}
- persona_profile_id
- tool_policy_id
- max_agent_steps

## 相关文档

- [docs/architecture/workflow-runtime.md](../architecture/workflow-runtime.md)
- [docs/api/workflows.md](workflows.md)
- [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)
- [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md)
- [docs/api/workflow-persona-profiles.md](workflow-persona-profiles.md)
- [docs/api/workflow-tool-policies.md](workflow-tool-policies.md)