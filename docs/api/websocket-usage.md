# WebSocket 使用文档

## 文档目的

本文档用于说明当前公开 WebSocket 资源流的接入顺序、恢复流程和最小客户端规则。

本文档面向浏览器前端、工作站程序、MES 辅助界面、HMI、嵌入式模块 UI、桌面工具和其他第三方系统，不假设调用方一定是 Web 前端。

## 适用范围

- `/ws/v1/projects/events`
- `/ws/v1/workflows/preview-runs/events`
- `/ws/v1/workflows/runs/events`
- `/ws/v1/workflows/app-runtimes/events`
- 对应的 REST 快照接口和事件历史接口

## 总体原则

- REST 是正式快照面，WebSocket 是增量事件面。
- 第一次进入页面或程序视图时，先读 REST，再建 WebSocket。
- `projects.events` 不支持 `after_cursor` 回放；断线后必须重新读项目 summary，再重连。
- preview-runs、runs、app-runtimes 三类资源流支持 `after_cursor` 和 `limit`，适合做断线补回和最小重放。
- `limit` 只影响建连后的首轮 replay，不影响后续 live 事件推送。
- 需要持久化恢复点时，只保存业务事件的数值 cursor，不保存 `*.heartbeat` 或 `*.lagging` 的 synthetic cursor。
- 如果调用方无法在 WebSocket 握手里写入自定义 `x-amvision-*` 请求头，应通过 SDK、本地代理、边车服务或可控网关代发握手；当前实现不提供 query token 替代规则。

## 鉴权和握手规则

当前 WebSocket 握手沿用 REST 的主体与 scope 请求头：

- `x-amvision-principal-id`
- `x-amvision-project-ids`
- `x-amvision-scopes`

当前常见关闭码和原因如下：

| 关闭码 | 原因 | 说明 |
| --- | --- | --- |
| `4401` | `authentication_required` | 缺少主体信息 |
| `4403` | `permission_denied` | scope 不足 |
| `4400` | `*_required` / `after_cursor_invalid` / `topic_invalid` | 查询参数缺失或格式非法 |
| `4404` | `*_not_found` / `project_not_found` | 资源不存在或当前主体不可见 |
| `1013` | `subscriber_queue_overflowed` | 客户端消费落后，服务端主动结束连接 |
| `1011` | `*_not_ready` | 服务端运行时装配未完成 |

## 统一消息规则

所有公开 WebSocket 消息都带统一骨架字段：

- `stream`
- `event_type`
- `event_version`
- `occurred_at`
- `resource_kind`
- `resource_id`
- `cursor`
- `payload`

控制消息与业务消息分开处理：

| 消息类型 | 处理方式 |
| --- | --- |
| `*.connected` | 只做握手确认，不写业务状态 |
| `*.heartbeat` | 只更新连接活跃时间，不推进业务游标 |
| `*.lagging` | 视为需要重建的告警，随后通常会被 `1013` 关闭 |
| 业务事件 | 推进本地状态，并更新可恢复游标 |

### cursor 使用规则

| 资源流 | 可否作为恢复参数复用 | 恢复参数 |
| --- | --- | --- |
| `projects.events` | 否 | 无；断线后重新读 REST summary |
| `workflows.preview-runs.events` | 是 | `after_cursor=<sequence 字符串>` |
| `workflows.runs.events` | 是 | `after_cursor=<sequence 字符串>` |
| `workflows.app-runtimes.events` | 是 | `after_cursor=<sequence 字符串>` |

对于 preview-runs、runs、app-runtimes：

- 只持久化业务事件的数值 `cursor`。
- 不要把 `workflows.*.heartbeat` 或 `workflows.*.lagging` 的 `cursor=heartbeat|...`、`lagging|...` 当作恢复点。
- 如果错误地把 heartbeat cursor 回填到 `after_cursor`，当前服务会返回 `4400 after_cursor_invalid`。

## 推荐连接顺序

### 项目总览、工作台、HMI 总面板

推荐顺序：

1. `GET /api/v1/projects/{project_id}/summary`
2. 渲染当前项目 summary 快照
3. 建立 `/ws/v1/projects/events?project_id=...`
4. 如果只关心某类聚合更新，再追加 `topic=workflows.preview-runs|workflows.runs|workflows.app-runtimes|deployments`
5. 收到 `projects.connected` 后确认连接可用
6. 收到 `projects.summary.snapshot` 后，用这条消息覆盖当前内存 summary
7. 后续对 `projects.summary.updated` 做整块替换或按字段覆盖

