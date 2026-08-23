# 任务执行与运行时可靠性实施基线

## 状态与职责

状态：**设计已冻结，可以按阶段开始实现；代码尚未完整落地**。

本页是 [ADR-0006](../decisions/ADR-0006-task-execution-and-runtime-reliability.md) 的唯一详细实施基线，用于约束 Task、Training Resume、Conversion、前端 Task 状态和 Node Pack timeout 的后续改动。各架构专题在对应阶段通过门禁前仍描述当前代码行为，不能引用本页后就把目标状态视为已完成。

本页不是会话记录，也不保存一次性测试输出。每个阶段完成后应把稳定事实合并到对应架构/API/运维文档，并更新本页状态；全部阶段完成后删除本实施清单，只保留 ADR 和正式专题文档。

“可以开始实现”只授权从阶段 0 开始按顺序落地，不代表可以一次性跳过阶段门禁。实现若发现本页状态机、持久字段或故障恢复矩阵与真实约束矛盾，必须先修正 ADR 与本页并重新审查，再改变语义；不得在代码中临时增加兼容分支、隐藏重试或第二套协议。

## 目标

- Task 取消、超时、成功和恢复通过明确命令与 CAS 收敛，旧 Worker 不能覆盖权威终态。
- Training resume 的状态更新与重新入队具备 Transactional Outbox 崩溃一致性。
- Conversion 在一个可跨重启恢复的总 deadline 内完成重计算和验证，并通过不可逆发布栅栏保证文件、数据库和 Task 状态一致。
- Preview 保持进程内高性能调用；正式 Workflow Runtime 对 Node Pack timeout 提供 worker 级硬终止。
- 后端、前端、WebSocket 和发行包对全部 Task 状态、profile 与运行时模块保持一致。

## 不可偏离的约束

以下行为已确认正确，不属于本轮重构范围：

- Training profile 的 `max_concurrent_tasks` 保持 1；不增加 CUDA 等待队列、隐藏重试或按 Deployment 总数限流。
- Workflow App Version、revision、generation、稳定 Runtime/Trigger id 保持现有设计，不实现 Deployment Channel。
- Core、内置和第三方 Node Pack 均按可信本地代码执行；Preview 不创建子进程或串行任务队列。
- 正式 Workflow Runtime 仍是独立常驻 worker；节点硬超时以整个 worker 为最小可强制终止边界。
- 图片继续使用 LocalBuffer；mmap/ZeroMQ 只传控制信息和引用，不把大图改回 Base64 跨进程复制。
- `save_location` 同时支持 ObjectStore 根目录下的原始相对位置和本机磁盘绝对路径；本轮不自动增加 project id 前缀，也不修改其公开语义。
- 不修改模型结构、权重、前处理、后处理、训练精度策略或推理数值容差。
- `release/<profile-id>/` 始终由 `assemble-release` 生成，不能手工修补。

## 当前差距与目标状态

| 范围 | 当前需收敛的差距 | 本轮目标 |
| --- | --- | --- |
| Task 状态 | 通用事件仍可能间接改变状态；取消与旧 Attempt 回写存在竞争 | 命令级状态机、Task CAS、终态不可变 |
| Attempt | 终态入口分散，写入权 fence 信息不统一 | 单一 finalizer 核验 worker、heartbeat 和 queue lease |
| Training resume | 部分路径仍存在 DB/Queue 双写窗口 | 四条 resume 路径统一 Transactional Outbox |
| Conversion deadline | 子进程 timeout 已有基础，但跨恢复 deadline 与父进程提交边界不完整 | 持久 UTC deadline、进程内 monotonic 剩余预算、单一发布栅栏 |
| Conversion recovery | publication marker 已有基础，迟到取消和 rename 后恢复规则需收敛 | rename 前可中止，rename 后只允许完成登记 |
| Process supervisor | 公共实现仍位于 Worker 组装层，Windows 绑定窗口和日志边界需统一 | `backend/runtime/processes/` 中立实现与 bootstrap |
| 前端 Task 状态 | 手工类型、徽标和 store 遗漏 `paused`、`timed_out` | 完整 OpenAPI enum + 手工同步 + 契约门禁 |
| Node Pack timeout | manifest 字段与正式执行语义没有完整闭环 | Preview 协作式，正式 Runtime worker 级硬终止 |

## 目标状态机与命令 API

### TaskRecord 状态矩阵

| 当前状态 | 命令 | 目标状态 | 说明 |
| --- | --- | --- | --- |
| `queued` | `claim_task_execution` | `running` | 必须绑定当前 attempt/lease，并在同一事务创建 Attempt |
| `queued` | `cancel_task` | `cancelled` | 单事务 CAS |
| `running` | `request_task_pause` | `running` | 只保存控制意图，不提前声称 checkpoint 已完成 |
| `running` | finalizer pause | `paused` | Worker 已在 batch 安全点停止，并验证最近完整 epoch checkpoint |
| `running` | finalizer complete/fail/timeout/cancel | 对应终态 | 终态事件只在 CAS 成功后写入 |
| `paused` | `resume_task_with_outbox` | `queued` | 新 attempt number |
| `paused` | `cancel_task` | `cancelled` | 不再允许恢复 |
| `failed` | `resume_task_with_outbox` | `queued` | 必须存在有效 checkpoint |
| `succeeded` / `timed_out` / `cancelled` | 任意普通执行命令 | 拒绝 | 不可变终态 |

不存在 Attempt 时不能调用 finalizer，因此 `queued` 不直接由 finalizer 变成 failed/timed_out。Outbox 投递异常时 Task 保持可观察的 `queued`，Dispatcher 按现有有界退避继续持久投递；这属于消息交付重试，不是 Worker 执行重试。当前不引入隐式排队期限；将来如需 submission expiry，必须增加独立命令和公开契约。

