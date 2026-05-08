# WorkflowExecutionPolicy 接口草案

## 文档目的

本文档用于说明 WorkflowExecutionPolicy 资源的 REST API 草案。

本文档只收敛资源边界、请求响应草案和最小字段，不表示当前主干已经公开或已经实现这些接口。

## 适用范围

- WorkflowExecutionPolicy 资源定位
- create、list、get 三组接口草案
- 请求字段、响应字段和最小 JSON 示例
- 与 Workflow runtime、PersonaProfile 和 ToolPolicy 的关系

## 当前边界

- WorkflowExecutionPolicy 主要用于表达 preview 和 runtime 的执行默认项。
- 当前资源不负责 PLC、运动控制、传感器接入或结果上报的硬件权限控制。
- 这类硬件或外部系统行为继续由 custom node 或 node pack 本身决定。
- 当前资源更适合承接 timeout、trace、node_records 保留方式、max_agent_steps，以及默认绑定哪一份 PersonaProfile 和 ToolPolicy。
- 当前资源属于 workflow runtime 控制面草案，不进入 current-api 总览。

## 接口入口

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：/api/v1/workflows/execution-policies
- 当前状态：接口草案，尚未公开

## 鉴权草案

- list 和 get 建议使用 workflows:read
- create 建议使用 workflows:write

当前阶段不单独拆 execution-policies 专用 scope，避免过早把控制面权限做复杂。

## 资源字段草案

- execution_policy_id
- display_name
- policy_kind，取值建议为 preview-default 或 runtime-default
- default_timeout_seconds
- trace_level，取值建议为 none、summary、node-summary、full
- retain_node_records_enabled
- retain_trace_enabled
- persona_profile_id，可选
- tool_policy_id，可选
- max_run_timeout_seconds
- max_agent_steps
- metadata

## 接口清单

### POST /api/v1/workflows/execution-policies

- Content-Type：application/json
- 建议需要 workflows:write
- 用途：创建一条可复用的 WorkflowExecutionPolicy

#### 请求字段

- execution_policy_id
- display_name
- policy_kind
- default_timeout_seconds
- trace_level
- retain_node_records_enabled
- retain_trace_enabled
- persona_profile_id，可选
- tool_policy_id，可选
- max_run_timeout_seconds
- max_agent_steps
- metadata

#### 响应字段

- execution_policy_id
- display_name
- policy_kind
- default_timeout_seconds
- trace_level
- retain_node_records_enabled
- retain_trace_enabled
- persona_profile_id
- tool_policy_id
- max_run_timeout_seconds
- max_agent_steps
- metadata

#### 最小请求 JSON

```json
{
  "execution_policy_id": "preview-default",
  "display_name": "Preview Default",
  "policy_kind": "preview-default",
  "default_timeout_seconds": 30,
  "trace_level": "node-summary",
  "retain_node_records_enabled": true,
  "retain_trace_enabled": true,
  "persona_profile_id": null,
  "tool_policy_id": null,
  "max_run_timeout_seconds": 30,
  "max_agent_steps": 0,
  "metadata": {
    "notes": "用于节点编辑器里的快速试跑"
  }
}
```

#### 最小响应 JSON

```json
{
  "execution_policy_id": "preview-default",
  "display_name": "Preview Default",
  "policy_kind": "preview-default",
  "default_timeout_seconds": 30,
  "trace_level": "node-summary",
  "retain_node_records_enabled": true,
  "retain_trace_enabled": true,
  "persona_profile_id": null,
  "tool_policy_id": null,
  "max_run_timeout_seconds": 30,
  "max_agent_steps": 0,
  "metadata": {
    "notes": "用于节点编辑器里的快速试跑"
  }
}
```

### GET /api/v1/workflows/execution-policies

- 建议需要 workflows:read
- 用途：列出当前 Project 下可用的 WorkflowExecutionPolicy 摘要

#### 列表项建议字段

- execution_policy_id
- display_name
- policy_kind
- default_timeout_seconds
- trace_level
- persona_profile_id
- tool_policy_id
- max_run_timeout_seconds
- max_agent_steps

### GET /api/v1/workflows/execution-policies/{execution_policy_id}

- 建议需要 workflows:read
- 用途：查询单条 WorkflowExecutionPolicy 详情

#### 详情建议字段

- execution_policy_id
- display_name
- policy_kind
- default_timeout_seconds
- trace_level
- retain_node_records_enabled
- retain_trace_enabled
- persona_profile_id
- tool_policy_id
- max_run_timeout_seconds
- max_agent_steps
- metadata

## 与其他资源的关系

- WorkflowPreviewRun 和 WorkflowAppRuntime 可以引用 execution_policy_id。
- PersonaProfile 和 ToolPolicy 是 WorkflowExecutionPolicy 的可选依赖资源。
- 该资源不替代 custom node 的节点参数，也不替代 node pack 自己的实现语义。

## 相关文档

- [docs/architecture/workflow-runtime.md](../architecture/workflow-runtime.md)
- [docs/api/workflows.md](workflows.md)
- [docs/api/workflow-persona-profiles.md](workflow-persona-profiles.md)
- [docs/api/workflow-tool-policies.md](workflow-tool-policies.md)