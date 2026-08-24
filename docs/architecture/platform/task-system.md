# 统一任务系统

> 当前状态：命令级 Task 状态机、取消 CAS、Attempt owner/heartbeat/Queue lease fencing、统一 finalizer、Training Resume Outbox 与完整前后端状态契约均已落地。剩余仓库级发行和真实模型门禁见 [任务执行与运行时可靠性实施基线](../../development/task-runtime-reliability-implementation.md)。

## 定位

任务系统把数据集导入导出、训练、验证、转换和批量推理等重任务从 HTTP 请求进程隔离出去，并统一保存状态、尝试、事件、取消和结果。

它不是 Kubernetes、Ray、Slurm 或通用硬件调度器；GPU、输入尺寸和模型参数属于具体任务规格，不进入通用 TaskRecord。

## 拓扑

```text
backend-service
  -> 同一 UnitOfWork：业务记录 + TaskRecord/Event + QueueOutboxMessage
      -> Outbox Dispatcher
          -> QueueBackend
              -> TaskAttempt CAS claim
                  -> Worker Profile -> Runner
                      -> Task/Attempt state, event and result
```

- **backend-service**：校验请求，在同一事务内创建业务资源、TaskRecord、初始事件和 Outbox，不直接跨越数据库事务写文件队列。
- **Outbox Dispatcher**：短事务领取待发送记录，在事务外写 QueueBackend，再用 CAS 标记已发送或安排重试。
- **QueueBackend**：本地持久化任务队列和 claim/ack/recovery。
- **TaskAttempt CAS claim**：以 `task_id + attempt_no` 原子取得执行权，lease recovery 只接管同一 attempt，旧执行者不能写入终态。
- **Worker Profile**：按职责消费一种任务池，由 full Supervisor 注入 topology identity。
- **Runner**：执行数据集、模型训练、验证、转换或批量推理实现。

## 核心记录

### TaskRecord

任务主记录包含 task id/kind、Project、创建者、spec、worker pool、状态、当前 attempt、进度、结果、错误和时间戳。业务详情仍属于 DatasetImport、TrainingTask、ConversionTask 等资源，TaskRecord 不复制完整业务模型。

### TaskAttempt

一次实际执行尝试，记录 worker/host/process identity、attempt number、heartbeat、exit code、结果和错误。相同 Queue attempt 的 lease recovery 通过 CAS 接管同一 TaskAttempt；只有队列进入新的 attempt number 才创建新的记录。终态写入同时校验 worker 和 heartbeat owner，已经失去租约的旧执行者不能覆盖恢复后的结果。

### QueueOutboxMessage

任务提交事务内保存的待入队记录，包含确定性的 message id、Queue 路由、payload 和 fingerprint。Dispatcher 可以安全重复投递，Worker 侧再由 `task_id + attempt_no` claim 防止重复副作用。同步 inference reply、deployment 控制和其他请求/响应型消息不进入 Outbox。

### TaskEvent

追加式状态审计、结果、日志和进度事件。历史事件写入 `task_events`，实时事件通过 service event bus/WebSocket 分发。

### ResourceProfile

最小执行画像，保存 worker pool、executor mode、max concurrency 和 metadata。它不承担通用 CPU/RAM/显存/NUMA 调度。

## 状态

TaskRecord 使用 `queued`、`running`、`paused`、`succeeded`、`failed`、`timed_out`、`cancelled`。Attempt 使用 `running` 与对应终态。`paused` 只用于具备 checkpoint 恢复语义的任务；所有其他执行路径必须收敛到终态，不能让异常任务永久停留在 running。

取消是显式状态迁移：API 请求取消，QueueBackend/Worker 按当前 attempt identity 收敛。取消不等于删除业务记录或输出文件。

## Worker Profiles

full Supervisor 启动六类 Worker Profile：

| Profile | 任务 |
|---|---|
| dataset-import | zip 落盘后的解析、校验、版本写入 |
| dataset-export | 统一 DatasetVersion 导出 |
| training | YOLOX、Ultralytics、RF-DETR 训练 |
| validation | 评估和验证 |
| conversion | ONNX、OpenVINO、TensorRT 等转换 |
| batch-inference | 离线批量推理 |

在线 deployment 推理和 Workflow 常驻执行不进入这些任务池，它们由各自的长期 Runtime 进程管理。

Worker 不能直接用 `python -m backend.workers.main` 启动。源码开发使用 `python -m backend.workers.supervisor`，生产发行使用 full Supervisor；二者负责注入 topology id、profile、owner identity 和停止信号，直接启动单 Profile 缺少这些不变量并会被拒绝。

## GPU 与并发

通用任务层只决定 worker pool 和 profile 并发。训练设备、`gpu_count`、`device`、batch size 等由 TrainingTaskSpec 与训练 backend 校验。当前公开训练链只支持 CPU 或单 GPU；未实现的多 GPU 组合不会进入公开 capability。

各 Profile 并发由发布配置控制。QueueBackend 不在业务层隐藏无限重试；失败、取消和恢复均产生可观测的 attempt/event。

Training 和 CUDA Conversion 在任务执行边界获取跨进程独占 GPU/MIG lease；CUDA Deployment 在实例进程生命周期持有共享 reservation。资源键使用稳定 GPU UUID/MIG UUID，进程异常退出由 OS 文件句柄自动释放。该协调不进入单次 inference 热路径。详细规则见 [设备资源协调](../models/device-resource-coordination.md)。

## API 与页面

公开入口：

- `POST /api/v1/tasks`
- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/events`
- `POST /api/v1/tasks/{task_id}/cancel`
- `/ws/v1/tasks/events`

`/tasks` 是全局任务索引，`/tasks/{task_id}` 是通用状态页。主链接优先进入业务详情页，状态链接进入 Task 页面：

| task kind | 业务详情 |
|---|---|
| `dataset-import` | `/datasets/imports/{dataset_import_id}` |
| `dataset-export` | `/datasets/exports/{dataset_export_id}` |
| `*-training` | `/models/{task_type}/training-tasks/{task_id}` |
| `*-conversion` | `/models/{task_type}/conversion-tasks/{task_id}` |

删除、下载、部署和登记等业务动作放在业务详情页，不放在通用 Task 状态页。删除时必须检查 DatasetVersion、ModelVersion、ModelBuild、Deployment 和 Workflow 的引用关系。

## 实现入口

- 任务应用服务：`backend/service/application/tasks/`
- QueueBackend 稳定端口：`backend/service/application/ports/queue.py`
- 本地文件队列 adapter：`backend/service/infrastructure/queue/local_file.py`
- Transactional Outbox 与 Dispatcher：`backend/service/application/tasks/queue_outbox.py`
- Worker TaskAttempt claim：`backend/workers/task_execution_claim.py`
- Worker：`backend/workers/`
- Task 持久化：`backend/service/infrastructure/persistence/task_repository.py`
- API：`backend/service/api/rest/v1/routes/tasks/`
- Supervisor：`runtimes/launchers/full/start_amvision_full.py`

启动和 profile 说明见 [Backend Worker 启动](../../deployment/backend-worker-startup.md)，WebSocket 契约见 [WebSocket 架构](websocket.md)。

## 明确边界

- 不在 FastAPI request handler 直接执行重任务；
- 不在通用 TaskRecord 中实现完整硬件资源调度；
- 不把外部 Redis/MQ 作为本地开发前提；
- 不把任务重试伪装成同一个 attempt；
- 不以 TaskRecord 代替业务详情资源。