`TaskEvent` 继续支持 `status`、`result`、progress、log 和 metadata。普通 `append_task_event()` 是无 Attempt 的服务侧纯追加入口，不能修改 TaskRecord；普通调用携带 `payload.state` 时必须拒绝。Worker 的 log/result observation 使用 `append_task_attempt_event()`，必须核验当前 Attempt owner、heartbeat、Queue message/attempt identity；失去执行权的旧 Worker 不能继续向权威事件流追加。需要更新 TaskRecord 进度快照时，Worker 使用 `record_task_progress()`，在相同 fence 下只更新 progress 和允许的 metadata patch，并在同一 Unit of Work 追加 progress 事件。专用状态命令同样在一个 Unit of Work 中完成 Task CAS 和携带新 state 的 TaskEvent 追加，提交后再发布事件。因此 TaskEvent 是状态变化的审计结果，不是状态变化的命令来源。

暂停分为两个动作：控制面调用 `request_task_pause()` 只写持久控制请求，Task 保持 `running`；Worker 在 train/validation batch 安全点观察到请求后停止开始新 batch，丢弃当前未完成 epoch，将最近完整 epoch 的内存 checkpoint bytes 持久化或复用已有持久引用，再调用 finalizer 以 `paused` 同时结束当前 Attempt 并把 Task 变为 `paused`。暂停不得等待当前 epoch 结束，也不能把部分 epoch checkpoint 伪装为完整恢复点。`paused` 是 TaskAttempt 的合法终态，也是 Task 的可恢复状态，不能把暂停的 Attempt 记录成 `succeeded`。

### 训练暂停与完整 epoch checkpoint 协议

暂停响应和 checkpoint 保留是两个不同问题，统一契约如下：

1. YOLOX、YOLOv8/11/26 的 detection/classification/segmentation/pose/OBB 以及 RF-DETR detection/segmentation 都必须在每个 train batch 和 validation batch 完成后的安全点检查 attempt 级 `TrainingControlProbe`；不得只在 epoch callback 中检查。
2. `TrainingControlProbe` 每个 Attempt 只创建一个，内部只保存最近控制快照和 `next_poll_monotonic`。batch 安全点调用 probe 是进程内常数时间操作；只有达到默认 250 ms 观察间隔时才读取一次持久 Task 控制状态。它不创建后台线程、不增加控制队列、不自动重试，Worker/lease 恢复后从持久请求重新建立，因此既不把 SQLite I/O 放到每个 batch，也不会因进程内信号丢失暂停请求。
3. 观察到暂停后不再读取或执行下一个 batch。已经开始的 batch 允许完成必要的反向传播、设备同步和回调清理；因此正常暂停延迟上限是一个在途 batch（包含数据读取）加最多 250 ms 控制观察间隔，而不是一个 epoch。底层 CUDA、第三方算子或 DataLoader 已经阻塞时由独立 watchdog/终止协议处理，不能宣称 Python 回调可瞬时强杀。
4. 当前 epoch 的模型更新、optimizer/scheduler/scaler/EMA 状态、指标和部分验证结果全部视为未提交，不写入恢复 checkpoint。Worker 退出前释放本轮临时 tensor、梯度和 DataLoader 资源；恢复时重新加载最近完整 checkpoint，从被丢弃 epoch 的第一个 batch 重新训练。
5. 每次训练首次进入 batch 循环前建立 epoch 0 baseline bytes；从完整 checkpoint resume 时，该 checkpoint bytes 直接成为 baseline。warm start 只加载模型权重，仍须在 optimizer、scheduler、scaler、EMA 和 RNG 初始化后生成 epoch 0 完整 baseline，不能把仅含权重的 warm-start 文件冒充可恢复快照。
6. 每个完整 epoch 的训练、本轮应执行的验证和指标提交结束后，同步生成一份完整 checkpoint 到新的内存缓冲区。只有序列化成功、bytes 非空且 `completed_epoch`/模型/数据集/Attempt 身份自检通过后，才用新 bytes 替换上一份快照并开始下一 epoch。生成失败时保留旧快照用于错误说明，但当前 Attempt 必须 failed，不能继续训练。
7. 每个 Attempt 稳定状态只持有一个最近完整 epoch 快照，不保留内存历史，也不保留会继续变化的 `state_dict()` tensor 引用。为保证替换失败不破坏旧快照，生成期间允许短暂同时持有旧、新 bytes；专项门禁必须测量 checkpoint 序列化耗时、稳定内存和替换峰值内存，确认训练 profile 并发为 1 时仍满足主机容量。
8. 内存快照至少包含 model、optimizer、scheduler、AMP scaler、EMA、RNG、完整 epoch/global iteration、指标历史、训练配置、数据集/类别/模型身份和必要的框架 loop state。内存阶段不计算持久文件 hash，不执行 ObjectStore write、flush、fsync、原子 rename、publication pointer 或旧 Worker 文件 fencing。
9. 把现有 `resolve_training_checkpoint_decision()` 的职责和命名收敛为持久化决策，例如 `resolve_training_checkpoint_persistence_decision()` 与 `should_persist`。它继续按当前模型解析后的 `checkpoint_interval` 和 periodic、best、final、manual、pause、terminate 原因决定是否落盘；内存 completed-epoch snapshot 不受该函数阻止。旧 `should_serialize` API 在全部调用方迁移后删除，不保留兼容别名。
10. 周期、final、manual、pause 和 terminate 的完整 resume checkpoint 都接收当前内存 bytes。Attempt 内的 persistence coordinator 按 `completed_epoch`、内容身份和 checkpoint role 记录已持久引用；暂停遇到同一 epoch 已有可恢复的完整 checkpoint 时直接复用 object key，否则只写一次。模型专用 best/EMA/deployment artifact 若格式、权重或加载语义不同，保留现有专用生成逻辑，不能强制复用 resume bytes。
11. 暂停结果记录 `pause_requested_at`、`pause_observed_at`、`pause_observed_latency_ms`、`pause_completed_at`、`pause_completed_latency_ms`、`completed_epoch`、`discarded_epoch`、`discarded_train_batches`、`discarded_validation_batches` 和 checkpoint object key。页面进度回退并固定到 `completed_epoch`，不能保留被丢弃 epoch 的百分比造成已保存错觉。“一个在途 batch 加最多 250 ms”只约束 observed latency；completed latency 还包含已有 bytes 的持久化、校验和 finalizer 时间。
12. 暂停请求恰好发生在内存快照替换期间时，先完成本次内存生成和交换；成功后使用新 completed epoch，失败则 Attempt failed，不得开始下一 epoch。与训练自然完成竞争时，已经原子完成的 `succeeded` 优先；与 cancel 竞争时由 Task CAS 决定唯一终态。
13. RF-DETR 当前只支持单 GPU 或 CPU，平台入口也拒绝 `gpu_count > 1`。本轮只实现单进程 train/validation batch hook 和内存 Lightning checkpoint bytes，不增加 rank 广播、collective 或 DDP 门禁；未来启用 DDP 前必须另行设计跨 rank 一致快照与协同暂停。

