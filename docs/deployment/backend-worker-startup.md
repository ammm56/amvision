# backend-worker Topology

backend-worker 是后台任务执行层。`backend-service` 不创建进程内消费者。开发和生产都由明确的 Supervisor 激活一代 Topology，再启动严格 Worker Profile，但两种环境使用不同入口。

## 源码开发入口

从源码仓库根目录执行：

```powershell
conda activate amvision
python -m backend.workers.supervisor
```

源码开发 Supervisor 使用当前 conda Python，激活 Topology 后启动六个 Profile，并把各 Profile 的标准输出保留在当前开发终端。完整顺序见 [开发环境启动](development-environment.md)。

## 生产发行入口

进入已组装的发行目录执行：

```powershell
.\start-amvision-full.bat
```

生产 full Supervisor 统一负责数据库迁移、inference daemon、backend-service、Worker Topology、按日日志和完整进程回收。生产步骤见 [生产环境](production-environment.md)。

以下入口不是独立运行方式：

- `python -m backend.workers.main`
- `runtimes/launchers/worker/start_backend_worker.py`
- 手工只传一个 Profile 文件

低层 Worker 缺少 Supervisor 注入的 Topology id、generation、epoch、instance id 和精确 Profile 路径时会拒绝启动。

## Worker Profile

Profile 源文件位于 `runtimes/manifests/worker-profiles/*.json`，格式固定为 `amvision.worker-profile.v1`，未知字段会被拒绝。

| Profile | 主要职责 |
| --- | --- |
| `dataset-import` | zip 导入、格式校验、规范化和 DatasetVersion 落盘 |
| `dataset-export` | 数据集导出、打包和训练输入生成 |
| `training` | YOLOX、YOLOv8、YOLO11、YOLO26、RF-DETR 及各任务训练 |
| `conversion` | ONNX、OpenVINO 和 TensorRT 转换 |
| `evaluation` | detection、classification、segmentation、pose 和 OBB 评估 |
| `inference` | 五类异步推理队列与 gateway 转发 |

Profile 独立声明 consumer、并发数和轮询间隔。`config/backend-worker.json` 只保存共享数据库、ObjectStore、队列、workspace、telemetry 和 gateway 配置。

默认 `training` Profile 的 `max_concurrent_tasks` 为 `1`。该值只限制同时执行的独立训练任务数，不改变单个任务的 batch size、DataLoader worker 或训练数值语义。Training 已在任务执行边界获取跨进程 GPU/MIG `exclusive` lease；多 GPU 环境需要并发时，可以在完成目标机容量验证后提高该值。显式指向同一 GPU 的任务会按统一 busy/timeout 策略拒绝，CPU 训练不获取 GPU 锁。完整边界见 [GPU 设备资源协调](../architecture/models/device-resource-coordination.md)。

## Topology 契约

```text
data/runtime/backend-workers/
├─ active.json
├─ topology.lock
└─ topologies/<epoch>/
   ├─ manifest.json
   ├─ profiles/<profile-id>.json
   └─ locks/<profile-id>.lock
```

- `active.json` 是唯一活动 Topology 指针。
- `manifest.json` 固定期望 Profile、generation、epoch、Supervisor 和健康阈值。
- `profiles/*.json` 是当前代的严格心跳。
- `topology.lock` 保证同一应用根只有一个 full Supervisor。
- `locks/*.lock` 保证同一 epoch、同一 Profile 只有一个进程。

设置页诊断只读取 `active.json` 指向的当前 manifest 与精确心跳；历史 epoch、旧目录和 glob 结果不参与当前健康状态。

## 故障恢复

- 单个 Profile 退出：只恢复该 Profile，并生成新的 `worker_instance_id`。
- backend-service 或 inference daemon 退出：完整 stack 进入失败回收。
- 心跳、日志复制或监督循环异常：异常回传 Supervisor 主循环，不能静默降级。
- stop 同时核对 PID、创建时间、解释器、工作目录和命令行，避免 PID 复用误杀。

系统不为 Worker 启动引入业务队列、隐藏重试或备用兼容拓扑。

## 按日日志

```text
logs/full-stack/backend-worker-dataset-import-YYYYMMDD.log
logs/full-stack/backend-worker-dataset-export-YYYYMMDD.log
logs/full-stack/backend-worker-training-YYYYMMDD.log
logs/full-stack/backend-worker-conversion-YYYYMMDD.log
logs/full-stack/backend-worker-evaluation-YYYYMMDD.log
logs/full-stack/backend-worker-inference-YYYYMMDD.log
```

当天日志持续 append，跨过本地午夜后的第一段输出切换到新日期文件。`runtime-state.json` 记录当前日志路径与 `log_pattern`。

## 验收

1. 启动 full Supervisor。
2. 确认 `active.json`、当前 epoch manifest 和六份心跳存在。
3. 设置页确认全部 Profile 为 `running`，Topology generation/epoch 与心跳一致。
4. 提交目标任务，确认队列推进并写入对应日期日志。
5. 受控终止一个 Profile，确认只替换该 Profile 的 PID/instance，其他组件不变。
6. 跨日 soak 确认新日志进入下一日期文件，前一日文件不再增长。
