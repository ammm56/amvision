# ADR-0007：本机共享内存 Workflow Trigger

## 状态

已接受并完成阶段0–9实现。Workflow Trigger mailbox 的共享 overflow page 并发、单一总 deadline、独立 ACK deadline、PROCESSING 取消、per-source health，以及 ADR-0008 固定 arena 数据面均已接入正式链路；完整故障、容量、性能和业务 soak 仍在执行。这些实现完整性修正没有改变本 ADR 的 Trigger 产品边界。

本 ADR 固定本机高频 Workflow Trigger 的架构边界和关键取舍。协议细节与性能边界见[本机共享内存 Trigger 实施基线](../development/local-shared-memory-trigger-implementation.md)；当前完成状态和剩余门禁见[共享内存数据面可靠性实施基线](../development/shared-memory-data-plane-reliability-implementation.md)和 [ADR-0008](ADR-0008-local-buffer-fixed-arena-allocation.md)。[ADR-0009](ADR-0009-local-message-channel.md) 只把 Trigger 与 Inference 的重复底层实现收敛到公共 engine，不改变本文独立物理 Channel、单 owner、独立 epoch 和容量隔离。`local-shared-memory` 与 `zeromq-topic` 仍是并列的正式 adapter；发布目录只能由当前源码按目标 profile 重新 assemble，不能手工覆盖。

## 背景

当前 ZeroMQ TriggerSource 使用 multipart 第二帧传输图片，backend-service 收包后再把图片写入 LocalBufferBroker。该链路保持明确的协议隔离并已可用，但同机 20MP BGR24 图片仍会经过 libzmq 发送、接收和一次 LocalBuffer 写入，无法消除整图跨协议复制。

项目已经具备普通 LocalBuffer lease、`BufferRef`、raw BGR24 mmap view、Workflow 单次执行解码缓存和 inference mailbox guard/page-chain 原语。新的本机高频入口应直接复用这些能力，同时不能引入以下错误边界：

- 不能让所有 TriggerSource 共用一个全局图片调用 gate；
- 不能让启用但空闲的 TriggerSource 永久占用 LocalBuffer slot；
- 不能为每个 TriggerSource 创建独立 mmap 文件或永久 frame channel；
- 不能在 Runtime 满载时隐藏排队、重试、回退 ZeroMQ 或写临时文件；
- 不能让 LocalBufferBroker 承担图片格式识别或解码职责；
- 不能把当前 ZeroMQ 通用图片入口静默改成另一种公开语义；
- 不能把 generation、checksum 或普通 mmap 字段写入误认为能够物理撤销外部 writer；
- 不能向 SDK 返回会在 Workflow Run cleanup 中立即失效的短期 `BufferRef`；
- 不能为新 Trigger 单独建立与 Runtime `request_lock` 脱节的容量状态。

## 决策

### 1. 新增独立的 local-shared-memory Trigger

新增 `local-shared-memory` TriggerSource adapter，组件名使用 `LocalSharedMemoryTriggerAdapter`。它与现有 `zeromq-topic` 并列，不是 ZeroMQ 内部模式，也不通过 ZeroMQ 传输图片或业务参数。

同一 backend-service 实例使用一个全局 Workflow Trigger mailbox。mailbox 保存 descriptor、业务参数、LocalBuffer lease identity、小型结构化结果和大型结构化结果的 page-chain。直接公开的 `image-ref.v1` 图片主体始终位于 LocalBufferBroker；只有图中显式执行 `Image Base64 Encode` 后形成的 `image-base64.v1` 才作为结构化 JSON 进入 inline/page-chain，并受单响应容量上限约束。mailbox 采用当前开发期的 v1 契约，不创建旧协议兼容层，也不复用 inference mailbox 的文件或所有权空间。

mailbox 路径固定从中立的 `local_memory.root_dir` 派生。当前正式环境使用 `data/buffers/local-message/workflow-trigger-main.rpc.mmap`，guard 和 owner lock 也放在 `local-message/` 子目录。不增加 Workflow Trigger 专属 root 配置，不在其他数据目录、临时目录或 SDK 配置目录创建 mmap。Trigger、Inference 和 LocalBuffer 仍分别启停，物理隔离与 owner 边界保持不变。

### 2. 每次调用动态占用一个普通 LocalBuffer lease