各框架改造边界：

| 框架 | 当前差距 | 目标控制点 |
| --- | --- | --- |
| YOLOX | train batch callback 只上报进度，pause 只在 epoch callback 读取；validation evaluator 没有控制回调 | train batch callback 接入 probe；为 validation evaluator 增加 batch 安全点；完整 epoch builder 输出并替换唯一内存 bytes |
| YOLOv8/11/26 | 多条训练/验证链路已有 `control_callback`，但目前主要用于立即 terminate，pause 仍留到 epoch callback | 复用现有 callback 传递暂停决定，不另建线程/队列；共享内存快照与 persistence coordinator，不复制出不同语义 |
| RF-DETR | `on_train_batch_end` 只上报进度，`on_train_epoch_end` 才处理 pause；Lightning `ModelCheckpoint` 当前每 epoch 生成 `last` 文件 | 单进程 train/validation batch hook 检查 probe；使用完整 Lightning checkpoint payload 生成内存 bytes；移除每 epoch `last` 写盘，保留解析后的周期与模型专用 best/final 策略 |

RF-DETR 的底层 `TrainConfig.checkpoint_interval` 默认值当前为 10，但平台 `_build_train_config()` 会把未显式配置的应用请求解析为 5，`eval_interval` 解析为 1；因此“RF-DETR 默认一定是 10”不是当前平台链路事实。此次实现不顺带改变用户可见周期，只从最终解析后的 config 读取 checkpoint/evaluation interval，并删除快照逻辑中的硬编码默认值。后续若统一默认值来源，必须单独核对已有任务配置和公开 schema，不能借暂停改造静默改变训练行为。

RF-DETR 内存快照使用 Lightning 公共 `CheckpointIO` 扩展点：单 GPU/CPU Trainer 注入一个 attempt 级 checkpoint IO，内存目标把 Lightning 传入的完整 checkpoint dict 同步编码到 `BytesIO`，普通持久目标委托标准 IO。`on_fit_start` 在 model、optimizer 和 scheduler 均已挂接后生成 epoch 0 baseline；完整 epoch 的验证与指标回调结束后生成下一快照。当前每 epoch `last` ModelCheckpoint 删除，周期完整 resume checkpoint 改由 persistence coordinator 写当前 bytes；`BestModelCallback` 生成的 regular/EMA 部署兼容 artifact 保持原专用格式和指标逻辑。不得直接新增对 `_checkpoint_connector` 私有接口的依赖，也不得通过临时磁盘文件模拟内存快照。

单个 Attempt 的目标数据流固定为：

```text
初始化完整训练状态
  → serialize(epoch 0) 到局部 bytes
  → current_snapshot = epoch 0 bytes

每个完整 epoch 结束
  → serialize(completed epoch) 到 new bytes
  → 自检成功
  → current_snapshot = new bytes
  → 释放旧 bytes
  → persistence decision（只决定是否写盘）

batch 安全点观察 pause
  → 不再启动下一 batch
  → 丢弃当前未完成 epoch
  → persist-or-reuse(current_snapshot)
  → 验证持久引用
  → finalizer(paused)
```

不得采用的简化方式：在暂停时直接从已被当前 epoch 修改的模型现建 checkpoint、保留会继续变化的 tensor 引用、把 batch index 写成 epoch、等待 epoch 结束、依赖较旧周期 checkpoint 冒充最近完整 epoch，或通过强杀 Worker 跳过持久化/finalizer。这些方式分别会保存部分训练状态、污染快照、伪造进度、响应过慢、无提示丢失完整 epoch，或破坏资源和状态一致性。

目标应用服务入口：

- `claim_task_execution(...)`
- `request_task_pause(...)`
- `append_task_attempt_event(...)`
- `record_task_progress(...)`
- `cancel_task(...)`
- `resume_task_with_outbox(...)`
- `finalize_task_execution_attempt(...)`
- `begin_conversion_publication(...)`
- `complete_conversion_publication(...)`

### Repository CAS

Task repository 提供等价于以下语义的原子操作：

```text
try_transition_task(
  task_id,
  expected_states,
  expected_current_attempt_no,
  owned_field_patch,
)
```

`owned_field_patch` 只能包含当前命令拥有的字段。状态命令不得用完整 `updated_task` 覆盖并发写入的 progress/metadata；进度命令不得改变 state、result、finished_at 或 publication 字段。转换必须在 SQL `WHERE` 条件中包含 expected state 和 current attempt，不采用“先读后无条件写”。`record_task_progress` 还必须核验 Attempt owner、heartbeat、Queue message/attempt identity 和 Task 为当前 `running` Attempt；取消或终态 CAS 胜出后，迟到进度不得继续修改快照。`cancel_task` 在同一 Unit of Work 内核验 Task 当前状态、当前 attempt 和 Conversion publication reservation；取消 running Task 时同一事务把当前 running Attempt 标记为 cancelled。外部 watchdog 的 timeout 命令也必须以 current attempt 为 fence 同时结束 Task/Attempt。

### 原子 claim

`claim_task_execution(...)` 先核验 Queue name、message id、queue attempt count、lease identity 和 payload attempt number，再按数据库事实进入以下唯一分支：

