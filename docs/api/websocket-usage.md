# WebSocket 使用

## 连接规则

WebSocket 用于接收增量事件。客户端第一次打开资源时先读取 REST 快照，再建立对应连接；连接中断后重新读取快照并按资源支持情况补回历史。

鉴权沿用 REST：

```http
Authorization: Bearer <token>
```

配置 `websocket_query_token_enabled=true` 时，不能设置握手请求头的客户端可使用 `access_token` 查询参数。长期集成应使用服务端签发的调用 token，并按现场策略设置有效期。

## 资源流

| 路径 | 查询参数 | scope | 说明 |
| --- | --- | --- | --- |
| `/ws/v1/system/events` | 无 | 无 | 返回 `system.connected` 后正常关闭，用于连接探测 |
| `/ws/v1/auth/events` | `event_type`、`user_id`、`provider_id`、`credential_kind`，均可选 | `auth:read` | 登录会话与 token 审计，仅实时事件 |
| `/ws/v1/tasks/events` | `task_id` 必填；`event_type`、`after_cursor`、`limit` 可选 | `tasks:read` | Task 状态、进度、日志和结果事件 |
| `/ws/v1/training/telemetry` | `task_id` 必填；`after_cursor`、`limit` 可选 | `tasks:read` | 训练高频遥测，只接受 training Task |
| `/ws/v1/workflows/preview-runs/events` | `preview_run_id` 必填；`after_cursor`、`limit` 可选 | `workflows:read` | Preview Run 节点和终态事件 |
| `/ws/v1/workflows/runs/events` | `workflow_run_id` 必填；`after_cursor`、`limit` 可选 | `workflows:read` | 正式 Workflow Run 事件 |
| `/ws/v1/workflows/app-runtimes/events` | `workflow_runtime_id` 必填；`after_cursor`、`limit` 可选 | `workflows:read` | Runtime 生命周期与 heartbeat |
| `/ws/v1/deployments/events` | `deployment_instance_id` 必填；`runtime_mode`、`after_cursor`、`limit` 可选 | `models:read` | Deployment 生命周期与健康事件 |
| `/ws/v1/projects/events` | `project_id` 必填；`topic` 可选 | `workflows:read`、`models:read` | Project 聚合摘要快照与更新 |

`limit` 默认 `100`，最大 `500`，只限制首次历史补发，不限制后续实时事件。非法或非正整数按默认值处理。

## 消息格式

```json
{
  "stream": "workflows.runs.events",
  "event_type": "run.completed",
  "event_version": "v1",
  "occurred_at": "2026-08-21T08:00:00Z",
  "resource_kind": "workflow_run",
  "resource_id": "workflow-run-1",
  "cursor": "12",
  "payload": {}
}
```

客户端按以下规则处理：

- `*.connected`：确认握手，不推进业务游标。
- `*.heartbeat`：只更新连接活跃时间，不推进业务游标。
- `*.lagging`：停止信任当前增量流，重新读取 REST 快照。
- 其他业务事件：更新本地状态，并保存最后一个可恢复 cursor。

## 建连与恢复

### Task

1. 读取 `GET /api/v1/tasks/{task_id}`。
2. 需要历史时读取 `GET /api/v1/tasks/{task_id}/events`。
3. 连接 `/ws/v1/tasks/events?task_id=...&after_cursor=...&limit=...`。
4. 按事件 cursor 去重。

训练高频曲线使用 `/ws/v1/training/telemetry`。遥测历史是有界内存窗口；收到 `training.telemetry.lagging` 时重新读取 Task 或训练指标快照，不假设旧遥测仍可恢复。

### Preview Run

1. 读取 `GET /api/v1/workflows/preview-runs/{preview_run_id}`。
2. 读取 `GET /api/v1/workflows/preview-runs/{preview_run_id}/events?after_sequence=...&limit=...`。
3. 连接 `/ws/v1/workflows/preview-runs/events?preview_run_id=...&after_cursor=...&limit=...`。

### Workflow Run

1. 读取 `GET /api/v1/workflows/runs/{workflow_run_id}?response_mode=run`。
2. 读取 `GET /api/v1/workflows/runs/{workflow_run_id}/events?after_sequence=...&limit=...`。
3. 连接 `/ws/v1/workflows/runs/events?workflow_run_id=...&after_cursor=...&limit=...`。

### Workflow App Runtime

1. 读取 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}`。
2. 需要进程、fingerprint 或 heartbeat 快照时，再读 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health`。
3. 读取 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events?after_sequence=...&limit=...`。
4. 连接 `/ws/v1/workflows/app-runtimes/events?workflow_runtime_id=...&after_cursor=...&limit=...`。

`runtime.heartbeat_timed_out` 和 `runtime.heartbeat_recovered` 可用于告警展示；权威健康状态仍以 health REST 快照为准。

### Deployment

1. 读取 Deployment 实例详情。
2. 读取实例事件列表并保存最后一个 sequence。
3. 连接 `/ws/v1/deployments/events?deployment_instance_id=...&after_cursor=...&limit=...`。

`runtime_mode` 仅用于显式限制 `sync` 或 `async` 运行模式，不能替代实例 id。

### Project 聚合摘要

1. 读取 `GET /api/v1/projects/{project_id}/summary`。
2. 连接 `/ws/v1/projects/events?project_id=...`。
3. 用 `projects.summary.snapshot` 或 `projects.summary.updated` 整体更新本地摘要。

Project 流不支持 `after_cursor`。断线后重新读取 summary，再重连。`topic` 可限制为服务端声明的 Project summary topic。

## 关闭码

| 关闭码 | 含义 |
| --- | --- |
| `1000` | 正常关闭 |
| `4400` | 查询参数缺失或格式错误 |
| `4401` | 未认证 |
| `4403` | scope 不足 |
| `4404` | 资源不存在或不可见 |
| `1011` | 服务组件尚未就绪 |
| `1013` | 客户端消费落后，订阅队列溢出 |

收到 `1013` 后重新读取 REST 快照，不使用旧连接继续推导状态。`1011` 表示服务尚未装配完成，应先检查服务诊断信息。

## 相关文档

- [API 通用约定](conventions.md)
- [通信协议边界](communication-contracts.md)
- [WebSocket 架构](../architecture/platform/websocket.md)
- [Workflow Preview Run](workflow-preview-runs.md)
- [Workflow Run](workflow-runs.md)
- [Workflow App Runtime](workflow-app-runtimes.md)
