# 本机共享内存 Trigger 实施基线

## 状态与职责

状态：**已交付的历史功能基线；后续可靠性和动态 LocalBuffer 修复已经按新的实施基线完成。**

本页保留 [ADR-0007](../decisions/ADR-0007-local-shared-memory-workflow-trigger.md) 已交付协议、.NET SDK External LocalBuffer Writer Lease、全局 Trigger mailbox、Runtime execution token、output lease handoff、结果生命周期和历史性能证据。当前完成状态以[共享内存数据面可靠性实施基线](shared-memory-data-plane-reliability-implementation.md)为准，未来结构化消息收敛以[本机结构化消息通道实施基线](local-message-channel-implementation.md)为准。

[共享内存数据面可靠性实施基线](shared-memory-data-plane-reliability-implementation.md)中的 overflow page 并发、总 deadline、ACK deadline、PROCESSING 取消、per-source health 和 [ADR-0008](../decisions/ADR-0008-local-buffer-fixed-arena-allocation.md) 固定 arena 迁移已经完成。后续尚未实现的结构化 mmap 公共 engine 收敛只按 [ADR-0009](../decisions/ADR-0009-local-message-channel.md) 与[本机结构化消息通道实施基线](local-message-channel-implementation.md)执行；本文中的旧目录是历史实现记录，不覆盖新的迁移目标。

以下表格是已交付基线的历史验证记录，不是下一阶段完成清单：

| 阶段 | 状态 | 已通过门禁 |
| --- | --- | --- |
| 0 | 完成 | schema/codegen/fixture 一致；真实 net472 编译；Python/.NET Windows byte-range guard 互斥；1080p/4K/20MP checksum 基准；正式路径 containment |
| 1 | 完成 | inference mailbox 已复用中立 guard、owner lock、path fencing、CRC32、uint32 publication、连续优先/非连续 page-chain；相关控制与运行时测试 47 项全部通过 |
| 2 | 完成 | External LocalBuffer 精确长度 PREPARE/publish；writer/reader byte-range guard；私有 receipt；单 pool 与跨 pool batch CAS；deadline 自动 sweep；REVOKING/QUARANTINED；旧 generation/owner fencing；LocalBuffer 与 mailbox 合并回归 63 项通过 |
| 3 | 完成 | 唯一 Runtime execution token 封装真实 handle gate；wait/reject；REST/async/Trigger 统一接入；ZeroMQ reject；旧 generation fencing；删除窗口不再使用独立 sync admission；管理器、Runtime、Trigger 与真实 API 回归通过 |
| 4 | 完成 | 单一全局固定 mailbox；PREPARE/WRITING/REQUEST/PROCESSING/RESPONSE/ACK 状态机；128 descriptors 与 128 MiB page pool；route generation；每 source 单在途；无隐藏队列 executor；真实 Runtime admission；输入 guard publication 与首次 owner handoff；payload checksum、deadline、重启 fencing 和各失败点补偿；阶段 0–4、inference mmap、Runtime、Trigger 与 API 组合回归 155 项通过 |
| 5 | 完成 | `result_bindings` 原子迁移；固定 Trigger/Worker output plan；JSON/单图/多图规范化与物理 identity 去重；ObjectStore immutable snapshot；FrameRef reader guard；整批 output handoff；Worker 和父进程发布失败条件回收；Trigger、Runtime、LocalBuffer、ObjectStore 与文档示例组合回归通过 |
| 6 | 完成 | .NET mailbox/External LocalBuffer client；BGR24、正负 stride、Mono8、Bitmap、File、Base64 输入；SDK 配置包；output reader guard 与 Dispose/ACK；`Image Encode`；raw 零解码、encoded mmap view 和并行 single-flight；跨 Python/.NET 逐字节门禁与阶段组合回归 92 项通过 |
| 7 | 完成 | 协议中立结果 dispatcher；统一 ZeroMQ Result v1 及 0..N binary frames；物理 frame 去重；发送前 transport registry 预留；逐帧 tracker、REP socket 重建与安全回收；ObjectStore 稳定快照；`result_bindings` 数据迁移；.NET 严格解析；前端有序多选；后端组合回归 65 项、ZeroMQ 专项 37 项、前端 285 项和 .NET 零警告编译/契约探针通过 |
| 8 | 完成 | PREPARE/WRITING/REQUEST/PROCESSING/RESPONSE/ACK、owner handoff、Runtime/worker、ZeroMQ send/tracker、Broker deadline/重启/CRC/identity 故障门禁；分阶段 backend/health timing；.NET opt-in timing；Python 组合回归 100 项和 .NET net472 Release 零警告构建通过 |
| 9 | 完成 | 1080p/4K/20MP/57.1 MiB 真实 BMP 性能矩阵；10,000 次混合 soak；真实 HTTP Base64 Workflow、ZeroMQ Trigger、本机共享内存 Trigger 和 Deployment sync 连续负载；资源零泄漏；源码开发环境完整验证通过。现有发行包不在本次源码修改中手工覆盖，后续发布按 profile 重新 assemble |

`zeromq-topic` 与 `local-shared-memory` 是两个并列的正式 TriggerSource adapter。稳定事实已经同步到架构、API 和 SDK 文档；本页继续保留 binary layout、状态机、故障门禁和性能证据，作为后续维护的实施记录。

## 目标

- 同机 .NET SDK 把调用方选择的 BGR24 或 encoded bytes 直接写入 backend-service 分配的 LocalBuffer lease，消除 ZeroMQ 图片主体传输和 backend-service 的第二次整图写入。
- 使用一个全局 Workflow Trigger mailbox 传递参数、lease identity 和结果，不为每个 TriggerSource 新建 mmap 文件。
- 每个在途调用动态占用一个输入 slot；空闲 TriggerSource 不占资源，不同 TriggerSource 可以并行。
- v1 每次调用只接收一张输入图片；PREPARE 和最终 request 的完整 LocalMessage envelope 均不超过 64 KiB，返回 0 到 N 张图片；多图片输入后续单独版本化，不在 v1 中隐式扩展。
- 同一 TriggerSource 默认单在途；同一单 worker Runtime 满载时立即失败，不排队、不重试。
- raw BGR24 零解码；文件、Base64 和 encoded bytes 正式入口在单次 Workflow 首次消费时最多解码一次。
- 正式支持把 Workflow 公开输出中的 LocalBuffer 图片引用返回给 SDK，并通过 owner handoff 保持到 ACK 或 response deadline。
- 由 Workflow 公开输出类型决定结果语义：直接 `image-ref.v1` 返回图片 attachment，显式 `image-base64.v1` 返回受容量约束的 JSON。
- 同一次 Trigger reply 可以同时选择结构化 JSON、单图和多图；adapter 只映射传输，不暗中改变图片表示。
- ZeroMQ 收敛为一个 `amvision.workflow-trigger-result.v1`：Frame 0 是 JSON manifest，后续 0..N 帧是图片 attachment bytes；没有图片时自然只有一帧。
- 所有退出、超时、取消和重启路径都按 request、generation、owner、epoch、deadline 和 OS guard 回收 descriptor、lease 和 Runtime token。
- 高速入口仍保留最小 WorkflowRun 生命周期记录，不以关闭全部记录换取性能。

## 当前实现基线

以下是实现开始前必须保留或明确替换的代码事实：

| 范围 | 当前行为 | 本次要求 |
| --- | --- | --- |
| ZeroMQ Trigger | envelope 与图片 multipart 进入 adapter，adapter 再写 LocalBuffer | 保持现有公开行为 |
| `InvokeBgr24` | 发送 `image/raw`、HWC、uint8、bgr24 和完整 shape | 新入口继续提供 BGR24 高性能方法 |
| `InvokeImageBytes/File/Base64` | 发送 JPEG、PNG、BMP 等原始 encoded bytes，不统一转 BGR24 | 新入口继续正式支持 encoded bytes |
| LocalBuffer | 普通 lease 保持原接口；External lease 已支持精确 allocate/commit、writer/reader guard、receipt、CAS owner transfer、整批 output handoff 和状态化回收 | 阶段 6 SDK 复用该边界 |
| Broker commit | 普通 `commit_lease()` 保持原行为；External commit 按 PREPARE 精确长度和 checksum 提交 | 保持两类边界，不给普通链路增加额外协议成本 |
| Broker release | 普通公开释放接口保留；新 Trigger、Workflow cleanup 和异常回收已按完整 receipt identity 条件释放 | output 交付继续只使用 receipt，不退回 lease-id-only 回收 |
| raw 图片读取 | `memoryview -> np.frombuffer().reshape()`，默认不复制、不执行 `cv2.imdecode` | 保持 |
| encoded 图片读取 | 借用 encoded mmap view，在 `cv2.imdecode` 内生成目标 BGR matrix | 保持并纳入 single-flight |
| Workflow 解码复用 | 单次执行按引用、generation、元数据和 decode flags 做有界只读缓存 | 保持 |
| Workflow cleanup | worker finally、父进程 owner sweep 和发布失败补偿均按 receipt 条件释放；owner 已转移时 no-op | 阶段 6–7 继续复用该边界 |
| Workflow Runtime | 唯一 execution token 已封装真实 handle gate，并支持 wait/reject | 所有后续 adapter 继续复用，不另建容量事实 |
| 高速策略 | `_is_high_speed_trigger_source()` 已同时识别 ZeroMQ 和 `local-shared-memory` | 保持 minimal 记录策略 |

新实现不得删除或悄然修改当前 ZeroMQ 公开方法。`local-shared-memory` 是新的明确 trigger kind，不是旧入口兼容分支。

当前代码锚点：

- [.NET BGR24 请求契约](../../sdks/dotnet/src/Amvar.Vision/ZeroMq/ImageTriggerRequest.cs)
- [.NET ZeroMQ BGR24 调用](../../sdks/dotnet/src/Amvar.Vision/TriggerSource/ZeroMQ/InvokeBgr24.cs)
- [.NET encoded bytes 调用](../../sdks/dotnet/src/Amvar.Vision/TriggerSource/ZeroMQ/InvokeImageBytes.cs)
- [.NET 文件调用](../../sdks/dotnet/src/Amvar.Vision/TriggerSource/ZeroMQ/InvokeImageFromFile.cs)
- [.NET Base64 调用](../../sdks/dotnet/src/Amvar.Vision/TriggerSource/ZeroMQ/InvokeImageBase64.cs)
- [ZeroMQ adapter 写 LocalBuffer](../../backend/service/infrastructure/integrations/zeromq/zeromq_trigger_adapter.py)
- [raw/encoded 图片矩阵读取](../../backend/service/application/images/image_matrix.py)
- [Workflow 单次执行图片缓存](../../backend/nodes/runtime_support.py)
- [LocalBuffer arena lease 与 frame channel](../../backend/service/infrastructure/local_buffers/local_buffer_arena_pool.py)
- [Workflow Runtime manager](../../backend/service/application/workflows/worker/manager.py)
- [通用 LocalMessage descriptor guard](../../backend/service/infrastructure/ipc/local_message/guards.py)
- [Workflow Trigger Mailbox extension](../../backend/service/infrastructure/ipc/workflow_trigger_mailbox.py)
- [mailbox、route、admission 与 handoff supervisor](../../backend/service/application/workflows/trigger_sources/local_shared_mailbox_supervisor.py)

## 不可偏离的设计边界

### 每次调用一个动态输入 lease

- 每个正在执行的图片 Trigger 调用动态占用一个普通 LocalBuffer writing lease。
- TriggerSource 启用但未调用时不占 slot。
- 调用结束、失败、取消或超时后按身份释放。
- 同一图片在图内两个并行分支和多个推理节点中仍只使用一个输入 lease。
- 物理 slot 可以在调用之间复用，但 TriggerSource 不绑定固定 slot。
- Workflow 生成并返回结果图片时还会占用 output lease，容量规划必须同时考虑输入、输出、REVOKING 和 QUARANTINED。

并发准入按本次调用的实际资源需求逐项判断，不使用一个只计算输入 slot 的静态公式：

- PREPARE 至少需要一个可用输入 lease、一个 mailbox descriptor 和目标 Runtime 的可用路由；
- REQUEST 还必须非阻塞取得目标 Runtime execution permit 和有界执行器 permit；
- 输入图片直接作为输出时复用同一 lease 并执行 owner handoff，不额外占 slot；
- Workflow 新生成的每个独立输出图片都需要 output lease；相同物理 lease 的重复逻辑 attachment 只占一份物理容量；
- 输出容量不足时整批 handoff 失败并返回 `local_buffer_output_capacity_exhausted`，不得发布部分成功响应；
- REVOKING、QUARANTINED 和尚未完成协议交付的 response lease 均不可计入可用容量。

