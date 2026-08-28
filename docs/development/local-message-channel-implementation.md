# 本机结构化消息通道实施基线

## 状态与职责

状态：**阶段 0–6 已完成；阶段 7 的源码、本机故障、性能、10,000 次压力和发行装配门禁已完成。真实发行环境 24 小时混合 soak 仍是发布前门禁，因此 ADR 暂不标记为“已实现”。**

本文是 [ADR-0009](../decisions/ADR-0009-local-message-channel.md) 的唯一详细实施顺序，负责把 Workflow Trigger mailbox、Inference mailbox 和训练 telemetry ring 收敛到统一 LocalMessageChannel 基础设施，并为现有 Queue 热路径建立可测量的窄 Mailbox/Event port。

当前实现与目标实现必须明确区分。任何阶段未完成其原子切换与门禁前，正式 composition root 继续使用当前 transport，文档和页面不得宣称对应链路已经迁移。

## 当前事实基线

| 链路 | 当前文件或 IPC | 关键语义 |
| --- | --- | --- |
| Workflow Trigger | `data/buffers/local-message/workflow-trigger/mailbox.mmap` | 通用 Mailbox + Trigger 业务字段、PREPARE/WRITING、response page-chain、ACK |
| Inference daemon | `data/buffers/local-message/inference/mailbox.mmap` | 通用 Mailbox request/response、segmentation page-chain、取消、ACK、daemon epoch |
| Training telemetry | `data/buffers/local-message/training-telemetry/<worker-session-id>.event.mmap` | 通用 EventRing、owner lock、sequence、CRC、gap、非阻塞发布 |
| Workflow Runtime | 每 Runtime request/response `multiprocessing.Queue` | 命令、结果、heartbeat、取消 |
| LocalBuffer | `data/buffers/local-buffer/` | 图片 bytes、连续 extent、lease 与 guard；不属于本轮 allocator 替换范围 |

已确认的现状边界：

- Workflow Runtime 自身没有 mmap mailbox；图中模型节点经 Inference mailbox调用daemon。
- Training telemetry只传指标，数据库和checkpoint仍是训练控制与恢复事实源。
- Trigger与Inference各自依赖单server owner和进程内page allocator lock。
- 两套MAILBOX mailbox重复实现大量header、descriptor、page、CRC、deadline、回收和health逻辑。
- 普通参数通常很小，但结构化response必须继续覆盖现有32 MiB级别结果。

## 目标模块边界

建议源码结构：

```text
backend/contracts/ipc/schemas/
├─ local_message_channel.v1.json
└─ workflow_trigger_mailbox.v1.json

backend/service/application/message_channels/
├─ ports.py
├─ models.py
└─ errors.py

backend/service/infrastructure/ipc/local_message/
├─ registry.py
├─ common_layout.py
├─ guards.py
├─ page_pool.py
├─ mailbox.py
├─ event_ring.py
├─ health.py
└─ errors.py

backend/service/infrastructure/ipc/
└─ multiprocessing_queue_channel.py
```

实际文件名可以按仓库命名规则微调，但职责不能重新散回 inference、workflow或training业务目录。application 只保存 port、DTO 和领域错误；mmap、Queue、文件路径、offset、guard、page layout 和具体 transport adapter 全部属于 infrastructure。领域目录只保留 payload 映射、handler 和状态扩展。

`local_message_channel.v1.json` 是唯一的 LocalMessage binary schema 文件，在同一个版本化文档内分别定义 common header、Mailbox profile/descriptor/page 和 EventRing profile/slot layout。这只是共用生成与 fixture 入口，不表示 Mailbox 与 EventRing 共享状态机或容量几何。common header 显式保存 magic、version、byte order marker、Channel kind/id、owner epoch 和 layout fingerprint；checksum algorithm 是 schema 顶层的固定契约，alignment 由固定 field offset/size 与 layout fingerprint 约束，不伪装成不存在的 header 字段。path containment、guard 获取、publication 顺序、owner lock 与恢复规则属于 engine 规范。page-chain 只存在于 Mailbox layout；EventRing 不引用 Mailbox descriptor、page 或 ACK 状态。Workflow Trigger 业务契约 组合 Mailbox contract，但不把 PREPARE/WRITING 或 LocalBuffer receipt 写入通用 Mailbox/Event 字段。`.NET` 只生成公开 Trigger 所需的 common/Mailbox/extension 类型，不生成内部 Training EventRing SDK 类型。

## 不可变实施规则