| 分支 | 前置数据库事实 | 同一 Unit of Work 内的行为 | 是否进入业务执行 |
| --- | --- | --- | --- |
| 首次领取 | Task=`queued`、payload attempt=`current_attempt_no+1`、该 Attempt 不存在 | 创建 running Attempt；CAS Task 为 `running` 并推进 current attempt；追加唯一 started status event | 是 |
| 同 lease 重复投递 | Task/Attempt 均为当前 `running`，Queue message、owner、heartbeat 和 recovery identity 没有形成合法接管 | 不改数据库，不重复 started event | 否，抑制重复消息 |
| lease recovery | Task/Attempt 均为当前 `running`，同一 Queue message，且 recovery count/新 lease 能证明旧 lease 已回收 | 以旧 owner/heartbeat/recovery count 为 fence 原子接管同一 Attempt；Task 不变，不重复 started event | 是，由新 owner 继续本 Attempt |
| finalization recovery | Task 与 Attempt 已由同一 Attempt 收敛到匹配终态，但 Queue ack 丢失 | 返回持久终态供消费侧 ack；不写事件、不重放业务 | 否 |
| 协议矛盾 | Attempt 已终态但 Task 非终态，或新协议下 Task 终态但 Attempt 仍 running | 拒绝业务执行、保留记录并报告维护错误 | 否 |
| 过时/越号 | attempt 小于或大于唯一合法轮次 | 过时消息幂等抑制；越号消息拒绝并报告 | 否 |

首次领取分支中，Attempt 创建、Task CAS 或 event 写入任一步失败时整个事务回滚。新 Task 初始 `current_attempt_no=0`，首次 claim 领取 Attempt 1。Resume 事务只计算下一轮并写入 Outbox，不提前修改 `current_attempt_no`；该字段始终表示最近已经成功领取的 Attempt，而不是排队 reservation。

阶段 1 发布前停止正式 Task Worker，并确认不存在 running Task/Attempt；queued Task 可由新 claim 协议继续领取，paused Task 保持可恢复。完成迁移后不保留“Attempt 已创建但 Task 仍 queued”的兼容分支。

### Attempt finalizer

统一接口语义：

```text
finalize_task_execution_attempt(
  attempt_id,
  attempt_outcome,
  error_code,
  error_message,
  result,
  metadata,
  expected_worker_id,
  expected_heartbeat_at,
  expected_queue_message_id,
  expected_queue_attempt_count,
)
```

实现规则：

1. 通过 `attempt_id` 读取 Attempt，并派生 task id 与 attempt number。
2. 核验 worker id、heartbeat owner、Queue message id、Queue attempt count 和 Task current attempt。
3. `attempt_outcome` 只允许 `paused`、`succeeded`、`failed`、`timed_out`、`cancelled`；Attempt 仍为 running 且 fence 一致时执行 CAS。
4. `paused` 只允许具备 checkpoint 语义的训练任务，并且内存快照已成功持久化或复用已有持久引用，最终文件 hash、身份和 `completed_epoch` 已验证；同一事务把 Attempt 和 Task 都改为 `paused`。其他 outcome 按 Task 状态矩阵写入终态。Task 已由同一 Attempt 写入更详细终态时只结束尚未终结的 Attempt。
5. 只在本次命令实际推进 Task 终态时追加唯一终态事件；已有业务终态事件时不追加第二条通用事件。
6. 事务提交后发布内部 event bus；发布失败不回滚数据库，WebSocket 通过持久化事件补发。
7. 重复调用发现 Attempt 已终态时返回已有结果，不重复写事件、文件或业务记录。

固定长度标识：

```text
task-started-{uuid5(namespace, "attempt:{attempt_id}:running").hex}
task-terminal-{uuid5(namespace, "attempt:{attempt_id}:{state}").hex}
queue-resume-{uuid5(namespace, "task:{task_id}:attempt:{attempt_no}").hex}
```

## 分阶段实施

### 阶段 0：冻结基线和保护现有正确行为

先增加或固定回归测试，避免可靠性重构改变产品边界：

- Training profile 并发为 1，GPU busy 返回明确错误，不排队、不自动重试。
- Preview 直接调用可信节点，不创建进程、线程池队列或跨进程数据复制。
- 正式 Runtime/Trigger 的稳定 id、revision 和 generation 行为保持不变。
- LocalBuffer 图片引用、mmap 控制信息和 `save_location` 相对/绝对路径行为保持不变。
- 模型输出用当前模型专用 tolerance 比较，不要求跨设备逐位相同。
- 记录当前 Task、Conversion、Workflow Runtime 的功能、延迟和资源释放基线；训练暂停基线必须证明现状会等待 epoch 结束，防止后续测试误把旧行为当成目标。

阶段门禁：基线测试可重复运行；变更范围内不存在未解释的既有失败；源码 training profile 明确为 1。

### 阶段 1：Task CAS、取消竞争与 Attempt finalizer

1. 增加命令级状态矩阵和 Task repository CAS。
2. 将 Queue claim、Attempt 创建/接管、Task `running/current_attempt_no` 和 started event 合并为原子 `claim_task_execution`。
3. 增加 `append_task_attempt_event`、`record_task_progress` 的 Attempt/lease fence 和字段级 patch；普通事件改为无 Attempt 的服务侧纯追加。
4. 将 `request_task_pause` 与“batch 安全点停止、内存快照持久化/复用、finalizer pause”拆开；TaskAttempt state 增加 `paused`，Queue complete metadata 必须保留该 outcome。
5. 将 `cancel_task` 改为单事务 CAS，并把 `timed_out` 纳入不可取消终态。
6. 实现统一 Attempt finalizer 和固定长度终态 event id。
7. 先迁移 detection 相关 Worker，再覆盖全部 Task 种类：dataset import/export、training 的 classification/segmentation/pose/OBB/RF-DETR/YOLOX、evaluation、conversion 和异步 inference。不能只搜索 Worker 文件，还要迁移业务 service 中直接追加状态/结果事件的路径。
8. 删除普通 TaskEvent 任意改变 Task 状态、结果、metadata、progress 和隐式 `queued → running` 的旧入口，不保留兼容适配。
9. 迁移期间，业务服务已经写入更丰富终态时 finalizer 不得覆盖或重复发事件；迁移完成后丰富错误 payload 直接交给 finalizer。
10. 将 checkpoint policy 从“是否序列化”改为“是否持久化”，统一 CompletedEpochSnapshot 和 persistence coordinator；更新全部调用方后删除旧 `should_serialize` 契约。
11. 按“训练暂停与完整 epoch checkpoint 协议”统一改造 YOLOX、YOLOv8/11/26 全任务和 RF-DETR：建立内存 epoch 0 baseline、每个完整 epoch 生成并替换唯一不可变 bytes，在 train/validation batch 安全点停止，不保留各框架旧的 epoch-only pause 分支或每 epoch `last` 文件写入。
12. 增加静态门禁：除状态命令模块外不存在携带 `payload.state` 的普通 append；Worker 不调用无 fence 的普通 append；所有运行中进度快照都经过 `record_task_progress`；所有 Queue Worker 都经过统一 claim/finalizer；训练 pause 控制不只出现在 epoch callback；非持久化 epoch 不调用 ObjectStore/checkpoint writer。