因此实际并发由 descriptor、输入和输出 lease、Runtime permit、有界执行器 permit 以及不同 TriggerSource 单在途状态共同决定。它不由已创建、已启用或数据库中保存的 TriggerSource 总数决定，也不能承诺“8 个 slot 必然支持 8 个带图片输出的并发调用”。

### 每个 TriggerSource 单在途

每个启用的 `local-shared-memory` TriggerSource 只维护轻量运行状态：

```text
trigger_source_id
active_request_id: null | request_id
route_generation
```

请求开始时原子执行 `null -> request_id`，所有结束路径执行 `request_id -> null`。同一 TriggerSource 的第二个并发请求立即返回 `trigger_source_busy`；不同 TriggerSource 互不阻塞。该状态不预留 slot，不创建专用线程、进程、channel 或 mmap 文件。

单在途 permit 的生命周期覆盖完整协议交付，而不只覆盖 Workflow 图执行：

- local-shared-memory 保持到 SDK ACK、取消完成或 response deadline 回收完成；
- ZeroMQ 保持到全部已提交 physical frame tracker 完成，或未完成 Frame/view/guard 已由发送前预留的 adapter transport-lifetime registry 持续承担责任，lease 已进入 Broker 的 REVOKING/QUARANTINED 回收链；
- Runtime execution token 可以在图执行与输出 handoff 完成后释放，两者不能混成同一个生命周期。

### 图片格式与解码

LocalBufferBroker 不识别、解码或转换图片，只管理 bytes、lease、identity 和引用元数据。

图片可以来自相机、磁盘、网络、已有内存或任意其他来源。SDK 不根据来源强制选择传输表示；开发者通过调用的方法明确选择以下两条正式路径：

- **BGR24 高性能默认路径**：SDK 接收现成 BGR24，或使用已有转换方法把 Bitmap、BMP、JPEG、PNG、Mono8、RGB24、带 stride buffer 等转换为连续 BGR24 后写入；后端直接使用 mmap view。
- **encoded 正式支持路径**：SDK 保留 JPEG、PNG、BMP 等编码 bytes，或只把 Base64/Data URL 还原成编码 bytes后写入；后端首次消费时解码一次。

| 输入入口 | SDK 写入内容 | BufferRef 元数据 | Workflow 处理 |
| --- | --- | --- | --- |
| 已有连续 BGR24 | 直接写 BGR24 | `image/raw`、HWC、uint8、bgr24、shape | mmap view，无解码 |
| Bitmap/Mono8/RGB24/带 stride buffer 的显式 raw helper | 转换时直接写目标 lease | 同上 | mmap view，无解码 |
| 通用 encoded bytes | 原始编码 bytes | 准确 MIME；raw 字段为空 | 首次矩阵消费时解码一次 |
| 图片文件 | 原始 JPEG/PNG/BMP 等文件 bytes | 按明确参数或扩展名设置 MIME | 首次矩阵消费时解码一次 |
| Base64/Data URL | SDK 先还原 encoded bytes | 参数或 Data URL MIME | 首次矩阵消费时解码一次 |

约束：

- BGR24 是本机高性能默认表示，不是强制格式；开发者可以显式选择 encoded 路径。
- raw BGR24 长度必须等于 `height * width * 3`，并严格校验 shape、dtype、layout 和 pixel format。
- encoded 输入不得伪装成 `image/raw`；raw 输入也不得缺失布局元数据。
- LocalBuffer 不根据扩展名、magic bytes 或 MIME 自行选择 codec。统一图片 helper 只用 `media_type` 区分 raw/encoded；encoded 的具体 codec 由 OpenCV 在解码边界根据内容识别。
- 同一图片引用、generation 和 decode flags 在单次 Workflow 内只允许一个 decoder 执行；并行分支等待同一个 single-flight 结果。
- 不同 decode flags 可以形成不同缓存项；节点需要修改共享矩阵时显式 copy，不能修改共享只读矩阵。
- 单次执行解码缓存保持有界；超大图片不能为了缓存突破配置的内存上限。

### 不新增 external frame channel

新入口只复用普通 lease：

```text
allocate external writing lease
  -> SDK 在 writer guard 内写入
  -> Broker 取得 guard、校验并 commit
  -> BufferRef
  -> Workflow Runtime
  -> identity-fenced release 或 output handoff
```

不使用 ring `FrameRef` channel，不为 TriggerSource 静态预留槽位，不允许新一代帧覆盖尚未完成 Workflow 的 active 输入。组件名称固定为 **External LocalBuffer Writer Lease**。

### trusted-local，不是安全沙箱

- 能读写 `data/buffers/` 的同一 OS 用户域进程属于 trusted-local 边界。
- SDK 内部只创建 lease 范围的 mmap view，但恶意进程仍可自行重新打开 pool 文件。
- generation、owner、epoch 和 checksum 负责发现错误，不能物理阻止已获得写句柄的异常进程。
- 复用安全由每 lease OS writer/reader guard 保证；无法取得 guard 的槽位只能隔离，不能复用。
- 不为本地可信能力增加远程鉴权、权限沙箱或多租户隔离逻辑。

## binary protocol v1

### 文件与固定容量

- backend-service 实例拥有一个在 FastAPI lifespan 启动时创建、运行时不扩容的 `data/buffers/local-message/workflow-trigger/mailbox.mmap`。
- 路径从中立 `local_memory.root_dir` 派生，不新增第二个 mmap root。
- descriptor guard、server lock、writer/reader guard 和恢复辅助文件全部位于图片数据面 `data/buffers/` 对应协议目录或 pool 目录。
- 正式运行不得在仓库根目录、`data/files/`、`data/queue/`、`.tmp/`、系统临时目录或 SDK 配置目录创建 Workflow Trigger mailbox。训练遥测使用 `data/buffers/local-message/training-telemetry/` 下的独立 EventRing，始终不进入 LocalBuffer 图片 arena。
- 自动化测试可以把 buffers root 重定向到 `.tmp/<test>/buffers/`，但必须复用正式 path builder 和 root containment 校验。

v1 默认容量：

| 项目 | 默认值 |
| --- | ---: |
| descriptor 数 | 128 |
| inline request 上限 | 64 KiB |
| inline response 上限 | 64 KiB |
| overflow page 大小 | 256 KiB |
| overflow page 数 | 512 |
| 单响应 wire page 上限 | 129；公开 JSON 正文仍为 32 MiB |
| 初始 poll interval | 1 ms |
| 数字字节序 | little-endian |
| 字段对齐 | 8 byte |
| 内容校验 | CRC32 IEEE（polynomial `0xedb88320`，algorithm id `1`） |

完整 request envelope 超过 64 KiB 时返回 `trigger_request_too_large`，不建立 request page-chain、文件 fallback 或第二控制通道。结构化响应超过 inline 上限时使用同一 mailbox 内的固定 overflow page-chain；公开 JSON 正文超过 32 MiB 或全局 page 容量不足时返回明确的超限或容量错误。

直接公开的 `image-ref.v1`/`image-refs.v1` 图片主体始终使用 LocalBuffer attachment，不进入 inline 或 page-chain。图中显式 `Image Base64 Encode` 产生的 `image-base64.v1` 已经是结构化 JSON，允许进入 inline/page-chain，但不扩大默认 32 MiB 单响应上限、不自动改成 LocalBuffer、不回退文件或其他协议。57.1 MiB BMP 形成的约 76 MiB Base64 不属于默认 mailbox 可接受结果，应改用直接图片 attachment。

### binary contract 单一事实源

阶段 0 已完成以下实现并作为后续代码的唯一输入：

- common schema：`backend/contracts/ipc/schemas/local_message_channel.v1.json`；
- Trigger 业务契约 schema：`backend/contracts/ipc/schemas/workflow_trigger_mailbox.v1.json`；
- Python extension layout：`backend/contracts/ipc/workflow_trigger_mailbox_v1.py`；
- Python/.NET fixture 由 contract test 双向校验，不再维护旧 mailbox 生成器。
- .NET layout：`sdks/dotnet/src/Amvar.Vision/SharedMemory/WorkflowTriggerMailboxV1.g.cs`；
- common fixture：`tests/fixtures/local_message_channel.v1.fixture.json`；
- Trigger 业务契约 fixture：`tests/fixtures/workflow_trigger_mailbox.v1.fixture.json`。

layout 固定为 256-byte common header、256-byte Mailbox profile header、256-byte descriptor header 和 64-byte page header。common fixture 保存 schema SHA-256，Python/.NET contract test 同时校验冻结字段、offset、profile 和 extension bytes；协议已按 ADR-0009 阶段 4 原子迁移，不再读取旧 mailbox layout。

- 使用一份带固定 offset、width、alignment、enum 和 magic/version 的 schema 生成 Python 与 .NET 常量。
- Python 与 .NET 不分别手写 descriptor offset。
- request id 使用固定 16-byte UUID；owner token 和 epoch 使用非零 uint64。
- 变长字符串和业务对象放入 UTF-8 JSON payload；header 只保存固定 identity、长度、校验算法/值和位置。
- contract fixture 必须覆盖所有字段最大值、空值、字节序、最终校验算法和值以及 page-chain。
- binary contract 已冻结；后续不兼容修改必须显式修改 schema、重新生成两端代码和 fixture，并在 capability 对外发布前完成全部迁移门禁。

### 阶段 0 checksum 测量与输入发布结论

2026-08-24 使用开发数据中的真实图像内容，统一转换为连续 BGR24 后对 1080p、4K 和 20MP 数据完成 Python bytes、Python read-only mmap 与 net472 SDK 增量基准。每组预热后执行 5 次，chunk 为 1 MiB；完整报告由 `python -m backend.maintenance.workflow_trigger_checksum_benchmark` 写入 `.tmp/workflow-trigger-stage0/checksum-benchmark.json`。

| BGR24 数据 | 大小 | CRC32 Python mmap | CRC32 .NET incremental | SHA-256 Python mmap | SHA-256 .NET incremental |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1080p | 6,220,800 bytes | 4.73 ms | 6.87 ms | 6.50 ms | 3.75 ms |
| 4K | 24,883,200 bytes | 18.87 ms | 24.05 ms | 29.85 ms | 14.20 ms |
| 20MP | 60,543,936 bytes | 50.86 ms | 60.31 ms | 72.65 ms | 34.41 ms |

测量证明对同一张 20MP 输入在 SDK 写侧和 backend 发布侧各扫描一次会额外消耗约 95 ms，并抵消共享内存链路收益。`local-shared-memory` 输入因此不携带 full-image checksum：SDK 通过精确 allocation 写入，在释放 view 和 writer guard 后才发布 REQUEST；backend 重新取得 writer guard，并在同一 Broker 锁内校验 receipt、broker epoch、generation、owner、deadline 和精确长度，随后原子完成 `WRITING -> ACTIVE` 与首次 owner transfer。SDK 在 writer guard 释放前退出时不会发布 REQUEST，部分写入不会成为可消费 lease。

CRC32 IEEE 继续用于 mailbox 结构化 request/response payload、page-chain 和需要跨 transport 交付的结果 attachment；这些校验不承担密码学认证。固定文本 fixture `amvision-workflow-trigger-mailbox-v1` 的值为 `0x72d66131`。输入图片的 publication 完整性与结构化 payload 的传输完整性是两个不同边界，不提供把旧的双重整图 CRC 恢复到热路径的兼容开关。

### descriptor 字段

每个 descriptor 至少包含：

- state、descriptor index、generation；
- server epoch、request UUID、owner token；
- accepted timeout、route generation；
- request payload size/checksum algorithm/checksum；
- LocalBuffer lease id fingerprint、buffer id fingerprint、broker epoch、generation、offset 和精确 content length；
- image media type、shape、dtype、layout、pixel format；
- response inline/page-chain size、原始大小、codec、checksum algorithm 和 checksum；
- worker instance、Runtime revision/generation 和 snapshot fingerprint；
- response output lease 数量、handoff 状态和结构化错误码。

完整字符串 identity 保存在校验后的 payload 中；header fingerprint 用于快速拒绝和防止读取错误 generation，不能替代服务端实体查询。

### descriptor guard 与发布顺序

