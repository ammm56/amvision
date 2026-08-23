# ADR-0006：任务终态、转换发布与节点超时治理

## 状态

已接受，实施契约已冻结，待分阶段实现。

详细实施顺序、迁移边界和验收门禁见 [任务执行与运行时可靠性实施基线](../development/task-runtime-reliability-implementation.md)。在对应阶段通过门禁前，本 ADR 不表示相关能力已经落地。

## 背景

Task、TaskAttempt、训练恢复、模型转换和 Workflow 节点执行已经具备各自的基础设施，但跨线程、跨进程和崩溃恢复场景仍存在几类共同风险：

- Task 状态可被通用事件间接修改，取消与旧 Worker 的成功回写可能竞争；
- Attempt 终态写入没有在一个入口完整核验 lease owner；
- 训练恢复的数据库更新与重新入队不是同一个持久化事务；
- Conversion 子进程具备进程树监督，但 deadline、结果验证、文件发布和数据库登记尚未形成一个可恢复的提交协议；
- Node Pack timeout 已出现在 manifest 中，但 Preview 与正式 Runtime 的可执行语义尚未完全闭环；
- 前端 Task 状态集合遗漏 `paused`、`timed_out`，与后端完整状态契约尚未形成自动门禁。

这些问题不应通过隐藏排队、无限重试、每节点新建进程或更改模型数值实现来掩盖。目标是在保持本地高性能链路和既有准确率边界的前提下，建立少量、明确、可验证的状态机与恢复协议。

## 决策

### 1. Task 状态只能由命令修改

TaskEvent 继续保存 `status`、`result`、进度、日志和可观测 metadata。普通 `append_task_event()` 是无 Attempt 的服务侧纯追加入口，不得修改 TaskRecord；普通调用即使携带 `payload.state`，也必须拒绝。Worker 产生的 log/result observation 必须通过带当前 Attempt owner/heartbeat/Queue lease fence 的 `append_task_attempt_event()`；旧 Attempt 失去执行权后不能继续污染权威事件流。需要维护 TaskRecord 进度快照时使用同样受 fence 保护的 `record_task_progress()`，在同一 Unit of Work 中更新 progress/允许的 metadata 字段并追加 progress 事件。状态命令和进度命令都只能修改自己拥有的字段，不能用一份先前读取的完整 TaskRecord 覆盖其他并发更新。

只有专用状态命令可以在同一 Unit of Work 中先 CAS 修改 TaskRecord，再写入携带新 state 的状态审计事件，提交后发布实时事件。TaskEvent 是状态变化的审计结果，不是状态变化的命令来源。

TaskRecord 采用以下命令级状态矩阵：

| 当前状态 | 允许命令 | 目标状态 |
| --- | --- | --- |
| `queued` | `claim_task_execution` | `running` |
| `queued` | cancel | `cancelled` |
| `running` | request pause | `running` |
| `running` | worker 在 batch 安全点中止未完成 epoch，并确认最近完整 epoch checkpoint | `paused` |
| `running` | complete/fail/timeout/cancel | 对应终态 |
| `paused` | resume | `queued` |
| `paused` | cancel | `cancelled` |
| `failed` | resume | `queued` |
| `succeeded` / `timed_out` / `cancelled` | 无 | 保持不变 |

不存在 Attempt 时不能调用 finalizer，因此 `queued` 不直接通过 finalizer 进入 failed/timed_out。Outbox 的持久投递失败保持可观察的 `queued`，按现有有界退避继续投递；这只是消息交付重试，不是 Worker 执行重试，也不得暗中重新运行已经开始的 Attempt。若未来需要排队期限，必须另行版本化为明确的 submission-expiry 命令。

暂停请求只记录控制意图，不能在 checkpoint 尚未安全确认时提前把 Task 标记为 `paused`。训练 Worker 必须在每个 train/validation batch 的安全点检查 attempt 级控制探针；探针以 monotonic 时间节流持久状态读取，默认最多每 250 ms 查询一次，不能让每个 batch 都直接访问数据库，也不建立额外控制线程或隐藏队列。观察到请求后不再开始下一个 batch，立即放弃当前未完成 epoch 的模型更新、指标和验证结果，不等待该 epoch 结束，也不得把部分 epoch 状态保存成可恢复 checkpoint。正常响应上限是一个已经开始的 batch（含其数据读取和设备同步）加最多 250 ms 控制观察间隔，不承诺中断不可协作的底层算子。