1. LocalBuffer只保存图片和大块连续binary；LocalMessage只保存结构化消息与引用。显式`image-base64.v1`可以作为JSON进入MAILBOX，但不是高性能图片路径并受序列化前32 MiB单响应上限约束。
2. Mailbox物理Channel只有一个server owner、一个owner epoch和一个server进程内response page allocator；EventRing物理Channel只有一个producer owner、一个producer epoch和固定ring slots，不存在descriptor、page allocator或ACK。
3. 不建立跨Trigger、Inference、Training的全局动态payload arena或allocator lock。
4. Mailbox和EventRing共享可组合的identity/CRC/path/owner-lock原语，descriptor guard只属于Mailbox；两者不共享完整binary schema、状态机或容量几何，page-chain也只属于Mailbox。
5. Mailbox client request保持有界inline；response page只由server owner分配，避免跨进程共同修改page allocator；EventRing只执行非阻塞slot publication和覆盖检测。
6. publication最后写state；读取方在guard内重新校验epoch、generation、owner、deadline、长度和CRC。
7. 满载立即失败；不排队、不重试、不重跑业务、不切换持久队列或临时文件。
8. 当前开发阶段只保留v1；每条链路原子迁移后删除旧layout和双读代码。
9. 所有正式mmap、guard和owner lock位于中立`local_memory.root_dir`，默认`data/buffers/`；测试只重定向整个root。
10. Queue是否替换由真实基准决定，不能把“统一接口”误解成“统一强制mmap transport”。
11. 不增加全局`local_message.enabled`；LocalMessage基础设施、Inference MAILBOX和Training Event不依赖LocalBuffer enable。Workflow Trigger的配置与路径所有权独立，但当前v1 PREPARE强制包含输入图片，因此其服务ready明确依赖LocalBufferBroker ready，并通过Trigger capability/health对SDK公开。
12. 普通部署配置不包含`channel_profiles`；Trigger Mailbox、Inference MAILBOX和Training Event的稳定默认profile由代码固定并写入header。
13. 已迁移 LocalMessage 的 application adapter 不能直接 import `mmap`、LocalMessage 文件布局或具体 transport；它们通过四个窄 port 由 composition root 注入。未迁移的领域 Queue/pipe 通道保留自己的并发、主动事件和路由语义，不建立一个覆盖全部 IPC 的过宽 `MessageChannelPort`。

### 文件锁身份与关闭规则

- `owner.lock` 是 owner 用于 OS byte-range lock 的稳定路径，文件存在不表示锁仍被持有。Mailbox server/EventRing producer 在整个 owner 生命周期持有 handle；正常关闭显式 unlock，进程被强制结束时由 OS 释放，下一 owner 复用同一路径并发布新 epoch。
- Mailbox 的 `access.guard` 由首次创建 mailbox 文件的 server 创建并固定为 descriptor 数量对应的精确长度。只有 mailbox 数据文件尚未创建或仍为零长度/未发布状态时，下一 owner 可以收敛首次启动中断留下的空或短 guard；已有已发布 mailbox 的 guard 缺失或长度不符时 server/client 都拒绝启动。client、SDK 和短 guard 路径不得创建、扩容或 truncate。
- Mailbox server/client 在 mapping 生命周期持有 `access.guard` identity handle；Windows handle 禁止 delete/rename/replace sharing，避免活动 Channel 的路径被替换为第二个文件。每次 descriptor guard 后仍重验 epoch、generation、owner 和 state。
- EventRing 没有 descriptor、reader/writer guard 或 `access.guard`；它只使用每个 producer session 独立的 `owner.lock`。`owner_alive()` 通过尝试取得该 owner lock 判断异常退出，PID 和 event 文件存在只作诊断。
- 关闭先拒绝新操作，再关闭导出的 response/view、mmap 和数据文件；Mailbox 再关闭 guard identity，server/Event producer 最后释放 owner lock。关闭过程中出现活动 memoryview 或资源关闭错误时保留尚未关闭的 handle，并允许重试；owner lock release 必须线程安全且幂等。
- 当前正式锁互操作认证为 Windows x64。Linux/macOS 的 mmap layout 可以保持相同，但 POSIX lock 后端须完成同进程线程、跨进程、强杀和路径替换门禁后才可标记为正式支持；不能把当前 `lockf` 开发实现直接解释为同等认证。

## 阶段 0：测量与契约冻结

本阶段已经完成。可复现实测结果、原始报告校验值、Queue 裁决和三个冻结 profile 见 [LocalMessage Channel 阶段 0 基线](local-message-channel-stage0-baseline.md)。以下内容保留为阶段 0 的测量契约和回归门禁。

在固定机器、电源策略、进程拓扑和依赖版本下采集当前真实链路。Cold 与 Steady 必须分成两组，不能混用预触碰状态：

- Cold-create：每轮使用新文件和新 mapping，不预热、不预触碰，单独统计首次创建、首次映射和首次实际页访问；
- Cold-reopen：每轮在 owner 已完全退出后重新打开相同路径和既有固定文件，不预热、不预触碰，用于覆盖正式服务重启而非首次安装；
- Steady：固定预热次数，只预触碰本场景实际访问的 header、descriptor/slot 和 payload page，然后执行至少5轮等长采样，并使用各轮指标的中位数比较。

两组共同采集：

