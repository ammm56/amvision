# backend-worker Topology 与启动说明

## 目的

backend-worker 是任务消费执行层。正式运行只允许 full Supervisor 根据严格 Worker Profile 激活一代 Topology，再启动其中声明的 Profile 进程。backend-service 不创建进程内任务消费者。

## 唯一正式入口

开发态和发布态都使用完整 Supervisor：

```powershell
conda activate amvision
python runtimes/launchers/full/start_amvision_full.py --app-root . --python-executable python
```

发布目录使用：

```powershell
.\start-amvision-full.bat
```

`python -m backend.workers.main`、固定 Profile wrapper 和只传 `--worker-profile-file` 的旧启动方式已经删除。Worker 进程缺少 Supervisor 注入的 topology id、generation、epoch、instance id 或 Profile 路径时会直接拒绝启动。

`runtimes/launchers/worker/start_backend_worker.py` 是 Supervisor 使用的低层入口，不是独立部署入口。

## Profile 是唯一职责配置

Profile 位于 `runtimes/manifests/worker-profiles/*.json`，格式固定为 `amvision.worker-profile.v1`，严格拒绝未知字段。每个 Profile 明确声明：

- `profile_id`
- `display_name`
- `enabled_consumer_kinds`
- `max_concurrent_tasks`
- `poll_interval_seconds`

当前 Profile：

| Profile | 职责 |
| --- | --- |
| `dataset-import` | 数据集导入 |
| `dataset-export` | 数据集导出与训练输入生成 |
| `training` | YOLOX、YOLOv8、YOLO11、YOLO26、RF-DETR 及非 detection 训练 |
| `conversion` | ONNX、OpenVINO、TensorRT 转换 |
| `evaluation` | detection、classification、segmentation、pose、obb 评估 |
| `inference` | 五类任务的异步推理队列消费与 gateway 转发 |

`config/backend-worker.json` 只保存共享数据库、对象存储、队列、workspace 和 gateway 配置，不再保存全量消费者集合或并发策略。

## Topology 运行契约

Supervisor 每次启动创建新的 epoch，并原子更新当前指针：

```text
data/runtime/backend-workers/
├─ active.json
├─ topology.lock
└─ topologies/<epoch>/
   ├─ manifest.json
   ├─ profiles/<profile-id>.json
   └─ locks/<profile-id>.lock
```

- `active.json`：唯一活动 Topology 指针，格式 `amvision.worker-topology-pointer.v1`。
- `manifest.json`：本代期望 Profile、generation、epoch、Supervisor id 和健康阈值。
- `profiles/*.json`：本代 Profile 的严格心跳，格式 `amvision.worker-heartbeat.v1`。
- `topology.lock`：同一应用根目录只允许一个 full Supervisor。
- `locks/*.lock`：同一 epoch 的每个 Profile 只允许一个进程。

诊断只读取 `active.json` 指向的 manifest 及其精确 Profile 心跳。旧 epoch、旧 `_worker_health` 目录、文件 glob 和损坏的历史文件都不参与当前健康计算。

## 故障隔离与恢复

- backend-service 或 inference daemon 退出：Supervisor 停止完整 stack。
- 单个 Worker Profile 退出：只恢复该 Profile，不停止其他 Profile 和 service。
- 恢复采用有上限的退避，失败立即反映到当前 Profile 心跳和设置页。
- 心跳线程、日志复制线程发生异常时，异常会进入 Supervisor 主循环，不能静默停止。
- stop 只操作状态文件中 PID、创建时间、解释器、工作目录和命令行全部匹配的进程，避免 PID 复用导致误杀。

## 按日日志

Supervisor 将每个组件 stdout/stderr 追加到本地日期文件：

```text
logs/full-stack/backend-service-YYYYMMDD.log
logs/full-stack/inference-daemon-YYYYMMDD.log
logs/full-stack/backend-worker-<profile>-YYYYMMDD.log
logs/full-stack/database-migration-YYYYMMDD.log
```

同一天持续 append 到同一个文件；跨过本地午夜后的第一段输出自动切换到新日期文件。当天文件保持打开并在切换时关闭，避免每条日志反复打开文件。`runtime-state.json` 同时记录当前日志路径和 `log_pattern`。

## 验收

1. 启动 full Supervisor，确认 `active.json` 和当前 epoch manifest 存在。
2. 设置页“运行状态”确认 Topology generation/epoch 和全部 Profile。
3. 每个 Profile 应为 `running`，`running_count == worker_count`。
4. 提交对应任务，确认队列状态推进并写入当天 Profile 日志。
5. 仅终止一个 Worker Profile，确认 Supervisor 只生成该 Profile 的新 instance id，其他组件 PID 不变。
6. 跨日 soak 确认新日志进入下一日期文件，旧文件不再增长。
