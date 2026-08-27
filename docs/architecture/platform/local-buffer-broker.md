# LocalBufferBroker

## 定位与状态

LocalBufferBroker 是同一主机内 backend-service、deployment runtime、Workflow Runtime 和其他 Worker 之间传递大图片与视频帧的共享内存数据面。控制消息只携带引用和元数据，像素字节由消费者直接读取 mmap，避免 Base64、JSON 和重复整图复制。

当前实现使用固定总容量 arena、动态 extent、lease 和控制协议，并由 buddy allocator 依据精确 `content_length` 分配最小可容纳的连续 extent。实现与验证顺序见[共享内存数据面可靠性实施基线](../../development/shared-memory-data-plane-reliability-implementation.md)，架构决策见 [ADR-0008](../../decisions/ADR-0008-local-buffer-fixed-arena-allocation.md)。

LocalBuffer 不是持久化存储、任务队列、图片 codec、跨主机协议或 Workflow Trigger mailbox。

LocalBuffer 是全项目短期内存图片的统一数据面。HTTP/ZeroMQ/local-shared-memory 输入进入本机同步处理链后、Workflow 节点间图片、同步 Deployment 输入与结果图、Preview运行期图片和节点生成的新图片都通过 BufferRef/FrameRef 交接。只有跨重启异步队列、长期保存和审计使用 ObjectStore/文件。节点内部仅在一次 handler 调用期间存在的 OpenCV/NumPy矩阵或模型 tensor不属于公开传输契约，不能作为节点输出跨边界泄漏。

## 进程与 owner

- `LocalBufferBrokerSupervisor` 管理 broker companion process；
- broker process 是 allocator、descriptor、lease 和 deadline 的唯一写入 owner；
- `LocalBufferClient` 负责 allocate、commit、acquire、transfer、release 和状态查询；
- Python direct reader/writer 和 .NET SDK 只通过受限 locator、guard 和精确 mmap view 访问图片 bytes；
- backend-service takeover 只在验证旧 owner 后接管，不允许同一 root 出现两个 allocator owner。

backend-service 主图片 arena 与 inference daemon 私有异步暂存 arena 是两个互不重叠的 owner。两者可以使用相同文件格式和分配器，但容量、epoch、owner lock 和 descriptor 表独立；同步调用不复制到私有 arena。

主 arena 由 backend-service、Workflow Runtime、各种节点、同步 Deployment和本机 Trigger共享，按实际在途图片动态占用；不按 Runtime、Deployment、TriggerSource或节点数量静态预留。只读消费者借用 mmap view，产生新像素的节点申请新 extent并在写完后发布不可变引用。零整图复制指消除协议和模块桥接中的可避免副本，不包括解码、颜色转换、裁剪、绘制和模型预处理必需的算法写入。

实现位于 `backend/service/application/local_buffers/` 和 `backend/service/infrastructure/local_buffers/`。

## 文件目录

当前共享根由中立的 `local_memory.root_dir` 配置，默认保持 `./data/buffers`，不能收窄为某个 LocalBuffer 子目录，因为 Inference/Workflow Trigger/Training Telemetry Channel 也从该根派生。LocalBuffer 只消费其中的 `local-buffer/` 子目录，且不会与 LocalMessage 共享 enable、owner 或生命周期。

```text
data/buffers/
├─ local-buffer/
│  ├─ arena-main.mmap           主图片 bytes，arena_id=local-buffer-main
│  ├─ allocator-main.mmap       固定 header 与 descriptor 表
│  ├─ arena-main.guard          publication/writer/reader byte-range guards
│  └─ arena-main.owner.lock     Broker 单 owner lock
├─ local-message/
│  ├─ inference-daemon-main.rpc.mmap
│  ├─ workflow-trigger-main.rpc.mmap
│  └─ training-telemetry/       每个训练 Worker 的独立 EventRing
└─ inference-daemon-private/    daemon 私有异步暂存 arena
```

该目录树描述当前实现。三类结构化 Channel 已按 [ADR-0009](../../decisions/ADR-0009-local-message-channel.md) 原子迁移到 `local-message/`。它们共享底层 engine，但不会合并 owner、epoch、descriptor、page pool 或容量；旧 `inference-control/` 与 `workflow-trigger/` layout 不再读取。

约束如下：