- Trigger和Inference request/response序列化后长度的P50、P95、P99和最大值；
- descriptor并发、inline命中、page数量、高水位、压缩收益和容量拒绝；
- Training telemetry payload分布、publish频率、覆盖、gap和文件数量；
- Workflow Runtime Queue的serialize、put、wakeup、get、deserialize、取消和清理完整端到端耗时；Queue 必须同时采集当前 Python object/pickle、统一 envelope/JSON bytes Queue 两组，候选 mmap 再使用同一 envelope/bytes，形成三路对照；
- 进程启动、重启、reload和异常退出时的owner/handle状态。

负载矩阵固定包含：实际inline消息分布、1/8/16/32 MiB page-chain、并发1/2/8/16、Cold首次触页和Steady复用。每轮同时记录P50/P95/P99、CPU时间、working set、page fault、poll wakeup、context switch、线程数和文件句柄数。业务模型或Workflow计算时间与IPC阶段时间分开统计，不能把模型波动归因于transport。

根据结果在代码中冻结三个有名称的稳定默认profile。不能直接沿用当前512 KiB inline，也不能先假定4 KiB、64 KiB或其他新值。profile至少包含descriptor、inline request/response、page大小/数量、单响应页上限、单消息上限和poll/wakeup策略，但本轮不把这些字段加入普通部署配置。

同阶段完成：

- ADR、架构文档和schema字段复核；
- Python/.NET little-endian、字段宽度、对齐和CRC fixture；
- 旧文件、配置、测试fixture和SDK生成物的原子迁移清单；
- EventRing owner lock、owner epoch、worker session identity、诊断PID/process start identity，以及正常close与异常退出的回收判定；EventRing 不创建 descriptor access guard。

同阶段冻结四个窄 port 的共同传输契约：

- `MailboxClientPort`输入request id、不可变wire bytes、绝对`deadline_ns`和cancellation source，返回持有response bytes与ACK/close生命周期的handle；
- `MailboxServerPort`返回request context与cancel probe，并保证每个request最多发布一次response；
- `EventPublisherPort.try_publish()`只接受不可变wire bytes并非阻塞返回published/full/closed结果；
- `EventReaderPort.read()`接受cursor和绝对等待`deadline_ns`，返回event batch、next cursor、gap和producer closed状态；
- MAILBOX外部timeout duration只在权威server入口换算为其monotonic clock domain的绝对deadline；公开.NET SDK不得提交自身monotonic绝对值，重启由owner epoch fence并统一返回`ChannelRestarted`；
- structured payload统一使用同一紧凑UTF-8 JSON codec编码为bytes，codec位于contract/application边界；Queue和mmap transport均接收同一envelope和bytes；
- 普通structured response在client取得自有bytes后ACK；Trigger 业务契约含输出LocalBuffer lease时，response handle持有ACK直至SDK result dispose；
- `close(deadline_ns)`幂等，关闭后拒绝新操作；Queue backend的ACK可为幂等no-op，但cancel、deadline、close和错误分类必须与候选mmap port一致。

同阶段只冻结中立配置迁移清单：后续新增`local_memory.root_dir=./data/buffers`并删除`local_buffer_broker.root_dir`的路径所有权；LocalBuffer、当前旧Trigger/Inference path builder和SDK配置包统一改读中立root，实际目录和协议行为不变。阶段0不修改正式配置或composition root。

门禁：只有测量脚本、fixture和文档变更；正式运行行为不变。

## 阶段 1：通用 contract 与底层 engine

本阶段已经完成。已实现独立的 common layout、Mailbox、EventRing、Queue adapter、application ports、Python/.NET fixture、owner restart fence 和分类型 health；正式 composition root 未引用新 engine。`local_memory.root_dir` 配置所有权也已独立迁移，现有 LocalBuffer、Inference 与 Workflow Trigger 的实际目录和 transport 未变化。

同机 5 轮阶段 1 Mailbox 回归基准使用冻结的 `inference-mailbox.v1` profile，与阶段 0 当前 Inference mailbox 的单次 request/response 基线比较。原始报告保存在 `.tmp/local-message-channel-stage1/benchmark.json`：

| response | 新 engine P99 | 阶段 0 current P99 | 门禁 |
| --- | ---: | ---: | --- |
| 1 KiB | 3.5932 ms | 17.9565 ms | 通过 |
| 1 MiB | 42.7198 ms | 61.4136 ms | 通过 |
| 8 MiB | 320.0137 ms | 383.1169 ms | 通过 |
| 32 MiB | 1267.1362 ms | 1407.0472 ms | 通过 |

每轮结束后 descriptor 和 page 均恢复到冻结总量。该结果只证明独立 engine 没有引入 transport 性能回退，不表示 Inference 正式链路已经迁移。

实现不接业务composition root的通用基础设施：

