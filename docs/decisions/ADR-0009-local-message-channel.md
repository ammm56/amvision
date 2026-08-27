# ADR-0009：本机结构化消息共享内存通道

## 状态

已接受，部分实现。阶段 0–6、阶段 7 源码门禁、本机 10,000 次压力和独立发行装配验证均已完成；Training Telemetry、Inference RPC、Workflow Trigger 三条正式链路已原子迁移。阶段 5 基准已裁决保留 Workflow Runtime、PublishedInferenceGateway 和 LocalBuffer Broker 的现有 Queue/pipe 传输，不创建对应 mmap Channel。真实目标发行环境 24 小时混合 soak 尚未执行，因此本 ADR 暂不标记为“已实现”。实现顺序与验证门禁见[本机结构化消息通道实施基线](../development/local-message-channel-implementation.md)。

## 背景

项目已经形成统一的图片大数据面 LocalBuffer，但 JSON、UTF-8 文本、控制元数据和结构化结果仍分散在多套进程间实现中：

| 链路 | 当前实现 | 所有者与语义 |
| --- | --- | --- |
| Workflow Trigger | 独立 LocalMessage RpcMailbox + Trigger extension | backend-service 单 server owner；PREPARE、WRITING、REQUEST、RESPONSE、ACK |
| Inference daemon | 独立 LocalMessage RpcMailbox | inference daemon 单 server owner；REQUEST、PROCESSING、RESPONSE、ACK |
| 训练遥测 | 每个训练 Worker 一个 LocalMessage EventRing | 单 producer；允许覆盖并报告 gap |
| Workflow Runtime | 每个 Runtime 一组 `multiprocessing.Queue` | Runtime manager 与 worker 的命令、响应和 heartbeat |

Workflow Trigger、Inference 和训练遥测原有的重复底层实现已经分别在阶段 4、阶段 3、阶段 2 删除，并接入通用 RpcMailbox/EventRing engine。Trigger 的两阶段握手与 LocalBuffer handoff 保留为窄业务 extension，不进入 common layout 或 EventRing。

普通请求通常只有几 KiB，但 segmentation polygon/RLE 和显式 Base64 节点结果可能达到现有 32 MiB 上限。因此目标不能退化成只支持小文本的固定 ring，仍需保留小消息 inline 快路径与有界大响应 page chain。

## 决策

### 1. 建立项目级 LocalMessageChannel

LocalMessageChannel 与 LocalBuffer 平行，二者职责互斥：

```text
LocalMemory
├─ LocalBuffer
│  └─ 图片、视频帧和需要连续 view 的大块 binary
└─ LocalMessageChannel
   ├─ RpcMailboxChannel
   └─ EventRingChannel
```

LocalMessageChannel 承载 JSON、UTF-8 文本、控制元数据、BufferRef/FrameRef 和结构化计算结果。原始图片 bytes、JPEG/PNG/BMP 等 encoded binary attachment、视频帧、OpenCV/NumPy 矩阵和模型 tensor 不进入 LocalMessageChannel。

用户显式执行 `Image Base64 Encode` 后得到的 `image-base64.v1` 属于结构化 JSON，可以进入 RPC inline/page-chain，但它是兼容输出而不是本机高性能图片路径，并继续受序列化前 32 MiB 单响应上限约束。默认图片输入输出继续使用 LocalBuffer 引用。

Database、Transactional Outbox、LocalFileQueue 和 ObjectStore 继续负责持久状态、跨重启任务、审计与长期文件。mmap 满载不能自动切换持久队列、临时文件、Base64 或其他协议。

### 2. 统一框架，按 owner 隔离物理 Channel

项目只维护一套 LocalMessageChannel 基础设施，包括：

- binary header、layout fingerprint、Channel identity、owner epoch 和 checksum 算法标识；
- guard、publication、owner lock、路径约束、恢复和 health 公共实现；
- Python/.NET 共用的 schema 生成工具、fixture 和代码生成；
- backend 配置、容量摘要与错误分类。

Binary contract 分为四层，不能把 RPC 与 EventRing 合成一份完整 schema：

```text
LocalMessage binary common schema v1
├─ magic / version / byte order / alignment
├─ channel kind / channel id / owner epoch
├─ layout fingerprint / checksum algorithm id
│
├─ RpcMailboxChannel.v1
│  └─ descriptor / inline / page-chain / request-response lifecycle
├─ EventRingChannel.v1
│  └─ ring slot / sequence / overwrite / gap / producer lifecycle
└─ Workflow Trigger RPC extension v1
   └─ PREPARE / WRITING / LocalBuffer receipt / output handoff
```

