# Task 执行、暂停与终态

## 当前实现

命令级 Task 状态机、Attempt claim/finalizer、Training Resume Outbox、Conversion 发布恢复和 Node Pack timeout 已实现；源码真实业务链路与发行基础设施已有验收。本文保留 Task 执行协议，转换与节点超时分别由正式专题定义，不再维护已完成的实施步骤。

## 状态与执行协议


### TaskRecord 状态矩阵

| 当前状态 | 命令 | 目标状态 | 说明 |
| --- | --- | --- | --- |
| `queued` | `claim_task_execution` | `running` | 必须绑定当前 attempt/lease，并在同一事务创建 Attempt |
| `queued` | `cancel_task` | `cancelled` | 单事务 CAS |
| `running` | `request_training_pause` | `running` | 只保存控制意图，不提前声称 checkpoint 已完成 |
| `running` | finalizer pause | `paused` | Worker 已在 batch 安全点停止，并验证最近完整 epoch checkpoint |
| `running` | finalizer complete/fail/timeout/cancel | 对应终态 | 终态事件只在 CAS 成功后写入 |
| `paused` | `resume_task_with_outbox` | `queued` | 新 attempt number |
| `paused` | `cancel_task` | `cancelled` | 不再允许恢复 |
| `failed` | `resume_task_with_outbox` | `queued` | 必须存在有效 checkpoint |
| `succeeded` / `timed_out` / `cancelled` | 任意普通执行命令 | 拒绝 | 不可变终态 |

不存在 Attempt 时不能调用 finalizer，因此 `queued` 不直接由 finalizer 变成 failed/timed_out。Outbox 投递异常时 Task 保持可观察的 `queued`，Dispatcher 按现有有界退避继续持久投递；这属于消息交付重试，不是 Worker 执行重试。当前不引入隐式排队期限；将来如需 submission expiry，必须增加独立命令和公开契约。

`TaskEvent` 继续支持 `status`、`result`、progress、log 和 metadata。普通 `append_task_event()` 是无 Attempt 的服务侧纯追加入口，不能修改 TaskRecord；普通调用携带 `payload.state` 时必须拒绝。Worker 的 log/result observation 使用 `append_task_attempt_event()`，必须核验当前 Attempt owner、heartbeat、Queue message/attempt identity；失去执行权的旧 Worker 不能继续向权威事件流追加。需要更新 TaskRecord 进度快照时，Worker 使用 `record_task_progress()`，在相同 fence 下只更新 progress 和允许的 metadata patch，并在同一 Unit of Work 追加 progress 事件。专用状态命令同样在一个 Unit of Work 中完成 Task CAS 和携带新 state 的 TaskEvent 追加，提交后再发布事件。因此 TaskEvent 是状态变化的审计结果，不是状态变化的命令来源。

暂停分为两个动作：模型训练服务的 `request_training_pause()` 通过 `execute_task_patch_event_command()` 写持久控制请求，Task 保持 `running`；Worker 在 train/validation batch 安全点观察到请求后停止开始新 batch，丢弃当前未完成 epoch，将最近完整 epoch 的内存 checkpoint bytes 持久化或复用已有持久引用，再调用 finalizer 以 `paused` 同时结束当前 Attempt 并把 Task 变为 `paused`。暂停不得等待当前 epoch 结束，也不能把部分 epoch checkpoint 伪装为完整恢复点。`paused` 是 TaskAttempt 的合法终态，也是 Task 的可恢复状态，不能把暂停的 Attempt 记录成 `succeeded`。

### 训练暂停与完整 epoch checkpoint 协议

暂停响应和 checkpoint 保留是两个不同问题，统一契约如下：