必须验证：

- cancel 与 success/fail/timeout 并发，只有一个权威终态；
- pause request 不提前改变状态；Worker 最迟在当前 train/validation batch 安全结束后观察暂停且不再开始新 batch，不等待当前 epoch 结束；
- epoch 1 首批、epoch 中段、最后一个 batch、validation 中段和内存快照替换期间请求暂停，均只发布最近完整 epoch checkpoint；当前 epoch 的模型、optimizer、scheduler、scaler、EMA、指标和部分验证状态不进入 checkpoint；
- 从 paused 恢复时从 `completed_epoch + 1` 的首批重新执行，训练结果与从同一完整 checkpoint 正常恢复的既有数值容差一致；
- 没有 pause/terminate/manual 控制时，任意数量 batch 不产生 checkpoint 文件写入；一个 epoch 若没有 periodic、best、final、manual、pause、terminate 任一持久化原因，完成后 ObjectStore/checkpoint writer 调用次数为 0；
- 暂停时对最近完整 epoch 最多新增一次 checkpoint 写入；该 epoch 已有等价完整持久 checkpoint 时直接复用 object key，新增写入为 0；
- baseline/完整 epoch 内存快照生成失败时不能开始下一 epoch；暂停持久化失败或 hash/身份不匹配时不能进入 paused，必须形成明确 failed；
- 内存快照稳定状态只有一份，替换峰值内存有界且连续多 epoch 不增长；
- `pause_observed_latency_ms` 满足一个在途 batch 加控制观察间隔的目标，`pause_completed_latency_ms` 独立覆盖写盘、校验和 finalizer；
- RF-DETR 不产生每 epoch `last` 文件，同时保留平台解析后的 periodic、best 和 final 结果；单 GPU/CPU 行为不变；
- 迟到 progress/metadata patch 不能覆盖 cancel、paused 或其他终态；
- Attempt insert、Task running/current attempt 和 started event 任一点失败都原子回滚；
- 首次 claim、重复 delivery、lease recovery 和 finalization recovery 均符合相同 attempt number 规则；
- `timed_out` 和 `cancelled` 不能被旧 Worker 改写；
- heartbeat、worker id、queue message 或 queue attempt 不匹配时拒绝写入；
- finalizer 重放不产生重复 event；
- 数据库提交后 event bus 失败，权威 GET 与 WebSocket 补发仍正确；
- 在 Task 更新、Attempt 更新、Queue ack 各崩溃点恢复后状态可收敛。

### 阶段 2：Training resume Transactional Outbox

只迁移现有四条 resume 路径，不重写已经使用 Outbox 的新任务创建链路。

1. 在事务外检查 checkpoint 文件存在性和基本可读性，避免持有长 SQLite 写事务。
2. 事务内重新读取 Task、业务训练记录和 checkpoint metadata。
3. 只允许 `paused` 或 `failed` 恢复；通过 CAS 切换为 `queued`，计算 `next_attempt_no=current_attempt_no+1`，但不提前修改 `current_attempt_no`。
4. 同一事务追加包含 next attempt number 的 resume event 和确定性 QueueOutboxMessage。
5. Dispatcher 保持 at-least-once 投递；Worker 通过 `(task_id, attempt_no)` claim 去重。
6. Worker 通过原子 `claim_task_execution` 严格领取 Outbox 指定轮次，并在开始执行前再次核验 checkpoint，防止提交后文件被移动或删除。

Dispatcher 对未送达消息使用现有 Outbox `pending/attempt_count/last_error` 和有界退避持续重试，并写入明确日志；它不得创建新的 attempt number，也不得重放已经被 Worker 领取的训练执行。checkpoint 在 claim 后复核失败时，由当前 Attempt finalizer 明确收敛为 failed，不自动再次 resume。

当前 `queue_outbox_messages` 只有 `message_id` 主键，没有 `(task_id, attempt_no)` 独立字段或唯一约束。本阶段统一使用 `queue-resume-{uuid5(namespace, "task:{task_id}:attempt:{attempt_no}").hex}` 作为 message id；所有四条 resume 命令必须调用同一个 builder，依靠确定性主键实现同一轮次幂等，payload 中的 task id/attempt number 由 Worker claim 交叉校验。因此阶段 2 不新增 Alembic revision，也不增加重复索引或从 JSON payload 派生数据库列。

必须验证：事务回滚、提交后进程退出、Dispatcher 重放、重复 Queue message、checkpoint 在各时点丢失，以及四种模型训练恢复链路。

### 阶段 3：最小抽取公共进程监督器

本阶段只移动 Conversion 治理需要的公共能力，不以“清除全部 application → workers 依赖”阻塞 P1 修复。

目标目录：

```text
backend/runtime/processes/
├─ process_tree_supervisor.py
├─ bounded_log_sink.py
├─ attempt_deadline.py
└─ windows_job_bootstrap.py
```

要求：

- 行为保持一致地迁移调用方，再在中立层完成 deadline、取消、日志和 Windows Job 治理。
- 删除旧 Worker 路径实现，不建立 re-export 或双实现兼容层。
- 同步项目结构、打包收集规则和 bundled Python import smoke。
- 剩余 application → workers 反向依赖记录到阶段 7 统一清理。