Overflow page-chain 只属于 RPC，不进入 common primitives 或 EventRing。公共原语可以由两个完整 schema 引用或由同一生成工具组合，但不能形成要求两种 Channel 使用相同状态机、header 全字段或容量几何的单一 on-disk contract。

路径 containment、guard 获取顺序、publication 顺序、owner lock 和异常恢复属于 engine 规范及公共实现，不是 on-disk binary schema 字段，也不进入代码生成 DTO。`.NET` 只生成公开 Workflow Trigger 使用的 common、RPC 和 Trigger extension contract；内部 Training EventRing 不生成 SDK 类型。

Health 同样采用“公共 envelope + 分类型指标”：公共部分只报告 channel id/kind、owner epoch、layout fingerprint、服务状态、容量摘要和最近错误；RPC 单独报告 descriptor/page、request、ACK、cancel 和 timeout；EventRing 单独报告 slot、sequence、gap/drop 和 producer。不能为形式统一向 EventRing 填充无意义的 ACK/page 指标。

每个 Channel 仍使用独立 mmap 文件、独立 owner lock 和独立 epoch。物理文件是故障与容量隔离单元，不代表独立实现。两种 Channel 的所有权和容量语义分别固定为：

- `RpcMailboxChannel`：单 server owner、descriptor + inline + response page pool，并由 server 进程内 page allocator 独占分配和释放 response page；
- `EventRingChannel`：单 producer owner、固定 ring slots、sequence/generation、overwrite/gap/drop，不包含 descriptor、page pool、ACK 或 server page allocator。

不建立由 Trigger、Inference 和 Training 任意进程共同修改的全局动态 payload arena。当前 mailbox 的 page 安全性依赖单 server owner 与进程内 allocator lock；把它改成多 owner 全局 allocator 会要求额外的单 allocator owner、崩溃原子日志或在线一致性重建协议，并扩大锁竞争与故障影响范围。

### 3. 只提供两种现行 Channel 语义

`RpcMailboxChannel.v1` 提供：

- 有界 request/response descriptor；
- 小消息 inline request/response；
- server owner 分配和释放的 response overflow page chain；
- REQUEST、PROCESSING、RESPONSE、ACK、cancel、deadline 和异常回收；
- domain extension，但不把所有领域字段写入通用 descriptor。

Workflow Trigger 在通用 RPC engine 上保留 PREPARE、WRITING、External LocalBuffer Writer Lease、Runtime admission 和 output handoff 扩展。Inference 使用普通 RPC 路径，不承担 Trigger 的 External Writer 状态。

`EventRingChannel.v1` 提供：

- 单 producer、固定有界 ring；
- sequence、generation、CRC、producer epoch；
- reader cursor、覆盖、gap/drop 统计和 producer close；
- 非阻塞 publish，不增加 RESPONSE、ACK、cancel 或 owner transfer。

本轮不增加 latest-value/notification 第三种 Channel。只有真实 heartbeat 或通知基准证明现有 Queue/事件机制成为瓶颈后，才另行决策。

### 4. 开发期只保留一个 v1

当前协议仍处于发布前开发阶段。schema 分为 `local-message-common.v1`、`local-message-rpc.v1`、`local-message-event-ring.v1` 和 Workflow Trigger RPC extension v1；领域 contract 继续使用各自 v1 标识并引用或组合公共原语。

每条业务链迁移时，后端、前端、配置、Python/.NET SDK、fixture、测试资产和现有开发文件在同一提交链中原子切换。迁移完成后删除旧 binary layout、旧字段和双读代码，不创建 v2，也不长期并行运行两套协议。

### 5. 统一根目录但不合并 allocator

所有正式共享内存文件统一位于受信任的 `data/buffers/` 根目录。目标布局为：

```text
data/buffers/
├─ local-buffer/
│  ├─ arena-main.mmap
│  └─ allocator-main.mmap
├─ local-message/
│  ├─ inference-daemon-main.rpc.mmap
│  ├─ workflow-trigger-main.rpc.mmap
│  └─ training-telemetry/
│     └─ <worker-session-id>.event.mmap
└─ inference-daemon-private/
```

训练遥测迁移到 `data/buffers/local-message/training-telemetry/`，但仍不属于 LocalBuffer 图片 arena。测试使用 `.tmp/<test>/buffers/` 下的同一布局。