- 正式图片数据面 mmap、guard 和 owner lock 只能位于 `data/buffers/` 的明确子目录；
- 不在仓库根、`data/files/`、`data/queue/`、`.tmp/`、系统临时目录或 SDK 配置目录创建正式 mmap；
- 训练遥测不承载图片，使用 `data/buffers/local-message/training-telemetry/` 的独立 EventRing，但始终不属于 LocalBuffer 图片 arena；
- 发行包使用发行应用根下的 `data/buffers/`，不能引用源码工作区绝对路径；
- 测试可重定向到 `.tmp/<test>/buffers/`，但使用同一 binary layout、guard 和路径 containment；
- 文件由 Broker/daemon owner 创建，SDK 不创建或选择 arena/metadata 路径；
- locator 打开前解析绝对路径；SDK 只从配置包取得受信 `data/buffers` 根目录，arena 文件名、容量、descriptor/guard 几何和 layout fingerprint 从 allocator header 自动发现并与本次 allocation fingerprint 交叉校验。

## 固定 arena 与动态 size class

backend-service 主 arena 默认总容量 2 GiB，最小 block 1 MiB，单次连续分配上限 1 GiB。Broker 根据精确 `content_length` 选择最小可容纳 buddy order；1、2、4、8、16、32、64、128、256、512、1024 MiB 是动态 size classes，不是固定 pool 或调用参数。

正式 Broker 使用64-bit进程。2 GiB 是固定逻辑 arena/file容量，不代表全部页面始终锁定在物理RAM；文件支持 mmap 仍可能被操作系统分页或异步写回。启动必须校验文件长度、可写空间和 layout fingerprint，默认不为获得表面基准数据而预触碰整个 arena。

每个 lease 保存：

- `content_length`：可读取、校验和传递的精确有效字节；
- `allocation_capacity_bytes`：buddy block 容量；
- offset/order：allocator 回收与合并所需信息。

图片必须保持一个连续 extent。LocalBuffer 不用 page chain，不做活动 block compaction，不在运行时扩展 mmap，不创建 dedicated 临时 mmap。连续容量不足时立即失败；不排队、不重试、不 fallback。

默认 `huge_reserve_bytes=0`。这表示 arena 能在连续空间存在时支持 1 GiB 图片，但不保证任意碎片状态下都成功。现场需要 1 GiB 硬保证时显式保留 1 GiB 高地址区域；普通 lease 和 frame channel 不借用该区域，其容量成本必须在 health 中可见。

general 区由一个或多个 `max_allocation_bytes` 大小的顶级 buddy root 组成，root之间不合并。free list按 order 分桶并按offset升序；分配优先最低offset，split继续使用低地址child并归还高地址child，从而聚集常用小图并尽量保留高地址大连续extent。相同请求序列必须得到确定性的offset结果。

## allocator metadata

allocator metadata 使用固定 header 和 descriptor 表。descriptor 数量为 `arena_size_bytes / min_block_size_bytes`，默认 2048。当前开发期只保留一个现行 `v1` layout，不维护旧布局或 `v2` 兼容层；header 固定 layout version/fingerprint、arena 几何、guard 几何、broker epoch 和 publication generation。

descriptor 是活动 allocation、identity 与恢复的持久化事实，保存固定长度 state、descriptor index/generation、offset/order/capacity、content length、lease identity、128-bit opaque owner token、deadline 和必要 checksum/flags。media type、shape、dtype、layout、pixel format、可变 owner 文本和业务 JSON 不进入 descriptor。

buddy free lists 只保存在 Broker 进程内，启动时从 descriptor 和 guard 状态重建。descriptor 已按最小 block 数配置，正常满载不应先耗尽 descriptor；提前耗尽属于 allocator 完整性错误。

## 引用与所有权

公开 `BufferRef.v1`/`FrameRef.v1` 是定位和图片表示契约。目标 locator 至少包含：

- arena id；
- descriptor index/generation；
- broker epoch；
- offset；
- content length；
- allocation capacity；
- shape、dtype、layout、pixel format、media type 和 readonly。

公开引用不承担权威 owner、deadline、guard 或清理授权。服务端所有权操作使用私有 `LeaseOwnershipReceipt`，额外保存 expected owner kind/id、deadline、guard identity、layout fingerprint 和完整 extent identity。

locator 不携带可由请求选择的 mmap/metadata/guard路径。SDK从受信 `buffers_root` 派生固定主 arena 文件，再从 allocator header发现真实容量、descriptor/guard几何、epoch和layout fingerprint；worker按服务端 arena registry解析。旧 `size`、`generation`、`slot_capacity_bytes` 和 `pool_name` 不进入新layout，分别使用 `content_length`、`descriptor_generation`、`allocation_capacity_bytes` 和 `arena_id`。展示用 `buffer_id` 不能作为回收凭据。