每个正在执行的图片 Trigger 调用动态申请一个普通 writing lease。TriggerSource 启用但未调用时占用为零；调用完成、失败或超时后按身份释放 lease。协议不把 TriggerSource 固定绑定到物理 slot，也不创建 `external producer frame channel`。

SDK 通过 PREPARE 获得 backend-service 分配的精确长度 lease，然后只通过 SDK 内部受限 view 写入本次 `path + offset + size`。backend-service 仍是 allocate、publish、validate、owner transfer 和 release 的权威协调者。该能力命名为 **External LocalBuffer Writer Lease**。v1 每次调用最多携带一张输入图片；PREPARE 和最终 request 的完整 LocalMessage envelope 均不得超过 64 KiB。结果可以包含 0 到 N 张图片。多图片输入不复用或隐式扩展 v1，后续如确有需要再显式版本化。

### 3. External Writer 属于 trusted-local 协作边界

SDK 映射 pool 文件后，操作系统不能把同一进程永久限制在某个逻辑 slot。`generation`、owner、epoch、guard 和适用边界中的 checksum 只能检测身份、并发或传输内容错误，不能阻止已经获得写句柄的异常进程继续修改共享字节。因此该能力不是恶意进程安全沙箱，其信任边界是可以读写 `data/buffers/` 的同一 OS 用户域进程。

每个 external writing lease 必须使用 OS byte-range writer guard：

- SDK 从开始写入到写 view 销毁期间持有 writer guard；完成写入后先释放 guard，再发布 REQUEST；
- Broker 只有取得同一 guard 后才能原子 publish/owner transfer 或回收；trusted-local 输入不做第二次 full-image CRC；
- WRITING 过期先进入 REVOKING，不能立即复用；
- 撤销宽限期后仍无法取得 guard 的槽位进入 QUARANTINED；
- SDK 取消确认、进程退出或 guard 释放后，Broker 才能按完整 identity 回收；
- QUARANTINED 必须进入容量、健康和告警指标，不能静默占用。

SDK 只向普通调用方暴露 lease 范围的 Span/View，不暴露任意 pool 写入 API。该限制用于减少误用，不改变 trusted-local 安全边界。

### 4. 并发按在途调用和真实资源决定

同一个 TriggerSource 默认最多一个在途同步调用；第二个调用立即返回 `trigger_source_busy`。不同 TriggerSource 可以同时获得不同 LocalBuffer lease 并调用不同 Workflow Runtime。

有效并发上限由输入和输出 LocalBuffer lease、Workflow Trigger mailbox descriptor、Runtime execution permit、有界执行器 permit 和实际在途 TriggerSource 共同决定，不按已创建或已启用的 TriggerSource 总数计算。输入容量耗尽时返回 `local_buffer_capacity_exhausted`；新生成图片需要的 output lease 不足时，整批失败并返回 `local_buffer_output_capacity_exhausted`。输入图片直接作为输出时复用同一 lease，不重复占用。Runtime 满载时立即返回 `workflow_runtime_busy`。

全局 mailbox poller 只扫描、校验、取得 permit、投递和发布结果，不能同步等待 Workflow 完成。有界执行器在提交前必须已经获得真实 Runtime permit和非阻塞 executor permit；任一 permit 不可用时立即失败并释放已经取得的资源。不能直接依赖带无界内部队列的执行器形成隐藏排队。

### 5. 图片来源与传输表示解耦

.NET SDK 调用方可以从工业相机、磁盘文件、网络、已有内存或任意其他方式获得图片。图片来源不决定 LocalBuffer 中必须保存哪一种表示；调用方通过明确的 SDK 方法选择 raw BGR24 或 encoded bytes。

高性能默认路径是由 SDK 接收或转换出连续 BGR24，再直接写入 External LocalBuffer Writer Lease，不执行 BMP、JPEG、PNG 或 Base64 编码。引用固定携带：

- `media_type=image/raw`；
- `shape=[height,width,3]`；
- `dtype=uint8`；
- `layout=HWC`；
- `pixel_format=bgr24`。

JPEG、PNG、BMP 等文件、Base64 和通用 encoded bytes 同样是正式支持的入口。调用方可以选择保留编码格式并直接写入 LocalBuffer，同时携带准确 `media_type`；后端只在本次 Workflow 首个矩阵消费者处解码一次。同一引用、generation 和 decode flags 在单次 Workflow 内通过 single-flight 与只读缓存复用，不能因并行分支或多个模型节点重复解码。

