# ADR-0008：LocalBuffer 固定总容量与动态分配

## 状态

已接受并完成阶段0–9实现。固定 arena、buddy allocator、持久 descriptor、guard/reclaim、BufferRef、Python/.NET SDK、frame channel、配置和正式调用点已原子迁移；阶段10源码开发环境的故障、容量、完整回归、真实图片传输与有界 soak 已通过，发行重组后的10,000次和24小时持续认证仍按[共享内存数据面可靠性实施基线](../development/shared-memory-data-plane-reliability-implementation.md)执行。本文关于 LocalBuffer 连续图片 allocator 的决策继续有效；结构化 mailbox 与训练遥测的后续目录和公共 engine 收敛由 [ADR-0009](ADR-0009-local-message-channel.md)更新。

## 背景

迁移前 LocalBufferBroker 按 `image-640x640`、`image-1080p`、`image-4k` 等名称创建固定大小、固定数量的 slot。该实现能提供简单的连续 mmap 区域，但存在以下结构性问题：

- 未显式指定 `pool_name` 时进入默认大图 pool，小图也会占用完整大 slot；
- 调用方必须理解服务端 pool 配置，图片尺寸与资源配置耦合；
- pool 之间的空闲容量不能互相使用；
- 单 lease 不能超过最大固定 slot，无法覆盖极端大幅面线扫图；
- 增加更多分辨率 pool 只会继续放大配置、容量浪费和维护成本。

LocalBuffer 承担图片 bytes 和短期生命周期，不承担图片格式识别、解码、业务排队或持久化。分配策略应只依据精确 `content_length`，不依据分辨率名称或 media type。

主 LocalBuffer 是 HTTP/ZeroMQ/local-shared-memory 输入进入同步处理后的统一图片数据面，也承载 Workflow 节点间图片、同步 Deployment 输入与结果图、Preview运行期图片和节点新生成的图片。跨边界公开值使用 BufferRef/FrameRef；节点内部一次调用内的临时矩阵和模型tensor不属于公开传输契约。异步跨重启与长期保存仍使用ObjectStore。

## 决策

### 1. 每个 Broker owner 使用一个固定容量 arena

backend-service 主 LocalBuffer 默认使用一个 2 GiB、启动时固定大小的 arena。inference daemon 私有异步暂存区仍属于独立 Broker owner，可以使用相同文件格式和分配器，但有独立容量；不同 owner 不共享 allocator 状态。

默认几何参数：

| 参数 | 默认值 | 含义 |
| --- | ---: | --- |
| `arena_id` | `local-buffer-main` | allocation/引用使用、跨 Broker owner 唯一的稳定 arena 标识 |
| `arena_size_bytes` | 2 GiB | 主图片 arena 总容量 |
| `min_block_size_bytes` | 1 MiB | buddy allocator 最小块 |
| `max_allocation_bytes` | 1 GiB | 单次连续分配上限 |
| `huge_reserve_bytes` | 0 | 默认不为超大图硬保留容量 |
| `reader_guard_slots` | 64 | 每个 descriptor 的并发只读 guard 数 |
| `flush_on_write` | `false` | 临时图片写入不主动同步 flush |

`min_block_size_bytes` 必须是 2 的幂；`arena_size_bytes / min_block_size_bytes` 与 `max_allocation_bytes / min_block_size_bytes` 必须是 2 的幂，且 max 不得超过 arena。当前 hard reserve 为保持单一简单语义，只允许 `0` 或 `max_allocation_bytes`；非零 reserve 固定在 arena 高地址端。general 区由一个或多个大小等于 `max_allocation_bytes` 的顶级 buddy root 组成，不能跨 root 合并。配置不合法时启动失败，不能静默修正。

### 2. size class 是 allocator order，不是固定 pool

分配器按最小可容纳 `content_length` 的 2 次幂 block 分配，默认形成 1、2、4、8、16、32、64、128、256、512、1024 MiB 的 order。Small、Medium、Large、Huge 只用于状态页汇总，不是独立文件、独立容量池或调用参数。

`content_length` 与 `allocation_capacity_bytes` 必须分开保存。前者限定有效数据和读取范围，后者用于回收、容量核算和内部碎片指标。

典型 BGR24 分配如下：

| 输入 | 约有效长度 | 分配容量 |
| --- | ---: | ---: |
| 640 × 640 | 1.17 MiB | 2 MiB |
| 1024 × 1024 | 3 MiB | 4 MiB |
| 1920 × 1080 | 5.93 MiB | 8 MiB |
| 3840 × 2160 | 23.73 MiB | 32 MiB |
| 5000 × 4000 | 57.22 MiB | 64 MiB |
| 1 GiB 线扫图 | 1 GiB | 1 GiB |

### 3. 图片 lease 必须保持单段连续内存

普通图片、raw BGR24 和 encoded bytes 都使用一个连续 extent。LocalBuffer 不采用 inference/workflow mailbox 的 page chain，因为 OpenCV、NumPy、.NET `Span` 和模型预处理需要连续视图；把图片拆成页会在消费边界重新拼接并引入整图复制。

