# WebSocket 架构

## 文档目的

本文档用于定义 backend-service 的 WebSocket 子系统边界，回答 WebSocket 在项目里做什么、不做什么、如何按版本和资源组织，以及如何与 REST 一起组成完整公开通信面。

本文档也用于回答 workflow preview events 应该放在哪一层，避免为了单个功能继续扩出割裂的专用 socket。

如果需要按客户端实现视角直接接入第三方系统、HMI、嵌入式 UI 或前端界面，连接顺序和恢复流程见 [docs/api/websocket-usage.md](../api/websocket-usage.md)。

## 适用范围

- backend-service 对浏览器前端和外部订阅方公开的 WebSocket 路由
- WebSocket 的路由组织、版本化方式、鉴权、筛选字段和连接行为
- 任务、workflow runtime、deployment 和 system 事件流的统一分层
- 事件重放、断线重连、流量控制和当前本地优先实现的约束

## 当前结论

- WebSocket 是与 REST 并列的公开通信面，不为单个功能临时开特例。
- 公开资源应按“REST 快照 + WebSocket 事件流”成对设计，而不是只提供其中一边。
- 第一阶段保持“一条连接只订阅一个资源流”的简单模型，不先引入单连接多订阅命令协议。
- workflow preview events 属于 workflow runtime 资源流，不单独再造 preview 专用 WebSocket 体系。
- backend-service 内部统一使用 service_event_bus 作为实时事件分发骨干，数据库、对象存储和运行时 manager 负责各自的回放面与状态快照。
- 当前不把 Redis、Kafka 这类外部消息中间件作为本地开发前提；“全局事件总线”指的是统一事件分发边界，不等于必须先上独立基础设施。

## 与其他通信边界的分工

更通用的通信职责拆分见 [docs/api/communication-contracts.md](../api/communication-contracts.md)。

### REST API

- 负责资源读写、详情查询、列表查询、管理动作和正式写入语义。
- 负责提供当前状态快照、结果摘要和可追溯资源引用。

### WebSocket

- 负责状态变化、进度、日志、节点执行过程、部署健康和低频系统事件。
- 不替代资源型查询，不承担正式写入，也不承载图片二进制或大对象正文。

### ZeroMQ 与 LocalBufferBroker

- ZeroMQ 继续用于受控场景下的高速触发和协议桥接，不替代公开 WebSocket。
- LocalBufferBroker 继续用于本机进程间大图和帧数据交换，不直接暴露给浏览器前端。

## 设计目标

- WebSocket 路由按版本和资源域组织，与 REST 的 `/api/v1/...` 分层保持对齐。
- 所有公开事件流共享同一组连接规则、鉴权规则、关闭语义和最小消息结构。
- 每条公开事件流都能对应到一个明确资源域，而不是按页面临时拼装消息主题。
- 断线重连优先依赖 REST 快照和事件重放，而不是假设连接永久可靠。
- 当前实现允许不同资源域使用不同底层事件来源，但对外暴露统一规则。

## 明确不做的事

- 不把 WebSocket 当成写入接口，不通过 socket 驱动取消、重试、发布或配置变更。
- 不在第一阶段设计单连接上的 subscribe、unsubscribe、ack 等命令协议。
- 不为了实时预览把图片二进制直接塞进 WebSocket 消息。
- 不让 worker 或隔离进程直接暴露 WebSocket 端口给前端。
- 不要求引入独立消息总线后才能公开新的资源流。

## 路由组织

### 总体规则

- 公开前缀统一使用 `/ws/v1`。
- `backend/service/api/ws/router.py` 只负责挂载版本化 router，不继续承载资源流实现。
- 不再保留 `/ws/*` 这类无版本公开路径。
- 新增资源流直接进入 `/ws/v1/...`，不再追加无版本新路径。

### 资源流清单

| 路径 | 主要筛选字段 | 用途 | 当前状态 |
| --- | --- | --- | --- |
| `/ws/v1/system/events` | 无 | 系统连接探针、低频系统通知、全局告警 | 已实现 |
| `/ws/v1/tasks/events` | `task_id`，可选 `event_type`、`after_cursor`、`limit` | 任务状态、进度、日志和结果事件 | 已实现 |
| `/ws/v1/workflows/preview-runs/events` | `preview_run_id`，可选 `after_cursor`、`limit` | preview run 的节点执行过程和运行终态 | 已实现 |
| `/ws/v1/workflows/runs/events` | `workflow_run_id`，可选 `after_cursor`、`limit` | 正式 WorkflowRun 的执行过程和结果事件 | 已实现 |
| `/ws/v1/workflows/app-runtimes/events` | `workflow_runtime_id`，可选 `after_cursor`、`limit` | 已发布应用运行态、主动 heartbeat、超时恢复和生命周期事件 | 已实现 |
| `/ws/v1/deployments/events` | `deployment_instance_id`，可选 `runtime_mode`、`after_cursor`、`limit` | deployment 启停、健康、重启和回滚相关事件 | 已实现 |
| `/ws/v1/projects/events` | `project_id`，可选 `topic` | 项目级看板需要的聚合低频状态流 | 已实现 |