- 每个 descriptor 使用跨进程 OS byte-range guard。
- Windows 必须验证 Python `msvcrt.locking` 与 .NET `FileStream.Lock` 真实互斥；其他平台使用等价系统 byte-range lock。
- state 在 guard 外只能作为 poll hint；读取方必须取得 guard 后重新确认。
- 发布端在 guard 内依次写 body、长度、checksum、identity 和 page-chain，最后写 state。
- 读取端取得 guard 后校验 state、generation、owner、epoch、deadline、长度、checksum 和 page-chain。
- 不依赖 Python/.NET 普通 mmap 字段赋值的原子性或内存可见性。
- page body 与 header 全部完成后才能发布 RESPONSE；异常响应始终放入 inline 区，不依赖 overflow page。
- SDK 必须先销毁写 view并释放 writer guard，再发布 REQUEST；Broker 只有成功取得该 guard 才能原子 publish + owner transfer。本协议不允许 SDK 持有 writer guard 等待 Workflow 执行完成。

通用 guard、owner lock、path fencing、checksum 和 page-chain helper 从 inference mailbox 提取到中立 IPC 基础设施。两个 mailbox 只共享实现和测试，不共享文件、epoch、descriptor 或 owner 空间。

backend-service 对 Workflow Trigger mailbox 实行单 owner 规则：

- 只有取得 mailbox owner lock 的进程可以创建或重置文件、更新 server epoch、扫描和回收 descriptor/page；
- `--reload` 新旧进程重叠时，新进程在取得 owner lock 前不得重置 mmap 或发布新 epoch；
- takeover 必须先确认旧 owner 已退出或 owner lock 已由操作系统释放，再以新 epoch 重建所有 descriptor/page 状态；
- 健康检查应区分 active owner、等待 takeover 和失去 owner，不允许两个 supervisor 同时声明可服务。

### descriptor 状态机

```text
FREE
  -> PREPARE
  -> WRITING
  -> REQUEST
  -> PROCESSING
  -> RESPONSE
  -> ACKED
  -> FREE

任意未完成状态
  -> CANCELLED
  -> FREE

PREPARE / WRITING / REQUEST / PROCESSING
  -> RESPONSE(error, attachments=[], payloads=[])
  -> ACKED
  -> FREE
```

LocalBuffer external lease 另有独立驻留和回收状态：

```text
FREE -> WRITING -> ACTIVE

WRITING -> REVOKING -> FREE
                    -> QUARANTINED -> FREE

ACTIVE  -> REVOKING -> FREE
                    -> QUARANTINED -> FREE
```

WRITING 撤销等待 writer guard；ACTIVE 撤销等待所有 OS reader guard。ZeroMQ tracker 由 adapter 进程内 transport-lifetime registry 等待，Broker 只根据 adapter 的条件释放调用和 OS guard 状态改变 lease state，不保存或轮询 tracker。descriptor 可以在 lease 已进入 QUARANTINED 后释放，但 Broker 必须保存私有 handoff receipt 和独立回收 identity；不得因为 descriptor 复用而丢失隔离状态。

### 状态迁移唯一写入方

每个状态只有一个权威写入方，所有迁移都在 descriptor guard 内完成：

| 迁移 | 权威写入方 | 前置条件 |
| --- | --- | --- |
| `FREE -> PREPARE` | SDK | claim 时校验 server epoch、generation 和 owner token |
| `PREPARE -> WRITING` | backend-service | TriggerSource/route/长度校验通过，输入 lease 已分配 |
| `WRITING -> REQUEST` | SDK | 图片按精确 allocation 写入完成；先销毁写 view并释放 writer guard，再以 descriptor request payload 的 CRC 发布 REQUEST |
| `REQUEST -> PROCESSING` | backend-service | 已重新取得 writer guard并确认 receipt/epoch/generation/owner/deadline；Runtime/执行器 permit 与 WorkflowRun identity 已建立；Broker 在同一锁内原子发布 lease并把输入 owner 从 writer receipt transfer 到 Runtime receipt；worker submit 已接受 |
| `PROCESSING -> RESPONSE` | backend-service | 图执行、结果规范化和整批 handoff 成功，response body 已完整写入 |
| `PREPARE/WRITING/REQUEST/PROCESSING -> RESPONSE(error)` | backend-service | error body 已完整写入，attachments/payloads 为空；已取得资源已按当前 receipt 清理，或 ZeroMQ 进程内资源已由预留 transport-lifetime registry 持续负责且 lease 已进入 Broker 回收链 |
| 任意未完成状态 `-> CANCELLED` | backend-service | SDK 只提交取消意图；backend 校验 identity 后发布取消状态 |
| `RESPONSE -> ACKED` | SDK | JSON-only/SDK-owned copy 已完成，或结果对象 `Dispose`/`DisposeAsync` 已使全部共享 view 失效并释放全部 reader guard |
| `ACKED/CANCELLED -> FREE` | backend-service | page、token 和 source permit 已清理；lease 已按 receipt 释放，或已从 descriptor 脱离并由 adapter transport registry 与 Broker REVOKING/QUARANTINED identity 继续回收 |

SDK 不得直接写 `FREE`，也不得改写 Broker lease state、owner 或 commit metadata。backend-service 不得在 SDK 仍持有 writer/reader guard 时复用物理 slot。generation、owner token 或 epoch 不匹配时只能拒绝当前操作，不能清理可能属于新请求的资源。

## Workflow 结果契约与传输映射

### 公开输出语义

结果语义只来自已发布 Workflow App Version 的公开输出契约：

| 公开 payload | 结果语义 | 是否需要 output lease handoff |
| --- | --- | --- |
| 普通 inline JSON payload | `response_payload` | 否 |
| `image-base64.v1` | Base64 JSON，受 mailbox/协议容量限制 | 否 |
| `image-ref.v1` | 单图片 attachment | 是，短期 LocalBuffer 输出 |
| `image-refs.v1` | 多图片 attachments，保留 item index | 是，短期 LocalBuffer 输出 |

图片直接连接 App Result 时保持 `image-ref.v1`。新增 `Image Encode` 节点负责把 raw 图片显式编码为 JPEG、PNG、BMP 或 WebP，并继续输出携带准确 `media_type` 和表示元数据的 `image-ref.v1`。现有 `Image Base64 Encode` 明确生成 `image-base64.v1`。现有 `Image Body` 显式生成 `response-body.v1`，在 adapter capability 和容量允许时可以被 `result_bindings` 明确选择，但不会被 Trigger adapter 隐式插入或用作传输选择器。

raw BGR24 直接输出时，任何 adapter 都不得隐式编码；只有经过 `Image Encode` 的输出才能作为对应 JPEG/PNG 等编码图片交付。图片表示与 Trigger transport 是两个独立维度。

### 多 binding result mapping

TriggerSource 使用：

```json
{
  "result_bindings": [
    "inspection_result",
    "annotated_image",
    "cropped_images"
  ]
}
```

- `result_bindings` 可以为空；为空时只返回状态和 `workflow_run_id`。
- 每个 binding 必须存在于固定 Workflow App Version 的公开输出契约。
- 不递归扫描 `value.v1`、`workflow-result.v1`、template outputs、node records 或调试 payload 中的临时 image-ref。
- 临时图片必须作为独立公开 `image-ref.v1`/`image-refs.v1` binding 才能 handoff。
- 已选择的普通 JSON binding 如果嵌套 `memory`、`buffer` 或 `frame` 临时引用，执行失败并返回 `ephemeral_image_ref_in_json_result`；不得递归提升为 attachment，也不得把短期引用序列化给客户端。
- 删除当前“未知 binding 时回退全部 outputs”和单个 `result_binding` 运行分支。
- 数据迁移把已有非空 `result_binding` 转成单元素 `result_bindings`；迁移完成后不保留双读兼容代码。

结果模型分为内部准备层和公开 wire 层：

- `PreparedTriggerResult` 保存结构化 `response_payload`、有序 `logical_attachments` 和去重后的 `physical_payloads`；它只在 worker、父进程和 adapter 内部传递，不包含 ZeroMQ frame index 等协议字段；
- `PreparedLogicalAttachment` 保存 attachment id、binding id、item index、payload type 和 `payload_id`；多个逻辑 attachment 可以合法引用同一 `payload_id`；
- `PreparedPhysicalPayload` 保存规范化 image ref、representation identity、media type、content length、checksum、width/height、shape、dtype、layout、pixel format 和服务端私有 `LeaseOwnershipReceipt`；
- `WorkflowTriggerResultV1` 是公开统一结果，包含有序 `attachments` 和按 `payload_id` 去重的 `payloads`；attachment 只引用 payload，payload 使用 tagged locator union：`local-buffer`、`zeromq-frame` 或 `object-store`；不允许用多个可空字段猜测 locator 类型；
- attachment 顺序固定为 `result_bindings` 顺序，再按 `image-refs.v1.items` 顺序；`source_image` 不自动成为 attachment；
- 相同物理 payload 的重复逻辑 attachment 保留各自 binding/item 关系，但 handoff、校验、ZeroMQ frame 和释放按完整 identity 去重。

物理 payload identity 不能只使用 `lease_id`。LocalBuffer 至少结合 pool、buffer、lease、broker epoch、generation、offset、length、representation metadata 和 checksum；ObjectStore 至少结合 object key、version/checksum 和 representation metadata。实现可以在规范化后生成不可变 `payload_id`，后续层只根据该 id 建立共享关系。

公开 locator 的最小字段固定如下：

| `kind` | 必需字段 | 生命周期 |
| --- | --- | --- |
| `local-buffer` | 现有 BufferRef 定位和代次字段，以及协议所需 reader guard locator；不公开权威 owner、pool 或 deadline | SDK result dispose/ACK 或 response deadline |
| `zeromq-frame` | `frame_index`；多个逻辑 attachment 可以共享同一索引 | 当前 multipart message 收包完成后由 SDK 拥有 bytes |
| `object-store` | `object_key`、`media_type`、`content_length`、`checksum_algorithm`、`checksum`、`immutable_version` | 按不可变 ObjectStore 对象策略 |

locator 与 attachment metadata 分离：shape、dtype、layout、pixel format、长度和 checksum 仍属于物理 payload；locator 只说明到哪里读取。公开 wire schema 使用 `kind` discriminator，未知 kind 必须拒绝，不能猜测或回退。服务端另行保存 `LeaseOwnershipReceipt`，其中包含 pool、完整 expected owner、epoch、generation、deadline 和 guard identity；公开 BufferRef 不承担清理授权。

### ObjectStore 稳定读取端口

稳定 `object-store` locator 不是普通文件路径字符串。应用层 ObjectStore 必须增加以下正式契约：

- `ObjectSnapshotMetadata`：`object_key`、`content_length`、`media_type`、`checksum_algorithm`、`checksum`、`immutable_version` 和 `is_immutable`；
- `stat_object(object_key)`：返回已经持久保存的对象元数据，不能在每次响应时重新全量扫描大图生成 checksum；
- `open_read_snapshot(object_key, expected_version, expected_checksum)`：返回 context-managed 只读 snapshot，snapshot 的 handle/view 在调用方释放前保持同一不可变对象；
- `write_immutable_object(...) -> ObjectWriteReceipt`：写入新的 run/version/content-addressed key，完整写入并原子发布，返回上述稳定元数据；
- `materialize_immutable_object(source)`：旧对象、可变 key 或缺少稳定元数据时创建新的不可变受管理对象。

本地 ObjectStore 对已发布不可变 key 禁止覆盖。现有允许覆盖的通用 object key 不能只凭 path、mtime 或 size 视为稳定 snapshot。ZeroMQ 从 ObjectStore 构建零复制 frame 时，read snapshot 必须与 `zmq.Frame` 一起保持到 tracker 完成。普通本机绝对路径不受 ObjectStore writer 协议约束：它仍可作为 Workflow 输入或保存位置，但响应交付前必须复制到受控 LocalBuffer、adapter 自有不可变 bytes 或新的不可变 ObjectStore 对象，不能直接生成稳定 locator。

### TriggerResponsePlan

TriggerSource 创建、enable、Runtime 切版和实际调用前，根据以下固定信息生成 `TriggerResponsePlan`：

- Runtime revision、generation、snapshot fingerprint；
- Workflow App Version 公开输出契约；
- 顶层 `result_mode`、`reply_timeout_seconds`、`ack_policy` 和 `result_mapping.result_bindings`；
- adapter 的 submit modes、result modes、attachment delivery kinds，以及最大 JSON、单物理 payload、逻辑 attachment 数、物理 payload/frame 数和总响应容量；
- TriggerSource route generation、公开输出契约 fingerprint 和 adapter capability revision。