为保证能够回到最近一个完整 epoch，每个训练 Attempt 在内存中只保留一份已经序列化的不可变 completed-epoch checkpoint bytes：首次 batch 前建立 epoch 0 baseline；每个完整 epoch 的训练、应执行的验证和指标提交结束后，在局部缓冲区生成新快照，成功后替换旧快照，不在每个 epoch 写磁盘。快照生成失败时不能开始下一 epoch。稳定状态只保留一份快照；替换期间允许短暂同时存在旧、新两份 bytes，必须计入训练主机内存基线和门禁。

共享 checkpoint policy 改为只决定**持久化原因**，不能再用 `should_serialize` 同时表达内存快照生成和磁盘写入。各模型现有可配置 `checkpoint_interval`、`evaluation_interval` 以及 periodic、best、final、manual、pause、terminate 规则保持不变。周期、final、manual、pause 和 terminate 的完整 resume checkpoint 复用当前内存 bytes；模型专用 best/EMA/deployment artifact 若公开格式或权重语义不同，继续使用其专用 builder，只在指标改善时生成和写入，不能为了统一复用而改变准确率或加载契约。

暂停时先停止新 batch并丢弃当前 epoch，再将上一完整 epoch 的内存快照持久化一次；若同一 completed epoch 的等价完整 resume checkpoint 已由周期或其他原因安全持久化，则直接复用其 object key，不重复写文件。恢复从 `completed_epoch + 1` 重新执行被丢弃的 epoch。暂停 finalizer 只有在持久 checkpoint 已存在、身份和完整性验证通过后，才在同一 Unit of Work 中把 TaskAttempt 和 Task 都标记为 `paused`。观测指标拆成请求到 Worker 观察控制的 `pause_observed_latency_ms`，以及请求到 checkpoint 可恢复且状态进入 paused 的 `pause_completed_latency_ms`；“一个 batch 加 250 ms”只约束前者。

`paused` 是 Attempt 的终态，但不是 Task 的不可恢复终态。`failed → queued` 和 `paused → queued` 只能由专用 resume 命令完成。`succeeded`、`timed_out`、`cancelled` 是不可变终态，旧 Attempt 不得覆盖。取消 running Task 时，同一事务还要把当前 running Attempt 标记为 cancelled；外部 watchdog 取得 timeout 决策权时同样收敛当前 Attempt，避免留下 Task 终态但 Attempt 仍 running 的正常路径。取消通过单事务 CAS 完成；一旦 Conversion 取得 publication reservation，取消返回冲突，不再与即将或已经发布的结果竞争。

Queue claim、TaskAttempt 创建、Task `queued → running`、`current_attempt_no` 推进和 started 状态事件必须由 `claim_task_execution` 在同一 Unit of Work 中完成。已有 running Attempt 的 lease recovery 只原子接管该 Attempt 的 owner/heartbeat，Task 保持 running，不重复 started 事件。数据库终态已提交但 Queue ack 丢失时只根据持久终态完成 ack，不再进入业务执行。`current_attempt_no` 表示最近已经成功领取的 Attempt，不表示仅排队但尚未领取的轮次：新 Task 从 0 领取 Attempt 1；Resume 事务只计算并固化下一 attempt number 到 Outbox，Worker claim 成功后才推进 Task 字段。

### 2. Attempt 由一个原子 finalizer 收敛

所有 Worker 使用统一 finalizer 完成 Attempt。Attempt 终态集合为 `paused`、`succeeded`、`failed`、`timed_out`、`cancelled`；其中只有 `paused` 可以通过 Task resume 创建下一 Attempt。调用方只传 `attempt_id`、目标终态、结果或错误，以及预期的 worker/heartbeat/queue lease 身份。`task_id` 与 `attempt_no` 从数据库中的 TaskAttempt 派生，不能由调用方重复声明。

finalizer 必须同时核验：

- `expected_worker_id`；
- `expected_heartbeat_at`；
- 当前 Queue message id 与 queue attempt count；
- Task 当前 attempt number 和允许的 Task 状态。

Attempt CAS 失败且记录已经终结时返回已有结果，不重复产生副作用。Task 已经通过同一 Attempt 保存更具体的业务终态和事件时，finalizer 只收敛尚未结束的 Attempt，既不覆盖业务详情，也不再追加第二条通用终态事件。迁移完成后，业务服务把丰富错误 payload 直接交给统一 finalizer，不再先独立写 Task 终态。

终态事件和 resume Outbox message 使用固定长度 UUIDv5 标识，原始 task id、attempt number 和状态保留在 payload/metadata 中，避免超过数据库 128 字符边界。

### 3. Resume 使用 Transactional Outbox

训练恢复采用 at-least-once 语义：checkpoint 的初步文件检查在事务外完成；事务内重新读取 Task 和恢复 metadata，通过 CAS 切换为 `queued`，计算下一 attempt number，并同时追加恢复事件和 QueueOutboxMessage。Task 的 `current_attempt_no` 在 Worker 原子 claim 成功时才推进。Worker 消费时再次核验 checkpoint 和 attempt identity。

