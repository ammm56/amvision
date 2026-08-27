# 本机结构化消息通道实施基线

## 状态与职责

状态：**规划已接受，代码尚未开始迁移。**

本文是 [ADR-0009](../decisions/ADR-0009-local-message-channel.md) 的唯一详细实施顺序，负责把 Workflow Trigger mailbox、Inference mailbox 和训练 telemetry ring 收敛到统一 LocalMessageChannel 基础设施，并为现有 Queue 热路径建立可测量的窄 RPC/Event port。

当前实现与目标实现必须明确区分。任何阶段未完成其原子切换与门禁前，正式 composition root 继续使用当前 transport，文档和页面不得宣称对应链路已经迁移。

## 当前事实基线

| 链路 | 当前文件或 IPC | 关键语义 |
| --- | --- | --- |
| Workflow Trigger | `data/buffers/workflow-trigger/workflow-trigger-main.mmap` | 128 descriptor、inline request/response、response page chain、PREPARE、ACK |
| Inference daemon | `data/buffers/inference-control/inference-daemon-main.mmap` | request/response、segmentation page chain、取消、ACK、daemon epoch |
| Training telemetry | `data/runtime/training-telemetry/worker-*.mmap` | 单 producer ring、sequence、CRC、gap、非阻塞发布 |
| Workflow Runtime | 每 Runtime request/response `multiprocessing.Queue` | 命令、结果、heartbeat、取消 |
| LocalBuffer | `data/buffers/local-buffer/` | 图片 bytes、连续 extent、lease 与 guard；不属于本轮 allocator 替换范围 |

已确认的现状边界：

- Workflow Runtime 自身没有 mmap mailbox；图中模型节点经 Inference mailbox调用daemon。
- Training telemetry只传指标，数据库和checkpoint仍是训练控制与恢复事实源。
- Trigger与Inference各自依赖单server owner和进程内page allocator lock。
- 两套RPC mailbox重复实现大量header、descriptor、page、CRC、deadline、回收和health逻辑。
- 普通参数通常很小，但结构化response必须继续覆盖现有32 MiB级别结果。

## 目标模块边界

建议源码结构：

```text
backend/contracts/ipc/schemas/
├─ local_message_common.v1.json
├─ local_message_rpc.v1.json
├─ local_message_event_ring.v1.json
└─ workflow_trigger_rpc_extension.v1.json

backend/service/application/message_channels/
├─ ports.py
├─ models.py
└─ errors.py

backend/service/infrastructure/ipc/local_message/
├─ registry.py
├─ common_layout.py
├─ guards.py
├─ page_pool.py
├─ rpc_mailbox.py
├─ event_ring.py
├─ health.py
└─ errors.py

backend/service/infrastructure/ipc/
└─ multiprocessing_queue_channel.py
```

实际文件名可以按仓库命名规则微调，但职责不能重新散回 inference、workflow或training业务目录。application 只保存 port、DTO 和领域错误；mmap、Queue、文件路径、offset、guard、page layout 和具体 transport adapter 全部属于 infrastructure。领域目录只保留 payload 映射、handler 和状态扩展。

`local_message_common.v1` 只定义 magic、version、byte order、alignment、Channel kind/id、owner epoch、layout fingerprint 和 checksum algorithm id。path containment、guard 获取、publication 顺序、owner lock 与恢复规则属于 engine 规范，不是 binary schema 字段。page-chain 只存在于 `local_message_rpc.v1`；EventRing 不引用 RPC descriptor、page 或 ACK 状态。Workflow Trigger extension 组合 RPC contract，但不把 PREPARE/WRITING 或 LocalBuffer receipt 写入通用 RPC/Event 字段。`.NET` 只生成公开 Trigger 所需的 common/RPC/extension 类型，不生成内部 Training EventRing SDK 类型。

## 不可变实施规则