- 受信buffers root与稳定Channel path builder；
- file header、layout fingerprint、owner epoch和owner lock；
- descriptor/ring header读写；
- byte-range guard、CRC、token和publication helper；
- server-owned response page reserve、write、publish、read、rollback和free；
- Mailbox状态机、deadline、cancel、ACK和sweep；
- EventRing sequence、generation、gap/drop和closed publication；
- common health envelope与分类型指标：MAILBOX报告descriptor/page/request/ACK/cancel，Event报告slot/sequence/gap/drop/producer；
- application `MailboxClientPort`、`MailboxServerPort`、`EventPublisherPort`、`EventReaderPort`、wire envelope DTO、payload codec和领域错误；
- infrastructure Queue adapter，但正式composition root暂不切换。

同阶段以独立原子提交迁移中立root配置：代码、默认配置、发行profile、SDK配置包和当前LocalBuffer/Trigger/Inference path builder一起改用`local_memory.root_dir`，删除`local_buffer_broker.root_dir`且不保留双读。该提交只转移路径配置所有权，现有文件位置、协议和transport保持不变，不能与底层engine实现混在同一提交中。

底层engine不得import Workflow、Inference、Training、FastAPI、数据库或模型代码。application port不得import infrastructure transport。

门禁：

- Python binary fixture逐字节稳定；公开Trigger所需部分与.NET fixture一致；
- inline边界、page-chain循环/越界/CRC、owner/generation/epoch损坏全部拒绝；
- server在claim、body write、page publication、RESPONSE和ACK各阶段退出后资源可收敛；
- 多个独立Channel同时运行，不共享epoch、page或health；
- 一个Channel page pool满载时其他Channel继续工作。
- `rg`确认application port与领域模块不import`mmap`、LocalMessage layout或具体路径。

## 阶段 2：迁移 Training telemetry EventRing

状态：**已完成。**

先迁移风险较低且允许gap的训练遥测：

- Worker Publisher改用`EventRingEngineV1`；
- backend Receiver使用通用reader、cursor和health；
- 路径迁移到`data/buffers/local-message/training-telemetry/`；
- backend-service与backend-worker共享中立`local_memory.root_dir`和代码内Training Event默认profile；
- `training_telemetry.root_dir`迁移到中立root，slot/payload容量迁移到代码profile；Worker的`min_publish_interval_seconds`是训练遥测发布节流策略，必须保留；
- backend receiver的`poll_interval_seconds`与`scan_interval_seconds`在阶段0根据延迟、CPU、文件扫描成本决定保留为运行策略或冻结进代码profile，测量完成前不得删除；
- 删除`training_telemetry_mmap.py`中的独立mmap/header/ring实现，只保留TrainingTelemetryPoint映射；
- 关闭、异常退出、Windows延迟句柄和过期文件清理继续有界重试。

数据库TrainingControlProbe、Task/Attempt、checkpoint和训练日志不改变。

门禁：

- batch/epoch/validation/runtime指标逐字段一致；
- publish不阻塞训练，节流和payload超限行为一致；
- ring wrap、reader落后、gap、producer正常/异常退出和多worker并发通过；
- 服务重启不删除仍存活producer文件；关闭producer最终被清理；
- 不出现checkpoint、图片或控制命令进入EventRing。

实际实现已收敛为：

- `training_telemetry_channel.py` 只负责 `TrainingTelemetryPoint` 与 `training-telemetry.event.v1` wire envelope 的逐字段映射，以及按 `task_id` 执行 `min_publish_interval_seconds` 业务节流；
- `infrastructure/ipc/training_telemetry.py` 只负责 worker session 文件发现、通用 EventRing endpoint 组合、owner lock 存活判断与退休文件清理；
- 原 `training_telemetry_mmap.py` 的独立 header、ring、CRC、PID 探测和 reader/writer 已删除；
- backend-service 普通配置只保留 `training_telemetry.enabled`，backend-worker 只保留 `enabled` 与 `min_publish_interval_seconds`；路径统一读取 `local_memory.root_dir`，4 KiB × 512 slots、50 ms poll、100 ms scan 只来自冻结代码 profile；
- receiver 停止或 service 重启不会删除仍由 worker owner lock 持有的文件；正常关闭与异常退出都会先读取已发布的稳定 slot，再清理该 session 的 mmap 与 owner lock 文件。

同机阶段 2 复测使用 5 轮、每轮 30 个真实 spawn producer 事件和 50 ms poll；原始报告只写入 `.tmp/local-message-channel-stage2/telemetry-benchmark.json`，本次报告 SHA-256 为 `8513bfa90ece52a6080f26a7babba22e95c430fbe7230c680685e323ba3407c5`。结果如下：

| 指标 | 阶段 0 | 阶段 2 | 允许上限 | 结果 |
| --- | ---: | ---: | ---: | --- |
| P95 | 49.614065 ms | 49.657680 ms | 54.575472 ms | 通过 |
| P99 | 50.664828 ms | 50.623332 ms | 55.731311 ms | 通过 |

复测脚本为 `python -m tests.integration.local_message_channel_stage2_telemetry_benchmark`；Windows 必须使用模块入口，以便 `multiprocessing.spawn` 能重新导入主模块。