LocalBuffer slot 只保存字节和 lease 状态。`BufferRef` 保存 `media_type`、shape、dtype、layout 和 pixel format。raw/encoded 分流发生在统一图片读取 helper；encoded 图片的具体 codec 由 OpenCV 在解码边界读取文件头，不在 Broker 中探测。

### 6. Runtime admission 使用唯一真实执行 gate

PREPARE 可以检查 Runtime 健康，但最终 execution permit 在 SDK 完成图片写入并发布 REQUEST 后非阻塞获取。这样既不在 SDK 写图期间占住 Runtime，也不让已写入的图片在 `request_lock` 前排队。

REST、ZeroMQ、local-shared-memory 和异步 Runtime 调用必须共享 Workflow Runtime handle 的同一个真实 execution gate。新 token 固定 worker instance、revision、generation、snapshot fingerprint 和 request identity；`local-shared-memory` 使用 nonblocking acquire，普通入口可以保持既有等待语义。禁止增加与 `request_lock` 并行存在的 semaphore、布尔 busy 状态或第二套容量事实。

旧 completion、worker restart、切版、取消和 timeout 只能按 token identity 释放本次 gate，不得影响新 handle 或新 generation。

### 7. Workflow 节点决定图片表示，adapter 决定传输

Workflow App 的公开输出契约是结果语义的唯一事实源。节点和公开输出决定返回内容及表示，Trigger adapter 只负责把已经确定的表示映射到对应协议：

- 图片直接连接 App Result 时公开为 `image-ref.v1`，表示图片附件；
- `image-refs.v1` 表示一组图片附件，返回时保留 binding 和 item index；
- 图片经过 `Image Base64 Encode` 后公开为 `image-base64.v1`，表示用户明确选择的 Base64 JSON；
- 新增通用 `Image Encode` 节点，把 raw `image-ref.v1` 编码为 JPEG、PNG、BMP、WebP 等仍由 LocalBuffer 支持的 `image-ref.v1`；
- 不经过 `Image Encode` 的 raw BGR24 输出继续保持 raw bytes、shape、dtype、layout 和 pixel format，adapter 不得暗中编码；
- 现有 `Image Body` 显式生成 `response-body.v1`，可以在 adapter capability 和响应容量允许时被 `result_bindings` 明确选择；它不会被 Trigger adapter 隐式插入或用作图片传输方式选择器。

TriggerSource 结果映射从单个 `result_binding` 收敛为有序的 `result_bindings` 列表，以便同一次响应同时选择结构化 JSON、单图和多图。顶层 `result_mode`、`reply_timeout_seconds` 和 `ack_policy` 是唯一事实源，`result_mapping` 只保存 `result_bindings`。绑定的 payload 类型必须从已发布 Workflow App Version 的公开契约读取，不递归扫描 `value.v1`、`workflow-result.v1`、node records 或调试载荷中的嵌套临时引用。需要返回的临时图片必须作为独立公开 `image-ref.v1` 或 `image-refs.v1` binding；没有选择任何 binding 时只返回运行状态和 `workflow_run_id`。

选中的普通 JSON binding 仍需递归校验其中是否包含 `memory`、`buffer` 或 `frame` 短期 image-ref。发现此类嵌套引用时返回 `ephemeral_image_ref_in_json_result`，不能返回随后即失效的句柄，也不能把它们自动提升为 attachment。`result-record.v1` 或 `workflow-result.v1` 如需同时返回图片，图片必须另行发布成独立 application output binding。

不再保留“binding 不存在时返回全部 outputs”的 fallback。开发期迁移把已有单个 `result_binding` 转为单元素 `result_bindings` 后，删除旧字段和双读分支。

结果模型分为内部准备层和公开 wire 层，避免把 ZeroMQ frame index 写进 Workflow 执行层：

- 内部 `PreparedTriggerResult` 保存 JSON `response_payload`、有序 `logical_attachments` 和按完整物理 representation identity 去重的 `physical_payloads`。逻辑 attachment 只保存 binding/item 与 `payload_id`；物理 payload 保存规范化 output `BufferRef`、表示元数据和私有 handoff receipt。checksum 只用于完整性校验，不能单独作为 lease 所有权或传输去重依据。
- 公开 `WorkflowTriggerResultV1` 使用 `amvision.workflow-trigger-result.v1`，包含有序 logical attachments 和按 `payload_id` 去重的 physical payloads；attachment 引用 payload，payload 通过带 `kind` 的 locator 明确表示 `local-buffer`、`zeromq-frame` 或 `object-store` 交付位置。