Windows bootstrap 必须先加入 Job Object，再启动真正 converter；绑定失败时 converter 不得运行。停止顺序为协作式退出、等待 grace、`TerminateJobObject`、等待 force-kill completion。Job handle 一直持有并启用 kill-on-close。

### 阶段 4：Conversion 端到端 deadline、数据库 reservation 和恢复

#### Schema 与迁移

在 `tasks` 增加仅供内部命令和 Repository 使用的字段，不加入公开 Task API：

- `publication_state`：`String(32)` nullable，非空值只允许 `reserved`、`published`、`registered`、`aborted`；
- `publication_token`：`String(64)` nullable，reservation 建立后为固定长度随机 token；
- `publication_attempt_no`：`Integer` nullable，非空时必须大于 0；
- `publication_updated_at`：`String(64)` nullable，保存带时区 UTC ISO 时间。

CheckConstraint 必须保证四列要么全部为空，要么 state 合法且 token、正数 attempt number、updated_at 全部存在，不能允许 state 为空但残留 token 的半状态。增加 `(publication_state, publication_updated_at)` recovery 索引。Alembic migration 必须验证 SQLite、MySQL 和 PostgreSQL；历史终态 Task 保持这些字段全部为空。

本阶段同时增加 `python -m backend.maintenance.main verify-task-runtime-upgrade` 预检，并把它写入生产升级步骤。预检必须通过 SQLAlchemy Core/reflection 只读取旧 schema 已存在的列，不能先用包含新 publication 字段的 Task ORM 查询旧数据库。它按代码中的 canonical conversion task kinds 查询 Task/Attempt/Queue Outbox：停止 Conversion Worker 后，只要仍有旧协议的 queued/running Conversion Task、running Conversion Attempt 或未完成的 Conversion Outbox，就拒绝升级并列出 id；不得靠人工目测。Alembic revision 在执行 DDL 前重复最小活动任务检查，防止跳过预检直接升级。

生产顺序固定为：停止 backend/Worker/Runtime 写入 → 使用新发行包的 maintenance 预检旧 schema → 备份数据库与 publication 目录 → `alembic upgrade head` → 启动新服务并运行 recovery smoke。确认排空后再升级；不实现旧 marker 与新 reservation 的双写兼容路径。

#### 固定默认值

| 参数 | 默认值 |
| --- | --- |
| 基础总 Attempt timeout | 7200 秒 |
| 包含 TensorRT 的格式覆盖 | 10800 秒 |
| 多格式任务 | 取适用总预算的最大值 |
| cancel/deadline poll | 1 秒 |
| terminate grace | 15 秒 |
| force-kill 后等待 | 5 秒 |
| stdout 文件上限 | 16 MiB |
| stderr 文件上限 | 16 MiB |
| stdout/stderr 内存 tail | 各 64 KiB |
| 子进程结果 descriptor 上限 | 1 MiB |

这是单一总 Attempt deadline，不增加会重新计时的 stage deadline。日志超过保留上限后停止写入保留文件，但必须继续排空 pipe。

#### Deadline 固化

Timeout policy 的事实来源是 Task 中不可变的 conversion plan/task spec；Queue metadata 只作交叉校验，不能覆盖 Task。首次 claim 在 Attempt metadata 原子保存：

- UTC `deadline_at`；
- `timeout_seconds`；
- timeout policy source；
- 匹配的目标格式和 override 结果。

当前进程使用 UTC 剩余量构造 monotonic deadline。lease recovery 或进程重启只读取 Attempt 中的固化策略与 `deadline_at`；剩余时间小于等于零时直接按 timeout 收敛，不能重新分配 7200/10800 秒。`helper_timeout_seconds` 不再形成独立预算，任何 helper 的有效 timeout 都是配置上限与 Attempt remaining 的较小值。

#### 子进程与父进程职责

受监督子进程负责：

- 目标格式转换；
- 输出结构、非空和配对文件检查；
- 来源与目标数值一致性检查；
- OpenVINO/TensorRT runtime smoke；
- 文件 size/hash 计算；
- 写入有界 JSON result descriptor。

父进程只负责：

- 解析固定 schema 的 descriptor；
- 验证 descriptor 和文件均位于 Attempt staging 范围；
- 核对 manifest、size 和 hash，不重复执行 runtime smoke；大文件 hash 使用分块读取，并在块间检查 deadline 和 reservation owner；
- 检查取消/deadline；
- 建立数据库 publication reservation；
- 原子 rename；
- 单 UoW 登记 ModelBuild/ModelFile、Task/Attempt 终态和 TaskEvent。

#### Stop reason

supervisor 原子记录首次观察到的 `completed`、`cancelled`、`timed_out` 或 `setup_failed`。已有权威 Task 终态优先于旧执行者的本地观察；最终数据库 CAS 和 publication reservation 决定是否允许发布，不能只依赖时间先后日志。

#### Publication 顺序

```text
child success
  → 读取并核验 result descriptor
  → 检查 cancel/deadline
  → DB CAS: publication_state null → reserved，并固化 token/attempt
  → 写入带相同 token 的 publishing marker
  → 核验 reservation，并最后检查 deadline
  → 同文件系统原子 rename
  → DB CAS: reserved → published
  → 写 published_pending_registration marker
  → 单 UoW：ModelBuild/ModelFile + Task/Attempt succeeded + Event
             + publication_state published → registered
  → 写 registered marker
```

规则：

- reservation 前取消或 deadline 到期：终止发布、清理本 Attempt staging，并按权威终态收敛。
- `begin_conversion_publication` 的 CAS 与 `cancel_task` 竞争同一 Task 行。取消只允许 `publication_state IS NULL`；reservation 胜出后取消返回 409。
- `reserved → published`、`reserved → aborted` 和 `published → registered` 的 CAS 都在 SQL `WHERE` 中核验 publication state、token、publication attempt number、Task current attempt 和该步骤允许的 Task state；恢复者不能只凭 marker 或进程内 token 推进数据库。
- `reserved` 不是文件不可逆点。rename 前 deadline 或技术错误必须 CAS 为 `aborted`，并在同一终态事务把 Task/Attempt 收敛为 `timed_out` 或 `failed`。
- rename 成功后：视为文件提交已发生。迟到取消返回 409，原 deadline 不再阻止 recovery 登记。
- 绝不形成“Task cancelled/timed_out，但同一 Attempt 的文件已作为成功 Build 发布”的新状态。

