# WebSocket 架构

本文主体描述当前已实现的状态/事件流。新增运行页面的公开结果流已接受、待实现：允许 Base64 图片，完整 JSON 消息上限为 64MB，不要求硬实时、不建结果队列或历史恢复，不阻塞 Workflow/Runtime/Trigger；第三方前端可使用同一公开标准。具体容量口径、类型解析和隔离验收统一见[amvar app 实施基线第 6 节](../../development/workflow-views-and-app-packages-implementation.md#6-在线结果传输前后端隔离与稳定性)。下文现有流的“不传大对象正文”、订阅队列和恢复规则不自动套用到该新增结果流，也不因新规划改变现有接口。

新结果流发送单 Runtime 的完整公开输出；统一覆盖同步、持久化异步及 none + event-only 临时异步终态，清理完成后轻量交接，容量约束前置到后台任务/回调提交之前。认证复用默认全权限用户永久 token 和现有登录态，不新增查看/调用等角色或权限配置；精确路径、消息和 token 接入见实施基线第 6.5–6.9 节。下文当前接口的 scope 列表保留事实描述，不代表新增页面需要建设同类分级配置。

## 职责

WebSocket 是 backend-service 的公开增量事件面。REST API 提供资源快照、查询和控制动作；WebSocket 提供状态变化、进度、遥测和健康事件。两者共同组成公开通信接口。

WebSocket 不承担以下职责：

- 不处理发布、取消、启停或配置写入；这些动作使用 REST API。
- 不传输图片、视频帧或其他大对象正文；大对象使用 ObjectStore、LocalBufferBroker 或明确的引用协议。
- 不替代 Deployment、Workflow Runtime 等独立进程之间的 ZeroMQ 通信。
- 不让 worker 直接向浏览器公开端口。

## 对外边界

所有公开路由使用 `/ws/v1` 前缀。一条连接只订阅一个资源流，服务端不实现连接内的 `subscribe`、`unsubscribe` 或 `ack` 命令协议。

| 路径 | 资源 | 必需 scope | 恢复方式 |
| --- | --- | --- | --- |
| `/ws/v1/system/events` | 系统连接探针 | 无 | 单次连接响应后关闭 |
| `/ws/v1/auth/events` | 登录与 token 审计 | `auth:read` | 仅实时事件 |
| `/ws/v1/tasks/events` | Task 事件 | `tasks:read` | `after_cursor` + 数据库事件 |
| `/ws/v1/training/telemetry` | 训练高频遥测 | `tasks:read` | `after_cursor` + 有界内存历史 |
| `/ws/v1/workflows/preview-runs/events` | Preview Run | `workflows:read` | `after_cursor` + `events.jsonl` |
| `/ws/v1/workflows/runs/events` | Workflow Run | `workflows:read` | `after_cursor` + `events.jsonl` |
| `/ws/v1/workflows/app-runtimes/events` | Workflow App Runtime | `workflows:read` | `after_cursor` + Runtime 事件记录 |
| `/ws/v1/deployments/events` | Deployment | `models:read` | `after_cursor` + `events.jsonl` |
| `/ws/v1/projects/events` | Project 聚合摘要 | `workflows:read`、`models:read` | 重新读取 REST 快照 |

查询参数、关闭码和客户端恢复步骤见 [WebSocket 使用](../../api/websocket-usage.md)。路由声明以 `backend/service/api/ws/v1/router.py` 为实现来源。

## 内部分层

```text
业务服务 / Runtime manager / Deployment supervisor
                         │
                         ▼
               InMemoryServiceEventBus
                         │
                         ▼
                 /ws/v1 资源路由
                         │
                         ▼
                 浏览器或外部订阅方

数据库 / JSONL / Runtime 事件记录 ──► 历史重放
REST service                    ──► 当前快照
```

- 事件生产方发布统一的 `ServiceEvent`，不直接依赖页面或 WebSocket 连接。
- `InMemoryServiceEventBus` 只负责当前 backend-service 进程内的实时分发，不承担持久化。
- 数据库、JSONL 和 Runtime 事件记录分别承担对应资源的历史读取。
- REST 详情接口是当前状态的权威快照；事件丢失或连接落后时，客户端重新读取快照。
- Project 流发送聚合快照，不维护跨资源游标。

本地部署不依赖 Redis、Kafka 或独立消息服务。以后如需多 backend-service 实例，可替换事件总线实现，但必须保持 `/ws/v1` 的公开消息契约。

## 消息契约

所有公开消息使用同一骨架：

- `stream`：资源流名称。
- `event_type`：业务事件或控制事件类型。
- `event_version`：消息格式版本，当前为 `v1`。
- `occurred_at`：事件时间。
- `resource_kind`、`resource_id`：资源类型和标识。
- `cursor`：可恢复的业务游标；不支持恢复时为空。
- `payload`：结构化摘要，不包含大对象正文。

控制事件包括 `*.connected`、`*.heartbeat` 和 `*.lagging`。只有业务事件的 cursor 可以作为恢复点；heartbeat 和 lagging 的合成 cursor 不得持久化为业务游标。

## 鉴权与可见性

- WebSocket 复用 REST 的主体、scope 和 Project 可见性模型。
- 默认通过 `Authorization: Bearer <token>` 鉴权。
- 只有配置允许时，不能写握手请求头的客户端才可使用 `access_token` 查询参数。
- 服务端在发送业务数据前验证 scope、资源存在性和 Project 可见性。
- 管理动作始终通过 REST 完成，连接内消息不能绕过 API 鉴权。

## 重放与流量控制

支持重放的流在连接建立后先发送历史事件，再转入实时订阅。客户端按业务 cursor 去重，并在断线后执行“REST 快照 → 历史补回 → WebSocket 重连”。

每个订阅队列都有界。客户端消费落后时，服务端发送 `*.lagging`（适用时）并以 `1013 subscriber_queue_overflowed` 关闭连接，避免长期运行时无限占用内存。训练遥测只保留有界历史；游标超出窗口时要求重新读取快照。

## 稳定性边界

- 事件实时分发与事件持久化相互独立；持久化失败不得由无限内存缓存掩盖。
- Runtime heartbeat 历史按窗口裁剪，Workflow Run、Preview Run 和 Deployment 事件按 JSONL 追加。
- WebSocket route 只做参数、鉴权、重放与消息映射，不执行业务控制逻辑。
- 新资源流必须同时定义 REST 快照来源、实时事件来源、恢复方式和慢客户端策略。

## 相关文档

- [通信协议边界](../../api/communication-contracts.md)
- [WebSocket 使用](../../api/websocket-usage.md)
- [Workflow Runtime](../workflows/runtime.md)
- [Deployment Runtime](../models/deployment-runtime.md)