## 阶段 3：迁移 Inference Mailbox

本阶段已经完成。Inference 内部 Python 链路已原子迁移到通用 Mailbox：

- 保留现有task payload和result envelope；
- 保留classification、detection、segmentation、pose、OBB与只读状态路由；
- 保留32 MiB级别有界page-chain、透明无损压缩和CRC；
- 保留request deadline、cancel、ACK和daemon epoch；
- 图片继续只传LocalBuffer引用；
- start、stop、reset、warmup等持久化控制继续使用原控制队列；
- `inference_daemon.mmap_mailbox`中的descriptor/inline/page/压缩几何改用代码内Inference MAILBOX默认profile；poll字段在阶段0测量后裁决，不能预先删除；
- `inference_daemon.mmap_mailbox.max_concurrent_requests`是真正的推理handler admission，原子迁移为领域字段`inference_daemon.max_concurrent_inference_requests`，同步更新service、daemon、配置、发行profile和测试，不藏入transport profile；
- 原子切换路径到`local-message/inference/mailbox.mmap`后删除`inference_local_mmap.py`中的底层mmap实现。

实际实现已收敛为：

- application 层新增 `InferenceMessageClient`、`inference-daemon.request.v1` 和 `inference-daemon.response.v1`，只处理业务 envelope 与图片正文拒绝；
- `infrastructure/ipc/inference_mailbox.py` 组合通用 Mailbox、handler admission、错误序列化和现有 health 摘要；
- 正式 service/daemon composition root 只创建新 adapter，旧 `inference_local_mmap.py` 已删除，不存在双读或 fallback；
- 普通配置只保留 `mmap_mailbox.enabled`，handler admission 已迁移为 `inference_daemon.max_concurrent_inference_requests`；transport 几何只来自 `inference-mailbox.v1`；
- daemon 停止先发布 closed owner fence，再等待已 claim handler；owner 重启不自动重放已发布请求；page pool 满载发布稳定 capacity error。

门禁：

- 512 KiB旧边界、目标新inline边界及1/8/16/32 MiB结果；
- 16并发混合小响应和多页response；
- page pool满载时inline错误仍可发布，推理只执行一次；
- daemon在多页写入中退出重启；旧epoch/generation/owner请求不能影响新请求；
- 真实五类模型结果逐字段一致，segmentation数值不因传输变化；
- 小响应P95/P99不超过阶段0允许的回退阈值。

专项测试已覆盖 256 KiB、旧 512 KiB、1/8/16/32 MiB、16 并发混合响应、page pool 满载、跨进程、owner 重启、停止取消、LocalBuffer 引用和 detection/segmentation 业务 DTO；通用 engine 测试继续覆盖 CRC、page-chain、publication stage、generation、ACK 与资源恢复。五类模型 runtime 的业务结果由全量测试门禁覆盖，transport adapter 不解释或变换模型字段。

同机阶段 3 小响应复测使用 5 轮、每轮预热 10 次后采样 30 次。原始报告只写入 `.tmp/local-message-channel-stage3/inference-benchmark.json`，SHA-256 为 `1161d657183fb128c7f605847406bbfa4df4a88ade142444660237e3bf44974e`：

| 指标 | 阶段 0 | 阶段 3 | 允许上限 | 结果 |
| --- | ---: | ---: | ---: | --- |
| P95 | 17.552205 ms | 4.344305 ms | 19.307426 ms | 通过 |
| P99 | 17.956461 ms | 4.830960 ms | 19.752107 ms | 通过 |

复测脚本为 `python -m tests.integration.local_message_channel_stage3_inference_benchmark`。该性能结果只适用于当前同机固定拓扑。

## 阶段 4：迁移 Workflow Trigger Mailbox（已完成）

正式链路已经原子切换到通用 Mailbox。Trigger 业务契约 只保留
PREPARE/WRITING、相对 timeout 接受、route generation、业务错误和 LocalBuffer
handoff 字段；descriptor、page-chain、CRC、owner epoch、cancel、deadline、ACK
与回收均由通用 engine 负责。旧 `workflow_trigger_mailbox.py`、旧 binary schema、
旧 fixture 和旧固定目录实现已经删除，没有双读或 fallback。

迁移期间发现并修复了三项通用 engine 热路径问题：response state 必须最后发布，
lock-free reader 只把 state 作为快速判断并在读取 response 时重新取得 descriptor
guard；Trigger supervisor 每轮只执行一次按活动 descriptor 集合收敛的 sweep；request
claim 在同一 guard 内返回 extension 快照，避免窄协议重复加锁。mailbox owner 由
composition root provider 注入并延迟到 FastAPI lifespan 启动，Windows spawn 导入
模块不会抢占正式 owner。

在同一提交链中迁移：