#### Recovery 矩阵

| 数据库/文件观察状态 | Recovery 行为 |
| --- | --- |
| DB 为 `reserved`，marker 不存在，最终目录不存在 | 按 token、Attempt、descriptor、staging 和 deadline 重建 marker并继续，或 CAS 为 `aborted`；不能留下永久 reservation |
| DB 为 `reserved`，marker 存在，最终目录不存在 | 核验 token 后继续 rename；已过 deadline 时标记 `aborted` 并收敛 Task |
| DB 为 `reserved`，最终目录存在 | 原子 rename 已发生；验证 size/hash 后 CAS 为 `published` 并完成登记 |
| DB 为 `published` / marker 为 `published_pending_registration` | 不受原 deadline和迟到取消影响，完成或核对登记 |
| DB 为 `registered` 或已有完整 Build | 验证文件、Task 终态并修复 `registered` marker |
| DB 为 `aborted` 且最终目录不存在 | 回收未提交 staging；不得恢复发布 |
| DB 为 `aborted` 但最终目录存在，或 `published` 但最终目录不存在 | 保留现场并报告协议矛盾，不破坏性删除 |
| 文件、marker、DB 相互矛盾且无法证明安全操作 | 保留现场、报告明确告警，不破坏性删除 |

正常的已提交目录不能因为 Task 后来被取消、超时或删除而由通用 staging sweep 删除。只有数据库为 `aborted` 或能够证明从未跨过原子 rename 的 staging 可以回收。

必须验证：转换成功/失败/取消/超时、reservation/cancel 竞争、DB reservation 与 marker 之间崩溃、父子进程各阶段崩溃、Windows 子孙进程、日志大量输出、descriptor 越界或路径逃逸、大文件 hash 中断、rename 前后崩溃、DB 登记失败、recovery 重放，以及 ONNX/OpenVINO/TensorRT 当前真实模型门禁。

### 阶段 5：后端与前端完整 Task 状态契约

1. 后端公开 TaskRecord state 使用正式 enum/Literal，OpenAPI 必须列出全部状态。
2. 手工同步 `frontend/web-ui/src/shared/contracts/generated/api.ts`；当前项目未接入自动生成器，不能在文档中声称自动生成。
3. 同步 Task store、过滤器、徽标、详情页和中英文文案。
4. 增加 OpenAPI 状态集合与前端集合的契约测试。
5. 验证 `paused`、`timed_out` 的实时 WebSocket 事件、断线重连后的持久化事件补发，以及终态后的权威 GET。

完整集合固定为 `queued`、`running`、`paused`、`succeeded`、`failed`、`timed_out`、`cancelled`。前端不得把 `paused` 或 `timed_out` 折叠成 `failed`/`unknown`；展示可以复用色系，但公开状态值必须保留。

### 阶段 6：Node Pack timeout 闭环

保留 manifest 中：

- `defaultSeconds`
- `maxSeconds`
- `killGraceSeconds`

不增加节点实例 override。有效 deadline 为：

```text
min(workflow_remaining, node_pack.defaultSeconds)
```

`maxSeconds` 当前只校验 default 不越界。HTTP、数据库、相机等节点自身的业务 I/O timeout 仍由节点参数控制，但它是业务调用超时，不是执行器强制终止 timeout。

#### Preview

- backend-service 内进程直接执行可信 handler；
- 通过 execution context 传递 deadline/cancellation token；
- 节点在可中断点协作退出；
- 不创建每节点进程、全局串行 Preview worker、容量队列或隐藏重试；
- 无法协作退出的可信 Preview 节点不能被 Python 安全强杀，可能继续占用当前 Preview 请求线程直至 handler 自行返回；返回后记录已超预算事实，服务日志和页面说明必须明确这是可信代码的协作式限制，不能承诺超时瞬间一定返回，也不能伪装成硬隔离。

#### 正式 Runtime

当前 worker 取得 `invoke-run` 后同步执行整张图，执行期间不会继续消费 request queue，因此不能把协作取消设计成新的 request queue 消息。每个 Runtime worker generation 创建一个新的 `multiprocessing.Event`，同时保存到 manager handle 并作为 worker 启动参数传入：

- Event 在新 generation 创建时为 clear；旧 generation 的 Event 不复用。
- manager 在健康 worker 分派新 Run 前清理 Event；worker 不在收到请求后再次 clear，避免吞掉并发到达的取消。
- Event 注入 ExecutionControl 和节点上下文，协作节点在既有检查点响应。
- 任一节点超时后 manager 设置 Event，取消的是整个 Run，不尝试只取消一个并行分支。
- `deadline_monotonic` 只在同一台主机、同一系统 boot 内由 manager 与其子进程比较；它不持久化、不跨主机、不在 worker generation 间复用。持久化的 Workflow deadline 仍使用 UTC，manager 启动/恢复时重新计算本机 monotonic 剩余量。

节点生命周期通过 worker 已有 response queue 单向上报，不建立节点数据 RPC：

```text
node-started(run_id, node_invocation_id, node_id, pack_id,
             deadline_monotonic, kill_grace_seconds, worker_generation)
node-ended(run_id, node_invocation_id, node_id, worker_generation, outcome)
```

Graph Executor 为每次实际 handler 调用生成固定长度、线程安全且在 Run 内唯一的 `node_invocation_id`。只有 `NodeDefinition.node_pack_id` 非空且能从当前 Registry 解析 manifest timeout policy 的调用，才在进入 handler 前上报 started、在 `finally` 中上报 ended；ForEach 的每一轮和 Parallel 的每个实际 Node Pack 调用都有独立 id。Core Node 不发送这组消息，继续只受 Workflow 总 deadline，避免给核心推理热路径增加每节点控制 IPC。生命周期消息属于超时控制协议，不写入节点 payload，不改变节点公开输入输出，也不替代现有节点耗时记录。response channel 失效时仍由既有 Workflow 总 deadline 终止 worker，不能让控制异常绕过全局超时。