1. LocalBuffer只保存图片和大块连续binary；LocalMessage只保存结构化消息与引用。显式`image-base64.v1`可以作为JSON进入RPC，但不是高性能图片路径并受序列化前32 MiB单响应上限约束。
2. RpcMailbox物理Channel只有一个server owner、一个owner epoch和一个server进程内response page allocator；EventRing物理Channel只有一个producer owner、一个producer epoch和固定ring slots，不存在descriptor、page allocator或ACK。
3. 不建立跨Trigger、Inference、Training的全局动态payload arena或allocator lock。
4. RpcMailbox和EventRing共享可组合的identity/guard/CRC/path原语，但不共享完整binary schema、状态机或容量几何；page-chain只属于RPC。
5. RpcMailbox client request保持有界inline；response page只由server owner分配，避免跨进程共同修改page allocator；EventRing只执行非阻塞slot publication和覆盖检测。
6. publication最后写state；读取方在guard内重新校验epoch、generation、owner、deadline、长度和CRC。
7. 满载立即失败；不排队、不重试、不重跑业务、不切换持久队列或临时文件。
8. 当前开发阶段只保留v1；每条链路原子迁移后删除旧layout和双读代码。
9. 所有正式mmap、guard和owner lock位于中立`local_memory.root_dir`，默认`data/buffers/`；测试只重定向整个root。
10. Queue是否替换由真实基准决定，不能把“统一接口”误解成“统一强制mmap transport”。
11. 不增加全局`local_message.enabled`；LocalMessage基础设施、Inference RPC和Training Event不依赖LocalBuffer enable。Workflow Trigger的配置与路径所有权独立，但当前v1 PREPARE强制包含输入图片，因此其服务ready明确依赖LocalBufferBroker ready，并通过Trigger capability/health对SDK公开。
12. 普通部署配置不包含`channel_profiles`；Trigger RPC、Inference RPC和Training Event的稳定默认profile由代码固定并写入header。
13. application层不能直接import`mmap`、具体Queue实现或LocalMessage文件布局；所有transport通过四个窄port由composition root注入，不建立过宽的`MessageChannelPort`。

## 阶段 0：测量与契约冻结

在固定机器、电源策略、进程拓扑和依赖版本下采集当前真实链路。Cold 与 Steady 必须分成两组，不能混用预触碰状态：

- Cold：每轮使用新文件和新 mapping，不预热、不预触碰，单独统计首次打开、首次映射和首次实际页访问；
- Steady：固定预热次数，只预触碰本场景实际访问的 header、descriptor/slot 和 payload page，然后执行至少5轮等长采样，并使用各轮指标的中位数比较。

两组共同采集：

- Trigger和Inference request/response序列化后长度的P50、P95、P99和最大值；
- descriptor并发、inline命中、page数量、高水位、压缩收益和容量拒绝；
- Training telemetry payload分布、publish频率、覆盖、gap和文件数量；
- Workflow Runtime Queue的serialize、put、wakeup、get、deserialize、取消和清理完整端到端耗时；
- 进程启动、重启、reload和异常退出时的owner/handle状态。

负载矩阵固定包含：实际inline消息分布、1/8/16/32 MiB page-chain、并发1/2/8/16、Cold首次触页和Steady复用。每轮同时记录P50/P95/P99、CPU时间、working set、page fault、poll wakeup、context switch、线程数和文件句柄数。业务模型或Workflow计算时间与IPC阶段时间分开统计，不能把模型波动归因于transport。

根据结果在代码中冻结三个有名称的稳定默认profile。不能直接沿用当前512 KiB inline，也不能先假定4 KiB、64 KiB或其他新值。profile至少包含descriptor、inline request/response、page大小/数量、单响应页上限、单消息上限和poll/wakeup策略，但本轮不把这些字段加入普通部署配置。

同阶段完成：

- ADR、架构文档和schema字段复核；
- Python/.NET little-endian、字段宽度、对齐和CRC fixture；
- 旧文件、配置、测试fixture和SDK生成物的原子迁移清单。

同阶段冻结四个窄 port 的共同传输契约：

- `RpcClientPort`输入request id、不可变wire bytes、绝对`deadline_ns`和cancellation source，返回持有response bytes与ACK/close生命周期的handle；
- `RpcServerPort`返回request context与cancel probe，并保证每个request最多发布一次response；
- `EventPublisherPort.try_publish()`只接受不可变wire bytes并非阻塞返回published/full/closed结果；
- `EventReaderPort.read()`接受cursor和绝对等待`deadline_ns`，返回event batch、next cursor、gap和producer closed状态；
- RPC外部timeout duration只在入口换算为同主机monotonic绝对deadline；重启由owner epoch fence，统一返回`ChannelRestarted`；
- structured payload统一使用同一紧凑UTF-8 JSON codec编码为bytes，codec位于contract/application边界；Queue和mmap transport均接收同一envelope和bytes；
- 普通structured response在client取得自有bytes后ACK；Trigger extension含输出LocalBuffer lease时，response handle持有ACK直至SDK result dispose；
- `close(deadline_ns)`幂等，关闭后拒绝新操作；Queue backend的ACK可为幂等no-op，但cancel、deadline、close和错误分类必须与候选mmap port一致。