如果同一个界面还要展开 preview run、WorkflowRun 或 app runtime 详情，先让 `projects.events` 稳定，再按需追加资源级 socket。

### PreviewRun 调试页、流程编辑器试跑面板

推荐顺序：

1. 已有 `preview_run_id` 后，先读 `GET /api/v1/workflows/preview-runs/{preview_run_id}`
2. 如果本地已经保存上一次成功处理的最大 sequence，再读 `GET /api/v1/workflows/preview-runs/{preview_run_id}/events?after_sequence=<last_sequence>&limit=<n>`
3. 记录最新业务 sequence
4. 建立 `/ws/v1/workflows/preview-runs/events?preview_run_id=...&after_cursor=<last_sequence>&limit=<n>`
5. 收到 `workflows.preview-runs.connected` 后，不更新业务游标
6. 处理 replay 事件和后续 live 事件，并持续保存最新业务 sequence

### WorkflowRun 结果页、任务步骤详情页

推荐顺序：

1. 先读 `GET /api/v1/workflows/runs/{workflow_run_id}`
2. 如果本地保存了上一次成功处理的最大 sequence，再读 `GET /api/v1/workflows/runs/{workflow_run_id}/events?after_sequence=<last_sequence>&limit=<n>`
3. 建立 `/ws/v1/workflows/runs/events?workflow_run_id=...&after_cursor=<last_sequence>&limit=<n>`
4. 收到 `workflows.runs.connected` 后，不更新业务游标
5. 处理 replay 与 live 事件，并持续保存最新业务 sequence

### App Runtime 监控页、产线运行态面板

推荐顺序：

1. 先读 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}`
2. 如果界面需要最新 worker 进程号、fingerprint 和 heartbeat 时间，再追加 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health`
3. 如果本地保存了上一次成功处理的最大 sequence，再读 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events?after_sequence=<last_sequence>&limit=<n>`
4. 建立 `/ws/v1/workflows/app-runtimes/events?workflow_runtime_id=...&after_cursor=<last_sequence>&limit=<n>`
5. 收到 `workflows.app-runtimes.connected` 后，不更新业务游标
6. 处理 replay 与 live 事件，并持续保存最新业务 sequence

## 各资源流的恢复流程

### `/ws/v1/projects/events`

当前查询参数：

- `project_id`，必填
- `topic`，可选

首次连接：

1. `GET /api/v1/projects/{project_id}/summary`
2. 建立 WebSocket
3. 忽略 `projects.connected` 的 `cursor`
4. 用 `projects.summary.snapshot` 覆盖本地 summary
5. 对后续 `projects.summary.updated` 做整块替换

断线恢复：

1. 把当前界面标成 stale
2. 重新执行 `GET /api/v1/projects/{project_id}/summary`
3. 重新建立 `/ws/v1/projects/events?project_id=...`
4. 如果之前用了 `topic`，重连时保持同一筛选条件

当前注意点：

- `projects.events` 不支持 `after_cursor`
- `projects.summary.snapshot` 与 `projects.summary.updated` 都返回完整聚合摘要，适合直接覆盖
- `projects.heartbeat` 和 `projects.lagging` 不应用作业务状态输入

### `/ws/v1/workflows/preview-runs/events`

当前查询参数：

- `preview_run_id`，必填
- `after_cursor`，可选，使用 sequence 字符串
- `limit`，可选，默认 `100`，最大 `500`

首次连接：

1. 读 `GET /api/v1/workflows/preview-runs/{preview_run_id}`
2. 如需补回历史，读 `GET /api/v1/workflows/preview-runs/{preview_run_id}/events`
3. 如果已经拿到最后一条业务事件的 `sequence`，转成字符串后作为 `after_cursor`；如果当前还没有历史事件，可省略 `after_cursor`
4. 建立 WebSocket
5. 处理 replay，再处理 live

断线恢复：

1. 记住最后一个业务 `sequence`
2. 重新读 `GET /api/v1/workflows/preview-runs/{preview_run_id}`
3. 重新读 `GET /api/v1/workflows/preview-runs/{preview_run_id}/events?after_sequence=<last_sequence>&limit=<n>`
4. 重新建连，并带上 `after_cursor=<last_sequence>`
5. 去重依据使用 `sequence`

### `/ws/v1/workflows/runs/events`

当前查询参数：

- `workflow_run_id`，必填
- `after_cursor`，可选，使用 sequence 字符串
- `limit`，可选，默认 `100`，最大 `500`

首次连接：

1. 读 `GET /api/v1/workflows/runs/{workflow_run_id}`
2. 如需补回历史，读 `GET /api/v1/workflows/runs/{workflow_run_id}/events`
3. 如果已经拿到最后一条业务事件的 `sequence`，转成字符串后作为 `after_cursor`；如果当前还没有历史事件，可省略 `after_cursor`
4. 建立 WebSocket
5. 处理 replay，再处理 live

断线恢复：

1. 记住最后一个业务 `sequence`
2. 重新读 `GET /api/v1/workflows/runs/{workflow_run_id}`
3. 重新读 `GET /api/v1/workflows/runs/{workflow_run_id}/events?after_sequence=<last_sequence>&limit=<n>`
4. 重新建连，并带上 `after_cursor=<last_sequence>`
5. 去重依据使用 `sequence`

### `/ws/v1/workflows/app-runtimes/events`

当前查询参数：

- `workflow_runtime_id`，必填
- `after_cursor`，可选，使用 sequence 字符串
- `limit`，可选，默认 `100`，最大 `500`

首次连接：

1. 读 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}`
2. 如果需要最新 worker 运行态，再读 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health`
3. 如需补回历史，读 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events`
4. 如果已经拿到最后一条业务事件的 `sequence`，转成字符串后作为 `after_cursor`；如果当前还没有历史事件，可省略 `after_cursor`
5. 建立 WebSocket
6. 处理 replay，再处理 live