1 GiB 分配在默认 `huge_reserve_bytes=0` 时属于“容量支持但不保证任意碎片状态下成功”。若现场必须保证随时可分配 1 GiB，必须显式配置 1 GiB hard reserve。hard reserve 是一个独立 buddy root，只接受 rounded capacity 等于该 reserve 大小的请求；普通 lease、较小请求和 frame channel 不能借用。因此 2 GiB arena 开启 1 GiB reserve 后，普通工作负载只剩 1 GiB。服务不得通过压缩、移动活动 block、临时文件或等待队列掩盖连续空间不足。

general 区采用确定性的低地址聚集策略：从最小可容纳 order 向上查找，选择最低 offset 的 free block；split 时继续使用低地址 child，把高地址 child 放回按 offset 升序维护的 free list。该策略优先保留高地址顶级 root 的大连续 extent，使相同请求序列得到一致分配结果和可复现碎片指标。

### 4. 元数据持久化，free list 可重建

arena 数据与 allocator 元数据分文件保存。descriptor 数量固定为 `arena_size_bytes / min_block_size_bytes`，默认 2048；descriptor 是分配状态、identity 和恢复的唯一持久化事实。buddy free list 只存在于 Broker 进程内，启动时从通过 guard/epoch 校验的 descriptor 状态重建，不持久化链表指针。

descriptor 保存固定长度字段：state、arena id、descriptor index/generation、broker epoch、offset、order/capacity、content length、lease identity、128-bit opaque owner token、deadline、publication generation、校验与必要 flags。可变 owner 字符串、media metadata 和业务参数不能写入固定 descriptor 表。

### 5. guard 与 identity 共同防止旧进程破坏新 lease

每个 descriptor 固定拥有一个 publication guard、一个 writer guard 和 64 个 reader guard byte ranges。公开 `BufferRef.v1` 只负责定位和数据表示；权威 owner、deadline、guard 和回收权限只存在于服务端私有 `LeaseOwnershipReceipt`。

外部 SDK 取得 allocation 后必须先取得 writer guard，再在 publication guard 内重新校验 broker epoch、descriptor generation、lease、owner、offset、capacity 和 deadline，成功后才创建 writable view。Broker 在 WRITING/ACTIVE 回收时先发布 `REVOKING`，随后按 writer、reader index 升序非阻塞取得并持续持有全部外部 guards；取得成功后才进入 allocator lock 与 publication guard 完成最终 identity/state 校验、generation 提升、FREE publication 和 buddy merge，最后释放外部 guards。无法取得全部 guards 时释放本次已取得的 guards并保持 `REVOKING`，超过 grace 后进入 `QUARANTINED`。Broker 重启不能让旧 SDK 在新 generation 上继续写入。

### 6. BufferRef 与 SDK 映射按 extent 工作

开发期未冻结的 `BufferRef.v1`、Workflow Trigger allocation、Python reader/writer 和仓库内 .NET SDK 在同一提交链中原地升级。locator 至少包含：

- `arena_id`；
- `descriptor_index`；
- `descriptor_generation`；
- `broker_epoch`；
- `offset`；
- `content_length`；
- `allocation_capacity_bytes`。

服务端私有 receipt 另含权威 owner、deadline、guard identity 和 layout fingerprint。SDK 配置包只固定允许的 `buffers_root`；SDK从固定 allocator header自动发现arena容量、descriptor/guard几何、epoch和fingerprint，并用 allocation 携带的fingerprint交叉校验。当前开发期完整header直接作为唯一`v1`布局，Python与.NET不保留旧版本兼容。配置包不复制arena path、容量、reader guard数或图片上限，SDK也不接受请求载荷指定任意 mmap/metadata 路径。

新 `BufferRef.v1` 与 Trigger allocation 不再传输可由请求选择的 `path`，SDK/worker只按 `arena_id` 从固定配置解析路径；旧 `size`、`generation`、`slot_capacity_bytes` 和 `pool_name` 分别由语义明确的 `content_length`、`descriptor_generation`、`allocation_capacity_bytes` 和 `arena_id` 取代。`buffer_id` 如为日志展示保留，也不得参与权威回收。最终实现不保留旧字段双读。

.NET SDK 以 `buffers_root + header identity` 建立 mapping cache，整个arena只映射一次，普通调用只创建精确 extent lease并随结果生命周期释放；frame channel可以按稳定descriptor集、generation、offset和capacity复用。backend、Broker、Workflow/deployment worker、独立运行时和仓库内 .NET SDK 统一要求 64-bit；.NET SDK 固定使用 x64 目标并在启动时校验进程架构，不提供 32-bit 容量协商、错误分支或降级路径。

### 7. frame channel 使用预留 extent