`arena_id` 在一次安装内跨 Broker owner唯一且稳定：主 Broker 强制使用 `local-buffer-main`，配置为其他值时启动校验直接失败；当前 inference daemon私有 owner使用 `inference-daemon-private`；未来多个私有 owner使用 `inference-daemon-private-<stable-daemon-id>`，不能使用 PID。同步 Workflow/Deployment/Trigger只解析主 arena id。

该规则只约束短期 LocalBuffer locator，不删除 `image-ref.v1` 已有的 ObjectStore 相对路径或受控本机绝对文件路径能力；文件输入与 mmap arena 是两种不同 transport kind。

generation、epoch、owner fence 和 guard 共同防止旧引用读取/释放新 lease。只按 buffer id、lease id、offset 或路径回收都不成立。

## guard 和 publication

每个 descriptor 固定分配：

- 1 个 publication guard；
- 1 个 writer guard；
- 64 个 reader guard。

producer 必须先取得 writer guard，再在 publication guard 内重验 descriptor/receipt，成功后才能创建 writable view。consumer 必须先取得一个 reader guard，再在 publication guard 内重验完整 locator，成功后才能创建 readonly view。

Broker 回收先在 publication guard 内发布 `REVOKING`，释放内部 guard 后按 writer、reader index升序非阻塞取得并持续持有全部外部 guards。任一 guard失败就释放本次已取得的guards并保持`REVOKING`；超过grace后进入`QUARANTINED`。只有持续持有全部外部guards时，Broker才能按`allocator lock -> publication guard`重验identity/state、提高generation、发布FREE并buddy merge；内部锁释放后才释放外部guards。禁止“探测guards为空、释放后再回收”的TOCTOU路径。Broker不能等待libzmq tracker，ZeroMQ tracker只由adapter进程的transport-lifetime registry管理。

Broker 同时需要内部锁时固定使用 `allocator lock -> publication guard`；SDK 不取得 allocator lock。任何路径都不能持有 publication/allocator lock等待外部 writer/reader guard，也不能使用 `publication guard -> allocator lock` 的反向顺序。

状态统一为：

```text
FREE -> WRITING -> ACTIVE

WRITING -> REVOKING -> FREE
                    -> QUARANTINED -> FREE

ACTIVE  -> REVOKING -> FREE
                    -> QUARANTINED -> FREE
```

## 生命周期

普通 lease：

```text
allocate -> write/commit -> reader guard -> read -> release
```

External SDK writer 的 publication 顺序更严格：取得 writer guard与publication guard重验后写入，销毁写 view并释放 writer guard，再发布 REQUEST；Broker 重新取得 writer guard并校验 receipt 后才执行 commit/ACTIVE publication。SDK 不能在仍持有 writer guard 时等待 Broker commit。

External Trigger 输入：

```text
workflow-trigger-write
  -> workflow-runtime
  -> workflow-trigger-response（仅当同一图片被选择为结果）
```

WorkflowRun 建立并取得真实 Runtime/executor permit 后、提交 worker 前执行第一次条件 owner transfer。Run 创建或 admission 失败按 writer receipt 回收；transfer 成功但 worker 提交失败按 Runtime receipt 回收。不能跳过第一次 transfer 后假设输入已属于 Run。

图片输出在 worker cleanup 前完成规范化与批量 handoff。所有可读取 RESPONSE在 publication前生成独立`response_ack_deadline_ns`；成功图片结果必须先以batch CAS把全部输出lease的owner和deadline同时切到response owner与同一ACK deadline，再发布descriptor RESPONSE。失败、deadline、busy和capacity RESPONSE同样有ACK deadline但不携带未完成handoff的图片。local-shared-memory SDK结果对象持有reader guard到`Dispose`/`DisposeAsync`，先使view失效并释放guard，再发布ACK。JSON-only或已复制到SDK自有bytes的结果可提前ACK。

## 图片格式边界

LocalBuffer 只保存 bytes 和生命周期：

- raw BGR24/Mono8 根据显式 shape/dtype/layout/pixel format 建立矩阵 view，不执行 codec decode；
- BMP/JPEG/PNG 等 encoded bytes 原样存储，首次矩阵消费时解码一次；
- Broker 不探测格式、不转换颜色、不编码图片；
- 直接图片输出继续使用 LocalBuffer；显式 Base64 节点产生受 mailbox/HTTP 容量约束的 JSON；
- 需要长期保留或跨重启的结果转存 ObjectStore/明确保存位置。

## frame channel

frame channel 是对一组 extent 的长期预留，不是另一个 pool。创建时必须提供 `frame_count` 和 `max_frame_content_length`，Broker在一个allocator临界区内为全部帧预留同一最小可容纳order；全部descriptor初始化后才发布channel，任一extent失败则回滚本次全部预留。帧写入保存实际content length，超过max立即拒绝；channel销毁时等待所有reader guard释放后再归还和合并extent。