每个逻辑 attachment 至少保存 attachment id、binding id、item index、payload type 和 `payload_id`。物理 payload 保存 media type、长度、校验值、尺寸和 raw 元数据。attachment 顺序固定为 `result_bindings` 顺序，再按 `image-refs.v1.items` 顺序；`source_image` 不自动作为 attachment。相同物理 payload 只 handoff、校验、发送和释放一次，多个逻辑 attachment 可以合法共享同一个 `payload_id`、LocalBuffer locator 或 ZeroMQ frame index。

### 8. 返回图片使用 output lease ownership handoff

本协议正式支持 Workflow 公开输出中的 LocalBuffer 图片引用，但不能沿用 Run 结束即释放的输入 lease 语义。

External Trigger 输入在进入 worker 前先完成第一次 owner transfer：backend-service 建立 WorkflowRun、取得真实 Runtime token 和有界执行器 permit 后，使用服务端私有 `LeaseOwnershipReceipt` 条件地把输入从 `workflow-trigger-write` 转给 `workflow-runtime`。Run 创建或 admission 失败时按原 writer receipt 回收；transfer 成功但 worker 提交失败时按 Runtime receipt 回收。公开 `BufferRef` 不保存权威 owner、pool 或 deadline，也不能替代 receipt。

在发布 RESPONSE 前，worker 必须按本次 `WorkflowOutputDeliveryPlan` 选中的公开图片 bindings，在 `WorkflowSnapshotExecution` 的普通 cleanup 之前完成图片规范化和 lease 接管：

- 当前 Run 完整拥有且 cleanup identity 完整的 BufferRef 可以零复制 transfer；
- memory image handle 必须在 execution image registry 清空前物化到 output lease；
- FrameRef 始终复制到独立 output lease，不增加 pin 分支；
- 目标为 `local-buffer` 时，storage/local-path 图片读取并物化到 output lease；目标为 `object-store` 时，只有同时具有不可变 version、checksum、准确长度和 media type 的受管理 ObjectStore 引用可以直接复用，缺少任一稳定性字段时先复制到新的不可变对象；目标为 `zeromq-frame` 时，受管理 ObjectStore 必须通过只读 snapshot 持续保护到 tracker 完成，普通本机绝对路径没有可强制外部 writer 遵守的 reader guard，必须先复制到受控 LocalBuffer 或 adapter 自有不可变 bytes；
- 不属于当前 Run 或 owner identity 不完整的 BufferRef 只能复制，不能抢占外部 owner。

worker 对需要交付的 lease 执行批量全量校验和 handoff，并返回 handoff receipt；父进程必须校验 receipt 后才能发布结果。response owner 使用 `delivery_kind + response_id`，不写死为 mailbox descriptor：local-shared-memory 的 response id 包含 descriptor/generation/request，ZeroMQ 的 response id 包含 listener/source/event/send generation。普通 Run cleanup 使用带 owner/generation/epoch 的条件释放，owner 已转移时只能 no-op。

一次响应包含多个图片引用时必须先把全部来源规范化，再批量全量校验、全量 handoff，不能产生部分成功。相同 lease 的重复引用只 handoff 一次。输入图未被返回时可以在图执行结束、输出已经稳定后先行条件释放，以便为新 output lease 让出 slot；任一 staging、分配或 handoff 失败时返回 `local_buffer_output_capacity_exhausted` 或对应结构化错误，并清理全部暂存资源。异步任务或需要长期保存的输出继续在持久化边界复制到 ObjectStore，不持久化短期 `BufferRef`。

Runtime execution token 在图执行和 output handoff 完成后即可释放；TriggerSource 单在途 permit 必须保持到协议责任已经安全结束或原子移交。local-shared-memory 的成功、失败、deadline、busy和capacity等所有可读取RESPONSE都有独立ACK deadline；成功图片结果必须先批量把output lease owner/deadline切到response owner与同一ACK deadline，最后才发布RESPONSE。零复制结果由SDK结果对象持有reader guard，只有`Dispose`/`DisposeAsync`先使view失效并释放全部guard后才发布ACK；JSON-only或已经复制到SDK自有`byte[]`的结果可以提前ACK。显式取消且不发布响应的CANCELLED不需要ACK deadline。ZeroMQ在全部已提交physical frame tracker完成，或未完成Frame已进入adapter进程内的transport-lifetime registry后释放source permit。socket send失败本身不代表lease可复用，不能在发布RESPONSE或关闭socket时直接结束全部生命周期责任。