frame channel 创建时必须给出 `frame_count` 和 `max_frame_content_length`。Broker 在一个 allocator 临界区内按每帧最小可容纳 order 预留全部 descriptor/extent，全部成功并初始化后才发布 channel；第 N 个 extent 分配或初始化失败时必须回滚本次已保留的全部 extent，外部不能观察到半创建 channel。通道存续期间容量计入 `frame_reserved_capacity_bytes`。帧切换仍使用 generation/sequence/guard publication，不能退回按分辨率选择 pool。

同步结果图片在 RESPONSE publication前必须以batch CAS把owner和deadline一并切换到response owner与独立ACK deadline。成功、失败、deadline、busy和capacity等所有可读取RESPONSE都获得ACK deadline；只有不发布响应的CANCELLED不需要。任何batch handoff失败都不能发布部分图片引用。

### 8. 满载立即失败

分配器不排队、不重试、不压缩、不移动活动 lease，也不 fallback 到 ObjectStore、临时文件、ZeroMQ 或 Base64。失败必须区分：

- 总可用容量不足；
- 连续块不足；
- hard reserve 不可用；
- 单请求超过配置上限；
- layout/identity/guard 状态异常。

descriptor 数量按最小 block 数配置，正常情况下不会先于 arena 容量耗尽。descriptor 提前耗尽属于 allocator 完整性错误，不能当作普通满载。

health按general与hard reserve分域报告free、reserved-writing、active、frame-reserved、REVOKING和QUARANTINED容量，并强制满足分域总量与`arena_total = general_total + huge_reserved_total`守恒。external fragmentation只按general free计算；守恒失败时停止新allocation并报告degraded，不能继续带病分配。

### 9. 文件根目录保持统一但范围不扩大

当前共享根由中立的 `local_memory.root_dir` 配置，默认是 `./data/buffers`。正式文件布局为：

```text
data/buffers/
├─ local-buffer/
│  ├─ arena-main.mmap              arena_id=local-buffer-main
│  ├─ allocator-main.mmap
│  ├─ arena-main.guard
│  └─ arena-main.owner.lock
├─ local-message/
│  ├─ inference-daemon-main.rpc.mmap
│  ├─ workflow-trigger-main.rpc.mmap
│  └─ training-telemetry/
│     └─ <worker-session-id>.event.mmap
└─ inference-daemon-private/
```

本文实施完成时，训练遥测继续使用 `data/runtime/training-telemetry/`，不属于当时的 LocalBuffer 图片数据面迁移范围。[ADR-0009](ADR-0009-local-message-channel.md) 阶段 2 现已把它迁移到 `data/buffers/local-message/training-telemetry/`；该目录使用独立 EventRing，仍不会写入 LocalBuffer arena。

ADR-0009 阶段 1 已把共享路径所有权提升为中立 `local_memory.root_dir`，并删除 `local_buffer_broker.root_dir`。该变化只移动配置归属，`local-buffer/` 文件布局、LocalBuffer enable、Broker owner、allocator 和生命周期保持独立。

`arena_id` 必须在一次安装内跨 Broker owner 唯一且不能使用 PID 等临时值。主 Broker 固定使用 `local-buffer-main`；当前单一 inference daemon 私有 owner 使用 `inference-daemon-private`；未来存在多个私有 owner 时使用 `inference-daemon-private-<stable-daemon-id>`。公开 locator 只用该 id 查询受信任配置映射，不能根据调用方输入拼接路径。

## 未采用方案

- 固定分辨率 pool/slot：容量隔离和浪费明显，调用方需要理解服务端配置。
- 运行时自动扩展 mmap 文件：改变映射和布局，增加跨进程失效与恢复复杂性。
- 图片 page chain：消费端需要拼接，不满足连续视图和零额外复制目标。
- 活动 block compaction：需要移动仍被外部进程读取的图片，破坏引用稳定性。
- 每次大图创建 dedicated 临时 mmap：制造文件和生命周期分支，不能形成统一容量事实。
- 默认硬保留 1 GiB：会无条件损失一半常用容量；应由确需保证超大图的现场显式选择。

## 影响

- 删除 `LocalBufferBrokerPoolSettings`、`default_pool_name`、`pools`、调用方 `pool_name` 和按分辨率 preset；不保留双读或兼容分配路径。
- `MmapBufferPool` 被 arena allocator 取代；普通 lease、External lease、frame channel、output handoff 和 direct reader 统一使用 descriptor/extent。
- Python、.NET SDK、配置包、fixture、前端状态页和所有测试资产必须原子迁移。
- 旧固定 pool 文件不能在线转换。升级时先停止所有 owner/SDK、确认 guard 释放，再运行明确的开发期维护命令重建 arena；新服务发现旧 layout 或 fingerprint 不一致时拒绝启动，不能自动 truncate。
- 该变更只替换图片 LocalBuffer 分配模型，不改变 Workflow Trigger mailbox、inference mailbox、ObjectStore 或训练遥测的数据职责；结构化 mmap 的后续公共 engine 收敛属于 [ADR-0009](ADR-0009-local-message-channel.md) 的独立原子迁移。