1. YOLOX detection、YOLOv8/11/26 的 detection/classification/segmentation/pose/OBB，以及 RF-DETR detection/segmentation 都必须在每个 train batch 和 validation batch 完成后的安全点检查 attempt 级 `TrainingControlProbe`；不得只在 epoch callback 中检查。
2. `TrainingControlProbe` 每个 Attempt 只创建一个，内部只保存最近控制快照和 `next_poll_monotonic`。batch 安全点调用 probe 是进程内常数时间操作；只有达到默认 250 ms 观察间隔时才读取一次持久 Task 控制状态。它不创建后台线程、不增加控制队列、不自动重试，Worker/lease 恢复后从持久请求重新建立，因此既不把 SQLite I/O 放到每个 batch，也不会因进程内信号丢失暂停请求。
3. 观察到暂停后不再读取或执行下一个 batch。已经开始的 batch 允许完成必要的反向传播、设备同步和回调清理；因此正常暂停延迟上限是一个在途 batch（包含数据读取）加最多 250 ms 控制观察间隔，而不是一个 epoch。底层 CUDA、第三方算子或 DataLoader 已经阻塞时由独立 watchdog/终止协议处理，不能宣称 Python 回调可瞬时强杀。
4. 当前 epoch 的模型更新、optimizer/scheduler/scaler/EMA 状态、指标和部分验证结果全部视为未提交，不写入恢复 checkpoint。Worker 退出前释放当前实现临时 tensor、梯度和 DataLoader 资源；恢复时重新加载最近完整 checkpoint，从被丢弃 epoch 的第一个 batch 重新训练。
5. 每次训练首次进入 batch 循环前建立 epoch 0 baseline bytes；从完整 checkpoint resume 时，该 checkpoint bytes 直接成为 baseline。warm start 只加载模型权重，仍须在 optimizer、scheduler、scaler、EMA 和 RNG 初始化后生成 epoch 0 完整 baseline，不能把仅含权重的 warm-start 文件冒充可恢复快照。
6. 每个完整 epoch 的训练、当前实现应执行的验证和指标提交结束后，同步生成一份完整 checkpoint 到新的内存缓冲区。只有序列化成功、bytes 非空且 `completed_epoch`/模型/数据集/Attempt 身份自检通过后，才用新 bytes 替换上一份快照并开始下一 epoch。生成失败时保留旧快照用于错误说明，但当前 Attempt 必须 failed，不能继续训练。
7. 每个 Attempt 稳定状态只持有一个最近完整 epoch 快照，不保留内存历史，也不保留会继续变化的 `state_dict()` tensor 引用。为保证替换失败不破坏旧快照，生成期间允许短暂同时持有旧、新 bytes；专项门禁必须测量 checkpoint 序列化耗时、稳定内存和替换峰值内存，确认训练 profile 并发为 1 时仍满足主机容量。
8. 内存快照至少包含 model、optimizer、scheduler、AMP scaler、EMA、RNG、完整 epoch/global iteration、指标历史、训练配置、数据集/类别/模型身份和必要的框架 loop state。内存阶段不计算持久文件 hash，不执行 ObjectStore write、flush、fsync、原子 rename、publication pointer 或旧 Worker 文件 fencing。
9. `resolve_training_checkpoint_persistence_decision()` 返回 `should_persist`，按最终解析的 `checkpoint_interval` 与 periodic、best、final、manual、pause、terminate 原因决定是否落盘；完整 epoch 的内存快照不受持久化周期阻止。旧 `should_serialize` 接口已移除。
10. 周期、final、manual、pause 和 terminate 的完整 resume checkpoint 都接收当前内存 bytes。Attempt 内的 persistence coordinator 按 `completed_epoch`、内容身份和 checkpoint role 记录已持久引用；暂停遇到同一 epoch 已有可恢复的完整 checkpoint 时直接复用 object key，否则只写一次。模型专用 best/EMA/deployment artifact 若格式、权重或加载语义不同，保留现有专用生成逻辑，不能强制复用 resume bytes。
11. 暂停结果记录 `pause_requested_at`、`pause_observed_at`、`pause_observed_latency_ms`、`pause_completed_at`、`pause_completed_latency_ms`、`completed_epoch`、`discarded_epoch`、`discarded_train_batches`、`discarded_validation_batches` 和 checkpoint object key。页面进度回退并固定到 `completed_epoch`，不能保留被丢弃 epoch 的百分比造成已保存错觉。“一个在途 batch 加最多 250 ms”只约束 observed latency；completed latency 还包含已有 bytes 的持久化、校验和 finalizer 时间。
12. 暂停请求恰好发生在内存快照替换期间时，先完成本次内存生成和交换；成功后使用新 completed epoch，失败则 Attempt failed，不得开始下一 epoch。与训练自然完成竞争时，已经原子完成的 `succeeded` 优先；与 cancel 竞争时由 Task CAS 决定唯一终态。
13. RF-DETR 当前只支持单 GPU 或 CPU，平台入口也拒绝 `gpu_count > 1`。当前实现只实现单进程 train/validation batch hook 和内存 Lightning checkpoint bytes，不增加 rank 广播、collective 或 DDP 门禁；未来启用 DDP 前必须另行设计跨 rank 一致快照与协同暂停。