`TriggerResponsePlan` 必须在创建、enable 和 Runtime 切版时构建，并在实际调用前重检所有 fingerprint。Runtime 从中派生只包含公开 binding、payload type 和目标交付类别的 `WorkflowOutputDeliveryPlan` 传给 worker，使 worker 在 cleanup 前知道需要规范化和 handoff 的准确输出。不能等 Run cleanup 后再扫描结果决定是否保留 lease。

### Adapter 映射

| 入口 | JSON | 直接图片 attachment |
| --- | --- | --- |
| `local-shared-memory` sync | mailbox inline/page-chain | LocalBuffer BufferRef；结果对象持有 reader guard 到 Dispose 后 ACK |
| ZeroMQ Trigger Result v1 | Frame 0 JSON manifest | Frame 1 到 N 唯一 physical payload；无图片时 N=0 |
| `event-only` PLC/IO/MQTT/目录/定时 | 丢弃 | 丢弃，不 handoff |
| `accepted-then-query` | 状态和 run id | 复制到 ObjectStore 后查询，或显式丢弃 |

`event-only` 固定丢弃所有结果，不建立 output handoff。同步 adapter 不支持某个已选择 binding 时，在创建、enable 或 Runtime 切版时拒绝配置；不需要返回的输出直接从 `result_bindings` 省略，不增加 discard 开关。`accepted-then-query` 不能保存短期 BufferRef：临时图片和绝对路径必须复制到受管理 ObjectStore；来源已经具有不可变 version、checksum、准确长度和 media type 时直接复用 locator，不重复物化。

### ZeroMQ Trigger Result v1

ZeroMQ 只有一个 `amvision.workflow-trigger-result.v1`。消息始终按 multipart API 接收和发送，不按帧数选择协议：

```text
Frame 0  UTF-8 JSON manifest
Frame 1  physical payload 1 bytes
...
Frame N  physical payload N bytes
```

Frame 0 manifest 固定包含 `format_id`、Trigger/Event/Run identity、state、`response_payload`、有序 `attachments`、去重 `payloads`、统一 `error` 和 metadata。`attachments=[]` 与 `payloads=[]` 表示没有后续帧。失败和 adapter 错误也使用相同 result format，不再维护独立 ZeroMQ error envelope。

```json
{
  "format_id": "amvision.workflow-trigger-result.v1",
  "trigger_source_id": "trigger-source-line-1",
  "event_id": "trigger-event-1",
  "state": "succeeded",
  "workflow_run_id": "workflow-run-1",
  "response_payload": {
    "inspection_result": {
      "code": 200,
      "message": "ok"
    }
  },
  "attachments": [
    {
      "attachment_id": "attachment-1",
      "binding_id": "annotated_image",
      "item_index": null,
      "payload_type_id": "image-ref.v1",
      "payload_id": "payload-1"
    },
    {
      "attachment_id": "attachment-2",
      "binding_id": "same_image_again",
      "item_index": null,
      "payload_type_id": "image-ref.v1",
      "payload_id": "payload-1"
    }
  ],
  "payloads": [
    {
      "payload_id": "payload-1",
      "locator": {
        "kind": "zeromq-frame",
        "frame_index": 1
      },
      "media_type": "image/raw",
      "content_length": 59904000,
      "checksum": {
        "algorithm": "<phase-0-frozen-algorithm>",
        "value": "<encoded-checksum>"
      },
      "shape": [3648, 5472, 3],
      "dtype": "uint8",
      "layout": "HWC",
      "pixel_format": "bgr24"
    }
  ],
  "error": null,
  "metadata": {}
}
```

错误发生在 envelope 完整解析之前时，adapter 仍能从监听实例确定 `trigger_source_id`；wire result 中 `event_id` 和 `workflow_run_id` 允许为 null，内部已解析 identity 不能无故丢失。失败或超时结果使用 `error={code,message,details}`，且 `attachments=[]`、`payloads=[]`，不返回部分成功图片。成功结果要求 `error=null`。所有唯一物理 ZeroMQ payload 的 `frame_index` 集合必须恰好为 1 到 N，不能留洞。多个逻辑 attachment 可以通过同一 `payload_id` 合法共享同一 `frame_index`；SDK 只拒绝越界、缺少物理帧、未声明额外帧或共享 payload 的物理元数据不一致。

manifest 分别记录 logical attachment 的 binding/item/payload 引用和唯一 physical payload 的 frame index、media type、content length、checksum 与图片元数据。raw BGR24 发送 raw bytes；`Image Encode` 生成的 JPEG/PNG 发送对应编码 bytes；`image-base64.v1` 只存在于 Frame 0 JSON，不重复生成 attachment。

backend ZeroMQ adapter 按唯一物理 payload 获得只读 mmap view 或 ObjectStore read snapshot，并创建 `zmq.Frame(copy=False, track=True)`。实现逐个提交 frame，只登记已经被 socket 成功接受的 tracker；不能依赖 `send_multipart(copy=False, track=True)` 返回的最后一帧 tracker证明整批生命周期安全，也不能把未成功提交的 Frame 加入永远无法完成的 tracker 等待集合。普通本机绝对路径不得直接作为 tracked file view，必须先物化为受控不可变来源。

发送使用 reply deadline 的剩余时间和有界 `SNDTIMEO`。adapter 在发送 Frame 0 前完成整个响应预检，按唯一 physical payload 数预留有界 transport-lifetime registry 容量，取得所有 reader guard/read snapshot，并创建 Frame；容量不足返回 `zeromq_transport_capacity_exhausted`，不得发送任何 multipart frame。socket 仍干净时可以发送一个不依赖 output lease 的小型 copy JSON 错误。第一帧发出后，预留项必须持续持有全部 Frame、tracker、view/snapshot、guard、lease receipt、deadline 和 socket generation，不能因为 registry 满载丢弃责任。

REP socket 发送超时、tracker 失败或状态机失配后，先停止监听并以 `linger=0` 关闭 socket，再等待全部已登记 tracker。全部完成后依次销毁 Frame/view、关闭 snapshot、释放 reader guard，再调用 Broker 的 identity-fenced release。关闭后仍未完成的资源继续留在 adapter 进程内 transport-lifetime registry，对应 ACTIVE lease 先 REVOKING、宽限期后 QUARANTINED，直到 tracker 和 guard 确认结束才回到 FREE。Broker 是独立 companion process，只管理 lease state、deadline、identity fence 和 OS guard；不能保存、等待或重试 `zmq.Frame`/`MessageTracker`。adapter 崩溃时由 OS 释放本进程资源，Broker 随后按 deadline 与 receipt 回收。

协议配置必须显式限制 manifest JSON 大小、单物理 payload 大小、逻辑 attachment 数、物理 frame 数、总响应字节数和 transport registry entry/bytes。任何超限在发送前失败，不建立部分 multipart reply。.NET SDK 必须校验逻辑 attachment、payload/frame 映射、帧集合、长度和 checksum，拒绝缺帧、额外帧、越界索引和损坏内容，但允许多个 attachment 合法引用同一物理 frame。ZeroMQ 仍存在协议栈及接收侧整图复制，不作为本机共享内存满载时的 fallback。

TriggerSource 和 SDK 配置包不增加 `reply_protocol`、JSON/multipart mode 或协商字段。当前开发期由后端和仓库内 .NET SDK 同步迁移到统一 v1，删除旧的单帧专用解析、独立 error format 和双协议兼容代码。

## 正常调用链路

### 1. PREPARE

- v1 只接受一张输入图片；SDK 完成输入类别判断或 Base64 还原，得到精确 `content_length`，结构化参数的完整 LocalMessage envelope 不得超过 64 KiB。
- SDK 只提交 TriggerSource id、event identity、业务参数和相对 `timeout_ms`。
- backend-service 读取已启用 TriggerSource 快照，固定 project、Runtime、revision、route generation、input mapping、默认 metadata 和 timeout 上限。
- backend-service 原子取得该 TriggerSource 的单在途 permit。
- Broker 按精确长度动态分配 external writing lease，返回 lease identity、精确 view 范围、broker epoch、generation 和 writer guard identity。
- PREPARE 只做 Runtime 健康预检，不取得 execution token。

### 2. WRITING

- SDK 取得 writer guard 后创建精确长度 mmap view。
- BGR24 helper 直接写连续 HWC 像素；encoded 入口直接写编码 bytes。
- SDK 不对 trusted-local 输入做 full-image checksum；精确 allocation 决定本次可写长度。
- SDK 完成写入后先销毁 mmap 写 view并释放 writer guard，再在 descriptor guard 内写入图片元数据和结构化 request payload，最后发布 REQUEST。REQUEST 之前的进程退出只留下不可消费的 WRITING lease，由 deadline 回收。
- SDK 发现 CANCELLED、epoch 变化或本地 timeout 时停止写入并释放 guard，不自行把 lease 设为 FREE。

### 3. REQUEST

- Broker 必须成功取得 writer guard，证明协作式 writer 已经停止。
- backend-service 校验 descriptor identity、route generation、deadline、精确长度和图片元数据；descriptor 自身的 request payload CRC 按 mailbox 协议校验。
- Broker 重新取得 writer guard，确认没有协作式 writer 持续写入；输入发布不创建整图 mmap view，也不扫描 full-image checksum。
- raw BGR24 额外校验长度等于 `height * width * 3`。
- Broker 在单个 pool lock 内把 external writing lease 原子发布为 ACTIVE、转移到 Runtime owner，并生成正式 `BufferRef` 和新的 Runtime `LeaseOwnershipReceipt`。公开 BufferRef 不包含权威 owner、pool 或 deadline。
- Runtime manager 非阻塞取得目标 handle 的真实 execution token；失败时按 writer receipt 条件释放输入 lease并发布 `workflow_runtime_busy`，TriggerSource permit 保持到该错误响应完成协议交付。
- adapter 还必须非阻塞取得有界执行器 permit；执行器实现不能只限制 worker 数却使用无界 `ThreadPoolExecutor` 提交队列。permit 失败时释放 Runtime token、按 writer receipt 释放输入 lease，并发布 `trigger_executor_busy`。
- backend-service 建立权威 WorkflowRun identity/记录；创建失败时释放两个 permit并按 writer receipt 回收。
- 在提交 worker 前，Broker 以 CAS 校验完整 writer receipt，在同一临界区完成 `WRITING -> ACTIVE` 并把输入 owner 从 `workflow-trigger-write` 转为 `workflow-runtime:{runtime_id}:{run_id}:{request_id}`，返回新的 Runtime receipt。publish/transfer 失败时不提交 worker，Run 进入失败终态并释放两个 permit；不得发布短暂的 writer-owner ACTIVE 状态。
- 成功后把 execution token、executor permit、BufferRef、Runtime receipt 和固定路由/response plan 提交给执行器；worker 提交失败时按 Runtime receipt 清理。每条完成、取消和异常路径都必须释放两个 permit。

### 4. PROCESSING

- Workflow Run 使用同一个 `BufferRef` 读取图片，使用私有 Runtime receipt 管理所有权；输入 lease 保持到图执行和输出 handoff 完成。
- 图内只读节点共享 raw view 或单次 encoded decode；不得为每个分支分配输入 slot。
- Runtime token 一直持有真实 handle execution gate，完成前其他入口不能绕过。
- Workflow timeout 使用 PREPARE 权威 deadline 的剩余时间，不能重新得到完整 timeout。

### 5. 输出图片 handoff