同一 node id 可能在 ForEach 中重复调用，也可能与其他节点并行，因此 manager 以现有 `node_invocation_id` 为唯一键维护：

```text
active_invocations[node_invocation_id] = {
  run_id, node_id, pack_id, deadline_monotonic,
  kill_grace_seconds, worker_generation
}
```

response loop 只更新 map，统一 monitor loop 观察最早 deadline，不为每个节点建立 timer thread。active invocation、Run timeout 和共享 Event 都保存在同一 handle 的 `state_lock` 边界内，并在匹配 generation 的 run result、worker exit 或 handle teardown 时统一清理。任一 invocation 到期后，manager 固化本次 Run 的第一次 timeout 原因、设置共享 Event；如果之后还有 invocation 到期，force-kill deadline 只能取更早值，不能被迟到的 `node-ended` 或更长 grace 延后。Run 级 timeout 不能被解除；grace 到期仍没有 run result 时终止整个 Runtime worker，由 manager 持久化明确的 node timeout 结果，再按既有 desired state 重启。本次 Run 不自动重跑有副作用的图。

Timeout policy 在 invocation 开始时从该 worker 当前已启用的 Runtime Registry/Node Pack manifest 解析并固化。当前不新增 NodeDefinition 或 Node Pack 版本锁定；新 worker generation 按其启动时 Registry 重新解析。内置 Core Node 没有 pack timeout 时只受 Workflow deadline，不能虚构默认 Node Pack policy。

必须验证：没有新增 per-node process、Preview 队列等待或后台泄漏线程；LocalBuffer owner/refcount 行为不变；普通节点完成后 invocation 正确移除；并行 invocation 使用不同 id；同一节点重复执行不互相覆盖；timeout 后迟到 node-ended 不能恢复 Run；旧 generation 的 Event/消息不能取消或终止新 worker；24 个推理调用、两个并行分支和长期 soak 无统计显著性能回退。

微秒级单点阈值不作为 CI 硬门禁。使用同机、同数据、预热后的 P50/P95 对比和资源泄漏检查判断回归。

### 阶段 7：分层清理、全链门禁和发行重组

1. 清理剩余 application → workers 反向依赖，应用层只依赖 port、domain 和中立 runtime infrastructure。
2. 删除迁移完成后的旧状态写入、旧 supervisor、兼容 re-export 和死配置。
3. 同步 Task、Conversion、Workflow Node、项目结构、开发/生产部署和运维恢复文档。
4. 执行后端完整 pytest、ruff、compile/import smoke、前端 typecheck/unit/build/E2E。
5. 验证 publication 字段 Alembic migration 的空库、历史库和 SQLite/MySQL/PostgreSQL 方言边界，并确认仓库仍为单一 head。
6. 执行竞争、崩溃、恢复、真实模型、Workflow/Trigger/deployment soak。
7. 只从源码执行：

```powershell
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-nvidia
```

8. 验证发行包 training profile 为 1、`backend/runtime/processes/` 已收集、bundled Python import 正常、Windows bootstrap smoke 和 full stack 启动通过。

全局告警门禁是“无新增项目自身 warning”。第三方依赖 warning 单独登记，不为追求表面零 warning 引入无关改动。

## 总体验收矩阵

### 一致性与故障注入

- cancel/success/fail/timeout 竞争不会产生双终态。
- 旧 worker、旧 heartbeat、旧 queue lease、旧 Runtime generation 不能写入或终止新执行者。
- Resume 在事务、Dispatcher、Queue 消费各崩溃点都能 at-least-once 收敛且不重复执行同一 attempt 副作用。
- Conversion 在子进程、日志、验证、publication、rename、DB 登记各崩溃点都能恢复到唯一可解释状态。
- 已发布文件不会因迟到取消或原 deadline 被回收；未提交 staging 不会永久泄漏。

### 准确率与功能

- YOLOX、Ultralytics、RF-DETR 的训练/验证/转换/部署公开链路保持原数值容差。
- ONNX/OpenVINO/TensorRT 的真实模型 smoke 与数值门禁通过。
- Task、业务详情、WebSocket、前端徽标和筛选对终态解释一致。
- Preview 与正式 Runtime 对同一节点保持相同 payload/参数语义。

### 性能与长期运行

- Preview 无新增进程启动、队列等待和 Base64 大图复制。
- Conversion 日志内存有界，pipe 持续排空，进程树无孤儿。
- Node Pack timeout 不改变正常节点热路径的数据面。
- 24 次 Workflow 推理调用、双并行分支和 Trigger 长期 soak 无统计显著回退、LocalBuffer 泄漏或 Runtime generation 误杀。
- Worker、Runtime 和发行包连续启停、崩溃恢复后无遗留 lease、staging、Job Object 或后台线程。

## 阶段完成记录规则

每个阶段只有在代码、专项测试、受影响的完整门禁和文档同步都完成后才标记完成。记录只保留“阶段状态、稳定结论、权威测试入口”，不粘贴日期化日志、机器路径、临时 task id 或一次性通过数量。

建议状态表：

| 阶段 | 状态 | 完成后应更新的正式文档 |
| --- | --- | --- |
| 0 基线冻结 | 待实现 | 本页 |
| 1 Task/finalizer | 待实现 | `architecture/platform/task-system.md`、Task API |
| 2 Resume Outbox | 待实现 | Task/Training 架构与 API |
| 3 Process supervisor | 待实现 | `architecture/project-structure.md`、部署打包 |
| 4 Conversion | 待实现 | `architecture/models/conversion-runtime.md`、运维恢复 |
| 5 完整 Task 状态契约 | 待实现 | Task API、前端状态规范 |
| 6 Node Pack timeout | 待实现 | `architecture/workflows/node-system.md`、Node Pack manifest |
| 7 全链与发行 | 待实现 | 开发、部署、运维入口 |
