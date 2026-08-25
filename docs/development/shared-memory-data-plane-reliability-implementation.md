# 共享内存数据面可靠性实施基线

## 状态与职责

状态：**已规划并完成代码事实审计，可以按本文顺序开始实现；所有阶段当前均未标记完成。**

本文是下一阶段本地共享内存修复与 LocalBuffer 重构的唯一实施顺序，覆盖：

- Workflow Trigger mailbox 共享 overflow page 并发、deadline、取消和终态错误；
- local-shared-memory Trigger 的配置、health、前端入口与故障回收；
- LocalBuffer 从固定分辨率 pool/slot 迁移到固定总容量 arena + buddy allocator；
- Python/.NET SDK、BufferRef、frame channel、配置、已有开发数据和验证门禁的原子迁移。

[ADR-0007](../decisions/ADR-0007-local-shared-memory-workflow-trigger.md) 继续定义 Trigger 产品边界，[ADR-0008](../decisions/ADR-0008-local-buffer-fixed-arena-allocation.md) 定义 LocalBuffer 分配模型。旧的[本机共享内存 Trigger 实施基线](local-shared-memory-trigger-implementation.md)保留已交付协议细节和历史性能证据，但不再作为下一阶段完成状态来源；与本文冲突时以本文和最新 ADR 为准。

## 审计结论

### 已确认的代码事实

| 项目 | 当前实现 | 结论 |
| --- | --- | --- |
| Trigger overflow page | descriptor 使用独立 guard，共享 page pool 分配/释放没有进程内全局 allocator lock | 真实并发竞态，P0 |
| 请求 deadline | PREPARE/写图后 Runtime invoke 再收到完整 `reply_timeout_seconds` | 总预算被重置，P0 |
| response ACK | output lease 通常沿用请求 deadline，没有独立 ACK 读取期限 | 生命周期缺口，P0 |
| PROCESSING 取消 | descriptor 有 `cancel_requested`，supervisor 未把它完整传播到当前 Workflow Run | 真实缺口，P0 |
| 终态错误 | schema 已区分 `deadline_exceeded` 与 `cancelled`，sweep 路径仍统一发布 cancelled | 诊断语义错误，P1 |
| timeout 默认值 | contract/数据库允许 `None`，不同 adapter 又使用 5/30/300 秒等分散默认 | 可能触发空值运算且有多个事实源，P1 |
| health | mailbox/adapter 主要返回全局计数，不能可靠说明单个 TriggerSource 的 timeout/错误 | 真实可观测性缺口，P1 |
| 前端 | 后端已有 local-shared-memory，创建页仍缺少正式模板 | 管理链路未闭环，P1 |
| LocalBuffer | 固定 `image-4k/image-1080p/image-640x640` pool/slot，默认进入 `image-4k` | 与目标容量模型冲突，P0 重构 |
| BufferRef | 没有 arena descriptor locator 与 allocation capacity | 新 allocator 前置契约缺口 |
| .NET mapping | 按 path、epoch、offset 缓存固定 slot capacity view | 不能直接适配动态 extent |
| frame channel | 只声明 frame 数量，不声明每帧最大长度 | 不能确定预留 order |

现有协议、owner handoff、reader/writer guard、统一 Runtime gate、LocalBuffer 图片输出和 ZeroMQ transport-lifetime registry 的主体设计保留。此次不是重写 Workflow 引擎或 ZeroMQ Trigger。

## 总体实施原则

1. 先修复当前 mailbox 正确性，再替换 LocalBuffer allocator；不能在两个不稳定资源层上同时调试业务 soak。
2. mailbox page pool 与 LocalBuffer arena 是两个不同问题：前者传结构化 JSON，后者传连续图片 bytes，不能共用 page allocator 或状态机。
3. 全部满载路径立即返回结构化错误，不排队、不重试、不 fallback。
4. 公开引用只负责定位和表示，权威 owner/deadline/guard 始终由私有 receipt 保存。
5. publication 前写完数据和 identity，publication 后内容不可变；consumer 只读取已发布状态。
6. 外部 SDK 可以写受限 view，但不能修改 descriptor、owner、deadline 或 allocator 元数据。
7. 当前处于开发阶段，协议和配置一次性原地升级；后端、前端、数据库、仓库内 SDK、fixture 和开发数据同批迁移，删除旧实现与双读代码。
8. 所有正式图片数据面 mmap、guard 和 owner lock 位于 `data/buffers/`；训练遥测不迁移。

