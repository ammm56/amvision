# LocalBufferBroker

## 定位

LocalBufferBroker 是同一主机内 backend-service、deployment runtime、Workflow Runtime 和其他 Worker 之间传递大图片与视频帧的共享内存数据面。控制消息只携带引用和元数据，像素字节由消费者直接读取 mmap，避免 Base64、JSON 和多次内存复制。

LocalBuffer 不是持久化存储、任务队列或跨主机传输协议。

## 进程与组件

- `LocalBufferBrokerSupervisor` 管理 broker companion process；
- broker process 管理 mmap pool、slot、lease 和控制协议；
- `LocalBufferClient` 负责 allocate、commit、acquire、release 和状态查询；
- `DirectMmapReader` 按引用直接读取共享内存；
- backend-service takeover 在 owner 进程异常时收敛本机 broker 状态。

正式独立 daemon 拓扑有两个互不重叠的 owner root：backend-service 管理主图片池，inference daemon 管理 `inference-daemon-private` 异步暂存池。每个 root 仍只有一个 broker owner；同步调用不会复制到私有池。

实现位于 `backend/service/application/local_buffers/` 和 `backend/service/infrastructure/local_buffers/`。

## 文件目录

LocalBuffer 图片数据面及其 inference/workflow image mailbox 统一位于应用数据目录下的 `data/buffers/`。图片数据面的根配置是 `local_buffer_broker.root_dir`，默认值为 `./data/buffers`；属于该数据面的 mmap、guard 和 owner lock 必须从这个根目录派生，不能为同一图片链路再定义互不相关的 mmap root。

```text
data/buffers/
├─ image-4k/                     LocalBuffer 主图片 pool
├─ image-1080p/                  LocalBuffer 图片 pool
├─ image-640x640/                LocalBuffer 图片 pool
├─ inference-control/            inference mailbox、guard 和 server lock
├─ workflow-trigger/             Workflow Trigger mailbox、guard 和 owner lock（规划能力）
└─ inference-daemon-private/     inference daemon 私有短期 LocalBuffer pool
```

约束如下：

- LocalBuffer pool 文件、inference/workflow image mailbox、slot guard 和对应 owner lock 都必须位于 `data/buffers/` 或其明确子目录；
- 不在仓库根目录、`data/files/`、`data/queue/`、`.tmp/`、系统临时目录或 SDK 配置目录创建图片数据面正式运行 mmap；
- 训练遥测等不承载图片或 Workflow Trigger 数据的独立子系统不属于本目录契约；当前训练遥测继续使用 `data/runtime/training-telemetry/`，本 ADR 不迁移或复用其 mmap；
- 发行包使用发行应用根目录下的 `data/buffers/`，不能引用源码工作区的绝对路径；
- 测试可以把同一根目录契约重定向到独立的 `.tmp/<test>/buffers/`，但目录结构和路径校验规则必须与正式环境一致；
- 文件和子目录由对应 backend-service、Broker 或 daemon owner 创建，SDK 和普通消费者不得自行选择或创建 mmap 路径；
- 所有外部引用在打开前必须解析绝对路径，并验证结果仍位于当前配置的 buffers root 内。

## 引用模型

公开 `BufferRef`/`FrameRef` 是图片定位和表示契约，保存 buffer/lease identity、broker epoch、generation、路径或 slot 定位、长度、shape、dtype、layout、pixel format 和校验元数据。它不承担权威 owner、pool、deadline 或清理授权。

服务端所有权操作使用私有 `LeaseOwnershipReceipt`。receipt 至少保存 pool、buffer、lease、broker epoch、generation、expected owner kind/id、deadline、guard identity 和精确范围。Workflow worker、父进程和 Broker 只根据 receipt 执行 transfer、release、revoke 或 sweep，不能因为公开 `BufferRef` 能定位字节就把它当作所有权凭据。

generation 与 owner fence 用于阻止已回收 slot 的旧引用读取新数据。deadline 用于诊断和清理失联 lease，不等同于请求超时后的无条件回收。

## 生命周期

