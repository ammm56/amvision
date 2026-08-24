# Workflow TriggerSource API

## 用途

WorkflowTriggerSource 把外部协议事件映射为稳定 WorkflowAppRuntime 调用。它只负责接收、规范化、输入绑定、提交和回执，不执行图内图片转换、模型推理或业务规则。

TriggerSource 绑定稳定 `workflow_runtime_id`。Runtime 通过 revision/generation 切换 Workflow App Version 后，TriggerSource id 和外部 endpoint 不变。

## 当前可运行 adapter

| `trigger_kind` | 作用 |
| --- | --- |
| `zeromq-topic` | ZeroMQ multipart/JSON 事件与本机图片高速数据面 |
| `plc-register` | Modbus TCP 寄存器轮询、条件匹配和 Workflow 提交 |
| `directory-poll` | 周期目录扫描、稳定期过滤、checkpoint 和批量提交 |
| `directory-watch` | 本地目录事件监听、稳定期过滤、checkpoint 和受控 polling fallback |

schema 可以识别其他预留 kind，但未注册 adapter 的 TriggerSource 无法 enable，并会返回明确配置错误。未注册类型不能写成已支持。

## 管理接口

```text
POST   /api/v1/workflows/trigger-sources
GET    /api/v1/workflows/trigger-sources?project_id=...&workflow_runtime_id=...&offset=0&limit=100
GET    /api/v1/workflows/trigger-sources/{trigger_source_id}
POST   /api/v1/workflows/trigger-sources/{trigger_source_id}/enable
POST   /api/v1/workflows/trigger-sources/{trigger_source_id}/disable
GET    /api/v1/workflows/trigger-sources/{trigger_source_id}/health
DELETE /api/v1/workflows/trigger-sources/{trigger_source_id}
```

读取需要 `workflows:read`，创建、启停和删除需要 `workflows:write`；所有操作同时校验 Project 可见性。

## 创建请求

以下是当前可运行 schema。`result_mapping.result_binding` 属于待迁移旧字段；目标 schema 见后文，实施完成后本示例必须同步改为 `result_bindings`，且不保留双读。

```json
{
  "trigger_source_id": "trigger-source-line-1",
  "project_id": "project-1",
  "display_name": "Line 1 image trigger",
  "trigger_kind": "zeromq-topic",
  "workflow_runtime_id": "workflow-runtime-line-1",
  "submit_mode": "sync",
  "enabled": false,
  "transport_config": {
    "bind_endpoint": "tcp://127.0.0.1:5555"
  },
  "match_rule": {},
  "input_binding_mapping": {
    "request_image_ref": {
      "source": "payload.request_image_ref"
    }
  },
  "result_mapping": {
    "result_binding": "workflow_result"
  },
  "default_execution_metadata": {
    "source": "line-1"
  },
  "ack_policy": "ack-after-run-finished",
  "result_mode": "sync-reply",
  "reply_timeout_seconds": 30,
  "debounce_window_ms": 0,
  "metadata": {}
}
```

## 提交与回执组合

| `submit_mode` | `ack_policy` | `result_mode` |
| --- | --- | --- |
| `sync` | `ack-after-run-finished` | `sync-reply` |
| `async` | `ack-after-run-created` | `accepted-then-query` 或 `event-only` |

不支持的组合在创建或 enable 时拒绝。同步调用不排队、不自动重试；Runtime 满载、停止、版本不一致或超时直接返回结构化错误。

## 版本与恢复

- 创建和 enable 时校验 Runtime 当前 revision、version、generation 与公开输入输出契约。
- Trigger 保存验证过的 revision/version/generation/contract fingerprint；Runtime 切版后必须重新校验。
- backend-service 启动先完成 Runtime recovery readiness，再恢复 enabled TriggerSource，避免 adapter 先接流量而 Worker 尚未就绪。
- 旧 generation 或旧 worker epoch 的回调不能污染当前 Runtime。
- disable/delete 在 Supervisor 停止 adapter 后更新持久状态；未完成停止时不假报成功。

## ZeroMQ 图片边界

ZeroMQ adapter 接收 envelope 与图片 bytes，把图片写入 LocalBufferBroker，再向 Workflow 提交 `image-ref.v1`。Workflow 图显式发布 `request_image_ref`，需要兼容 HTTP Base64 时在图内通过 coalesce 节点汇合。