### 9. 幂等只重放稳定结果

现有 TriggerSource 幂等能力继续防止同一 key 重复创建 WorkflowRun，但不能缓存并重放已经 ACK、发送或回收的临时 attachment：

- 没有 attachment 的 JSON 结果可以按现有 TTL 重放；
- 带临时 attachment 的请求只允许首个 owner 获得图片结果；并发或后续重复请求不得重新执行 Workflow，也不得复用原 BufferRef；
- 重复请求返回 `idempotent_attachment_result_not_replayable`，并携带原 `workflow_run_id`；
- 业务确实要求图片可重放时，必须显式使用 accepted-then-query/ObjectStore 持久化链路，不通过延长热路径 lease TTL 实现。

### 10. 跨 Python/.NET 发布依赖 guard，不依赖普通字段原子性

mailbox header、descriptor、状态、字段宽度、对齐、字节序和 checksum fixture 必须由单一 binary contract 生成 Python/.NET 常量。每个 descriptor 使用跨进程短临界区 guard：发布端在 guard 内先写 body、长度、checksum 和 identity，最后写 state；读取端取得 guard 后重新校验 state、generation、owner、epoch、deadline、长度和 checksum。

Windows guard 必须通过 Python `msvcrt.locking` 与 .NET `FileStream.Lock` 的真实双进程测试。Workflow mailbox 与 inference mailbox 共享中立 guard、owner lock、path fencing、checksum 和 page-chain 实现原语，但不共享 mmap 文件、epoch、descriptor 或 owner 空间。

backend-service 只有取得 Workflow mailbox owner lock 的进程才能创建或重置文件、更新 server epoch 和执行 sweep。开发态 `--reload` 的新旧进程重叠时，新进程在取得 owner lock 前不得改变 active mmap；takeover 必须等旧 owner 的 OS lock 释放后，以新 epoch 重建 descriptor/page 状态。任何时刻只能有一个进程对外声明 mailbox 可服务。

### 11. Deadline 与 lease 长度由 backend 权威控制

v1 的 PREPARE 必须给出最终 `content_length`，SDK 获得的 view 长度与之完全相等。BGR24、encoded byte array、File 和 Base64 还原后的 bytes 都能在 PREPARE 前确定精确长度，因此 v1 不保留 `capacity + written_size` 的可变长度语义。

SDK 只提交相对 `timeout_ms`。backend-service 根据已启用 TriggerSource 快照校验并建立本进程 monotonic deadline，PREPARE、写图、admission、Workflow、结果构建/序列化/压缩、page分配、output handoff和成功RESPONSE publication使用同一剩余预算；不同进程不比较绝对 monotonic 值。输入lease TTL覆盖请求与cleanup grace，输出lease在RESPONSE前更新为独立ACK deadline。binary schema使用固定`cancel_reason=none|request_timeout|explicit|client_shutdown`，不以单一bit混淆取消来源。backend-service或Broker重启时通过新epoch失效旧请求。

### 12. 路由和高速记录策略由服务端固定

SDK 请求只提交 `trigger_source_id`、事件 identity、业务参数和图片 lease。project、Runtime、revision、generation、input mapping、默认 metadata 和 timeout 上限全部来自服务端已启用的 TriggerSource 快照。PREPARE 后路由 generation 发生变化时返回 `trigger_route_changed`，不能悄悄执行不同 revision。

`local-shared-memory` 与 `zeromq-topic` 同属高速入口，默认使用 `workflow_run_record_mode=minimal`，关闭 trace、node records、input payload 和 output retention，保留必要生命周期记录与最终数据库提交。诊断 timing 由显式开关控制，不以 `none` 作为默认记录模式。

### 13. 不支持结果的 Trigger 使用显式交付策略

Workflow App 的公开输出与 Trigger 协议能力解耦。同一个 Runtime 可以同时绑定支持图片的本机共享内存或 ZeroMQ Trigger，以及不具备同步回传通道的 PLC、IO、目录、MQTT 或定时 Trigger。

每个 adapter 必须通过结构化 capability 声明支持的 submit modes、result modes、attachment delivery kinds，以及最大 JSON、单 attachment、attachment 数量和总响应容量。TriggerSource 在创建、enable 和 Runtime 切版时，根据公开输出契约、`result_bindings`、route generation、Runtime revision/generation/snapshot fingerprint 和 capability revision 构建不可变 `TriggerResponsePlan`；worker 只接收从中派生的协议中立 `WorkflowOutputDeliveryPlan`：