## 目标拓扑与唯一容量事实

```text
.NET SDK / backend producer
  -> LocalBufferBroker PREPARE(content_length)
  -> arena buddy allocation + descriptor receipt
  -> writer guard + descriptor revalidation
  -> exact mmap view write + commit
  -> BufferRef.v1
  -> Workflow Runtime / deployment / output handoff

Workflow Trigger 参数与结构化结果
  -> data/buffers/workflow-trigger/workflow-trigger-main.mmap
  -> 128 descriptors + inline 512 KiB + fixed overflow page pool
```

资源事实分开维护：

- LocalBufferBroker 是图片 arena 容量、extent、lease 和 guard 的唯一事实源；
- Workflow Trigger mailbox owner 是 descriptor/overflow page 的唯一写入 owner；
- Workflow Runtime handle 的 execution gate 是执行并发的唯一事实源；
- 每个 TriggerSource 的单在途 permit 只限制该 source，不限制其他 source；
- executor worker/submit permit 是进程内有界提交容量，不形成隐式队列。

## 第一部分：修复现有 Workflow Trigger mailbox

### 1. 共享 overflow page allocator

新增 mailbox server 进程内唯一 `_page_allocator_lock`。调用顺序固定为：

```text
descriptor guard
  -> page allocator lock
  -> 选择并写入 page identity/state reservation
  -> 释放 page allocator lock
  -> 写 page body/size/CRC/next
  -> 最后发布 page READY 与 descriptor RESPONSE
```

释放时使用相同顺序；任何代码不得先持有 page allocator lock 再等待 descriptor guard。allocator lock 只保护 page 选择、identity reservation、rollback 和 free，不覆盖 JSON 序列化、压缩或 page body 复制。mailbox 仍只有一个 server owner process，因此不新增跨进程 page lock 文件。

分配失败后不重新执行 Workflow、不切换控制队列。错误响应写 descriptor inline 区；page pool 满载时小型 inline response 仍必须工作。

### 2. 一个请求总 deadline

backend-service 在 PREPARE 接收 SDK 相对 timeout 后，用自身 monotonic clock 生成唯一权威 `request_deadline_ns`。Python 与 .NET 不交换可直接比较的 monotonic absolute value；SDK 只用自己的本地 timeout 约束等待。PREPARE、External lease 写入、REQUEST、Runtime admission、Workflow 执行和 output handoff 都消费 backend 的同一预算。每个后端阶段只接收 `request_deadline_ns - monotonic_now_ns` 的剩余值，禁止重新传入完整 timeout。

同步 TriggerSource 创建/更新时必须解析并持久化具体正数 `reply_timeout_seconds`；现有 sync source 的空值通过数据迁移填入服务端唯一默认值。新增唯一配置 `local_shared_trigger_default_reply_timeout_seconds=30.0`、`local_shared_trigger_response_ack_timeout_seconds=30.0` 和 `local_shared_trigger_cancellation_grace_seconds=2.0`，不再由 adapter 散落硬编码 5/30/300 秒。响应计划 fingerprint 包含解析后的 request timeout 与固定 ACK timeout，Runtime 不能读取 adapter 私有默认值。异步或无回复 source 可以保持其独立契约，但不能进入 local-shared-memory 同步热路径。

### 3. 独立 response ACK deadline

descriptor v1 的保留字段原地加入 `response_ack_deadline_ns` 和必要的响应生命周期字段。Workflow 成功且输出 handoff 完成后才创建 ACK deadline：

```text
request deadline 约束“服务何时完成响应”
response ACK deadline 约束“SDK 可持有零复制结果多久”
Broker cleanup grace 约束“guard 失联后何时进入回收/隔离”
```

ACK timeout 由服务配置固定并写入 response plan；SDK 不能延长。零复制结果对象在 Dispose 前持有 reader guard，Dispose 先使 view 失效并释放 guard，再 ACK。JSON-only 或已复制到 SDK 自有 bytes 的结果可以提前 ACK。

### 4. PROCESSING 取消传播