各框架当前接入点：

| 框架 | 控制观察 | 完整 checkpoint |
| --- | --- | --- |
| YOLOX | train batch callback 与 validation batch 安全点调用同一 Attempt probe | baseline 与完整 epoch 生成独立 bytes，由 coordinator 持久化或复用 |
| YOLOv8/11/26 | 训练/验证 callback 传递 pause、terminate 决定 | 共享 completed-epoch snapshot 与 persistence coordinator，保留各任务的模型输出格式 |
| RF-DETR | Lightning train/validation batch hook 检查 probe | Attempt 级 `RfdetrAttemptCheckpointIO` 编码完整 Lightning 状态，周期 resume 与专用 best/final 分开处理 |

RF-DETR 的底层 `TrainConfig.checkpoint_interval` 默认值当前为 10，但平台 `_build_train_config()` 会把未显式配置的应用请求解析为 5，`eval_interval` 解析为 1；因此“RF-DETR 默认一定是 10”不是当前平台链路事实。平台按最终解析配置保留用户可见周期，只从最终解析后的 config 读取 checkpoint/evaluation interval，快照逻辑不另设一套周期默认值。后续若统一默认值来源，必须单独核对已有任务配置和公开 schema，不能静默改变训练行为。

RF-DETR 内存快照使用 Lightning 公共 `CheckpointIO` 扩展点：单 GPU/CPU Trainer 注入一个 attempt 级 checkpoint IO，内存目标把 Lightning 传入的完整 checkpoint dict 同步编码到 `BytesIO`，普通持久目标委托标准 IO。`on_fit_start` 在 model、optimizer 和 scheduler 均已挂接后生成 epoch 0 baseline；完整 epoch 的验证与指标回调结束后生成下一快照。当前不再通过每 epoch `last` ModelCheckpoint 写盘，周期完整 resume checkpoint 由 persistence coordinator 写当前 bytes；`BestModelCallback` 生成的 regular/EMA 部署兼容 artifact 保持原专用格式和指标逻辑。不得直接新增对 `_checkpoint_connector` 私有接口的依赖，也不得通过临时磁盘文件模拟内存快照。

单个 Attempt 的数据流为：

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

TaskService 入口（训练暂停由模型训练服务的 `request_training_pause()` 调用 patch 命令）：

- `claim_task_execution(...)`
- `execute_task_patch_event_command(...)`
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


### Attempt finalizer

统一接口语义：

```text
finalize_task_execution_attempt(
  attempt_id,
  attempt_outcome,
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
7. 重复调用只有在 outcome、Task 当前 Attempt、Task 终态及不可变 Worker/Queue 身份均匹配时才返回既有结果，不重复写事件或业务记录；冲突终态或过期执行身份明确拒绝。终态幂等确认不再比较运行期 heartbeat。

固定长度标识：

```text
task-started-{uuid5(namespace, "attempt:{attempt_id}:running").hex}
task-terminal-{uuid5(namespace, "attempt:{attempt_id}:{state}").hex}
queue-resume-{uuid5(namespace, "task:{task_id}:attempt:{attempt_no}").hex}
```


## 其他执行边界

- [任务系统](task-system.md)：Outbox、Worker Profile 和公开状态。
- [训练与评估](../models/training-evaluation.md)：checkpoint、split 与数值约束。
- [转换执行与发布](../models/conversion-runtime.md)：总 deadline、reservation、rename 与恢复。
- [节点系统](../workflows/node-system.md)：Preview 协作取消与 Runtime generation 级硬终止。

## 持续验证

`tests/test_task_attempt_claiming_queue.py`、`tests/test_training_control_probe_and_checkpoint_snapshot.py`、`tests/test_conversion_deadline_policy.py`、`tests/test_conversion_publication_recovery.py`、`tests/test_conversion_publication_reconciler.py` 和 `tests/test_process_tree_supervisor.py` 覆盖领取、恢复、checkpoint、发布和进程边界。完整模型链使用 `tests/integration/model_task_e2e_matrix.py`。

源码真实业务验收与发行基础设施验收分别执行。发行包不复制开发数据库；需要真实模型、Deployment、Workflow 和 Trigger 的目标现场持续验收，应先登记这些资源并完成 warmup。LocalMessage 24 小时混合 soak 的待验收状态继续以[本机结构化消息通道验收](../../development/local-message-channel-implementation.md)为准，不能由本专题已有验收替代。