Workflow Runtime、PublishedInferenceGateway 和 LocalBuffer Broker 在基准裁决前不创建目标 mmap 目录或文件。稳定公开 Channel 使用固定 domain id；临时 Worker Channel 使用稳定 worker session identity，不能把 PID 单独作为权威 identity。EventRing 的 owner lock/guard、owner epoch 和 worker session identity 是生产者存活、重启隔离和回收的权威依据；producer PID 与 process start identity 只作为诊断和快速存活探测元数据。`producer closed` 只表示正常关闭，异常退出必须由 owner guard 释放和 epoch 规则收敛，不能等待不会再发布的 closed 状态。外部 SDK 只能发现公开 Workflow Trigger Channel；内部 Inference 和 Training Channel 不进入 SDK 配置包。

共享路径配置提升为中立的 `local_memory.root_dir`，默认 `./data/buffers`。它只定义受信文件根，不代表一个全局 owner、进程或 enable 开关：

- `local_buffer_broker.enabled` 只控制 LocalBuffer；
- `inference_daemon.mmap_mailbox.enabled` 只控制 Inference RPC Channel；
- `training_telemetry.enabled` 只控制 Training EventRing；
- Workflow Trigger Channel 的配置和路径所有权由对应 adapter/service 管理，不从 LocalBuffer 配置派生；
- LocalMessage 基础设施、Inference RPC 和 Training EventRing 不依赖 `local_buffer_broker.enabled`，训练遥测可以在没有 LocalBuffer 的训练 Worker 中工作；
- 当前 Workflow Trigger v1 的 PREPARE 必须申请输入图片 lease，因此 Trigger 服务能力明确依赖 LocalBufferBroker ready；Broker 未启用或未就绪时，Trigger capability 必须报告 unavailable，不能仅因 mailbox 文件存在而报告 healthy。

不增加全局 `local_message.enabled`。SDK 配置包从中立 `local_memory.root_dir` 获得 `buffers_root`，但 SDK 必须读取 Workflow Trigger capability/health 判断业务可用性，不能只根据 LocalBuffer enabled、路径存在或静态配置推断 Channel healthy。`data/buffers/` 的文档含义相应扩大为本机共享内存数据根，其中 `local-buffer/` 是连续图片数据面，`local-message/` 是结构化消息数据面。

### 6. 容量按 Channel 观测和配置

不以现有两个约 256 MiB 文件之和为理由冻结一个 512 MiB 全局 arena。mmap 逻辑文件长度不等于全部物理内存常驻，合并文件本身也不会消除协议重复。

迁移前先采集每个 Channel 的 request/response P50、P95、P99、最大值、并发、page 高水位和容量拒绝。随后为 Trigger RPC、Inference RPC 和 Training Event 分别在代码中冻结有名称的稳定默认 profile：

阶段 0 已按该契约完成测量，最终数值、环境与选择依据见 [LocalMessage Channel 阶段 0 基线](../development/local-message-channel-stage0-baseline.md)。

- descriptor 数；
- inline request/response 容量；
- overflow page 大小、总数和单响应页数上限；
- 单消息与单 Channel 在途容量上限；
- poll/wakeup 与压缩阈值。

普通部署配置不提供 `channel_profiles`，SDK、前端、TriggerSource 和 Workflow 节点也不显示 descriptor/page/profile。有效几何必须写入 header，client 打开文件后校验 header、layout fingerprint 和真实容量。只有真实消息分布证明某个固定默认值无法覆盖目标现场后，才单独设计仅供后端高级运维使用的容量覆盖项；本轮不预先实现该配置面。

模型推理、Workflow executor 和 TriggerSource 的业务执行并发不属于 Channel 几何，继续由各领域配置与真实 admission gate 管理，不能藏进 transport profile。

每个 Channel 容量独立，Inference 的大 segmentation 响应不得耗尽 Workflow Trigger 或训练遥测资源。满载立即返回稳定错误；不等待、不重试、不重跑推理或 Workflow。

### 7. LocalMessage 使用窄 port，现有 Queue 保留领域通道

LocalMessage 的 RPC/Event adapter 只通过四个窄 port、DTO、payload codec 和领域错误进入 application，不能把 `mmap`、文件路径、offset、guard 或 page layout 暴露给 application：

- `RpcClientPort`：提交不可变 wire bytes，并返回带受控 ACK/close 生命周期的 response handle；
- `RpcServerPort`：接收 request context、观察取消并发布一次 response；
- `EventPublisherPort`：非阻塞发布不可变 event wire bytes；
- `EventReaderPort`：按 cursor 读取 event batch，并显式返回 sequence gap/closed 状态。

Port 的 wire payload 统一为 `bytes`。typed DTO 与紧凑 UTF-8 JSON 的 encode/decode 位于 contract/application codec 边界，transport adapter 不解析业务 JSON。Queue 与 mmap 基准必须传输完全相同的 envelope 和 bytes，不能让 Queue 传 Python dict、mmap 传 JSON bytes。