client timeout/主动取消先在 descriptor guard 内发布 `cancel_requested`。supervisor 观察后调用当前 run 的 run-scoped cancellation primitive；worker 在节点/batch 安全点停止，不再提交后续节点，finally 仍执行 output/lease cleanup。

在有界 cancellation grace 内未停止时，只重启或隔离当前 Runtime worker instance，不能杀死 backend-service、Broker 或无关 Runtime。旧 completion 必须被 request identity、Runtime generation 和 snapshot fingerprint 拒绝，不能覆盖新请求终态。

### 5. 终态与错误码

至少区分：

- `deadline_exceeded`：权威 request deadline 到期；
- `cancelled`：调用方显式取消；
- `workflow_runtime_busy`：真实 Runtime gate 满载；
- `trigger_executor_busy`：有界 executor 无可用 permit；
- `trigger_response_capacity_exhausted`：mailbox page pool 不足；
- `local_buffer_capacity_exhausted` / `local_buffer_contiguous_capacity_exhausted`：图片 arena 容量问题；
- `identity_mismatch` / `checksum_mismatch` / `protocol_error`：协议完整性问题。

超时、取消和满载不能混为同一错误，也不能以 HTTP 200/成功 result 隐藏。

### 6. per-source health

全局 mailbox health 与 TriggerSource health 分开。每个 source 至少记录 active request、last state/error、request timeout count、client cancel count、busy reject count、capacity reject count、最近总耗时和最近成功时间；只保存数值摘要，不保存图片、参数或本地路径。health entry 只为已配置或当前 active source 保留，source 删除后同步清理，禁止以 request id 建立无界 metrics label。

## 第二部分：LocalBuffer 固定 arena + buddy allocator

### 1. 配置与文件布局

目标配置只保留一个主 arena 几何：

```json
{
  "local_buffer_broker": {
    "enabled": true,
    "root_dir": "./data/buffers",
    "arena_id": "main",
    "arena_size_bytes": 2147483648,
    "min_block_size_bytes": 1048576,
    "max_allocation_bytes": 1073741824,
    "huge_reserve_bytes": 0,
    "reader_guard_slots": 64,
    "max_32bit_view_bytes": 268435456,
    "flush_on_write": false,
    "startup_timeout_seconds": 60.0,
    "takeover_existing_process": true,
    "takeover_timeout_seconds": 10.0,
    "request_timeout_seconds": 5.0,
    "shutdown_timeout_seconds": 5.0,
    "expire_interval_seconds": 5.0,
    "revocation_grace_seconds": 5.0
  }
}
```

删除 `LocalBufferBrokerPoolSettings`、`default_pool_name`、`pools`、`slot_size_bytes`、`slot_count`、resolution preset 和调用方 `pool_name`。测试可使用较小但同几何规则的 arena，不创建另一套 test allocator。

正式文件：

```text
data/buffers/local-buffer/arena-main.mmap
data/buffers/local-buffer/allocator-main.mmap
data/buffers/local-buffer/arena-main.guard
data/buffers/local-buffer/arena-main.owner.lock
```

`workflow-trigger/`、`inference-control/` 和 `inference-daemon-private/` 保持独立职责。`root_dir` 不能改成 `./data/buffers/local-buffer`，否则其他图片数据面路径派生会漂移。

backend-service/Broker 正式进程要求 64-bit。启动 preflight 必须校验整数寻址、arena/metadata 文件长度、buffers root 可写空间和 layout fingerprint；2 GiB 是固定逻辑 arena/file 容量，不表示启动时把全部页面常驻锁定到物理 RAM。文件支持 mmap 仍可能被操作系统分页或异步写回，`flush_on_write=false` 只禁止主动同步 flush。默认不预触碰整个 arena，性能门禁必须同时观察首次触页和稳态数据。

### 2. allocator 几何和 hard reserve

buddy allocator 使用 1 MiB 最小块和 2 的幂 order。分配依据只有精确 `content_length`；media type、分辨率、BGR24/encoded 不参与 allocator 选择。

几何校验固定为：min block 是2的幂；arena/min与max/min都是2的幂；max不超过arena；hard reserve只允许0或max，非零reserve固定在arena高地址端且剩余general区仍是完整buddy root。启动时不满足任一条件都直接失败。

