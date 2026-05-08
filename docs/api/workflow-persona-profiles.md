# PersonaProfile 接口草案

## 文档目的

本文档用于说明 PersonaProfile 资源的 REST API 草案。

本文档只收敛资源边界、请求响应草案和最小字段，不表示当前主干已经公开或已经实现这些接口。

## 适用范围

- PersonaProfile 资源定位
- create、list、get 三组接口草案
- 请求字段、响应字段和最小 JSON 示例
- 与 WorkflowExecutionPolicy 和 AI 节点的关系

## 当前边界

- PersonaProfile 用于表达 LLM、VLM 或 agent 节点使用的人格、口吻、系统提示模板和默认语言。
- PersonaProfile 不负责 workflow 图结构，不进入 WorkflowGraphTemplate 或 FlowApplication。
- PersonaProfile 不负责硬件控制策略，也不负责工具集合选择；工具集合由 ToolPolicy 表达。
- 当前资源属于 workflow runtime 控制面草案，不进入 current-api 总览。

## 接口入口

- 版本前缀：/api/v1
- 资源分组：/workflows
- 资源路径：/api/v1/workflows/persona-profiles
- 当前状态：接口草案，尚未公开

## 鉴权草案

- list 和 get 建议使用 workflows:read
- create 建议使用 workflows:write

## 资源字段草案

- persona_profile_id
- display_name
- role_name
- system_prompt_template
- style_preset
- response_language
- memory_mode，取值建议为 none、session、workflow-run
- metadata

## 接口清单

### POST /api/v1/workflows/persona-profiles

- Content-Type：application/json
- 建议需要 workflows:write
- 用途：创建一条可复用的 PersonaProfile

#### 请求字段

- persona_profile_id
- display_name
- role_name
- system_prompt_template
- style_preset
- response_language
- memory_mode
- metadata

#### 响应字段

- persona_profile_id
- display_name
- role_name
- system_prompt_template
- style_preset
- response_language
- memory_mode
- metadata

#### 最小请求 JSON

```json
{
  "persona_profile_id": "quality-inspector-v1",
  "display_name": "Quality Inspector",
  "role_name": "工业质检助手",
  "system_prompt_template": "对检测结果做简洁、直接、面向现场的说明。",
  "style_preset": "concise-industrial",
  "response_language": "zh-CN",
  "memory_mode": "session",
  "metadata": {
    "domain": "industrial-vision"
  }
}
```

#### 最小响应 JSON

```json
{
  "persona_profile_id": "quality-inspector-v1",
  "display_name": "Quality Inspector",
  "role_name": "工业质检助手",
  "system_prompt_template": "对检测结果做简洁、直接、面向现场的说明。",
  "style_preset": "concise-industrial",
  "response_language": "zh-CN",
  "memory_mode": "session",
  "metadata": {
    "domain": "industrial-vision"
  }
}
```

### GET /api/v1/workflows/persona-profiles

- 建议需要 workflows:read
- 用途：列出可用 PersonaProfile 摘要

#### 列表项建议字段

- persona_profile_id
- display_name
- role_name
- style_preset
- response_language
- memory_mode

### GET /api/v1/workflows/persona-profiles/{persona_profile_id}

- 建议需要 workflows:read
- 用途：查询单条 PersonaProfile 详情

#### 详情建议字段

- persona_profile_id
- display_name
- role_name
- system_prompt_template
- style_preset
- response_language
- memory_mode
- metadata

## 与其他资源的关系

- WorkflowExecutionPolicy 可以引用 persona_profile_id。
- AI 节点可以直接引用 persona_profile_id，或间接通过 execution policy 获得默认值。
- PersonaProfile 不替代节点参数；节点仍可以覆盖 prompt、语言或输出风格。

## 相关文档

- [docs/architecture/workflow-runtime.md](../architecture/workflow-runtime.md)
- [docs/api/workflow-execution-policies.md](workflow-execution-policies.md)
- [docs/api/workflow-tool-policies.md](workflow-tool-policies.md)