当前 Outbox 表只有 `message_id` 主键，没有独立的 `(task_id, attempt_no)` 列或唯一约束。Resume 必须统一使用由 task id 与 attempt number 生成的固定长度 UUIDv5 message id；同一逻辑轮次因此命中同一主键，payload 中的 task id/attempt number 由 claim 再次交叉校验。本阶段不宣称 exactly-once，也不为 resume 建立独立队列协议。

### 4. Conversion 使用可恢复总 deadline、数据库 reservation 和原子提交点

首次领取 Conversion Attempt 时，从 Task 中不可变的 conversion plan/task spec 解析并固化 UTC `deadline_at`、`timeout_seconds`、策略来源和格式覆盖结果；Queue metadata 只用于交叉校验。当前进程再根据 UTC 剩余时间构造 monotonic deadline；同一 Attempt 恢复时只读取 Attempt 固化值，不得重新获得完整预算。任何 helper 上限只能与 Attempt 剩余时间取较小值，不能得到独立完整预算。

Publication 的并发仲裁必须由 Task 数据库行上的内部持久字段承载，不能只写 JSON metadata 或文件 marker：

- `publication_state`：`null`、`reserved`、`published`、`registered`、`aborted`；
- `publication_token`；
- `publication_attempt_no`；
- `publication_updated_at`。

`begin_conversion_publication` 只允许在 Task 为 `running`、current attempt 匹配且 `publication_state IS NULL` 时 CAS 为 `reserved`。取消只允许在可取消状态且 `publication_state IS NULL` 时成功。此后的 `reserved → published/aborted → registered` 每一步都必须在 SQL `WHERE` 中同时核验 publication state、token、publication attempt、Task current attempt 和允许的 Task state，不能只在内存中比较 token。`reserved` 是数据库排他 reservation，仍可在 rename 前因 deadline 或错误转为 `aborted`；真正不可逆的文件提交点是原子 rename。字段只属于内部持久化和命令协议，不进入公开 Task API。

转换、输出结构检查、数值一致性检查和 runtime smoke 均在受监督 Attempt 子进程内执行。父进程只读取有界结果描述、核对 schema/路径/hash、检查取消与 deadline、建立发布栅栏、执行同文件系统原子 rename，并在单一 Unit of Work 中登记 ModelBuild/ModelFile 和 Task/Attempt 终态。

发布顺序固定为：

1. 检查取消、deadline、Attempt owner 和结果描述；
2. CAS 取得 `reserved` publication reservation；
3. 写入带 token 的 `publishing` marker；
4. 核验 reservation token，并在 rename 前最后检查 deadline；
5. 原子 rename；
6. CAS 标记 `published`；
7. 当前执行者或 recovery 在同一 Unit of Work 中完成 ModelBuild/ModelFile、Task/Attempt/Event 登记并标记 `registered`。

取得 `reserved` 后，取消返回冲突；rename 前发生 deadline 或技术错误时在同一终态事务把 reservation 标记为 `aborted`。rename 成功后，迟到的取消和原 deadline 不得回滚已提交文件。Recovery 以数据库 reservation、最终目录和 publication marker 三方事实收敛；数据库已有 reservation 而 marker 尚未写入时，必须按 token、Attempt、deadline、staging descriptor 和最终目录继续、修复 marker或安全标记 aborted，不能留下永久 reservation。只有没有跨过原子 rename 的 staging 可以回收。

### 5. 进程监督进入中立 Runtime 层

Conversion 使用的进程树、deadline、日志 drain 和 Windows Job Object 能力迁入 `backend/runtime/processes/`。这是服务应用层与 Worker 组装层都可依赖的中立运行时基础设施，不保留从旧 Worker 路径的兼容转发。

Windows 通过 bootstrap 保证 converter 只能在成功加入 Job Object 后启动；先请求协作退出，grace 到期再终止整个 Job。Job handle 覆盖 supervisor 生命周期并启用 kill-on-close。stdout/stderr 持续排空到有界文件和内存 tail，达到保留上限后仍继续 drain，避免管道反压死锁。

### 6. Node Pack timeout 不引入每节点隔离

Node Pack 保留 `defaultSeconds`、`maxSeconds` 和 `killGraceSeconds`。当前不增加图节点级 timeout override，节点业务参数中的同名字段也不能改变执行器 timeout。