默认不硬保留 Huge。现场若必须保证 1 GiB 请求，显式设置 `huge_reserve_bytes=1 GiB`；reserve 使用固定高地址区域和独立 free root，只接受 rounded capacity 等于 reserve 大小的请求，普通 lease、较小请求和 frame channel 不借用。没有 reserve 时，1 GiB 在连续空间存在时成功，因碎片不足时立即返回明确错误。

### 3. persistent descriptor 与内存 free list

allocator metadata header 固定保存 magic、layout version、layout fingerprint、arena size、min/max order、descriptor count、guard layout、broker epoch 和 publication generation。descriptor count 默认 2048。

descriptor 保存固定二进制字段，包括128-bit opaque owner token，不保存可变 owner 文本或 JSON。buddy free list、order buckets 和统计索引由 Broker 启动时从 descriptor 重建；allocator metadata 不保存进程地址、链表指针或 Python 对象。

所有 metadata 状态更新遵循“写字段、保证进程间可见、最后发布 state/generation”的顺序。`flush_on_write=false` 只表示不主动同步刷盘，不改变跨进程 publication 和内存可见性要求。

### 4. locator、receipt 与协议原子迁移

`BufferRef.v1`、Workflow Trigger allocation、frame ref、私有 receipt 和 Python/.NET generated contract 同批增加：arena id、descriptor index/generation、broker epoch、offset、content length、allocation capacity。保留图片 shape/dtype/layout/pixel format/media type；这些表示字段不进入 allocator descriptor。

公开 locator 不增加权威 owner/deadline。服务端每次 transfer/release/revoke 都使用私有 receipt，并同时校验 arena、descriptor、generation、epoch、owner、deadline、offset 和 capacity。

协议原子迁移时删除 locator/allocation 中可由请求选择的 `path`，SDK/worker按 `arena_id` 从固定配置包解析 arena、metadata和guard路径；把旧 `size`、`generation`、`slot_capacity_bytes`、`pool_name` 替换为 `content_length`、`descriptor_generation`、`allocation_capacity_bytes`、`arena_id`。`buffer_id` 若因日志/追踪保留也只是展示字段，不参与权威回收；不写双读或字段别名。

这一删除只针对 buffer/frame locator，不改变 storage `image-ref.v1` 对 ObjectStore 相对路径和受控本机绝对文件路径的支持。

### 5. guard 和锁顺序

SDK writer：

```text
writer guard
  -> publication guard
  -> descriptor/receipt/layout 重新校验
  -> 释放 publication guard
  -> 创建精确 writable view并写入
  -> 销毁 view
  -> 释放 writer guard
  -> 发布 REQUEST
  -> Broker 重新取得 writer guard并校验 receipt
  -> Broker commit、ACTIVE publication和owner transfer
```

SDK/consumer reader：

```text
一个空闲 reader guard
  -> publication guard
  -> descriptor/BufferRef/layout 重新校验
  -> 释放 publication guard
  -> 创建精确 readonly view并读取
  -> 销毁 view
  -> 释放 reader guard
```

Broker reclaim：

```text
publication guard 内发布 REVOKING
  -> 释放 publication guard
  -> 非阻塞检查 writer 和全部 reader guards
  -> 若仍占用，保持 REVOKING，超过 grace 进入 QUARANTINED
  -> guards 全空闲后取得 allocator lock + publication guard
  -> 再次校验 identity/state
  -> generation++、FREE、buddy merge
```

禁止持有 publication guard 或 allocator lock 等待外部 guard，禁止 allocator lock 与 SDK guard 形成反向顺序。

Broker 在同一操作中需要两个内部锁时，唯一顺序是 `allocator lock -> publication guard`；SDK 永远不取得 allocator lock。初次发布 REVOKING 只需要 publication guard，释放后才检查外部 guards。代码和测试中不得出现 `publication guard -> allocator lock` 的反向路径。

### 6. 重启、layout 和 quarantine

Broker owner lock 仍保证每个 root 单 owner。重启更新 broker epoch，先根据 descriptor 和 OS guards 重建状态：无 guard 的旧 lease可回收；仍有 writer/reader 的 extent进入 REVOKING/QUARANTINED，不得复用。SDK 在取得 guard后的 descriptor revalidation 会拒绝重启前的 allocation。