## 64-bit 运行边界

.NET SDK 缓存 arena 文件 handle，普通 lease 按 descriptor generation、offset 和 capacity 建立精确 view并随结果生命周期释放；不能沿用固定 slot view cache。

backend、Broker、Workflow/deployment worker、独立运行时和仓库内 .NET SDK全部只支持64-bit；.NET SDK固定x64并在创建client时校验进程架构。项目不提供32-bit view配置、容量协商、错误分支或降级路径。SDK配置包只固定受信 `buffers_root`；不复制arena容量、内部路径、reader guard数量或图片上限，也不接受请求载荷指定任意文件。

## 满载语义

错误至少区分总容量不足、连续块不足、hard reserve不可用、单请求超限和allocator完整性错误。所有满载立即返回，不引入业务请求队列、重试、压缩、移动、临时文件或跨通道fallback。

Workflow Runtime gate、TriggerSource 单在途 permit、executor permit 和 LocalBuffer capacity 是独立资源，必须分别报告，不能按已部署 Runtime/TriggerSource 总数量静态预占图片内存。

## 健康与指标

health 至少报告：

- arena/general/huge reserve总容量，以及general/hard reserve各自的free容量；
- allocated capacity、published content、rounding waste；
- general/hard reserve分域的reserved-writing、active、frame reserved、REVOKING、QUARANTINED容量；hard reserve的frame reserved固定为0；
- 各 order free block 和最大连续块；
- 只按general free和largest general free计算的external fragmentation；
- active owner/lease、generation、deadline；
- total/contiguous/max/reserve/integrity分类失败；
- stale fence、guard wait、orphan/recovery 和 broker heartbeat。
- event router 的 active client channel、active forward thread、pending response route、closed channel、forward/drop error；短生命周期 client close 后 active/pending 必须回到调用前基线。

`rounding_waste_bytes` 只表示 block rounding，不混入 frame reserve、hard reserve 或 quarantine。

health 必须直接校验容量守恒：`general_total = general_free + general_reserved_writing + general_active + general_frame_reserved + general_revoking + general_quarantined`；hard reserve使用相同公式但没有frame bucket；`arena_total = general_total + huge_reserved_total`。`allocated_capacity`只是reserved-writing、active和frame-reserved的派生汇总，不能重复计数。守恒失败时服务降级并停止新allocation。

每个 `LocalBufferBrokerClient` 独占 supervisor 为其建立的 event channel。`close()` 必须发送无响应注销事件：同进程 route 同步移除，跨进程 route 由 forward thread 在处理关闭事件后移除并关闭队列。请求是同步的，关闭前不得存在未消费 response；router 停止时仍统一清理全部剩余 route。健康检查、Preview 和一次性控制调用不得因重复创建 client 让 active channel 单调增长。

## 启动、重启与迁移

- 每个 Broker root 只有一个有效 owner；
- Broker 重启提高 epoch，并从 descriptor/guard 重建状态；仍被旧进程持有的 extent 进入 REVOKING/QUARANTINED，不直接复用；
- layout fingerprint或文件大小不匹配时拒绝启动，不能自动 truncate；
- 固定 pool/slot 到 arena 是开发期一次性迁移：停止服务和 SDK、确认 guards 全部空闲、运行明确维护命令重建，再启动新代码；
- 新实现不保留固定 pool 双读、旧 BufferRef layout 或旧 SDK 映射兼容路径；
- 日志按日期轮转，异常包含 arena/descriptor/generation/owner/deadline，不记录图片内容。

## 明确边界

- 不支持跨主机共享内存；跨主机使用协议 adapter 或 ObjectStore。
- 不把短期 BufferRef 写入数据库、异步结果或长期业务资源。
- 不以 Base64、ZeroMQ、文件或 ObjectStore 作为 LocalBuffer 满载 fallback。
- 不把图片放入 inference/workflow mailbox 的结构化 JSON page chain。
- 不把 GPU IPC、RDMA 或恶意本地进程隔离写入当前 capability。

相关文档：[高性能图片数据面](image-data-plane.md)、[本机结构化消息通道 ADR](../../decisions/ADR-0009-local-message-channel.md)、[本机共享内存 Workflow Trigger ADR](../../decisions/ADR-0007-local-shared-memory-workflow-trigger.md)、[LocalBuffer 固定 arena ADR](../../decisions/ADR-0008-local-buffer-fixed-arena-allocation.md)、[共享内存数据面可靠性实施基线](../../development/shared-memory-data-plane-reliability-implementation.md)。