大图热路径不得把图片转成 Base64 JSON。BGR24、mmap、owner/generation/deadline 与槽位回收规则见 [高性能图片数据面](../architecture/platform/image-data-plane.md)。

当前 ZeroMQ reply 虽然通过 multipart API 发送，但实际只有一帧 `amvision.workflow-trigger-result.v1` JSON；当前 .NET SDK 也只解析第一帧。现阶段不能把 ZeroMQ 图片结果或本机共享内存图片 handoff 写成已交付能力。

## 已接受但尚未实现的结果返回设计

后续结果映射从单个 `result_binding` 迁移为：

```json
{
  "result_mode": "sync-reply",
  "reply_timeout_seconds": 30,
  "ack_policy": "ack-after-run-finished",
  "result_mapping": {
    "result_bindings": [
      "workflow_result",
      "annotated_image",
      "cropped_images"
    ]
  }
}
```

顶层 `result_mode`、`reply_timeout_seconds` 和 `ack_policy` 是唯一事实源，`result_mapping` 只保存有序 `result_bindings`。迁移完成后删除旧字段和“返回全部 outputs”fallback，不保留双读运行代码。`result_bindings` 可以同时选择 JSON、`image-ref.v1` 和 `image-refs.v1`；结果分类只读取已发布 Workflow App Version 的公开输出契约，不递归提升任意 JSON 中的临时图片引用。已选择 JSON 内出现嵌套 memory/buffer/frame ref 时返回 `ephemeral_image_ref_in_json_result`。

Trigger adapter 按能力映射结果：

- `local-shared-memory`：JSON 走 Workflow Trigger mailbox，直接图片走 LocalBuffer BufferRef；SDK 结果对象持有 reader guard 到 Dispose 后 ACK；
- ZeroMQ Trigger Result v1：Frame 0 是统一 JSON manifest，Frame 1 到 N 传唯一 physical payload 的 raw 或已显式编码图片 bytes；多个逻辑 attachment 可共享 payload/frame，无图片时 N=0；
- PLC、IO、MQTT、目录和定时等 `event-only` Trigger：明确丢弃输出，不建立图片 handoff；
- `accepted-then-query`：不能保存短期 BufferRef；临时图片和绝对路径复制到受管理 ObjectStore，只有同时具有不可变 version、checksum、准确长度和 media type 的 ObjectStore 引用可以直接复用。

同步 adapter 不支持某个已选择 binding 时，在创建、enable 或 Runtime 切版时拒绝配置；不需要返回的 binding 直接不选择，不增加 `discard` 配置。`local-shared-memory` v1 仅支持一张输入图片、最多 512 KiB 结构化参数和同步回复；输出可以包含 0 到 N 张图片。

公开结果统一为 `WorkflowTriggerResultV1`，包含有序 `attachments` 和按 `payload_id` 去重的 `payloads`；attachment 只保存 binding/item 与 payload 引用，physical payload locator 使用带 `kind` 的联合类型：

- `local-buffer`：现有 BufferRef 定位和代次字段加 reader guard locator；权威 owner、pool、deadline 只保存在服务端私有 handoff receipt 中；
- `zeromq-frame`：当前 multipart message 的物理 frame index；多个逻辑 attachment 可以共享同一索引；
- `object-store`：可持久查询的 object key、media type、content length、checksum algorithm/value 和 immutable version。

Workflow worker 内部使用 `PreparedTriggerResult`，其中 logical attachments 通过 `payload_id` 引用去重后的 physical payloads，不包含 ZeroMQ frame index。公开 BufferRef 只负责定位；服务端私有 `LeaseOwnershipReceipt` 才能执行 transfer/release。输入在 WorkflowRun 建立、Runtime/执行器 admission 成功后和 worker submit 前显式执行 `workflow-trigger-write -> workflow-runtime`，每个失败点按当前 receipt 补偿回收。