- Preview：可信节点仍在 backend-service 进程内直接调用，只提供协作式 deadline/cancellation，不建立 Preview 队列或每节点子进程；
- 正式 Runtime：节点仍在长期 Runtime worker 内直接调用。每个 worker generation 创建一个 manager 与 worker 共享的 `multiprocessing.Event`；manager 不能依赖执行期间无人消费的 request queue 发送取消。只有具有 `node_pack_id` 和 manifest timeout policy 的 Node Pack invocation 通过 response queue 上报带 `node_invocation_id` 的 started/ended 生命周期；Core Node 不增加这组控制消息，仍只受 Workflow deadline。manager 用 invocation map 同时跟踪并行和重复节点，观察最早 deadline。任一 invocation 超时后设置共享 Event 取消整个 Run，第一次超时固化原因，force-kill 时刻取所有已超时 invocation 计算值中的最早值，不能被迟到 ended 或更长 grace 延后。grace 到期仍未返回 run result 时终止整个 Runtime worker，并按既有 desired state 恢复；
- 大图继续通过 LocalBuffer，节点参数和结果不新增数据面 IPC。

有效节点 deadline 为 Workflow 剩余时间与 `defaultSeconds` 的较小值。`maxSeconds` 只校验 `defaultSeconds <= maxSeconds`，为将来经过单独版本化设计的 override 保留上限。

Timeout policy 从当前 Runtime worker 已启用的 Runtime Registry/Node Pack manifest 解析；invocation 开始后固化本次 budget。当前不引入 NodeDefinition 或 Node Pack 版本锁定机制，新 worker generation 按其当前 Registry 重新解析。

### 7. 契约和发行结果必须同步验证

后端公开 Task 状态使用正式 enum/Literal，使 OpenAPI 明确包含 `queued`、`running`、`paused`、`succeeded`、`failed`、`timed_out`、`cancelled`。前端当前手工维护最小公开类型，因此手工同步 `generated/api.ts`，并用契约测试防止后续漂移。

源码修改完成后只通过 `assemble-release` 重新生成 NVIDIA 发行包，不手工编辑 `release/`。发行门禁必须确认 training profile 的 `max_concurrent_tasks=1`、中立 runtime/processes 包已收集、bundled Python 可导入，并通过 Windows bootstrap smoke。

## 保持不变的边界

- 不引入 CUDA 隐藏排队、自动重试或改变训练 profile 并发；Training 与 CUDA Conversion 使用既有跨进程 lease，训练 profile 保持 1。
- 不引入 Deployment Channel；稳定 Workflow Runtime/Trigger 继续通过 App Version、revision 和 generation 切换。
- 不改变 `save_location` 的 ObjectStore 相对路径和磁盘绝对路径契约。
- 不改变 LocalBuffer、mmap 和 ZeroMQ 的图片数据面边界。
- 不修改模型结构、权重加载、前处理、后处理和数值容差，不以逐位相同替代既有准确率门禁。
- 不为可信 Core/Custom Node 引入权限沙箱、每节点进程或通用 RPC。

## 未采用方案

- **用 TaskEvent 任意回写状态**：无法表达合法命令和终态不可变规则，容易让旧执行者覆盖取消。
- **Resume 先提交数据库再直接 enqueue，或先 enqueue 再提交数据库**：均存在进程崩溃窗口。
- **只保存 monotonic deadline**：不能跨进程和重启恢复同一 Attempt 的剩余预算。
- **只在父进程阻塞操作前后检查 deadline**：不能形成硬 timeout。
- **只用 Task state/current attempt 或 JSON metadata 表示 publication fence**：`running → running` 不能阻止并发取消，文件 marker 也不能参与数据库 CAS。
- **rename 后接受取消并删除发布结果**：会形成 Task 状态与已发布文件矛盾。
- **每节点创建隔离进程或串行 Preview worker**：破坏可信本地节点的低延迟热路径，并增加队列与生命周期复杂度。
- **节点级 timeout override**：当前没有明确产品契约，会把执行器 timeout 与节点业务参数混在一起。
- **手工修改生成发行目录**：会让源码、profile 和发布 manifest 漂移。

## 影响

- Task 状态入口更少，Worker 和业务服务需要迁移到命令 API；旧的状态事件写入入口会删除而不保留兼容分支。
- Task publication 内部字段需要一条兼容 SQLite、MySQL 和 PostgreSQL 的 Alembic migration；升级期间先排空旧协议的活动 Conversion，不维护双写兼容路径。
- Conversion 的实现会拆成受监督工作进程、父进程提交协议和 recovery 三部分，但发布结果与 Task 状态的关系将可证明、可恢复。
- Preview 仍保持最低调用开销；正式 Runtime 以 worker 为故障域获得 Node Pack 硬超时能力。
- 全链需要新增竞争、崩溃、恢复、Windows 进程树、WebSocket 和发行组装门禁。