断线恢复：

1. 记住最后一个业务 `sequence`
2. 重新读 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}`
3. 如果界面依赖运行态健康字段，追加 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health`
4. 重新读 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events?after_sequence=<last_sequence>&limit=<n>`
5. 重新建连，并带上 `after_cursor=<last_sequence>`
6. 去重依据使用 `sequence`

当前注意点：

- `runtime.heartbeat_timed_out`、`runtime.heartbeat_recovered` 适合直接做告警和恢复提示
- 如果界面需要最新 `worker_process_id`、`loaded_snapshot_fingerprint` 或 `heartbeat_at`，以 `GET /health` 为正式快照面

## `lagging` 和 `heartbeat` 的处理规则

收到 `*.heartbeat` 时：

- 只更新连接活跃时间
- 不推进业务状态
- 不更新可恢复游标

收到 `*.lagging` 时：

- 立即停止把当前连接视为可靠来源
- 准备按对应资源的 REST 快照面重新补回
- 预期服务端随后以 `1013 subscriber_queue_overflowed` 结束连接

## 推荐的客户端本地状态

建议每条资源流至少保存以下本地字段：

- `resource_id`
- `connected`
- `stale`
- `last_business_cursor`
- `last_business_occurred_at`
- `last_disconnect_reason`
- `reconnect_attempt`

对于 preview-runs、runs、app-runtimes，`last_business_cursor` 推荐保存为整型 sequence；实际发起 WebSocket 重连时再转为字符串。

## 推荐的最小实现模式

### 只做项目总览

- HTTP：`GET /api/v1/projects/{project_id}/summary`
- WebSocket：`/ws/v1/projects/events`

### 只做试跑执行过程

- HTTP：`GET /api/v1/workflows/preview-runs/{preview_run_id}`
- HTTP：`GET /api/v1/workflows/preview-runs/{preview_run_id}/events`
- WebSocket：`/ws/v1/workflows/preview-runs/events`

### 只做正式运行结果页

- HTTP：`GET /api/v1/workflows/runs/{workflow_run_id}`
- HTTP：`GET /api/v1/workflows/runs/{workflow_run_id}/events`
- WebSocket：`/ws/v1/workflows/runs/events`

### 只做产线运行态监控

- HTTP：`GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}`
- HTTP：`GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health`
- HTTP：`GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/events`
- WebSocket：`/ws/v1/workflows/app-runtimes/events`

## 相关文档

- [docs/api/current-api.md](current-api.md)
- [docs/architecture/websocket-architecture.md](../architecture/websocket-architecture.md)
- [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)
- [docs/api/workflow-runs.md](workflow-runs.md)
- [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md)
- [docs/api/communication-contracts.md](communication-contracts.md)