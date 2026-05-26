# ToolPolicy 接口草案

## 文档目的

本文档用于说明 ToolPolicy 资源的 REST API 草案。

本文档只收敛资源边界、请求响应草案和最小字段，不表示当前主干已经公开或已经实现这些接口。

## 适用范围

- ToolPolicy 资源定位
- create、list、get 三组接口草案
- 请求字段、响应字段和最小 JSON 示例
- 与 WorkflowExecutionPolicy、AI 节点和工具调用 trace 的关系

## 当前边界

- ToolPolicy 用于表达 AI 节点可使用的工具集合和调用上限。
- ToolPolicy 主要服务于未来的 LLM / agent 节点，不负责 PLC、运动控制、传感器或其他硬件权限控制。
- 是否真正调用某个硬件或协议，仍由对应 custom node 的实现和节点选择决定。
- 当前资源属于 workflow runtime 控制面草案，不进入 current-api 总览。

## 接口入口

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：/api/v1/workflows/tool-policies
- 当前状态：接口草案，尚未公开

## 鉴权草案

- list 和 get 建议使用 workflows:read
- create 建议使用 workflows:write

## 资源字段草案

- tool_policy_id
- display_name
- enabled_tool_ids
- max_tool_calls_per_run
- parallel_tool_calls_enabled
- metadata

## 接口清单

### POST /api/v1/workflows/tool-policies

- Content-Type：application/json
- 建议需要 workflows:write
- 用途：创建一条可复用的 ToolPolicy

#### 请求字段

- tool_policy_id
- display_name
- enabled_tool_ids
- max_tool_calls_per_run
- parallel_tool_calls_enabled
- metadata

#### 响应字段

- tool_policy_id
- display_name
- enabled_tool_ids
- max_tool_calls_per_run
- parallel_tool_calls_enabled
- metadata

#### 最小请求 JSON

```json
{
  "tool_policy_id": "vision-agent-tools-v1",
  "display_name": "Vision Agent Tools",
  "enabled_tool_ids": [
    "workflow.read-run-trace",
    "workflow.search-node-catalog",
    "workflow.create-workflow-draft"
  ],
  "max_tool_calls_per_run": 8,
  "parallel_tool_calls_enabled": false,
  "metadata": {
    "notes": "服务于受控 AI 节点，不参与硬件权限判断"
  }
}
```

#### 最小响应 JSON

```json
{
  "tool_policy_id": "vision-agent-tools-v1",
  "display_name": "Vision Agent Tools",
  "enabled_tool_ids": [
    "workflow.read-run-trace",
    "workflow.search-node-catalog",
    "workflow.create-workflow-draft"
  ],
  "max_tool_calls_per_run": 8,
  "parallel_tool_calls_enabled": false,
  "metadata": {
    "notes": "服务于受控 AI 节点，不参与硬件权限判断"
  }
}
```

### GET /api/v1/workflows/tool-policies

- 建议需要 workflows:read
- 用途：列出可用 ToolPolicy 摘要

#### 列表项建议字段

- tool_policy_id
- display_name
- enabled_tool_ids
- max_tool_calls_per_run
- parallel_tool_calls_enabled

### GET /api/v1/workflows/tool-policies/{tool_policy_id}

- 建议需要 workflows:read
- 用途：查询单条 ToolPolicy 详情

#### 详情建议字段

- tool_policy_id
- display_name
- enabled_tool_ids
- max_tool_calls_per_run
- parallel_tool_calls_enabled
- metadata

## 与其他资源的关系

- WorkflowExecutionPolicy 可以引用 tool_policy_id。
- ToolPolicy 为 AI 节点提供默认工具集合，不改变 workflow 图中的普通 service 节点或 custom node 语义。
- 如果 workflow run 存在 AI tool 调用，建议在 WorkflowRun trace 中记录 tool 调用链。

## 相关文档

- [docs/architecture/workflow-runtime.md](../architecture/workflow-runtime.md)
- [docs/api/workflow-execution-policies.md](workflow-execution-policies.md)
- [docs/api/workflow-persona-profiles.md](workflow-persona-profiles.md)