同阶段只冻结中立配置迁移清单：后续新增`local_memory.root_dir=./data/buffers`并删除`local_buffer_broker.root_dir`的路径所有权；LocalBuffer、当前旧Trigger/Inference path builder和SDK配置包统一改读中立root，实际目录和协议行为不变。阶段0不修改正式配置或composition root。

门禁：只有测量脚本、fixture和文档变更；正式运行行为不变。

## 阶段 1：通用 contract 与底层 engine

实现不接业务composition root的通用基础设施：

- 受信buffers root与稳定Channel path builder；
- file header、layout fingerprint、owner epoch和owner lock；
- descriptor/ring header读写；
- byte-range guard、CRC、token和publication helper；
- server-owned response page reserve、write、publish、read、rollback和free；
- RpcMailbox状态机、deadline、cancel、ACK和sweep；
- EventRing sequence、generation、gap/drop和closed publication；
- common health envelope与分类型指标：RPC报告descriptor/page/request/ACK/cancel，Event报告slot/sequence/gap/drop/producer；
- application `RpcClientPort`、`RpcServerPort`、`EventPublisherPort`、`EventReaderPort`、wire envelope DTO、payload codec和领域错误；
- infrastructure Queue adapter，但正式composition root暂不切换。

同阶段原子迁移中立root配置：代码、默认配置、发行profile、SDK配置包和当前LocalBuffer/Trigger/Inference path builder一起改用`local_memory.root_dir`，删除`local_buffer_broker.root_dir`且不保留双读。该步骤只转移路径配置所有权，现有文件位置、协议和transport保持不变。

底层engine不得import Workflow、Inference、Training、FastAPI、数据库或模型代码。application port不得import infrastructure transport。

门禁：

- Python binary fixture逐字节稳定；公开Trigger所需部分与.NET fixture一致；
- inline边界、page-chain循环/越界/CRC、owner/generation/epoch损坏全部拒绝；
- server在claim、body write、page publication、RESPONSE和ACK各阶段退出后资源可收敛；
- 多个独立Channel同时运行，不共享epoch、page或health；
- 一个Channel page pool满载时其他Channel继续工作。
- `rg`确认application port与领域模块不import`mmap`、LocalMessage layout或具体路径。

## 阶段 2：迁移 Training telemetry EventRing

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

## 阶段 3：迁移 Inference RPC mailbox

Inference是内部Python链路，先用于验证通用RpcMailbox：

- 保留现有task payload和result envelope；
- 保留classification、detection、segmentation、pose、OBB与只读状态路由；
- 保留32 MiB级别有界page-chain、透明无损压缩和CRC；
- 保留request deadline、cancel、ACK和daemon epoch；
- 图片继续只传LocalBuffer引用；
- start、stop、reset、warmup等持久化控制继续使用原控制队列；
- `inference_daemon.mmap_mailbox`中的descriptor/inline/page/压缩几何改用代码内Inference RPC默认profile；poll字段在阶段0测量后裁决，不能预先删除；
- `inference_daemon.mmap_mailbox.max_concurrent_requests`是真正的推理handler admission，原子迁移为领域字段`inference_daemon.max_concurrent_inference_requests`，同步更新service、daemon、配置、发行profile和测试，不藏入transport profile；
- 原子切换路径到`local-message/inference-daemon-main.rpc.mmap`后删除`inference_local_mmap.py`中的底层mmap实现。

门禁：

- 512 KiB旧边界、目标新inline边界及1/8/16/32 MiB结果；
- 16并发混合小响应和多页response；
- page pool满载时inline错误仍可发布，推理只执行一次；
- daemon在多页写入中退出重启；旧epoch/generation/owner请求不能影响新请求；
- 真实五类模型结果逐字段一致，segmentation数值不因传输变化；
- 小响应P95/P99不超过阶段0允许的回退阈值。

## 阶段 4：迁移 Workflow Trigger RPC mailbox

在同一提交链中迁移：

- Trigger领域extension：PREPARE、WRITING、route generation和image metadata；
- External LocalBuffer allocation、writer guard和首次owner handoff；
- Runtime/executor admission、cancel传播和最终公开错误；
- output lease批量handoff与独立response ACK deadline；
- Python/.NET schema、generated constants、fixture、SDK、配置包和开发数据；
- 前端health只显示业务可用容量，不暴露内部路径和几何；
- 删除普通配置中的Trigger mailbox poll/descriptor/page几何；reply timeout、ACK timeout和executor并发继续作为领域策略保留；
- 路径切换到`local-message/workflow-trigger-main.rpc.mmap`；
- 删除旧`workflow_trigger_mailbox.py`底层实现和旧binary schema。