layout fingerprint 不一致、arena 文件大小不一致或旧固定 pool 文件存在时，新服务拒绝自动 truncate。开发期维护命令必须在服务停止且 guard 全空闲后显式重建；正式启动不做在线转换、双 layout 读取或隐式删除。

### 7. Python/.NET mmap view

Python direct reader/writer 从配置允许的 arena id/path解析 locator，校验 descriptor range 后只映射/切片当前 extent。不得继续按固定 slot 对齐校验。

.NET 缓存 arena `FileStream`/`MemoryMappedFile` handle；普通 lease 的 view key 至少包含 arena、epoch、descriptor generation、offset 和 capacity，view 随 lease/结果对象释放。frame channel 仅对稳定预留 extent复用 view。32-bit 进程只在单 view 不超过配置上限时支持，超限在 PREPARE/写入前失败；64-bit 是超大图正式要求。

### 8. frame channel

API 改为 `create_frame_channel(stream_id, frame_count, max_frame_content_length)`。创建时一次性分配并固定多个等 order extent；每次 frame 写入仍使用实际 content length，超过 max 明确拒绝。销毁 channel 后只有在所有 reader guard 释放后才能 buddy merge。

## 容量、指标和健康

必须分别暴露：

- `arena_total_bytes`、`general_total_bytes`、`huge_reserved_capacity_bytes`；
- `allocated_capacity_bytes`、`published_content_bytes`；
- `rounding_waste_bytes = allocation_capacity - content_length`；
- `frame_reserved_capacity_bytes`；
- `revoking_capacity_bytes`、`quarantined_capacity_bytes`；
- 每个 order 的 free block 数和最大连续可分配块；
- external fragmentation：总 free > 0 时 `1 - largest_free_block / total_free`；
- allocation failure 按 total/contiguous/max/reserve/32-bit/integrity 分类；
- stale epoch/generation/owner fence、guard wait/revoke/quarantine 和 restart recovery 计数。

不要把 frame reserve、hard reserve 或 quarantine 全部计入 rounding waste；否则指标无法解释实际内部碎片。

## 原子迁移与删除清单

同一提交链完成：

1. binary schema、Python codegen、.NET generated contract 和 fixture；
2. `BufferRef.v1`、allocation、receipt、frame channel API；
3. Broker settings 与所有 config profile；
4. Broker、client、direct reader/writer、Workflow/Deployment/Trigger 调用点；
5. .NET SDK mapping、writer、reader、SDK config package；
6. 前端 LocalBuffer/TriggerSource 表单与 health；
7. 测试 fixture、Postman/示例、已有开发数据库/TriggerSource 数据；
8. 架构、部署、SDK 和运维文档。

最终删除：固定 `MmapBufferPool` 分配路径、固定 pool preset、`pool_name` 传输字段、resolution-based test assumptions、旧 mapping cache key、旧 frame channel 签名、双 layout/双 contract 解析。低层 byte-range guard、owner lock、CRC 和 path containment 等中立原语继续复用。

阶段4至阶段8的新 allocator在隔离测试入口中构建，不增加可部署的 `allocator_mode` 开关。阶段9才原子切换全部运行时调用点并删除固定pool路径；任一正式提交状态都不能允许同一服务同时接受两种BufferRef/layout。

## 完整实施顺序

### 阶段 0：冻结基线与回归证据

- 固定本文、ADR-0007、ADR-0008 和 binary schema 变更范围。
- 记录当前固定 pool 配置、API/SDK fixture、local-shared/ZeroMQ/HTTP 真实性能和资源基线。
- 用隔离probe稳定复现并记录并发page分配、总deadline、PROCESSING cancel和null timeout问题；对应回归测试在阶段1/2与修复一起提交，默认门禁不保留失败测试。

门禁：能够稳定复现已确认缺口；无代码行为变更。

### 阶段 1：mailbox page allocator 正确性

- 增加唯一 page allocator lock、reserve/rollback/release。
- page body 移出 allocator 临界区，固定 publication 顺序和 lock-order 测试。
- 增加 page pool 满载时 inline response 仍可用门禁。

门禁：16 并发混合 inline/1/8/16/32 MiB、碎片化 chain、2,000 次四进程压力无重复 page、泄漏或 owner 失效。

### 阶段 2：deadline、ACK、取消和终态