### 内部事件总线

- 所有公开 WebSocket 资源流都应先进入统一的 service_event_bus，再由对应 stream service 转成公开消息。
- service_event_bus 只负责实时分发，不替代数据库、对象存储和运行时 manager 的正式回放面。
- 事件生产方只发布一次内部事件，不直接面向某个页面、某个路由或某个前端模块写专用推送逻辑。
- tasks 已经按这套结构落地：task_events 表负责历史回放，service_event_bus 负责实时推送。

### 为什么从一开始使用全局事件总线

- WebSocket 是与 HTTP API 同级别的公开子系统，内部实时分发面不应散落在各资源模块各自维护。
- 统一事件总线能把“事件生产”“历史回放”“公开推送”三层边界拆开，避免 route 直接依赖某个具体资源的存储细节。
- 在当前本地优先部署阶段，先采用进程内 service_event_bus 更符合整体约束；它保留了统一事件边界，但不会把外部消息中间件强行变成本地开发前提。
- 如果后续需要跨进程、跨实例分发，再替换 service_event_bus 的底层实现即可，不需要推翻公开的 `/ws/v1` 协议和资源流分层。

### 为什么先保持单流连接

- 当前任务事件已经按“一个路径对应一个资源流”落地，迁移成本最低。
- preview run、deployment 和 app runtime 的实时观察都天然依附单一资源 id，单流连接足够清楚。
- 本项目当前更需要稳定的公开规则，而不是过早引入复杂订阅协议和连接内路由器。

如后续确有大量跨资源聚合订阅需求，可以在更高版本里新增聚合流或命令式多订阅模型，但不在 `v1` 里预留半套协议。

## 连接与鉴权规则

- WebSocket 连接继续复用 REST 的主体与 scope 模型，不单独引入第二套 token 体系。
- 服务端在 `accept` 前完成身份、scope 和资源可见性校验；失败时沿用清晰的关闭码和关闭原因。
- 当前已使用的 `4401`、`4403`、`4400`、`4404` 语义继续保留，后续资源流复用同一风格。
- 第一阶段客户端不向连接内发送业务命令；建立连接后只接收服务端推送，取消、重试、启停等动作仍走 REST。
- 空闲长连接需要定期发送 `*.heartbeat` 控制事件，避免代理和浏览器把连接误判为死链。

## 消息结构

### 统一字段

所有公开 WebSocket 消息至少应包含以下字段：

- `stream`：资源流名，例如 `tasks.events`、`workflows.preview-runs.events`
- `event_type`：事件类型，例如 `tasks.connected`、`status`、`node.started`
- `event_version`：事件格式版本，首版统一为 `v1`
- `occurred_at`：事件发生时间，使用可序列化时间字符串
- `resource_kind`：资源类型，例如 `task`、`workflow_preview_run`
- `resource_id`：资源 id
- `cursor`：服务端生成的恢复游标；不支持重放时可为空
- `payload`：事件正文；只放摘要和结构化字段，不放大对象正文

### 控制事件与业务事件

- 控制事件用于连接建立、心跳、流量控制告警和服务端主动结束提示。
- 业务事件用于具体资源状态变化，例如 `status`、`progress`、`log`、`node.started`、`node.completed`、`run.cancelled`。

### 连接建立消息示例

```json
{
  "stream": "tasks.events",
  "event_type": "tasks.connected",
  "event_version": "v1",
  "occurred_at": "2026-01-01T00:00:00Z",
  "resource_kind": "task",
  "resource_id": "task-1",
  "cursor": null,
  "payload": {
    "filters": {
      "event_type": null,
      "after_cursor": null,
      "limit": 100
    }
  }
}
```

### preview run 事件示例

```json
{
  "stream": "workflows.preview-runs.events",
  "event_type": "node.started",
  "event_version": "v1",
  "occurred_at": "2026-01-01T00:00:02Z",
  "resource_kind": "workflow_preview_run",
  "resource_id": "preview-run-1",
  "cursor": "42",
  "payload": {
    "preview_run_id": "preview-run-1",
    "sequence": 42,
    "message": "node started",
    "node_id": "resize-1",
    "node_type": "opencv.resize",
    "display_name": "Resize Image"
  }
}
```

## 光标、重放与快照配合

### 总体规则

- REST 详情和列表仍是正式状态快照来源，WebSocket 只负责增量事件。
- WebSocket 的标准恢复参数统一收敛到 `after_cursor`，不再为新资源流扩散 `after_created_at` 这类各自为政的字段。
- 如果某个 REST 事件查询接口仍使用 `after_created_at`，那是 HTTP 读取面的筛选规则，不属于 WebSocket 订阅参数。
- 如果资源流支持重放，服务端应返回可继续使用的 `cursor`；如果不支持，客户端断线后必须重新读取 REST 快照。

### 推荐客户端流程

1. 先读取 REST 详情或事件列表，得到当前快照。
2. 再建立对应资源流的 WebSocket 连接，并带上最近一次成功处理的 `after_cursor`。
3. 按 `cursor` 顺序应用增量事件。
4. 连接断开后，先刷新 REST 快照，再按最近游标重连。