图片在 worker cleanup 前完成规范化：当前 Run receipt 对应的 BufferRef 可零复制 handoff；foreign/incomplete BufferRef、memory handle 和 FrameRef 按规则复制。storage/local-path 根据 delivery kind 选择 LocalBuffer 物化、不可变 ObjectStore locator 复用或受管理持久化。ZeroMQ 只从 LocalBuffer reader guard、ObjectStore `open_read_snapshot()` 或 adapter 自有不可变 bytes 构建 tracked frame；普通绝对路径没有稳定 reader guard，必须先复制到受控来源。`image-refs.v1` 只按 `items` 返回，顺序先按 `result_bindings`、再按 item；`source_image` 不自动加入。

TriggerSource 单在途状态保持到协议责任已经安全转移：本机共享内存保持到结果 Dispose/ACK、取消或 deadline 后的安全回收；ZeroMQ 保持到全部已提交 physical frame tracker 完成，或未完成资源已经由发送前预留的 adapter transport-lifetime registry 持续负责且 lease 进入 Broker 回收链。图执行和 handoff 完成后可以先释放 Runtime token，但不能因 socket send 失败就提前复用仍被 tracker 或 reader guard 持有的 lease。

幂等只重放稳定结果：JSON-only 结果可在 TTL 内重放；带临时 attachment 的重复请求不重跑 Workflow、也不重放旧引用，返回 `idempotent_attachment_result_not_replayable` 和原 `workflow_run_id`；只有 ObjectStore 持久结果可按查询链路重放。

图中直接图片输出表示 attachment；`Image Base64 Encode` 表示受响应容量限制的 JSON；新增 `Image Encode` 决定 JPEG/PNG/BMP/WebP 等编码表示。adapter 不暗中改变图片格式。完整决策见 [ADR-0007](../decisions/ADR-0007-local-shared-memory-workflow-trigger.md)，实施顺序见[本机共享内存 Trigger 实施基线](../development/local-shared-memory-trigger-implementation.md)。

ZeroMQ 不增加 `reply_protocol` 或 JSON/multipart mode。统一 format id 为 `amvision.workflow-trigger-result.v1`，成功、失败和 adapter 错误使用相同 manifest；删除独立 error envelope、只解析第一帧和双协议兼容分支。每个唯一物理 payload 使用 tracked frame，多个逻辑 attachment 可以共享同一 frame index。adapter 在发送 Frame 0 前预留有界 transport-lifetime registry 容量；发送受 reply deadline、`SNDTIMEO`、单物理 payload/逻辑 attachment/物理 frame/总容量和 registry entry/bytes 限制。失败时先以 `linger=0` 关闭 REP socket，再确认全部已提交 tracker；未完成 Frame/view/snapshot/guard 继续由 adapter registry 持有，lease 进入 REVOKING/QUARANTINED，不能立即释放。Broker 不管理 libzmq tracker。

Workflow TriggerSource result mapping REST payload 与 `amvision.workflow-trigger-result.v1` 当前属于发布前开发契约。本次迁移由后端、Alembic 数据迁移、前端、.NET SDK、fixture/Postman 和已有数据在同一提交链中整体升级，完成后删除旧字段、旧解析和双读代码。该声明只约束本次 Workflow Trigger 结果契约，不代表其他 REST `/api/v1` 接口不承诺兼容。

## 诊断

health 至少区分 desired/observed state、adapter 是否注册和运行、绑定 Runtime、验证 generation、endpoint、heartbeat 与最近错误。

## 本地目录示例

两个正式 Postman 场景覆盖本地目录接入：

- `09-industrial-local-directory-watch-detection-position-gate/`：事件监听，应用文件为 `industrial_local_directory_watch_detection_position_gate.application.json`。示例包含 `request_roi`、`input_binding_mapping.deployment_request.value`、`idempotency_key_path": "payload.batch_id"` 和 `force_polling = true`。
- `11-industrial-local-directory-poll-detection-position-gate/`：周期扫描，应用文件为 `industrial_local_directory_poll_detection_position_gate.application.json`，并显式配置 `scan_interval_seconds`。

完整请求、环境变量和现场占位值见 [Workflow Postman](postman/workflows/README.md)。示例中的目录、Deployment id 和 token 必须替换为当前环境值。

Postman 与场景示例见 [Workflow Postman](postman/workflows/README.md)，.NET 调用见 [Workflow SDK](workflow-sdks.md)。