- Trigger领域extension：PREPARE、WRITING、route generation和image metadata；
- External LocalBuffer allocation、writer guard和首次owner handoff；
- Runtime/executor admission、cancel传播和最终公开错误；
- output lease批量handoff与独立response ACK deadline；
- Python/.NET schema、generated constants、fixture、SDK、配置包和开发数据；
- 前端health只显示业务可用容量，不暴露内部路径和几何；
- 删除普通配置中的Trigger mailbox poll/descriptor/page几何；reply timeout、ACK timeout和executor并发继续作为领域策略保留；
- 路径切换到`local-message/workflow-trigger/mailbox.mmap`；
- 删除旧`workflow_trigger_mailbox.py`底层实现和旧binary schema。

Trigger mailbox路径、schema和启用配置不能从LocalBuffer配置派生，但当前v1 supervisor只有在LocalBufferBroker ready时才可接收PREPARE。正式capability/health必须同时校验Trigger owner和Broker ready；SDK不能用静态enabled或文件存在代替健康检查。

门禁：

- Python/.NET真实双进程guard、header和fixture一致；
- PREPARE、WRITING、REQUEST、PROCESSING、RESPONSE、ACK各阶段timeout/cancel；
- LocalBuffer input/output receipt、owner和deadline全量校验；
- page pool满载不重跑Workflow，其他Channel不受影响；
- 四进程2000次与16并发混合inline/page-chain无泄漏；
- 真实BMP/BGR24、双并行分支、24次推理、双Deployment实例和图片返回通过。

功能与资源门禁结果：

- Trigger/LocalBuffer/Workflow 跨层专项测试 `101 passed`；另两项 Windows spawn
  heartbeat 用例在修复 owner 延迟创建后隔离复跑 `2 passed`；
- supervisor 专项 `24 passed`；
- 4 client 进程共 2,000 次混合调用通过，用时 20.110 秒；
- 16 client 进程共 2,000 次混合 inline/page-chain 调用通过，用时 11.219 秒；
- 两轮压力结束后 128 个 descriptor 和 512 个 overflow page 全部回收。

原阶段 0 Trigger 矩阵没有等待全部 spawn client ready，并把总 warmup 次数分摊到
各进程；并发 16 时有 6 个进程没有预热，大响应并发 2 又只有 3 个样本，导致部分
单元出现由进程到达顺序决定的双峰。原报告保持不变，迁移报告
`.tmp/local-message-channel-stage4/trigger-benchmark.json` 的资源门禁和 15 个稳定单元
通过；其余 5 个单元使用迁移前提交 `1e5bfb62` 与当前实现执行相同 ready barrier、
逐进程 2 次预热和 5 轮 A/B。结果如下：

| response / concurrency | legacy P95 / P99 | current P95 / P99 | 裁决 |
| --- | ---: | ---: | --- |
| 1 KiB / 16 | 41.470 / 44.613 ms | 32.695 / 33.351 ms | 通过 |
| 1 MiB / 8 | 324.506 / 427.102 ms | 355.120 / 356.738 ms | 通过 |
| 1 MiB / 16 | 755.267 / 911.307 ms | 720.047 / 728.066 ms | 通过 |
| 8 MiB / 2 | 559.894 / 560.564 ms | 611.411 / 612.470 ms | 通过 |
| 16 MiB / 2 | 1295.527 / 1296.311 ms | 1163.071 / 1165.485 ms | 通过 |

五个单元的 P95/P99 均未回退超过 10%。A/B 工具为
`tests/integration/local_message_channel_trigger_ab_benchmark.py`；legacy/current 原始
报告保存在 `.tmp/local-message-channel-stage4/ab-*.json`。完整迁移报告 SHA-256 为
`c43ea1d4b7be1bd66974961747f79a708094a2bcbd5300c84db731eb1c9ef285`。

## 阶段 5：窄 Port 与 Queue 基准

本阶段已经完成，正式裁决为 `retain-queue`。候选基准使用阶段 1 的相同
`MailboxPort`、相同 wire envelope/bytes 和相同跨进程 echo 拓扑，比较
`MultiprocessingQueueMailbox*` 与只服务基准的 `MmapMailbox*`，未创建正式
`workflow-runtime/`、PublishedInferenceGateway 或 LocalBuffer Broker mmap 目录。

实际语义审计同时确认：

- Workflow Runtime response Queue 还承载主动 heartbeat、runtime state 和异步运行结果，不是严格的一问一答；
- PublishedInferenceGateway 使用 response router 支持并发请求和乱序响应，阶段 1 的 Queue MailboxClient 是单 endpoint 串行语义；
- LocalBuffer Broker 组合每 client response route、同进程直达和跨进程 pipe，不是单一 Queue Mailbox。

因此四个 LocalMessage port 只作为严格 Mailbox/Event 的协议边界，不强制覆盖上述
领域通道。保留链路不增加 JSON/bytes 二次编码、串行锁或形式化 wrapper；后续若要
迁移，必须先为对应异步语义单独设计 port 和基准，不能扩张当前 common schema。