- worker 在进入自身 `finally` cleanup 前，使用 `WorkflowOutputDeliveryPlan` 处理选中的 application 公开 `image-ref.v1`/`image-refs.v1` bindings；父进程在收到普通 outputs 后再 handoff 已经太晚。
- `image-refs.v1` 只读取有序 `items`；`source_image` 不自动返回。不扫描 template outputs、node records、调试载荷或任意嵌套 JSON。
- 当前 Run 的私有 receipt 证明完整所有权时，对应 BufferRef 可以零复制 transfer；没有 receipt、属于其他 owner 或来源不明的 BufferRef 必须复制到新的 output lease，不能窃取 owner。
- memory handle 必须在 worker cleanup 前物化为独立 output lease；FrameRef 始终复制到 output lease。storage/local-path 按 delivery kind 处理：`local-buffer` 物化为 output lease；`object-store` 只有在 checksum、不可变 version、准确长度和 media type 全部存在时复用既有 locator，否则复制到新的不可变受管理对象；`zeromq-frame` 只允许从 LocalBuffer reader guard、受管理 ObjectStore read snapshot 或 adapter 自有不可变 bytes 建立 tracked frame。普通本机绝对路径没有稳定 guard，不能直接建立 tracked file view。
- 规范化完成后得到包含 logical attachments 和唯一 physical payloads 的 `PreparedTriggerResult`。worker 按完整 identity 去重物理 payload，调用 Broker 批量 transfer；不同逻辑 attachment 关系和顺序仍全部保留。
- 整批操作必须先核算 output 容量和全量校验，再一次性发布 handoff；任一失败时回滚本批新建 output lease，不发布含悬空引用或部分 attachment 的成功响应。
- 输入图片被直接作为输出返回时，同一 lease 从 Run owner handoff 到 response owner，Run cleanup 条件释放必须 no-op。
- worker 返回 handoff receipt；父进程校验 worker instance、revision、generation 和 receipt 后才能发布 RESPONSE。
- 父进程在 handoff 后、RESPONSE 前退出时，Broker 仍按 response owner deadline 回收。

### 6. RESPONSE / ACKED

- 图执行和 output handoff 完成后释放 Runtime execution token 与 executor permit；未 handoff 的输入/中间 lease由 Run cleanup 条件释放。
- 小型结构化结果使用 inline response；大型结果使用固定 overflow page-chain；直接图片只返回 LocalBuffer 引用。显式 `image-base64.v1` 作为结构化 JSON 使用同一容量边界。
- SDK 校验 descriptor、结构化结果 checksum 和每个 output lease locator/guard identity。
- SDK 在公开结果对象返回前，为所有唯一物理 output lease 取得 reader guard；结果对象持有这些 guard，不能在首次 checksum 校验后释放。
- 结果对象实现幂等 `Dispose`/`DisposeAsync`：先原子禁止取得新 view，等待 SDK 内已经开始的读取结束并使 owner-backed view 失效，再释放全部 reader guard，最后发布一次 ACK。调用方不得在结果释放后继续使用先前取得的 `Span`/view。
- JSON-only 结果，或所有 attachment 已明确复制到 SDK 自有 `byte[]` 的结果，不再依赖共享 view，可以在 `Invoke` 返回前发布 ACK。SDK 应提供显式 copy-and-release helper，不能悄悄把零复制结果复制成托管大数组。
- backend-service 收到 ACK 后按 response owner identity 释放全部 output lease、page-chain 和 descriptor，最后释放 TriggerSource 单在途 permit。
- SDK 未 ACK 时，response deadline sweep 先把 ACTIVE lease 迁移到 REVOKING，再尝试取得 reader guard；取得后条件释放，无法取得时进入 QUARANTINED。deadline 不能使调用方仍在读取的 slot 被复用。
- 错误、取消和 deadline 路径同样必须在协议结果已交付、资源已安全回收，或未完成 ZeroMQ 资源已由预留 adapter transport registry 持续负责且 lease 已进入 Broker REVOKING/QUARANTINED 回收链后才释放 TriggerSource permit；发布 RESPONSE 或关闭 socket 本身不是 permit 结束点。

## LocalBufferBroker API 与所有权

### 新增正式操作

- `allocate_external_buffer()`：分配精确长度 WRITING lease 和 guard identity。
- `publish_and_transfer_external_buffer()`：trusted-local Trigger 输入取得 writer guard、校验 identity/长度并在单个 pool lock 内原子 publish + first owner transfer；不扫描 full-image checksum。
- `commit_external_buffer()`：内部把已物化的 output bytes 发布为 ACTIVE；输出交付需要 checksum 时保留该校验，不作为 Trigger 输入路径。
- `cancel_external_lease()`：进入 REVOKING，不直接释放。
- `transfer_lease_owner()`：接收 expected receipt，完成单 lease 条件 owner handoff并返回新 receipt。
- `transfer_lease_batch()`：接收 expected receipts，完成多 lease 全量校验和原子 handoff并返回新 receipts。
- `release_lease_if_identity()`：按 lease、buffer、epoch、generation、state 和 owner 条件释放。
- `mark_lease_revoking_if_identity()`：adapter/response sweep 按 receipt 条件发起 ACTIVE/WRITING 撤销，不携带进程内 tracker。
- `release_transport_lease_if_identity()`：ZeroMQ adapter 已确认 tracker/view/snapshot/reader guard 全部结束后，按 receipt 条件释放；Broker 不接收 `Frame` 或 `MessageTracker`。
- `set_lease_deadline()`：handoff 时更新 backend 权威 deadline。
- `sweep_external_leases()`：处理 REVOKING、QUARANTINED 和 response reader guard。

### owner 规则

| 阶段 | owner_kind | owner_id 组成 |
| --- | --- | --- |
| SDK 写入 | `workflow-trigger-write` | server epoch、descriptor、generation、request id |
| Workflow 执行 | `workflow-runtime` | runtime id、run id、request id |
| 协议交付输出 | `workflow-trigger-response` | `delivery_kind + response_id`；local-shared-memory 包含 server epoch、descriptor、generation、request id，ZeroMQ 包含 listener/source/event/send generation |

所有 cleanup 项必须保存私有 `LeaseOwnershipReceipt`，至少包含 expected lease id、buffer id、arena id、broker epoch、descriptor generation、owner kind/id、deadline、guard identity 和精确范围。旧 owner cleanup 遇到 handoff 后的新 owner 时返回幂等 no-op，不能按公开 BufferRef 或 lease id 释放。

### writer/reader guard

当前实现使用固定总容量 arena、持久 descriptor 和动态 buddy extent。写入/读取期间持有 OS guard，回收按 `REVOKING` publication → writer/全部 reader guards → allocator lock → publication guard → identity 重验 → FREE/merge 的固定顺序执行。物理 layout 与锁顺序以 [ADR-0008](../decisions/ADR-0008-local-buffer-fixed-arena-allocation.md) 和[共享内存数据面可靠性实施基线](shared-memory-data-plane-reliability-implementation.md)为准。

- 每个 arena 使用固定 guard 文件，descriptor 拥有独立 publication、writer 和 reader byte ranges；正式图片数据面文件位于 `data/buffers/local-buffer/`。
- SDK writer 从首字节写入前持有 guard，到 REQUEST 发布后释放。
- Broker commit、cancel 或 expiry 只有取得 guard 后才能读取或复用字节区。
- SDK output reader 在结果对象返回前取得 guard，并持有到结果 `Dispose`/`DisposeAsync`；首次 checksum/内容校验完成不是释放时点。
- 结果释放先使 view 失效并等待 SDK 内活动读取结束，再释放 reader guard，最后发布 ACK。JSON-only 或 SDK-owned copy 可以提前 ACK。
- SDK 进程/session owner lock只用于诊断客户端存活状态，不能替代每 lease guard；backend mailbox owner lock则是启动、reload 和 takeover 的唯一 owner fencing。

### REVOKING 与 QUARANTINED

- WRITING 超时、SDK cancel 或 descriptor epoch 失效时进入 REVOKING；ACTIVE response reader/tracker 超时或协议交付失败时同样先进入 REVOKING。
- backend-service 在 descriptor 中发布 CANCELLED，SDK 观察后停止并释放 writer guard。
- Broker 在可配置撤销宽限期内非阻塞重试对应 writer/reader OS guard，不能阻塞主控制循环。ZeroMQ adapter 进程内 transport-lifetime registry 独立等待 `zmq.Frame`/`MessageTracker`，结束后再调用 Broker 条件释放接口。
- 宽限期结束仍无法取得 guard时进入 QUARANTINED，不计入可用容量。
- sweep 后续取得 guard 后按 identity 清空并回到 FREE。
- Broker 重启时生成新 broker epoch，旧引用失效；仍需取得旧 external guard 后才能复用对应物理 extent。
- trusted-local 之外的恶意进程可以绕过 guard直接写 arena，该威胁不在本协议解决范围内。

## Runtime execution token

### 单一执行 gate

REST sync、ZeroMQ Trigger、local-shared-memory Trigger 和 async Runtime background execution全部通过同一 token API 获取 handle 的真实 execution gate。不得在 adapter、service 或 manager 另建 semaphore、busy boolean 或只用于 local-shared-memory 的容量状态。

token 至少固定：

- token id；
- runtime id；
- workflow run/request id；
- worker instance id；
- revision id；
- runtime generation；
- snapshot fingerprint；
- handle identity；
- acquisition mode：`wait` 或 `reject`。

### 获取顺序

1. lifecycle guard 内解析并固定当前 handle identity，登记 pending admission 防止删除窗口。
2. 释放 lifecycle guard。
3. 对同一个真实 execution gate执行 wait acquire 或 nonblocking acquire。
4. 再次进入 lifecycle guard，确认 handle、revision、generation 和 snapshot 未变化。
5. 注册 active token 并移除 pending admission。
6. invoke 消费 token，不再次获取 `request_lock`。
7. finally 按完整 token identity 释放；重复释放为幂等 no-op。

等待 gate 时不能长期持有 lifecycle guard，避免阻塞 stop、切版和健康恢复。获取后重检失败必须立即释放旧 gate并返回版本变化错误。

### 入口策略

| 入口 | acquisition mode |
| --- | --- |
| 普通 REST sync | `wait`，保持现有 timeout/cancel 语义 |
| ZeroMQ sync | `wait`，保持现有公开行为 |
| local-shared-memory sync | `reject`，立即返回 `workflow_runtime_busy` |
| async Runtime worker | `wait`，仍使用同一 gate |

现有 `reserve_sync_admission` 删除窗口能力需要合并进 token 的 pending/active registry，不继续保留两个独立事实源。

## Deadline、TTL 与时钟

- SDK 提交相对 `timeout_ms`，不能提交 backend 绝对 deadline。
- backend-service 按 TriggerSource `reply_timeout_seconds` 和系统上限校验或裁剪。
- backend-service 在 PREPARE 接受时使用自身 monotonic clock 创建权威 request deadline。
- SDK 使用自己的 monotonic clock限制本地等待，但不与 Python 比较绝对 monotonic 值。
- descriptor 保存 accepted timeout 和诊断时间，不把跨进程绝对 monotonic 作为协议判断依据。
- Workflow 执行只获得 request deadline 的剩余时间。
- 输入 lease deadline 至少覆盖 request deadline 与 cleanup grace。
- output response owner 使用独立 response ACK deadline 与 cleanup grace。
- Broker 内部使用 monotonic deadline决定运行期 expiry；UTC 时间只用于诊断展示。
- backend-service/Broker 重启时通过 server/broker epoch 统一失效旧请求，不恢复旧 monotonic 值。

## 幂等与结果重放

幂等 key 继续保证同一 TriggerSource 业务请求不会重复创建 WorkflowRun，但重放能力必须按结果稳定性区分：

- 只包含状态和结构化 JSON 的已完成结果可以在 TTL 内缓存并重放；缓存体不得包含已失效的临时引用；
- 包含 `local-buffer` 或 `zeromq-frame` attachment 的结果完成交付后，不缓存、重发或重建临时 attachment；重复请求返回 `idempotent_attachment_result_not_replayable`，并携带原 `workflow_run_id`；
- 只有 `accepted-then-query` 已把图片复制到 ObjectStore，且结果保存稳定 `object-store` locator 时，才允许按既有查询/幂等规则重放；
- 重复请求到达原请求仍在途时，只返回同一请求的进行中状态或明确 busy，不启动第二次 Workflow；
- idempotency record 保存 result class、原 run id、完成状态和稳定 payload fingerprint，不保存 output lease、descriptor generation 或 ZeroMQ frame index。

该规则必须替换当前“统一缓存完整 Trigger result 若干秒”的实现，避免 ACK 或发送完成后重放已经回收的 attachment 引用。

## 路由与高速执行策略

SDK PREPARE 只允许提供：

- `trigger_source_id`；
- event id、trace id、idempotency key；
- 业务 event payload；
- 相对 timeout 请求；
- 图片类型和精确 content length。

服务端从已启用 TriggerSource 快照固定：

- project id；
- Workflow Runtime id；
- active revision、runtime generation 和 snapshot fingerprint；
- input mapping；
- default execution metadata；
- reply timeout 上限；
- route generation。

REQUEST 时 route generation 已变化、source 已禁用或 Runtime 已切版时返回 `trigger_route_changed`，不能悄悄改用新路由。

`local-shared-memory` 纳入显式高速 trigger kind 集合，默认：