- `event-only` 明确丢弃全部结果，不建立 output handoff，不逐次记录不支持警告；
- `accepted-then-query` 只返回状态和 run id，待查询图片必须在持久化边界复制到 ObjectStore，不能保存短期 BufferRef；
- 同步 adapter 不支持某个被选择的 binding 时拒绝配置；不需要的输出直接从 `result_bindings` 中省略，不增加 discard 开关；
- 支持图片的同步 adapter 按自己的数据面交付 attachment，不改变图内 payload 表示。

不能在单次调用完成后再临时猜测是否丢弃图片。响应计划必须在 Workflow 执行前固定，使 worker 在 cleanup 前明确知道哪些 lease 需要 handoff。

local-shared-memory v1 只支持 `submit_mode=sync`、`ack-after-run-finished` 和 `sync-reply`。异步提交、查询结果和多图片输入不混入第一版共享内存热路径。

### 14. ZeroMQ 使用一个统一的 Trigger Result v1

现有 ZeroMQ TriggerSource 继续用于跨进程协议集成、已有客户端和不需要直接 mmap 的场景。它不作为 local-shared-memory 满载或失败后的 fallback。两个入口共享 Workflow 输入契约和 LocalBuffer 消费链路，但拥有不同的传输协议、健康状态和性能指标。

ZeroMQ reply 只保留一个 `amvision.workflow-trigger-result.v1` 定义。ZeroMQ 消息始终按 multipart 接收和发送：Frame 0 是 UTF-8 JSON manifest，后续 0 到 N 个 frame 是图片 attachments。没有图片时 `N=0`，消息自然只有一帧 JSON，不形成第二种协议、reply mode 或版本。

manifest 包含运行状态、结构化结果、统一 error 对象、logical attachments 和唯一 physical payload/frame 元数据。每个逻辑 attachment 记录 binding、item index 和 payload/frame 引用；物理 payload 记录 frame index、media type、长度、checksum、尺寸和 raw 元数据。SDK 必须拒绝缺帧、额外帧、越界索引、长度或 checksum 不符，但允许多个逻辑 attachment 共享同一物理 frame。成功、业务失败和 adapter 错误都使用同一个 result format；删除独立 ZeroMQ error envelope 和对应解析分支。

ZeroMQ 发送节点已经确定的原始表示：raw BGR24 发送 raw bytes，显式 `Image Encode` 产生的 JPEG/PNG 发送对应编码 bytes，`image-base64.v1` 只留在 Frame 0 JSON 而不重复生成 binary frame。adapter 按唯一物理 payload 建立受跟踪的零拷贝 `zmq.Frame`；多个逻辑 attachment 可以共享同一个 frame index，不能重复发送同一张大图。

adapter 逐个提交唯一物理 frame，只登记已经被 socket 成功接受的 tracker，不依赖 `send_multipart(track=True)` 返回的最后一帧 tracker推断整批完成。adapter 必须在发送 Frame 0 前为本次响应的全部唯一 physical frame 预留有界 transport-lifetime registry 容量，并取得所需 reader guard/read snapshot；容量不足时在任何 multipart frame 发出前失败。发送开始后该预留责任保持到所有 tracker 完成或 adapter 进程退出，不能因为 registry 满载丢弃 Frame、tracker 或 guard。发送或 tracker 超时后先停止监听并以 `linger=0` 关闭 REP socket，再等待所有已登记 tracker；全部完成后依次销毁 Frame/view、释放 reader guard/read snapshot，并调用 Broker 的 identity-fenced release。关闭后仍未完成的 Frame、tracker、view 和 guard 继续由 adapter 进程内 registry 持有，对应 ACTIVE lease 进入 REVOKING，宽限期后进入 QUARANTINED，不能立即复用。未成功提交给 socket 的 frame 不加入 tracker 集合，但已经取得的 guard/view 仍由当前预留项负责清理。ZeroMQ 仍有协议栈和接收侧整图复制，因此不能宣称与本机共享内存等价。