冻结基准参数为 5 轮、每轮 10 次预热和 50 次稳态调用，Windows `spawn`、单 client/
server 跨进程，载荷为 1/6/64 KiB。结果如下（单位 ms，均为五轮中位数）：

| payload | Queue P50 / P95 / P99 | mmap P50 / P95 / P99 | 裁决 |
| ---: | ---: | ---: | --- |
| 1 KiB | 0.162 / 0.296 / 8.850 | 1.902 / 3.336 / 3.469 | 保留 Queue |
| 6 KiB | 0.189 / 0.301 / 8.601 | 2.159 / 3.837 / 4.127 | 保留 Queue |
| 64 KiB | 0.275 / 0.413 / 8.874 | 2.329 / 3.633 / 3.951 | 保留 Queue |

mmap 降低了 Windows Queue 的偶发 P99 尾峰，但三档 P95 均显著回退，CPU 中位数
约为 0.28–0.30 秒而 Queue 为 0.047–0.063 秒，page fault 也更高，未达到迁移门槛。
可复现工具为 `tests/integration/local_message_channel_stage5_queue_benchmark.py`，原始
报告位于 `.tmp/local-message-channel-stage5/queue-benchmark.json`，SHA-256 为
`c38d188b4f7484371a4c3a873614b672d08f9ab496945e7c40efc945971fa219`。

基准和审计覆盖：

- 多轮中位P50、P95、P99与CPU；
- serialize/deserialize与poll/wakeup成本；
- working set、page fault、context switch、feeder/thread/handle数量；
- 进程退出、父进程崩溃、cancel和timeout清理；
- 长期运行内存、文件和Channel数量。

裁决规则保持为：只有 Mailbox 在至少 5 轮稳态采样中同时改善多轮中位 P95 和
P99 至少 10%，且至少一个指标绝对改善不小于 1 ms，同时 CPU、working set、page
fault、线程/句柄和关闭清理不差时，才另行更新 ADR 并原子切换对应链路。本轮未通过。

## 阶段 6：配置、目录和旧实现删除

状态：**已完成。**

完成所有已决定迁移后：

- 确认中立`local_memory.root_dir`是唯一正式共享内存根，LocalBuffer与LocalMessage独立派生子目录、配置所有权和底层资源生命周期；同时保留Workflow Trigger v1对LocalBufferBroker ready的明确业务运行依赖；
- SDK只保留公开Trigger Channel发现信息，不携带内部容量几何；
- 删除`inference-control/`、`workflow-trigger/`和`data/runtime/training-telemetry/`旧运行文件；
- 删除旧root配置、重复header/page/CRC/sweep代码和双读分支；
- 更新服务health、诊断命令、发行profile、文档和维护脚本；
- 重新assemble release，不手工修改`release/<profile-id>/app/`。

迁移必须在所有服务、worker、daemon和SDK停止且guard释放后执行。新代码发现旧layout时明确拒绝启动，不能自动truncate活动文件。

`rg`门禁：业务模块不再直接创建`mmap.mmap`；除LocalBuffer外，mmap打开只允许出现在`infrastructure/ipc/local_message/`。Training、Inference和Workflow目录只能使用engine/port。

实际收敛结果：

- `local_memory.root_dir` 已成为 LocalBuffer 与 LocalMessage 的唯一共享根配置；三个 Channel 的普通配置不再暴露 descriptor、page 或 ring 几何；
- 旧 Inference、Workflow Trigger 和 Training Telemetry mmap 实现、schema、fixture 与双读路径已经删除；新代码发现旧正式 layout 时会在取得新 owner 前明确拒绝启动；
- 开发机上确认没有存活 owner 后，旧运行文件已从正式目录移动到 `.tmp/local-message-channel-stage6/legacy-runtime/` 隔离保留，正式目录不再存在旧 Inference、Trigger、Telemetry layout；同时取得 194 个旧 owner/reader/writer guard 后，遗留的 LocalBuffer 固定分辨率池也已隔离到其 `local-buffer-fixed-pools/` 子目录；当前 `data/buffers/` 顶层数据面只保留唯一图片 arena `local-buffer/` 和结构化消息目录 `local-message/`；
- system diagnostics 已按 Channel 分别报告 Workflow Trigger Mailbox、Inference Mailbox 和 Training Event 状态，保留 Queue 的领域链路不会伪装成 LocalMessage；
- `full-windows-x64-nvidia` 已从当前源码装配到 `.tmp/local-message-channel-stage7/release/`，生成结果包含新 engine/schema 且不包含四个旧实现文件。该独立验证目录的 bundled Python 为 `placeholder-empty`，真实随包 Python 启动仍属于目标发行目录验收；
- 全仓静态扫描确认，迁移业务模块不直接 import `mmap` 或 LocalMessage layout；application 中保留的 `local_buffers/local_buffer_client.py` 是 ADR 明确排除的连续图片数据面。

## 阶段 7：完整故障、性能与持续负载