- `workflow_run_record_mode=minimal`；
- `trace_level=none`；
- `retain_trace_enabled=false`；
- `retain_node_records_enabled=false`；
- `retain_input_payload_enabled=false`；
- `retain_outputs_enabled=false`；
- timing/node timing 只在显式诊断开关打开时返回。

必须保留必要 WorkflowRun 生命周期和最终 SQLite commit。性能报告单列数据库 commit 与事件追加耗时，不能通过默认 `record_mode=none` 隐藏成本。

## .NET SDK 实现边界

新增 `SharedMemoryTriggerClient`、External LocalBuffer writer/reader 和职责等价的 helper。SDK配置包提供稳定TriggerSource路由、`buffers_root`和协议参数；arena容量、descriptor/guard几何与layout fingerprint由allocator header自动发现，不复制pool能力和内部文件路径。

`local-shared-memory` v1 只提供同步调用，不复用异步 task handle 语义。公开结果对象实现确定性释放：.NET 使用 `IDisposable`/`IAsyncDisposable` 管理唯一物理 output readers 与 ACK；reader guard 在 `Invoke` 返回后继续由结果对象持有。`Dispose`/`DisposeAsync` 使用原子状态机禁止新读取、等待 SDK 内活动 accessor 结束、使 owner-backed attachment view 失效、释放全部 guard，再发布一次 ACK。重复 Dispose 为幂等 no-op。调用方释放结果前 attachment view 保持有效，释放后不得继续访问或保留先前取得的 `Span`。SDK 终结器只能作为泄漏诊断和最后防线，不能替代显式 dispose。

SDK 可以提供显式 `CopyAttachmentsAndRelease` 或等价 helper：把选中 attachment 复制为 SDK 自有 `byte[]`，完成后按上述顺序释放共享 view 并 ACK。JSON-only 和已经复制为 SDK-owned bytes 的结果允许在 `Invoke` 返回前 ACK；零复制 LocalBuffer view 不允许提前 ACK。同一 TriggerSource 的单在途 permit 因调用方长期不 Dispose 而保持占用属于明确资源背压，SDK 应记录泄漏诊断和 response deadline，但不能用后台线程在调用方可能仍读取时强制释放 guard。

### BGR24 快速路径

- 已有连续 BGR24：校验长度后一次复制到 writing lease。
- 上游采集或处理库可写入调用方提供的目标 buffer 时：允许直接填充 SDK 暴露的受限 mmap span。
- Bitmap：`LockBits` 后逐行直接复制到目标 lease，不建立整张中间 BGR24 `byte[]`；正确处理正/负 stride。
- Mono8：写目标 lease 时展开为 `B=G=R`。
- 带 padding 的 BGR24：按行去除 stride padding，目标保持紧凑 HWC。
- RGB24 等显式 raw helper：转换时直接写目标 BGR24，方法名必须表达输入格式。

### encoded 正式支持路径

- `InvokeImageBytes` 保留调用方提供的 MIME 和原始编码 bytes。
- `InvokeImageFromFile` 保留文件 bytes，并按明确参数或扩展名给出 MIME。
- `InvokeImageBase64` 先完成 Base64/Data URL 还原，得到精确 bytes 后再 PREPARE。
- 这些路径不先在 SDK 解码再无条件膨胀成 BGR24；Workflow 首次消费时统一解码并复用。
- 显式希望客户端预解码的调用使用 `InvokeBgr24FromFile`、Bitmap/raw helper 等名称明确的入口。
- encoded 与 BGR24 路径具有相同 timeout、checksum、guard、生命周期和测试保证。

所有 client 复用 mailbox 与 pool 映射，不为每次调用重新打开整个文件。缓存只按 server/broker epoch 有效；epoch 变化时全部关闭并重新握手。SDK 不自动重试业务调用，不在容量错误时切回 ZeroMQ。

## 异常回收矩阵

| 退出位置 | 回收责任 |
| --- | --- |
| SDK 在 PREPARE 前退出 | 没有共享资源，无需回收 |
| SDK 在 PREPARE 后、WRITING 前退出 | deadline 进入 REVOKING；取得 writer guard 后释放 lease，完成 descriptor 回收后释放 source permit |
| SDK 写入中退出 | OS 释放 writer guard；Broker 校验 identity 后回收 |
| SDK 写入线程挂起但进程存活 | 槽位进入 QUARANTINED，绝不复用；其他 slot 继续服务 |
| SDK 发布 REQUEST 后退出 | Workflow 按既定语义完成或取消；输入按 Run 规则释放，response按 deadline 回收 |
| adapter 在 commit 前退出 | 新 server epoch 隔离 descriptor；Broker 通过 guard 回收 writing lease |
| adapter 在 PROCESSING 中退出 | Runtime deadline 收敛；旧 generation completion 不得发布到新 descriptor |
| Runtime 或执行器 busy | 立即释放已取得 permit/token和输入 lease，发布结构化错误；source permit 保持到错误交付终态 |
| Runtime 失败或超时 | 条件清理输入和未 handoff 输出；发布结构化错误 |
| worker 在 output handoff 前退出 | 所有 Run owner lease由条件 cleanup/owner sweep 回收 |
| worker 在 handoff 后、父进程发布前退出 | response owner deadline sweep 回收输出 lease |
| SDK 持有结果时退出 | OS 释放 reader guard；response sweep 按 receipt 回收 |
| SDK 持有结果时挂起或未 Dispose | output lease 在 deadline 后进入 REVOKING；guard 仍占用则进入 QUARANTINED，不能复用 |
| SDK Dispose | 先禁止新读取并使 view 失效，释放全部 reader guard，再发布一次 ACK；JSON-only/SDK-owned copy 可提前 ACK |
| ZeroMQ transport registry admission 失败 | 在任何 multipart frame 发出前返回 `zeromq_transport_capacity_exhausted`；清理全部预留 guard/snapshot/output receipt，不产生部分回复 |
| ZeroMQ frame send 失败或 tracker 超时 | adapter 先停止监听并以 `linger=0` 关闭 REP socket；等待所有已提交 tracker。全部完成后销毁 Frame/view、关闭 snapshot、释放 reader guard，再调用 Broker 条件释放；仍未完成则由 adapter 进程内 registry 持有全部资源，lease 进入 REVOKING/QUARANTINED，不得立即复用 |
| ZeroMQ adapter 进程退出 | OS 关闭 socket、Frame/view 和 guard handle；Broker 不恢复 tracker，只按 deadline、epoch、receipt 和 OS guard回收 lease |
| Broker 重启 | broker epoch 失效；旧引用拒绝，物理 slot 仍按 external guard安全恢复 |
| backend-service 重启 | server epoch 失效；旧 descriptor 不恢复，response/input owner按 deadline清理 |

所有 release 都必须幂等并带 identity fence；禁止仅按 descriptor index、slot id、lease id 或 TriggerSource id 无条件回收。

## 实施顺序

### 阶段 0：校正文档并冻结 binary contract

- 将状态保持为“架构已接受，binary protocol 待冻结”。
- 建立 binary schema 单一事实源，生成 Python/.NET layout 与 contract fixture。
- 固定 header、descriptor、page、状态、错误码、容量、guard、timeout 和 path builder；对真实 1080p/4K/20MP 图片完成 Python/.NET checksum、增量写入和 mmap 校验基准，据此冻结“结构化 mailbox payload 使用 CRC32、trusted-local 输入图片使用 guard publication”的边界。
- 固定 descriptor 状态迁移的唯一写入方、mailbox owner lock、reload/takeover fencing 和 source permit 生命周期。
- 明确正式能力包含 output lease handoff，不再保留“只返回小 JSON”未决项；冻结零复制结果对象持有 reader guard 到 Dispose/ACK 的生命周期。
- 冻结顶层 `result_mode/reply_timeout_seconds/ack_policy`、`result_mapping.result_bindings`、内部 `PreparedTriggerResult/PreparedLogicalAttachment/PreparedPhysicalPayload`、私有 `LeaseOwnershipReceipt`、公开 `WorkflowTriggerResultV1` locator union、`TriggerResponsePlan`、`WorkflowOutputDeliveryPlan`、ObjectStore snapshot/immutable write 端口和结构化 adapter capability 契约。
- 冻结 ZeroMQ adapter 进程内 transport-lifetime registry 的 entry、容量预留、满载错误和关闭顺序；明确 Broker 不管理 libzmq tracker。
- 冻结幂等分类：JSON-only 可重放、临时 attachment 不可重放、ObjectStore 稳定结果可查询。
- 冻结一个统一的 `amvision.workflow-trigger-result.v1`，成功、失败、JSON-only 和 binary attachment reply 不再分协议。
- 设计数据迁移，把已有 `result_binding` 转成单元素 `result_bindings`，迁移后删除旧字段和“返回全部 outputs”fallback。该迁移只声明 Workflow TriggerSource result mapping REST payload 与 `amvision.workflow-trigger-result.v1` 属于发布前开发契约；不能扩大成全部 REST `/api/v1` 均不承诺兼容。

门禁：Python/.NET fixture 完全一致；真实双进程能互斥同一 descriptor guard；reload 新旧 owner 重叠不重置 active mmap；图片数据面正式与发行配置生成的文件只位于各自 `data/buffers/`，训练遥测路径不被误迁移；依赖图中不存在阶段引用尚未落地的接口；已有 TriggerSource 迁移方案可以无损生成 `result_bindings`。

### 阶段 1：提取中立 mmap IPC primitives

- 从 inference mailbox 提取 guard、owner lock、path fencing、checksum、descriptor publication 和 page-chain helper；现有 inference CRC32 通过中立算法接口保持原行为，不因本协议基准而改变。
- inference mailbox 行为和性能不得回归。
- Workflow mailbox 只复用代码，不复用文件和 owner state。

门禁：现有 inference mailbox 全部测试通过；Python/.NET guard 进程测试覆盖锁占用、进程退出和重复获取。

### 阶段 2：External lease、receipt 与 CAS 基础 API

- 实现精确长度 allocate/commit。
- 实现每 lease writer/reader guard。
- 实现 REVOKING、QUARANTINED、取消确认和非阻塞 sweep。
- 实现 identity-fenced release、monotonic deadline 和健康容量指标。
- 引入私有 `LeaseOwnershipReceipt`，实现单 lease/batch CAS transfer、release 和 revoke；公开 BufferRef 只保留定位契约。
- 本阶段只验证 Broker/LocalBuffer 基础能力，不接入 WorkflowRun、Runtime token、SDK 结果或 ZeroMQ tracker。

门禁：正常 commit、写入中断、超时、挂起、Broker 重启、重复 transfer/release、batch 原子性和旧 writer 恢复都不泄漏、不部分转移，也不破坏新 slot。

### 阶段 3：统一 Runtime execution token

- 将真实 handle gate 封装为 wait/reject 两种 acquisition mode。
- REST、ZeroMQ、local-shared-memory 和 async execution 全部接入同一 token API。
- 合并 `reserve_sync_admission` 的删除窗口职责。
- worker restart、切版、旧 completion、取消和 timeout 按 token identity 收敛。

门禁：同一 Runtime 只有一个真实执行者；reject 模式立即 busy；不同 Runtime 真并行；旧 generation 不能释放新 token；REST/ZeroMQ/async 既有链路无行为回归。

### 阶段 4：全局 mailbox、executor admission 与首次输入 handoff

- 实现固定 mailbox、128 descriptor、response page-chain、server epoch、owner lock 和 supervisor 生命周期。
- 实现 descriptor guard、checksum、取消、deadline sweep、reload/takeover fencing 和异常恢复。
- 实现 TriggerSource route registry、route generation、每 source 单在途 CAS 和有界 executor permit；poller 不同步等待 Workflow，也不向无界执行器队列提交。
- 建立 WorkflowRun identity 并取得 Runtime token/executor permit 后、worker submit 前，按阶段 2 receipt 完成 `workflow-trigger-write -> workflow-runtime`。
- 为 Run 创建、Runtime/executor admission、首次 transfer 和 worker submit 各失败点实现按当前 receipt 的补偿回收。
- 本阶段用 Python contract harness 验证 JSON-only RESPONSE/ACK，不依赖尚未实现的 output attachment 或 .NET SDK。
- 纳入高速 execution metadata 和 minimal WorkflowRun 策略。

门禁：100 个 enabled/idle TriggerSource 的 LocalBuffer 占用为 0；同一 source 第二个调用立即 busy；不同 source descriptor 可同时进入 WRITING/PROCESSING；所有首次 input transfer 失败补偿闭环；executor 和 Runtime 满载不排队。