TriggerSource 不增加 `reply_protocol`、JSON/multipart mode 或协议协商字段。.NET SDK 始终接收完整 multipart message、解析 Frame 0 并严格校验其声明的后续 frames。当前仍处于开发阶段，Workflow TriggerSource result mapping REST payload 与 `amvision.workflow-trigger-result.v1` 由后端、Alembic 数据迁移、前端、仓库内 SDK、fixture/Postman 和已有数据在同一提交链中整体迁移，随后删除旧字段、“只解析第一帧”、独立 error format 和双读/双协议兼容分支。该声明只适用于本次未发布的 Workflow Trigger 结果契约，不代表其他 REST `/api/v1` 接口不承诺兼容。只有统一 v1 正式冻结并发布后再次发生不兼容变化，才增加新的协议版本。

### 15. SDK 零复制结果由结果对象持有 reader guard

`local-shared-memory` 的零复制 attachment 在 `Invoke` 返回后仍由调用方读取，因此 reader guard 不能在首次 checksum 校验完成后释放。SDK 必须在公开结果对象返回前取得所有唯一物理 attachment 的 reader guard，并由结果对象持有到确定性释放：

```text
Invoke 返回结果
  -> 调用方读取 attachment
  -> Dispose / DisposeAsync 原子禁止新读取
  -> 等待 SDK 内已开始的读取结束并使 view 失效
  -> 释放全部 reader guard
  -> 发布一次 ACK
```

结果对象的释放必须幂等，多次调用只发布一次 ACK。调用方不得保存并在结果释放后继续使用已取得的 `Span`/view；SDK 使用 `IMemoryOwner<byte>`、受控 accessor 或等价的 owner-backed API 表达该生命周期。终结器只用于泄漏诊断和尽力释放，不能替代 `Dispose`。response deadline 到达但 reader guard 仍被持有时，lease 只能进入 `ACTIVE -> REVOKING -> QUARANTINED/FREE`，不能复用 slot。JSON-only 结果以及已经显式复制到 SDK 自有内存的 attachment 不再依赖共享 view，可以在 `Invoke` 返回前完成 ACK。

### 16. ZeroMQ 传输生命周期只由 adapter 进程管理

`zmq.Frame`、`MessageTracker`、mmap/file view 和 ZeroMQ reader guard 都是 backend ZeroMQ adapter 进程内对象，不能跨进程交给 LocalBufferBroker。adapter 使用同进程有界 transport-lifetime registry 管理 normal-send 和 failed-send 两类 entry；每个 entry 保存 send identity、唯一 physical payload identity、Frame、tracker、view/snapshot、reader guard、lease receipt、deadline 和 socket generation。

LocalBufferBroker 只管理 lease state、deadline、generation/epoch/owner fence、OS guard 状态和条件 transfer/release。tracker 完成后由 adapter 释放本进程资源，再调用 Broker 的条件释放 API；adapter 进程崩溃时由操作系统释放其 socket、view 和 guard handle，Broker 随后按 deadline 与 receipt 回收。Broker 不等待、轮询或保存任何 libzmq tracker。

transport-lifetime registry 容量必须在发送第一帧前按本次响应的唯一 physical frame 数一次性预留。预留失败返回 `zeromq_transport_capacity_exhausted`，并在 socket 尚可用时仅发送不依赖 output lease 的小型 JSON 错误；不得形成部分 multipart 结果。第一帧发送后，当前响应已经取得的全部容量和清理责任必须保持到传输资源终结。

### 17. ObjectStore 直接复用依赖不可变读取快照

ObjectStore 增加正式应用端口：`stat_object()` 返回 object key、content length、media type、checksum algorithm/value、immutable version/etag 和 immutable 状态；`open_read_snapshot()` 返回在整个发送期间保持有效的只读 snapshot；不可变写入返回 `ObjectWriteReceipt`。公开 `object-store` locator 只有在 checksum、不可变 version、准确长度和 media type 全部存在时才可直接复用，这些字段不是“可用时提供”的可选诊断信息。

本地 ObjectStore 通过新的 run/version/content-addressed key、完整写入后原子发布和禁止覆盖形成不可变对象。checksum 在发布时生成并持久保存，不能在每次发送 20MP 图片前重复扫描。旧对象或可变 object key 缺少稳定元数据时，先物化为新的不可变受管理对象。`open_read_snapshot()` 的 handle/view 必须保持到 ZeroMQ tracker 完成。普通本机绝对路径可以继续作为 Workflow 输入或保存位置，但不能直接生成稳定响应 locator，也不能被描述为具有跨外部 writer 的 reader guard。

## 未采用方案