状态：**源码与本机自动化门禁已完成；真实发行环境 24 小时混合 soak 待发布前执行。**

必须覆盖：

- 多Channel同时运行、独立满载、独立重启和独立epoch；
- Client/server在所有publication状态退出；
- page/ring CRC、循环、越界、owner/generation/epoch错误；
- request timeout、response ACK timeout、explicit cancel和client shutdown；
- telemetry wrap、gap、producer crash和receiver restart；
- owner持锁时强杀Mailbox server/Event producer/LocalBuffer owner，下一owner必须立即可取得OS lock并按新epoch恢复；遗留`.lock`文件不能造成假死锁；
- Mailbox `access.guard` 缺失、长度错误或被替换时fail closed且client不得修复；Windows持有identity handle时delete/rename/replace必须失败；
- 活动response/view阻塞close时保留owner与资源handle，释放view后重试close成功；重复close/release不重复unlock；
- Queue保留/迁移链路的shutdown与handle守恒；
- 真实HTTP、ZeroMQ、local-shared、Workflow Runtime、Trigger、Inference和training telemetry混合负载；
- 10,000次门禁后descriptor、page、ring、file、guard、thread、handle和Channel回到基线；
- 发布前24小时持续soak无泄漏、串包、CRC错误、owner失效或不受控文件增长。

性能阈值以阶段0同机、多轮中位基线为准，所有比较使用相同预热、消息分布、并发、运行时间和进程拓扑：

- inline消息P95/P99不得回退超过`max(1 ms, 10%)`；
- 1/8/16/32 MiB结构化response的P95/P99不得回退超过10%；
- 未迁移Queue的链路不得因port抽象产生超过`max(0.5 ms, 5%)`的P95/P99回退；
- CPU和working set不得回退超过10%，page fault、poll wakeup、线程和句柄不能出现无解释的持续增长；
- 不以平均值或单轮最好值替代多轮中位P95/P99，不把Workflow模型执行耗时算作IPC传输收益。

本轮本机验证结果：

- 后端全量：`3796 passed in 2106.46s`；全量顺序首次暴露并已修复同一 FastAPI app 重复 lifespan 时 Trigger supervisor 被永久关闭的问题，最终 JUnit 位于 `.tmp/local-message-channel-stage7/backend-full-after-lifecycle-fix.xml`；
- 前端：`74` 个测试文件、`285` 项测试通过，Vue TypeScript 检查和 Vite 生产构建通过；
- .NET：`Amvar.Vision.ContractTests` 以 .NET Framework 4.7.2 Release 配置重新编译并执行通过，覆盖 LocalMessage common/Mailbox/Trigger 业务契约 的跨语言 fixture；
- Trigger 跨进程压力：8 个 client、10,000 次请求通过，耗时 60.969 秒；结束后 128 个 descriptor 和全部 response page 回到空闲基线；
- 阶段 0–5 原始报告 SHA-256 分别为 `f98c11c3445b525c734ecbe4d09fb845f212d269a76caac68520647d8bd69271`、`54559a4da315fe6cd6b468d7922c89140a7b9eb169e24f8a9eb8c12e5a2815c4`、`8513bfa90ece52a6080f26a7babba22e95c430fbe7230c680685e323ba3407c5`、`1161d657183fb128c7f605847406bbfa4df4a88ade142444660237e3bf44974e`、`c43ea1d4b7be1bd66974961747f79a708094a2bcbd5300c84db731eb1c9ef285` 和 `c38d188b4f7484371a4c3a873614b672d08f9ab496945e7c40efc945971fa219`。

24 小时门禁必须在具有真实 backend-service、bundled Python、Deployment instance、Workflow App Runtime、ZeroMQ TriggerSource、输入图片和访问令牌的目标发行环境执行 `tests/integration/deployment_workflow_trigger_soak.py`。源码工作区没有这些运行身份，不能以 mock、缩短时长或单链路压力结果替代，也不能据此提前把 ADR 标记为“已实现”。

## 明确不做

- 不建立一个跨所有owner的512 MiB动态payload arena。
- 不实现多进程共同写allocator metadata、在线allocator重建或事务日志。
- 不复用LocalBuffer buddy allocator或把图片放入message page-chain。
- 不增加latest-value/notification Channel。
- 不强制迁移没有基准收益的Queue。
- 不把数据库控制、checkpoint、日志、Task或Outbox迁入mmap。
- 不创建v2、旧layout兼容层或跨transport fallback。

## 完成判定

通用基础设施、Training、Inference 和 Workflow Trigger 的原子迁移以及阶段 0–6 已全部收口；同一 Channel 不存在新旧双跑或双读。阶段 7 的源码与本机发行装配门禁已经通过，但必须在真实目标发行环境完成 24 小时混合 soak 后，才能把 ADR 状态改为“已实现”。在此之前，架构文档和发布说明必须明确区分“代码迁移完成”与“发布持续负载验收完成”。