- schema 原地加入 ACK deadline；统一 sync timeout 解析和数据迁移。
- 全链路传递单个 absolute request deadline和剩余预算。
- 传播 run-scoped cancel；实现 cancellation grace和旧 completion fencing。
- 分开 deadline/cancel/busy/capacity错误。

门禁：在 PREPARE、WRITING、REQUEST、PROCESSING、RESPONSE、ACK 各点超时/取消均得到正确终态，资源回到基线。

### 阶段 3：Trigger health 与前端闭环

- 分离 global mailbox health和 per-source health。
- 前端新增 local-shared-memory 创建/编辑入口，只显示可配置项，不暴露内部 mmap 路径。
- 页面显示 request/ACK timeout、busy/capacity/cancel/timeout计数。

门禁：API、前端 typecheck/测试、真实创建-enable-disable-invoke-delete 链通过。

### 阶段 4：arena binary contract 与纯 buddy allocator

- 定义 header、descriptor、guard range、layout fingerprint。
- 实现不依赖 mmap 的纯 buddy allocator，支持 split、merge、hard reserve、最大连续块和分类错误。
- 运行至少 100,000 次随机 allocate/free 的 property/invariant 测试。

门禁：无重叠 extent；容量守恒；释放后完全合并；reserve不被普通请求借用；descriptor上限不会先于容量耗尽。

### 阶段 5：persistent descriptor、guard 与恢复

- 建立 arena/allocator/guard/owner 文件和 publication 规则。
- 实现 writer/reader/publication guard 与规定锁顺序。
- 启动从 descriptor重建 free list；实现 epoch、REVOKING、QUARANTINED和条件回收。
- 加入64-bit、文件长度、可写空间、layout fingerprint和首次触页/稳态诊断。

门禁：Broker 在 allocation reply、guard acquire、写入、commit、read 和 reclaim 各点退出；旧 SDK 不能写入新 generation；layout 不匹配拒绝启动且不破坏文件。

### 阶段 6：普通 lease、External lease 与批量 handoff

- 普通 allocate/commit/acquire/release 统一迁移到 extent。
- External PREPARE/revalidate/commit、receipt CAS transfer/release、batch output handoff 统一迁移。
- 保留 raw/encoded 表示和 output 生命周期，不改变 Workflow 公开语义。

门禁：普通、External、输入转 Runtime、输入直接作为输出、批量输出全成功/全失败和 foreign ref normalization 均通过。

### 阶段 7：Python reader/writer 与 .NET SDK

- 原地升级 BufferRef/allocation/fixture。
- Python direct reader/writer 改为 descriptor/extent校验。
- .NET 改为 arena handle cache + exact view，并加入32-bit明确限制。
- writer/reader均在 guard后重验 descriptor。

门禁：Python/.NET逐字节 fixture一致；BGR24/Mono8/正负 stride/BMP/JPEG/PNG/Base64准确；raw链路无 decode和整图中间副本；encoded只首次消费解码一次。

### 阶段 8：frame channel 与所有调用点

- API 增加 frame count/max frame length并预留 extent。
- 迁移 inference、Workflow、Preview、ZeroMQ、local-shared和异步暂存调用点。
- 删除调用方 pool选择。

门禁：ring wrap、旧 frame generation拒绝、channel销毁等待reader、不同大小帧复用和超限拒绝通过。

### 阶段 9：配置、数据迁移和旧实现删除

- 更新源码 config/profile模板、SDK package、前端、fixture、Postman示例、现有TriggerSource JSON开发数据和维护命令；不手工修改 `release/<profile-id>/app/`。
- 停止服务后验证 guard，重建开发 arena。
- 删除固定 pool/slot实现和双读代码。

门禁：`rg` 不再出现运行时 `default_pool_name`、`LocalBufferBrokerPoolSettings`、分辨率 preset或 Trigger `pool_name`；旧 layout启动明确失败；新安装一步启动。

### 阶段 10：故障、容量、性能与业务 soak

- 执行 allocator碎片化、满载、restart、SDK/backend/worker异常退出、deadline/cancel/ACK和持续运行门禁。
- 使用开发环境真实模型、Deployment、Workflow Runtime、ZeroMQ/local-shared Trigger和真实图片。
- 重新 assemble release 后运行同一 contract/smoke；不手工修改发行目录。

