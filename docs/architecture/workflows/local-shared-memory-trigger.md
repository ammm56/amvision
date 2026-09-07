# 本机共享内存 Trigger

## 当前实现

`local-shared-memory` 是同机 64-bit SDK 调用稳定 Workflow Runtime 的同步入口。图片 bytes 使用唯一 LocalBuffer 主 arena；请求、JSON/文本结果和图片引用使用独立的 Workflow Trigger LocalMessage Mailbox。两者不共享 allocator、owner、epoch 或容量。

Trigger 主体、结果 attachments、SDK、输入所有权交接、deadline/ACK、故障回收和通用 Mailbox 迁移均已实现。源码故障与本机压力门禁不替代真实目标发行环境 24 小时混合 soak；当前验收状态见[本机结构化消息通道验收](../../development/local-message-channel-implementation.md)。

## 配置与通道

- TriggerSource 绑定稳定 `workflow_runtime_id`；切换 App Version 后重新核验 revision/generation 和输入输出契约。
- 只支持 `submit_mode=sync`、`ack-after-run-finished` 与 `sync-reply`，必须有非空回复 timeout。
- 全局 Mailbox 路径从 `local_memory.root_dir` 派生为 `local-message/workflow-trigger/mailbox.mmap`；默认根目录为 `data/buffers`。
- 每个 TriggerSource 单在途；全局 descriptor、executor permit、Runtime execution token 和 LocalBuffer capacity 分别限流。满载立即失败，不增加隐藏队列或自动重试。
- SDK 配置只固定受信 buffers root，不允许请求指定 mmap 路径、arena 几何或 reader guard 数量。容量和 layout fingerprint 从 header 发现并校验。
- 未调用的 TriggerSource 不静态预留图片 extent，也不创建 external frame channel。

通用 profile 固定为 128 descriptors、64 KiB request inline、64 KiB response inline、512 个 256 KiB overflow page，单响应业务正文上限 32 MiB。page-chain 由唯一 server owner 分配，图片使用的连续 extent 不进入该 page pool。准确常量以 `backend/contracts/ipc/local_message_profiles.py` 为准。

## 输入与调用顺序

高性能输入只支持 `image-ref.v1`、`value.v1` 和 `text.v1`。Base64、普通文件和多文件输入使用 HTTP Runtime；Trigger 不隐式改走 HTTP。

```text
图片请求：PREPARE → LocalBuffer allocation → SDK write → REQUEST
无图片事件：event-only REQUEST
          ↓
Trigger mapping / 已发布 App Contract 校验
          ↓
Runtime execution token + 当前 revision/generation/worker identity
          ↓
图片 commit/owner handoff → Workflow worker
          ↓
结果规范化 / 输出图片 owner handoff → RESPONSE → SDK read → ACK
```

PREPARE 固定 source/event、精确图片长度、deadline 和 allocation identity。SDK 取得 writer guard 后重验 descriptor，写完必须销毁 writable view、释放 writer guard，再发布 REQUEST；不能持 guard 等待 Broker commit。服务端取得真实 Runtime 执行权后，原子 commit 并转交图片 owner，成功前不把 provisional 引用发给 worker。

event-only 使用 `amvision.workflow-trigger-event-request.v1`，跳过 PREPARE 和输入图片分配，仍使用同一 App Contract、mapping、admission 和结果契约。它是请求类型，不改变结果模式。

## 结果与所有权

`result_bindings` 显式选择公开输出。JSON binding 中嵌套短期 image-ref 会被拒绝；图片必须通过公开 image/image-list binding 输出，adapter 不扫描任意 JSON 猜测 attachments。

- raw 图片保留 shape、dtype、layout、pixel format；需要 JPEG/PNG 等编码时由图中 Image Encode 节点完成。
- 输出图片在 worker cleanup 前完成规范化和批量 handoff；全部 owner 与 ACK deadline 成功转移后才发布可读取 RESPONSE。
- 所有 RESPONSE，包括 JSON-only 和错误响应，都有独立 ACK deadline。
- 低层 .NET response lease 持有 reader guard 到 Dispose/DisposeAsync，先使 view 失效并释放 guard，再 ACK。
- 高层 Runner 物化 `TriggerResult.ImageAttachments` 后在返回前释放并 ACK；JSON-only 可以直接 ACK。
- 失败清理依据实际已经取得的 writer/runtime/response receipt，不能只凭 buffer id、路径或 offset 回收。

ZeroMQ 共用结果语义，但返回 manifest + binary attachments；其 transport-lifetime registry 等待 libzmq tracker，Broker 不等待 tracker。两种 adapter 不相互 fallback。

## Deadline、取消与恢复

PREPARE 建立单一服务端 absolute deadline；后续 admission 与执行只消费剩余预算。SDK 本地单调时钟不作为服务端时间基准。处理中的 timeout、显式取消和 client shutdown 保留不同原因，并作用于本次 Run 的取消信号。

descriptor 的 epoch、generation、owner、deadline 和 CRC 必须共同匹配。旧请求不能读、ACK 或回收新请求；owner 退出后操作系统释放文件锁，新 owner 使用新 epoch，已发布请求不自动重放。

LocalBuffer 回收先发布 REVOKING，持续取得全部 writer/reader guards 后才 FREE；仍有活动 view 的 extent 隔离为 QUARANTINED。Mailbox 回收独立恢复 descriptor 和 response pages。

## 代码与契约

- `backend/service/application/workflows/trigger_sources/local_shared_mailbox_supervisor.py`：路由、准入、执行和所有权交接。
- `backend/service/infrastructure/ipc/workflow_trigger_mailbox.py`：PREPARE/WRITING 业务扩展与通用 engine 适配。
- `backend/service/infrastructure/ipc/local_message/`：Mailbox、CRC、guards、page pool、owner 和恢复。
- `backend/contracts/ipc/` 与 `sdks/`：Python/跨语言 schema、生成物和 SDK。
- `tests/test_workflow_trigger_mailbox.py`、`tests/test_workflow_trigger_mailbox_supervisor.py`、`tests/test_local_buffer_external_leases.py`：协议、准入、故障和图片生命周期。

详细图片规则见 [LocalBufferBroker](../platform/local-buffer-broker.md)，公开调用见 [TriggerSource API](../../api/workflow-trigger-sources.md) 和 [Workflow SDK](../../api/workflow-sdks.md)。Windows x64 是当前 byte-range lock、强杀恢复与 Python/.NET 互操作认证基线；其他系统不能仅凭相同二进制布局宣称同等认证。