```text
allocate -> write -> commit -> acquire -> read -> release
```

External Trigger 输入必须显式完成：

```text
workflow-trigger-write
  -> workflow-runtime
  -> workflow-trigger-response（仅当同一图片被选择为结果）
```

WorkflowRun 建立并取得真实 Runtime/执行器 permit 后、提交 worker 前执行第一次条件 owner transfer。Run 创建或 admission 失败时按原 writer receipt 回收；transfer 成功但 worker 提交失败时按新的 Runtime receipt 回收。不能跳过第一次 transfer 后直接假设输入已经属于 Run owner。

1. producer 请求可容纳目标字节数的 slot；
2. producer 写入 mmap 并提交 shape、dtype、format 等元数据；
3. consumer 按引用 acquire lease；
4. consumer 直接读取 mmap；
5. 每个 owner 在 finally 中 release；
6. 所有 lease 释放后，slot 才能安全回到池中。

超时、取消、进程退出和 Runtime 切版都必须携带 generation/owner 条件释放。不能仅按 slot id 回收，否则会破坏正在处理的新一代引用。

## 调用链

- Web Preview 上传大图片后转换为 LocalBuffer `image-ref.v1`；
- deployment sync/async 调用传递 BufferRef，不复制整张图片；
- storage 或 inline 同步 deployment 输入由 backend-service 写入主 LocalBuffer；持久异步任务由 daemon 领取后写入私有短期 LocalBuffer；
- 需要返回结果图片时，backend-service 先分配 writing lease，daemon 直接写入，提交后再由 API/Workflow 边界决定返回或持久化；
- Workflow 节点间优先复用一次执行内 memory handle；跨进程时使用 LocalBuffer；
- Trigger 调用解析为当前 Runtime 可消费的图片引用；
- 需要长期保留或跨重启使用的结果转存 ObjectStore 或明确的磁盘保存位置。

### Workflow Trigger 输出所有权

本机共享内存和 ZeroMQ 图片结果共用同一套 output lease 规范化与 owner handoff 规则，差别只在协议交付：

- 当前 Workflow Run 的私有 receipt 证明完整所有权时，对应 BufferRef 可以零复制 transfer；
- foreign/incomplete-owner BufferRef、memory handle 和 FrameRef 必须在 worker cleanup 前按目标交付规范化；FrameRef 始终复制，不提供 pin 分支。storage/local-path 按 delivery kind 选择 LocalBuffer 物化、不可变 ObjectStore locator 复用或受管理持久化。普通绝对路径没有可强制外部 writer 遵守的稳定 reader guard，ZeroMQ 交付前必须复制到 LocalBuffer、adapter 自有不可变 bytes 或不可变 ObjectStore snapshot；
- 多个逻辑 attachment 可以引用同一物理 payload，handoff/release 和 ZeroMQ 传输按完整 identity 去重，逻辑 binding/item 顺序不丢失；
- response owner 使用 `delivery_kind + response_id`，不能写死为 mailbox descriptor：本机共享内存和 ZeroMQ 都能使用同一 fenced cleanup API；
- 一批输出先核算容量、规范化并全量校验，再原子 handoff；任一失败都清理暂存 lease并返回 `local_buffer_output_capacity_exhausted` 或对应错误，不发布部分成功；
- input、output、REVOKING、QUARANTINED 和等待 ACK/ZeroMQ send 终态的 lease 都计入容量。输入图直接作为输出时可以 transfer 同一 lease，不重复占 slot。

短期 output lease 只保持到协议终态：local-shared-memory 的 reader guard 由 SDK 结果对象持有到 `Dispose`/`DisposeAsync`，结果对象先使 view 失效并释放全部 guard，再发布 ACK；JSON-only 或已经复制为 SDK 自有 bytes 的结果可以提前 ACK。ZeroMQ 为全部已提交 tracked frame 完成；发送失败必须先关闭 socket，再确认 tracker，仍未完成的 reader 进入 REVOKING/QUARANTINED，不能立即释放。`accepted-then-query` 的临时图片必须复制到 ObjectStore；只有同时具有不可变 version、checksum、准确长度和 media type 的 ObjectStore 引用可以直接复用。