Trigger mailbox路径、schema和启用配置不能从LocalBuffer配置派生，但当前v1 supervisor只有在LocalBufferBroker ready时才可接收PREPARE。正式capability/health必须同时校验Trigger owner和Broker ready；SDK不能用静态enabled或文件存在代替健康检查。

门禁：

- Python/.NET真实双进程guard、header和fixture一致；
- PREPARE、WRITING、REQUEST、PROCESSING、RESPONSE、ACK各阶段timeout/cancel；
- LocalBuffer input/output receipt、owner和deadline全量校验；
- page pool满载不重跑Workflow，其他Channel不受影响；
- 四进程2000次与16并发混合inline/page-chain无泄漏；
- 真实BMP/BGR24、双并行分支、24次推理、双Deployment实例和图片返回通过。

## 阶段 5：窄 Port 与 Queue基准

让现有调用点依赖阶段1已建立的协议中立port，并适配当前Queue backend：

- Workflow Runtime manager/worker request、response、heartbeat和cancel；
- PublishedInferenceGateway内部请求/响应；
- LocalBuffer Broker控制请求/响应。

正式composition root继续使用Queue。Queue adapter和候选RpcMailbox必须经过相同port、相同wire envelope、相同JSON codec和相同bytes，使用只服务基准的候选Channel比较transport差异，不创建正式`workflow-runtime/`、PublishedInferenceGateway或LocalBuffer Broker mmap目录：

- 多轮中位P50、P95、P99与CPU；
- serialize/deserialize与poll/wakeup成本；
- working set、page fault、context switch、feeder/thread/handle数量；
- 进程退出、父进程崩溃、cancel和timeout清理；
- 长期运行内存、文件和Channel数量。

裁决规则：只有RpcMailbox在至少5轮稳态采样中同时改善多轮中位P95和P99至少10%，且至少一个指标绝对改善不小于1 ms，同时CPU、working set、page fault、线程/句柄和关闭清理不差时，才另行更新ADR并原子切换对应链路。否则保留Queue backend并记录基准结论。不得为了删除Queue而降低稳定性。

## 阶段 6：配置、目录和旧实现删除

完成所有已决定迁移后：

- 确认中立`local_memory.root_dir`是唯一正式共享内存根，LocalBuffer与LocalMessage独立派生子目录、配置所有权和底层资源生命周期；同时保留Workflow Trigger v1对LocalBufferBroker ready的明确业务运行依赖；
- SDK只保留公开Trigger Channel发现信息，不携带内部容量几何；
- 删除`inference-control/`、`workflow-trigger/`和`data/runtime/training-telemetry/`旧运行文件；
- 删除旧root配置、重复header/page/CRC/sweep代码和双读分支；
- 更新服务health、诊断命令、发行profile、文档和维护脚本；
- 重新assemble release，不手工修改`release/<profile-id>/app/`。

迁移必须在所有服务、worker、daemon和SDK停止且guard释放后执行。新代码发现旧layout时明确拒绝启动，不能自动truncate活动文件。

`rg`门禁：业务模块不再直接创建`mmap.mmap`；除LocalBuffer外，mmap打开只允许出现在`infrastructure/ipc/local_message/`。Training、Inference和Workflow目录只能使用engine/port。

## 阶段 7：完整故障、性能与持续负载

必须覆盖：

- 多Channel同时运行、独立满载、独立重启和独立epoch；
- Client/server在所有publication状态退出；
- page/ring CRC、循环、越界、owner/generation/epoch错误；
- request timeout、response ACK timeout、explicit cancel和client shutdown；
- telemetry wrap、gap、producer crash和receiver restart；
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

## 明确不做

- 不建立一个跨所有owner的512 MiB动态payload arena。
- 不实现多进程共同写allocator metadata、在线allocator重建或事务日志。
- 不复用LocalBuffer buddy allocator或把图片放入message page-chain。
- 不增加latest-value/notification Channel。
- 不强制迁移没有基准收益的Queue。
- 不把数据库控制、checkpoint、日志、Task或Outbox迁入mmap。
- 不创建v2、旧layout兼容层或跨transport fallback。

## 完成判定

通用基础设施可以先以未接入composition root的形式提交。Training、Inference和Workflow Trigger分别作为独立原子切换：同一Channel的代码、配置、schema、SDK、fixture、开发数据和旧实现删除必须在同一变更中完成，不能双跑或双读；其他尚未迁移的Channel可以暂时继续使用旧实现。阶段0–6全部收口且阶段7源码与发行门禁通过后，才能把 ADR 状态改为“已实现”。在此之前，架构文档必须持续标注目标尚未完成，页面和发布说明不得宣称项目已经使用统一LocalMessageChannel。