### 阶段 5：output plan、规范化、ObjectStore snapshot 与 handoff

- 实现 `TriggerResponsePlan`、`WorkflowOutputDeliveryPlan`、`PreparedTriggerResult`、logical attachment/physical payload 分层和完整 representation identity 去重。
- worker 在自身 cleanup 前按固定 plan 规范化 public outputs；current-run receipt 可 transfer，foreign/incomplete BufferRef、memory handle 和 FrameRef 按固定规则复制或物化。
- 扩展 ObjectStore port，落地 `stat_object()`、`open_read_snapshot()`、不可变写入 receipt 和旧对象 materialize；稳定 locator 强制 version、checksum、长度和 media type。
- storage/local-path 按 delivery kind 选择 LocalBuffer 物化、不可变 ObjectStore locator 或 adapter 可持有的 snapshot。普通绝对路径不能直接作为稳定 ZeroMQ file view。
- 整批 output 先核算容量、全量规范化和校验，再执行 batch handoff；任一失败不发布部分 attachment。
- response deadline、Run cleanup 和父进程发布前退出均按私有 receipt 条件回收。

门禁：Run cleanup 后 handoff 输出仍有效；Python harness ACK/deadline 后失效；同一物理 identity 只转移一次；多 lease 无部分 handoff；稳定 ObjectStore locator 不重复物化；可变对象和绝对路径进入受控不可变来源；snapshot 在消费者释放前内容不变化。

### 阶段 6：.NET local-shared-memory SDK 与 Workflow 图片节点

- 实现 mailbox 握手、descriptor claim、lease guard、写入、发布、response page-chain读取和 ACK。
- 实现 BGR24 直接写、Bitmap/Mono8/stride 转换直写和 encoded bytes/File/Base64 正式路径。
- 实现 output reader guard、checksum、cancel、deadline和epoch重连。
- 公开结果实现幂等 `IDisposable`/`IAsyncDisposable`，由结果持有 reader guard 到 view 失效后释放并 ACK；实现显式 copy-and-release helper，禁止零复制结果提前 ACK。
- adapter 提交标准 `image-ref.v1` BufferRef，不新增图内专用 payload。
- raw 路径保持 borrowed mmap view；encoded 路径继续统一 helper解码。
- 审计所有模型、OpenCV 和自定义节点，不允许自行解析 BufferRef 或绕过 ExecutionImageRegistry。
- 输入 lease 保持至整个 Workflow Run 与 output handoff 完成。
- 新增 `Image Encode`，明确输出 JPEG/PNG/BMP/WebP `image-ref.v1`；保留现有 `Image Base64 Encode` 的显式 JSON 语义。
- 直接 public image outputs 通过正式 handoff 返回，不进入 worker queue 的大型 bytes；显式 `image-base64.v1` 只走受容量限制的结构化响应。
- App Result 依据公开 payload type 分类 JSON 与 attachment；现有 `Image Body` 只在显式 binding 时作为受容量约束的 `response-body.v1` 返回，不承担 Trigger transport 选择。

门禁：BGR24、Bitmap、Mono8、正/负 stride 转换与基准矩阵逐字节一致；File/Base64 解码与当前 OpenCV 基准一致；同一 encoded 输入在顺序节点和两个并行分支中每种 flags 只解码一次；raw 输入零 `cv2.imdecode`；Dispose 前 view 有效、Dispose 后拒绝新访问、全部 guard 释放后只 ACK 一次；JSON-only/SDK-owned copy 可以提前 ACK。

### 阶段 7：结果 adapter、ZeroMQ transport registry 与原子协议迁移

- 实现协议中立 JSON + attachments dispatcher，不递归扫描嵌套临时 image-ref。
- 实现 local-shared-memory BufferRef 返回、统一 ZeroMQ Trigger Result v1 binary attachments、`event-only` 丢弃和 `accepted-then-query` 持久化边界。
- ZeroMQ adapter 实现同进程有界 transport-lifetime registry；首帧前按唯一 physical frame 预留容量，保存 Frame、tracker、view/snapshot、reader guard、receipt、deadline 和 socket generation。
- send/tracker 失败先关闭 socket；tracker 完成后 adapter 清理本进程资源并调用 Broker 条件释放。Broker 不保存、等待或重试 libzmq tracker。
- transport registry 满载在任何 multipart frame 发出前返回 `zeromq_transport_capacity_exhausted`；发送开始后不得放弃已经预留的生命周期责任。
- adapter 注册 capability；创建、enable 和 Runtime 切版时校验 response plan。
- 前端支持选择多个 `result_bindings`，并显示每个 binding 在当前 Trigger 中的 JSON、LocalBuffer、binary attachment、持久化或丢弃方式。
- 把 ZeroMQ .NET SDK reply 收敛为统一 `amvision.workflow-trigger-result.v1`，实现 Frame 0 manifest、0..N attachments、共享物理 frame 和严格帧校验。
- 后端、Alembic、前端、仓库内 SDK、fixture/Postman 和已有数据在同一提交链中把 `result_binding` 原子迁移为 `result_bindings`，删除独立 error format、第一帧专用解析、旧字段和双读代码。
- JSON-only 同步 adapter 不支持已选择图片 binding 时拒绝配置；不需要的 binding 直接不选择。
- 已选择 JSON 中出现嵌套临时 memory/buffer/frame ref 时返回 `ephemeral_image_ref_in_json_result`。
- 幂等层按稳定结果分类，禁止重放已交付或已回收的临时 attachment。

门禁：同一 Workflow 同时返回 JSON、单图和多图；同一完整物理 identity 被两个 binding 引用时只发送一个大图 frame；registry 容量不足不发送部分 multipart；tracker 超时不提前复用 slot；adapter 崩溃后 Broker 按 guard/deadline 回收；PLC/IO `event-only` 不建立 handoff；异步查询不持久化短期 BufferRef；迁移后不存在旧字段或双协议运行代码。

### 阶段 8：故障注入、恢复和观测收口

阶段 8 已完成。backend 只在 `return_timing_metadata_enabled=true` 时把当前调用的执行阶段耗时放入 Result `metadata.timings`；生产默认关闭。mailbox supervisor 和 ZeroMQ transport health 只保留最近一次数值摘要，不保存图片、路径或业务参数。.NET SDK 仅在 `SharedMemoryTriggerRequest.EnableTimings=true` 时创建 `SharedMemoryTriggerTimings`，关闭时不在图片写入热路径增加额外计时调用。

计时语义固定如下：

- `workflow_image_decode_ms` 只累计 encoded 图片在当前 Workflow 首次 cache miss 时的 codec 解码；同一引用的 cache hit 不重复累计。
- `workflow_raw_view_ms` 累计 raw BGR24 mmap/view 获取和 matrix 解释，不包含 codec 解码。
- `response_image_encode_ms` 是图中显式 `core.io.image-encode` 节点的执行耗时之和；Trigger adapter 不隐式编码图片。
- `workflow_persist_ms` 在实际 WorkflowRun/事件持久化完成后加入当前同步结果，不为保存 timing 再执行第二次数据库写入。
- `tracker_cleanup_ms` 和 ZeroMQ `lease_reclaim_ms` 发生在 multipart 已交给 transport 后，记录在 adapter health 的 `transport_timings` 中，不伪装成已经返回给客户端的 reply 耗时。
- .NET `InvokeReturnMs` 截止结果对象可返回；零复制 attachment 的 `AttachmentAccessMs` 和最终 `DisposeAckMs` 由同一个结果对象在读取、释放 reader guard 和 ACK 时补全。

统一记录：

- `sdk_convert_to_bgr24_ms`；
- `sdk_base64_decode_ms`；
- `sdk_write_local_buffer_ms`；
- `sdk_checksum_ms`（仅结果 attachment 校验；输入图片 publication 不做 full-image CRC）；
- `mailbox_prepare_ms`；
- `mailbox_request_detect_ms`；
- `broker_commit_owner_handoff_ms`；
- `runtime_admission_ms`；
- `workflow_image_decode_ms` 或 `workflow_raw_view_ms`；
- `workflow_execute_ms`；
- `workflow_persist_ms`；
- `output_handoff_ms`；
- `response_json_serialize_ms`；
- `response_image_encode_ms`；
- `zeromq_attachment_send_ms`；
- `invoke_return_ms`；
- `attachment_access_ms`；
- `dispose_ack_ms`；
- `tracker_cleanup_ms`；
- `lease_reclaim_ms`；
- `total_ms`。

health 显示 mailbox owner/epoch、descriptor/page 使用量、lease 状态、REVOKING/QUARANTINED 数量、active TriggerSource、Runtime token、ZeroMQ transport registry entry/bytes/reservation、ObjectStore snapshot、超时回收和最近协议错误；不暴露图片内容、本地路径或业务参数。

门禁：PREPARE、WRITING、REQUEST、PROCESSING、output handoff、RESPONSE、Dispose/ACK、ZeroMQ frame send 和 tracker cleanup 各阶段注入 SDK、adapter、Runtime、Broker 退出；资源全部回到基线或进入可解释的 QUARANTINED，不能泄漏 descriptor、page、slot、snapshot、registry entry、source permit 或 Runtime token。

### 阶段 9：性能、soak、发行和文档收口

阶段 9 已完成，源码开发环境的正式证据如下：

- 1080p、4K、20MP BGR24 和 57.1 MiB 实际 BMP 均完成同机 ZeroMQ 与 local-shared-memory 对照；20MP 并发 8 的三轮 candidate P99 为 715.1/738.5/810.0 ms，均显著低于对应 ZeroMQ 2067.2/2528.0/2187.6 ms；真实 BMP 并发 2/4/8 的 candidate P99 为 215.9/386.3/689.4 ms，对应 ZeroMQ 为 534.4/759.0/1511.6 ms。
- 10,000 次 1080p/4K、8 worker 混合调用全部成功，整体 P50/P95/P99 为 129.9/166.0/194.3 ms；结束后 descriptor、overflow page、LocalBuffer lease、REVOKING/QUARANTINED 和 Runtime token 全部回到基线。
- 57.1 MiB 实际 BMP 经 HTTP Base64 调用完整 24 次分类 Workflow：60 秒 21/21 成功，P50/P95/P99 为 2906/3187/3950 ms。
- 同一 Workflow 经 ZeroMQ encoded BMP：60 秒 48/48 成功，P50/P95/P99 为 1219/1317/1392 ms。
- 同一 Workflow 经 local-shared-memory raw BGR24：55/55 成功，P50/P95/P99 为 1107.9/1169.2/1270.2 ms；数据面 P50/P95/P99 为 20.4/23.5/25.9 ms，SDK 写入 59.9 MiB LocalBuffer 平均 7.5 ms，后端 codec 解码为 0，.NET Gen0/1/2 GC 均为 0。
- 真实 YOLO11 classification Deployment sync：60 秒 749/749 成功，P50/P95/P99 为 63/79/93 ms。
- 64 KiB request/inline response 边界、1/8/16/32 MiB page-chain、16 并发混合、restart、mid-write crash、timeout/cancel、CRC/owner/generation 损坏和 4 进程共 2,000 次 mmap 压测通过。
- 所有正式持续负载结束后，三个 LocalBuffer pool 的 `used/active/writing/revoking/quarantined` 均为 0，allocation failure 与 stale fence 均为 0；服务日志无 ERROR、WARNING 或 Traceback。

本轮验证针对源码开发环境。`release/<profile-id>/app/` 仍是 assemble 产物，禁止手工同步源码；生成下一版发行包时必须从当前源码按目标 profile 重新执行 `assemble-release`，并复用本页 contract、smoke 和 soak 门禁。

## 完整验收门禁

### 协议和跨语言