ZeroMQ `zmq.Frame`、`MessageTracker`、mmap/file view、ObjectStore read snapshot 和 reader guard 只由 backend ZeroMQ adapter 进程内的有界 transport-lifetime registry 管理。adapter 在发送 Frame 0 前为整个响应预留 registry 容量；满载时不发送部分 multipart。LocalBufferBroker 是独立 companion process，只管理 lease state、deadline、identity fence 和 OS guard，不等待、保存或轮询 libzmq tracker。tracker 完成后由 adapter 释放本进程资源，再调用 Broker 的条件释放 API；adapter 退出时由 OS 释放 guard，Broker 按 deadline/receipt 收敛。

External lease 的内存驻留状态固定为：

```text
FREE -> WRITING -> ACTIVE

WRITING -> REVOKING -> FREE
                    -> QUARANTINED -> FREE

ACTIVE  -> REVOKING -> FREE
                    -> QUARANTINED -> FREE
```

WRITING 撤销等待 writer guard；ACTIVE 撤销等待所有 OS reader guard。ZeroMQ tracker 由 adapter 进程管理，不是 Broker lease 状态的一部分。ACK 或 deadline 只触发回收意图，不得绕过 guard 直接复用 slot。

## 满载语义

LocalBuffer 与推理执行面都采用有界资源：

- 可用 slot 或推理线程不足时立即返回结构化冲突；
- 不在 broker 内引入业务请求队列；
- 不做隐式重试；
- 调用方按请求结果决定是否再次调用。

这种语义让过载可观测，并避免队列过期、恢复和长尾延迟复杂性。

## 健康与诊断

健康信息应能定位：

- pool 总容量、已用容量和 slot 数；
- active owner/lease 数；
- slot generation、owner、deadline；
- allocate/acquire/release 失败原因；
- broker pid、instance identity 和 heartbeat；
- orphan/recovery 计数。

服务健康页的 backend-worker/broker 状态来自真实进程拓扑与 heartbeat；缺少 topology identity、过期 heartbeat 或 companion process 不可用时显示 degraded，而不是使用旧兼容状态推断健康。

## 稳定性规则

- broker 只由 full Supervisor 或明确的 backend-service takeover 管理，不手工重复启动；
- 每个 broker root 只有一个有效 owner；backend 主池和 daemon 私有异步暂存池不得使用同一 root；
- producer/consumer 所有路径必须在 finally 释放 lease；
- status/health 不修改 slot 所有权；
- 日志按日期轮转，异常必须包含 buffer/slot/generation/owner/deadline；
- mmap 文件只在确认无有效 owner 后回收。

## 明确边界

- 不支持跨主机共享内存；跨主机使用协议适配或持久化对象。
- 不把 LocalBuffer 引用写成长期公开业务资源。
- 不以 Base64 作为性能回退主链路。
- GPU IPC、RDMA 等能力不在当前实现范围，不能写入公开 capability。

已经接受但尚未实现的 `local-shared-memory` Trigger 会在普通 lease 之上增加 external writer/reader guard、REVOKING/QUARANTINED、identity-fenced release 和 output owner handoff。它属于 trusted-local 协作式边界，不把 generation 或 checksum 描述成恶意进程隔离能力。正式设计见 [ADR-0007](../../decisions/ADR-0007-local-shared-memory-workflow-trigger.md)，实施顺序见[本机共享内存 Trigger 实施基线](../../development/local-shared-memory-trigger-implementation.md)。

v1 每次调用只分配一张输入图片 lease；SDK 在 descriptor guard 内发布 REQUEST 后立即释放 writer guard，Broker 随后取得 guard、校验和 commit。backend-service 只有取得 Workflow mailbox owner lock 的进程能重置 mmap 或更新 server epoch；reload/takeover 不得形成双 owner。

相关文档：[高性能图片数据面](image-data-plane.md)、[Workflow Runtime](../workflows/runtime.md)、[模型部署运行时策略](../models/deployment-runtime.md)。