本机同步 RPC deadline 统一使用同一主机、同一启动周期、同一 monotonic clock domain 内的绝对 monotonic nanoseconds；外部 duration 只在权威 server 入口换算一次，公开 SDK 不能把自身 monotonic 计数作为 Python server 的绝对 deadline。换算后的 deadline 不持久化且由 owner epoch 隔离重启。取消使用固定 `cancel_reason`，server 通过 request context 读取取消状态。client 完整取得 response bytes 后由 response handle ACK；普通 Queue adapter 的 ACK 可以是幂等 no-op，Workflow Trigger extension 可以把 ACK 延迟到输出 LocalBuffer result dispose。所有 port 的 `close(deadline_ns)` 必须幂等，owner epoch 变化统一映射为 `ChannelRestarted` 领域错误，不能向 application 暴露 offset、state 数值或 guard 异常。

阶段 5 实际链路审计确认，不能把这四个 port 扩大为所有进程通信的统一接口：Workflow Runtime response Queue 同时承载异步结果、主动 heartbeat 和 runtime state；PublishedInferenceGateway 支持多个调用线程和乱序响应；LocalBuffer Broker 还组合每 client route、同进程直达和跨进程 pipe。把三者强制适配为当前串行 `RpcClientPort` 会丢失语义或降低并发能力。三条链路继续使用各自的领域 Channel/Client 边界，不进入 LocalMessage common schema，也不创建新的通用大接口。

阶段 5 使用相同 `RpcPort`、相同 wire envelope/bytes 和同一跨进程 echo 拓扑比较 Queue adapter 与候选 RpcMailbox。1/6/64 KiB 三档均未满足 P95、P99 同时改善 10% 的门槛；mmap 的 P50/P95、CPU 和 page fault 明显更高，仅改善了 Windows Queue 的偶发 P99 尾峰。因此正式裁决为 `retain-queue`。不创建 `workflow-runtime/`、PublishedInferenceGateway 或 LocalBuffer Broker mmap 文件，也不在保留链路的热路径增加 JSON/bytes 二次适配。将来只有新的真实领域基准同时证明性能收益和语义适配成立时，才单独提出迁移 ADR。

### 8. 训练控制仍以数据库为权威

训练遥测 Channel 只传 loss、LR、batch、epoch、validation 和运行指标。训练暂停、终止、恢复、checkpoint 和 Task/Attempt 终态继续写数据库并由 TrainingControlProbe 确认。

EventRing 不作为训练控制事实源，也不用于保证指令必达。未来即使增加低延迟通知，Worker 收到通知后仍必须读取数据库确认当前控制状态。

## 未采用方案

- 单个跨进程动态 512 MiB payload arena：引入多 owner allocator、一致性恢复、全局锁竞争和跨 Channel 故障扩散。
- 复用 LocalBuffer buddy allocator：结构化消息允许 page chain，图片要求连续 view，生命周期和消费方式不同。
- 把所有消息强制塞进一个状态机：RPC 与允许覆盖的 telemetry ring 语义不同。
- 立即增加 latest-value/notification：当前没有测量确认的业务瓶颈。
- 无基准地把所有 `multiprocessing.Queue` 替换成 mmap：轮询可能增加延迟、CPU 和关闭复杂度。
- 把图片、checkpoint、持久任务或审计日志写入 LocalMessageChannel：破坏现有数据与恢复边界。
- 长期双协议或兼容旧 layout：当前开发阶段采用原子迁移和明确重建。

## 影响

- 新增分层 LocalMessageChannel contract、公共原语、RPC/Event engine、path、配置和分类型 health；不新增一份要求所有 Channel 共享完整字段的 contract。
- Workflow Trigger 与 Inference 保留独立文件和 owner，但删除重复的 page、CRC、deadline、sweep 和二进制读写实现。
- 训练遥测迁移到通用 EventRing engine 和统一 `data/buffers/` 根目录。
- Workflow Runtime、PublishedInferenceGateway 和 LocalBuffer Broker 保留现有领域 Channel 与 Queue/pipe 传输；阶段 5 基准不支持把它们切换到 RpcMailbox，也不支持把不同异步语义压缩成串行 `RpcPort`。
- [ADR-0007](ADR-0007-local-shared-memory-workflow-trigger.md) 中“不复用 inference mailbox 文件或所有权空间”继续成立；其中“永远维护独立 mailbox 实现”的含义由本文替换为“共享 engine、隔离 Channel”。
- [ADR-0008](ADR-0008-local-buffer-fixed-arena-allocation.md) 的 LocalBuffer 连续图片 allocator 保持不变；其中训练遥测目录与结构化 mailbox 目录说明由本文更新。