- **全局最多一个图片请求**：会让无关 TriggerSource 相互阻塞，无法利用多个 Runtime 和多个 LocalBuffer slot。
- **每个 TriggerSource 永久占用一个 slot**：启用数量会错误决定容量，空闲 TriggerSource 也会耗尽资源。
- **永久 external frame channel**：会静态预留槽位，并允许帧代次覆盖，不适合必须持有输入到 Workflow 完成的同步调用。
- **每个 TriggerSource 一个 `control.mmap` 或 `frames.mmap`**：增加文件、映射、恢复和生命周期复杂度，并形成不必要的第二图片缓冲区。
- **为 Workflow Trigger 图片数据面增加独立 mmap root**：会让图片 pool、inference image mailbox 和 Trigger mailbox 的目录配置漂移；这些数据面文件统一收口到 `data/buffers/`。训练遥测不进入图片 LocalBuffer；其后续结构化 Channel 目录迁移由 [ADR-0009](ADR-0009-local-message-channel.md) 单独定义。
- **仍通过 ZeroMQ 发送图片，再称为共享内存 Trigger**：保留整图协议复制，不能达到新入口目标。
- **所有图片入口强制转 BGR24**：会静默改变现有 SDK 语义，并可能让压缩图片无条件膨胀；encoded 入口继续正式支持。
- **LocalBuffer 内探测或解码图片格式**：混淆字节存储和图片处理职责，难以保持 Broker 稳定。
- **Runtime 锁前排队、自动重试或回退文件/ZeroMQ**：造成不可控长尾和恢复语义。
- **WRITING 超时后立即复用 slot**：旧 writer 可能破坏新 generation；必须先撤销或隔离。
- **只返回 ObjectStore 或小 JSON，永久取消本机图片结果**：无法覆盖工业现场同步获取处理图的正式需求；本项目选择实现 output lease handoff。
- **adapter 暗中把所有图片编码成 JPEG/PNG**：改变节点选择的表示并引入不可见编码成本；编码必须由显式节点决定。
- **把无图片 JSON reply 和有图片 multipart reply 定义成两个版本**：两者只是同一 multipart 消息的 `N=0` 与 `N>0`，拆分会增加配置、协商、SDK 分支和重复门禁；统一使用支持 0..N attachments 的 v1。
- **递归扫描任意 JSON 查找 image-ref**：无法依据公开契约提前建立 handoff 计划，也容易把调试或内部引用错误暴露；只处理选中的独立公开图片 binding。
- **不支持回复的 Trigger 在每次调用中临时忽略结果**：造成行为不可审计；通过 `result_mode`、capability 和固定 response plan 明确配置。
- **对 trusted-local 输入做 SDK/backend 双重 full-image CRC**：阶段 0 实测表明 20MP 输入的两次整帧扫描约增加 95 ms，且 writer guard、精确 allocation、REQUEST publication barrier、receipt/epoch/generation/owner/deadline 已经提供并发一致性与错代次防护。输入图片不携带 checksum；mailbox 结构化 payload、page-chain 和结果 attachment 仍保留各自 CRC/checksum，不提供恢复旧双扫描热路径的兼容开关。

## 影响

- .NET SDK 将新增本机共享内存 client、受限 mmap writer/reader guard 和 output ACK；ZeroMQ client 统一解析 `amvision.workflow-trigger-result.v1` 的 Frame 0 与 0..N 个 binary attachments，不维护 JSON-only 与 multipart 两套协议。
- backend-service 将新增全局 Workflow Trigger mailbox、每 TriggerSource 单在途 registry、统一 Runtime execution token、协议中立 attachment 和 output lease handoff。
- LocalBufferBroker 继续使用普通 lease，不新增永久 channel；需要新增 external writer revoke/quarantine、identity-fenced release、owner transfer 和 monotonic deadline。
- encoded 输入仍有一次必要的 OpenCV 解码和目标矩阵分配；raw BGR24 使用只读 mmap view。性能指标必须区分 SDK 转换、共享内存写入、输入 guard publication、结果 checksum、首次解码和 Workflow 执行。
- LocalBuffer 基于文件支持的 mmap 且默认不主动 flush；这不会每次同步刷盘，但不能表述为操作系统永不异步回写脏页。物理上完全不使用磁盘属于未来独立 shared-memory backend，不混入本次实现。
- API、SDK、配置包和架构文档必须同步使用当前已实现的 v1 契约；后续破坏性变更继续显式版本化，不能恢复双读或隐式兼容分支。