- Python/.NET 对同一 header、descriptor、page、状态、checksum algorithm/value、字节序和对齐生成完全一致的 fixture。
- Windows Python/.NET 双进程真实 guard 互斥、进程退出释放和重复获取通过。
- 64 KiB 新 inline 边界、旧 512 KiB 迁移样本及 1/8/16/32 MiB 结构化响应均通过。
- page pool 碎片化后非连续 page-chain可正常读取和回收。
- 显式 Base64 在 inline/page-chain 内能无损返回，超过单响应上限明确拒绝且不 fallback。
- 统一 ZeroMQ v1 无图为一帧；图片响应为 `1 + N` 帧，其中 N 是唯一物理 payload 数而不是逻辑 attachment 数；manifest 与 frame 集合、索引、长度、checksum 完全一致。
- SDK 不忽略未声明的 binary frames；成功、业务失败和 adapter 错误均由同一 result schema 解析。
- ZeroMQ 每个唯一物理 payload 使用 tracked frame；逻辑 attachment 可以共享 frame。adapter 在发送 Frame 0 前为全部唯一 frame 预留 transport-lifetime registry 容量；任一已提交 tracker 未完成时 lease 不释放，发送 timeout 后先关闭并重建 socket，未完成资源留在 adapter registry，lease 进入 REVOKING/QUARANTINED，后续请求不受 REP 状态污染。
- 最大 JSON、单 attachment、attachment 数、总响应容量和 transport registry entry/bytes 在发送前校验；超限或 registry 满载不产生部分回复，发送开始后不丢弃清理责任。
- Broker 测试断言其 API、状态和持久信息中不出现 `zmq.Frame`/`MessageTracker`；adapter 进程退出后依靠 OS guard 释放和 Broker deadline sweep 收敛。

### LocalBuffer 生命周期

- SDK 在 WRITING 前、写入中、REQUEST 后和取消阶段退出都不会误回收新 generation。
- writer 挂起时槽位进入 QUARANTINED；其他槽位仍可工作；guard释放后恢复。
- output BufferRef 在 Run cleanup 后仍有效；零复制结果在 `Dispose`/`DisposeAsync` 前 view 有效，Dispose 先使 view 失效并释放全部 reader guard，随后 ACK。
- SDK 在结果持有期退出或挂起时不会让新 writer 覆盖正在读取的字节；未 Dispose 超过 deadline 时 lease 进入 REVOKING/QUARANTINED。
- ACTIVE output reader/transport 超时会进入 REVOKING，并根据 OS guard 进入 FREE 或 QUARANTINED；ZeroMQ tracker 只由 adapter registry 等待，不能绕过 adapter/Broker 职责边界直接回收。
- JSON-only 与 SDK-owned attachment copy 可以提前 ACK；零复制 LocalBuffer view 提前 ACK 必须失败。
- Run 创建、Runtime/executor admission、第一次 owner transfer 和 worker submit 分别注入失败，输入 lease 始终由当时的权威 receipt 回收且不会跨 owner误释放。
- 同一输入作为输出返回时只 handoff 一次，Run cleanup不能释放。
- 多输出 handoff要么全部成功，要么不发布成功响应。
- 未被 `result_bindings` 选中的图片不 handoff，并由 Run cleanup 正常释放。
- current-run receipt/BufferRef、foreign/incomplete BufferRef、memory handle、FrameRef、storage/local-path ref 按 delivery kind 固定规则规范化后不会在 SDK 读取前失效或被覆盖。
- 同一物理图片被多个 binding/item 引用时逻辑关系全部保留，LocalBuffer handoff和 ZeroMQ 大图 frame 都只发生一次。
- 去重只按完整物理 representation identity；两个 checksum 相同但 lease/version/范围/表示不同的 payload 不自动共享 owner 或 frame。
- `image-refs.v1` 只按 `items` 和 binding 顺序返回，`source_image` 不被隐式加入；嵌套临时引用明确拒绝。
- Broker/backend-service重启后旧 epoch、generation和owner引用全部拒绝。

### Runtime 和并发

- 8 个 LocalBuffer slot、100 个 enabled TriggerSource，全部空闲时占用为 0。
- 8 个不同 TriggerSource绑定8个不同 Runtime、且结果不新增 output lease时，可同时占用8个输入 lease并真实并行。
- 第9个并发输入调用立即返回 `local_buffer_capacity_exhausted`；带新生成图片输出的调用按额外 output lease 需求更早返回 `local_buffer_output_capacity_exhausted`，均不排队、不重试、不 fallback。
- 同一 TriggerSource第二个并发调用立即返回 `trigger_source_busy`。
- 两个 TriggerSource绑定同一单 worker Runtime时，一个执行、另一个立即返回 `workflow_runtime_busy`。
- REST、ZeroMQ、local-shared-memory和async入口竞争同一 Runtime时共享同一真实 gate。
- Runtime token 在 handoff 后释放；同一 TriggerSource permit 在 Dispose/ACK/deadline 后的安全回收，或 ZeroMQ tracker 完成/已经由预留 transport registry 持续承担责任前不得释放。
- executor worker 和提交队列均有界；满载立即返回 `trigger_executor_busy`，不得在 `ThreadPoolExecutor` 内形成隐藏排队。
- worker restart、切版和旧 completion不能释放或污染新 token。
- 视频 Trigger连续同步调用时，其他 TriggerSource可以并发调用。
- backend reload 新旧进程重叠时只有 mailbox owner lock 持有者可更新 epoch；takeover 后旧 owner 不得清理新 generation。

### 图片准确率和复制边界

- BGR24、Bitmap、Mono8、带 stride和负 stride输入生成准确BGR24，像素与方向完全一致。
- JPEG、PNG、BMP、Base64/Data URL正式入口能正确解码；同一 Workflow Run、同一flags只解码一次。
- raw BGR24从 SDK 写入、BufferRef、Workflow节点到 Deployment inference全程不执行encode/decode，默认读取为只读mmap view。
- raw BGR24直接结果保持 raw bytes；只有显式 `Image Encode` 生成 JPEG/PNG/BMP/WebP，adapter 不暗中转码。
- `image-base64.v1` 只作为显式 JSON 返回，不同时生成重复 binary attachment。
- 图内两个并行分支和多个推理节点只持有一个输入 lease，不生成多份输入图片副本。
- 阶段 0 对真实 1080p、4K、20MP 图片比较 .NET/Python checksum 与 mmap 扫描成本；正式输入链路按实测结果使用 writer guard + identity fence publication，不重复扫描整帧；mailbox payload 与结果 attachment 继续按各自契约校验。

### 稳定性与目录

- PREPARE、WRITING、REQUEST、PROCESSING、output handoff、RESPONSE和ACKED各阶段分别注入SDK、adapter、Runtime和Broker退出，均不泄漏descriptor、page、slot或token。
- JSON-only 幂等重复请求重放同一稳定结果；包含临时 attachment 的重复请求不重跑 Workflow，也不重放旧引用，而是返回 `idempotent_attachment_result_not_replayable` 和原 run id。
- `accepted-then-query` 图片已持久化 ObjectStore 后可通过稳定 locator 查询；短期 BufferRef 不进入数据库或幂等缓存。
- ObjectStore locator 必须包含不可变 version、checksum、准确长度和 media type；缺少稳定元数据的旧对象会物化为新不可变对象。`open_read_snapshot` 在 consumer/tracker 结束前保持同一内容，普通绝对路径不能冒充稳定 snapshot。
- 连续10,000次多Trigger混合调用后，descriptor、page、active source、Runtime token、LocalBuffer active/REVOKING/QUARANTINED全部回到基线。
- 启动、调用、重启和退出后扫描图片数据面，所有 LocalBuffer、Inference Mailbox、Workflow Trigger Mailbox、Training EventRing、guard 和 owner lock 都只能出现在 `data/buffers/` 树内。训练遥测后续已按 ADR-0009 阶段 2 迁移到独立 EventRing Channel，始终不混入图片 arena。
- 源码开发环境和重新assemble的发行环境执行相同contract、smoke和soak门禁。

## 性能验收

### 测试矩阵

- 图片：1080p、4K、20MP BGR24，以及实际57.1 MiB BMP。
- 表示：已有BGR24 `byte[]`、调用方直写目标Span、JPEG/PNG/BMP encoded、Base64。
- 入口：现有同机ZeroMQ与新local-shared-memory。
- 并发：单调用及2/4/8个不同Runtime。
- 分位数：P50、P95、P99；每个矩阵 cell 在同一机器、同一模型、同一数据和相同 warmup 下独立执行三轮，每轮预热后至少1,000次，以最差轮次判定；另做10,000次稳定性soak。

### 分阶段指标

- SDK格式转换和Base64还原；
- mmap写入；结果 attachment 的 checksum 单独记录，不计入 trusted-local 输入 publication；
- PREPARE/REQUEST发现；
- Broker guard、receipt/epoch/generation/owner/deadline 校验和原子 publish + owner transfer；
- Runtime admission；
- Workflow raw view/encoded decode；
- Workflow执行；
- SQLite commit和生命周期事件追加；
- output handoff、`invoke_return_ms`、`attachment_access_ms`、`dispose_ack_ms`；
- ZeroMQ `tracker_cleanup_ms` 与 Broker `lease_reclaim_ms`；
- CPU、托管分配、Python大bytes峰值、内存带宽和操作系统磁盘写回。

### 通过标准

- 20MP大图数据面 P50和P95相对当前同机ZeroMQ基线至少降低40%。数据面逐请求定义为 SDK 端到端调用耗时减去 adapter 对同一 Workflow Runtime 的同步 invoke 耗时：ZeroMQ 使用 `trigger_runtime_submit_ms`，local-shared-memory 使用 `workflow_runtime_invoke_ms`。该边界覆盖 SDK/协议收发、mailbox/Broker、输入准备和小结果返回，但排除两个 transport 共用的 Runtime manager、worker IPC 与图执行。端到端分位数另行完整报告，不能从 P50 减平均值估算。
- 每个测试 cell 的 `candidate_p99 <= baseline_p99 + max(5 ms, baseline_p99 * 10%)`。
- 每个测试 cell 的尾部宽度满足 `candidate(p99 - p95) <= baseline(p99 - p95) + max(5 ms, baseline_p95 * 10%)`；20MP BGR24 local-shared-memory 的 P99 不得高于同机 ZeroMQ 基线。
- 三轮任一轮出现 timeout、协议错误、guard/slot/snapshot/registry entry 泄漏即失败，不能用其他轮次均值抵消。
- 1080p链路不得因新协议增加超过10%的数据面P95。
- raw BGR24 backend路径不得产生整图Python `bytes`副本或执行OpenCV decode。
- 调用方可直写目标Span时，不得再建立整张中间BGR24数组。
- 阶段 0 报告 SDK checksum 与 backend mmap 扫描成本，并据此证明 trusted-local 输入采用 guard publication；mailbox payload CRC、结果 attachment checksum、identity fence 或 writer guard 任一项不得为达成验收而关闭。
- 最终Workflow总耗时单独报告，但不能用模型执行时间掩盖数据面回归。
- LocalBuffer为文件支持mmap且`flush_on_write=false`时不主动同步flush；报告仍需观察OS异步写回，不能宣称物理磁盘永不参与。

## 明确不做

- 不删除或重写现有ZeroMQ TriggerSource。
- 不维护 ZeroMQ JSON-only/multipart 双协议、reply mode、协商或兼容分支；统一使用一个支持 0..N attachments 的 v1。
- 不提供local-shared-memory到ZeroMQ、文件或队列的自动fallback。
- 不按Deployment、Runtime或已启用TriggerSource总数量做静态限流。
- 不建立业务请求等待队列或有限自动重试。
- 不新增每TriggerSource mmap、`control.mmap`、`frames.mmap`或永久frame channel。
- 不为图片数据面新增第二个 mmap root；LocalBuffer、inference image mailbox 和 Workflow Trigger mailbox 统一使用 `data/buffers/`。本文阶段不迁移训练遥测；后续只允许按 ADR-0009 收敛到 `data/buffers/local-message/`。
- 不把LocalBufferBroker变成图片codec、颜色转换或模型预处理服务。
- 不让SDK直接修改Broker slot状态、lease owner或commit元数据。
- 不把短生命周期BufferRef持久化到异步任务或数据库。
- 不递归扫描任意 JSON 中的 image-ref；只处理选中的独立公开图片 binding。
- 不把嵌套 memory/buffer/frame 临时引用自动提升成 attachment；发现后明确拒绝。
- 不增加输出丢弃策略开关；不需要返回的 binding 直接不选择。
- 不在 local-shared-memory v1 中加入多图片输入或异步 task handle。
- 不缓存或重放已经交付、ACK 或回收的临时图片 attachment。
- 不使用无界 executor 提交队列，不在 Runtime gate 外形成隐藏排队。
- 不允许 reload 新旧进程同时重置 mailbox 或发布 server epoch。
- 不由 adapter 暗中决定 JPEG/PNG/Base64 表示。
- 不把 generation、checksum 或 SDK 受限 view 描述成恶意进程隔离能力。
- 不在writer/reader guard仍被占用时复用物理slot。
- 不为追求基准数字关闭正式链路 checksum 或最小生命周期记录。