门禁全部通过后才能把阶段和 ADR 状态改为已实现。

## 必须通过的验证矩阵

### 正确性与恢复

- 1 byte、1 MiB边界前后、2/4/8/64/512 MiB、1 GiB分配；超上限明确失败。
- 100,000 次随机分配/释放后容量完全回到基线。
- 多线程/多进程同时 allocate/commit/read/release无重叠和重复释放。
- Broker 重启时 SDK 分别位于 allocation reply前后、guard前后、写入中、commit前后和读取中。
- 旧 epoch/generation/owner、错误 offset/capacity、越界 view和损坏 descriptor全部拒绝。
- reader/writer挂起时进入REVOKING/QUARANTINED，其他extent继续工作；guard释放后恢复。
- hard reserve开启/关闭语义与health一致。
- frame channel、普通 lease、External input、output lease并发混合无容量泄漏。

### Trigger mailbox

- 512 KiB边界前后、1/8/16/32 MiB结构化结果。
- 16并发混合小响应和多页响应；page pool碎片化后非连续chain可用。
- client在请求写入、PROCESSING、response读取和ACK各阶段退出。
- daemon在多页写入中退出重启；CRC、owner/generation、page loop/越界损坏明确隔离当前descriptor。
- page pool满载时inline请求成功；满载不重跑Workflow。
- request deadline只消费一次；ACK deadline独立；cancel传播到当前run。

### 图片与业务准确率

- raw BGR24/Mono8与基准矩阵逐字节一致；BMP/PNG/JPEG解码与现有OpenCV基准一致。
- 1080p、4K、20MP BGR24和57.1 MiB真实BMP覆盖HTTP Base64、ZeroMQ和local-shared-memory。
- 同一Workflow保留两个并行分支、24次真实推理和双Deployment实例；分类/检测/分割/姿态/OBB输出不得因allocator变化而改变。
- 图片返回在Dispose前有效，Dispose后view失效并只ACK一次。

### 性能与长期稳定

- allocator allocate/commit/release P95 相对固定slot基线不得回退超过 `max(1 ms, 10%)`。
- 1080p local-shared-memory数据面P95不得回退超过10%。
- 20MP BGR24 local-shared-memory **数据面** P50/P95继续至少比同机ZeroMQ数据面降低40%，P99不得高于ZeroMQ。数据面按两个入口各自的SDK总耗时减去服务端同一Workflow Runtime invoke公共耗时计算；端到端分位数另行报告，不能混用平均值相减。
- 同一开发环境、模型、图片、warmup和并发下，local-shared-memory端到端P95/P99相对重构前自身基线不得回退超过 `max(5 ms, 10%)`。
- raw BGR24 backend路径不执行encode/decode，不产生整图Python `bytes`副本；调用方直写SDK Span时不建立整张中间数组。
- 每次实现门禁的10,000次混合lease/Trigger soak后，active/WRITING/REVOKING/QUARANTINED、descriptor/page、Runtime token全部回到基线；宣称生产/发行验证完成前还必须执行24小时持续soak并满足同一资源回收标准。
- 无ERROR/WARNING/Traceback、重复释放、所有权失效、静默串图、CRC错误或不受控mmap增长。

## 明确不做

- 不把图片存入 Workflow Trigger mailbox page chain。
- 不为LocalBuffer图片实现非连续extent或消费端拼接。
- 不做在线compaction、运行时mmap扩容、dedicated临时mmap或文件fallback。
- 不按已部署Runtime/TriggerSource总数量静态预占图片容量。
- 不建立等待队列、自动重试或跨通道fallback。
- 不让调用方选择size class/pool，也不按分辨率命名资源。
- 不让SDK修改allocator metadata、descriptor state、owner或deadline。
- 不把training telemetry迁入`data/buffers/`。
- 不在新实现中保留固定pool兼容层、旧字段双读或旧binary layout。

## 开始实现判定

本文已经把当前缺口、目标架构、依赖顺序、锁顺序、生命周期、迁移删除项和门禁固定到可实施粒度。下一步可以从阶段0开始代码实现。任何阶段只有在本阶段定向测试、相关回归、资源回基线检查和文档核对全部通过后才能标记完成，再进入下一阶段。