## 资源流与当前事件来源

| 资源流 | REST 快照面 | 当前或规划中的事件来源 | 说明 |
| --- | --- | --- | --- |
| `tasks.events` | `GET /api/v1/tasks/{task_id}`、`GET /api/v1/tasks/{task_id}/events` | `service_event_bus` + `task_events` 表 | 当前唯一已公开的长期事件流 |
| `workflows.preview-runs.events` | `GET /api/v1/workflows/preview-runs/{preview_run_id}`、`GET /api/v1/workflows/preview-runs/{preview_run_id}/events` | `service_event_bus` + `events.json` + `WorkflowPreviewRunManager` | 已接入统一 WebSocket；实时分发走 service_event_bus，历史回放继续走 events.json |
| `workflows.runs.events` | `GET /api/v1/workflows/runs/{workflow_run_id}`、`GET /api/v1/workflows/runs/{workflow_run_id}/events` | `service_event_bus` + `events.json` + `WorkflowRuntimeService` | 已接入统一 WebSocket；run 生命周期事件由 WorkflowRuntimeService 统一追加和分发 |
| `workflows.app-runtimes.events` | `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}`、`GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events` | `service_event_bus` + `events.json` + `WorkflowRuntimeService` + `WorkflowRuntimeWorkerManager` | 已接入统一 WebSocket；worker 主动 heartbeat 走统一事件总线，heartbeat 历史按窗口裁剪 |
| `deployments.events` | `GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}`、`GET /api/v1/models/yolox/deployment-instances/{deployment_instance_id}/events` | `service_event_bus` + `events.json` + deployment supervisor | 已接入统一 WebSocket；适合部署健康、重启和回滚通知 |
| `projects.events` | `GET /api/v1/projects/{project_id}/summary` | `service_event_bus` + `ProjectSummaryService` | 已接入统一 WebSocket；连接时先返回 summary 快照，后续推送项目级聚合更新 |
| `system.events` | `GET /api/v1/system/...` | service_event_bus + backend-service 低频系统通知源 | 只承担全局低频状态，不做大而全聚合 |

## preview events 的统一接入位置

- preview run 实时事件归属 `workflows.preview-runs.events`，而不是新增一个独立于 workflow runtime 之外的专用 socket。
- `POST /api/v1/workflows/preview-runs` 继续负责创建 preview run；`wait_mode=async` 返回 `preview_run_id` 后，前端通过 REST 快照和对应 WebSocket 资源流观察执行过程。
- `GET /api/v1/workflows/preview-runs/{preview_run_id}/events` 继续保留，作为断线恢复、历史回看和测试验证的正式读取面。
- `POST /api/v1/workflows/preview-runs/{preview_run_id}/cancel` 继续保持为取消入口，不通过 WebSocket 下发取消命令。
- preview 事件里的图片、文件和大结果继续通过对象存储键、输出摘要或其他引用字段表达，不在 WebSocket 中传二进制正文。

## 流量控制与稳定性规则

- 单连接发送缓冲必须有限，不能为了迁就慢客户端在内存中无限堆积事件。
- 客户端持续消费落后时，服务端可以发送一次 `*.lagging` 控制事件后关闭连接，或直接以带原因的关闭码结束连接。
- 资源流是否支持重放由底层回放面决定，但对外连接行为保持统一。
- 不同资源域可以有不同的回放介质，但实时分发都应统一经过 service_event_bus。

## 建议实现分层

### route 层

- 负责路径声明、查询参数解析、身份与 scope 校验和关闭码。

### stream service 层

- 负责读取 backlog、订阅 live 事件、生成 `cursor`、拼装统一消息结构。

### 事件来源层

- 允许按资源域分别对接数据库轮询、文件事件读取、运行时 manager 或 supervisor 回调。

### 共享对象层

- WebSocket 公共消息结构、筛选字段和关闭原因常量应收敛到共享模块，不继续散落在各 route 内部手工拼 JSON。

## 建议实现顺序

1. `/ws/v1/system/events` 和 `/ws/v1/tasks/events` 已经落地；其中 tasks 实时流已经收口到 service_event_bus，`task_events` 表继续负责回放。
2. `workflows.preview-runs.events` 已经按同一骨架落地：实时事件由 preview manager 写入 `service_event_bus`，`events.json` 继续负责回放。
3. `deployments.events` 已经按同一骨架落地：deployment supervisor 写入 `service_event_bus`，`events.json` 继续负责回放。
4. `workflows.app-runtimes.events` 已补 worker 主动 heartbeat、heartbeat 超时和恢复事件，继续保持“统一事件总线 + 各自回放面”的结构不变。
5. 如果后续需要跨进程或跨实例事件分发，再替换 service_event_bus 的底层实现，而不是改变公开协议。

## 推荐后续文档

- [backend-service.md](backend-service.md)
- [task-system.md](task-system.md)
- [workflow-runtime.md](workflow-runtime.md)
- [frontend-web-ui.md](frontend-web-ui.md)