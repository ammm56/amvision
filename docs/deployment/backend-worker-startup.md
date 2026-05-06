# backend-worker 启动说明

## 文档目的

本文档用于说明独立 backend-worker 的启动方式、worker profile 配置、deployment supervisor 行为和最小验收步骤。

本文档覆盖当前已经落地的独立 worker 拓扑，dataset import、dataset export、training、conversion、evaluation 和 inference 都已经切到独立 worker profile。

## 适用范围

- conda 开发环境中的 backend-worker 启动
- 同目录 Python 运行时中的 backend-worker 启动
- `config/backend-worker.json` 的默认配置
- `runtimes/manifests/worker-profiles/*.json` 的独立 worker profile
- 全部六类消费者纳入独立 worker 后的最小验证步骤

## 当前入口

- Python 模块入口：`backend.workers.main`
- bootstrap：`backend.workers.bootstrap.BackendWorkerBootstrap`
- task manager 组装：`backend.workers.main.build_background_task_manager`
- consumer registry：`backend.workers.consumer_registry.build_background_task_consumers`
- Python launcher：`runtimes/launchers/worker/start_backend_worker.py`
- wrapper：`runtimes/launchers/worker/start-backend-worker.bat`、`runtimes/launchers/worker/start-backend-worker.sh`

## 当前默认配置

当前仓库的默认 worker 配置位于 `config/backend-worker.json`，主要包含以下几组字段：

- `queue.root_dir`：本地持久化队列目录
- `task_manager.enabled_consumer_kinds`：当前独立 worker 需要托管的消费者种类
- `task_manager.max_concurrent_tasks`：最大并发任务数
- `task_manager.poll_interval_seconds`：空闲轮询间隔秒数
- `deployment_process_supervisor.*`：YOLOX async deployment supervisor 的默认行为

当前默认启用的消费者种类为：

- `dataset-import`
- `dataset-export`
- `yolox-training`
- `yolox-conversion`
- `yolox-evaluation`
- `yolox-inference`

## 当前 worker 拓扑约定

- backend-service 当前只承担 REST / WebSocket 控制面和 sync / async deployment supervisor，不再托管任何队列消费者。
- `config/backend-service.json` 里的 `task_manager` 字段仅保留兼容配置形态，当前 service 启动链不会再创建进程内 BackgroundTaskManager。
- backend-worker 通过统一 `enabled_consumer_kinds` 配置和 `worker profile` manifest 接管全部队列消费者。
- inference consumer 依赖 worker 内部创建的 async deployment supervisor，以便异步 `inference-tasks` 能在独立 worker 里消费 deployment 常驻会话。

## 开发环境启动

以下步骤从仓库根目录执行。

### 1. 激活 conda 环境

```powershell
conda activate amvision
```

### 2. 启动 backend-worker

```powershell
python -m backend.workers.main
```

如果需要按独立 profile 启动单一职责 worker，可直接调用 Python launcher：

```powershell
python runtimes/launchers/worker/start_backend_worker.py --worker-profile-file runtimes/manifests/worker-profiles/inference.json
```

### 3. 最小验证

- 确认 worker 进程已经读取 `config/backend-worker.json`
- 确认 `task_manager.enabled_consumer_kinds` 与当前部署形态匹配
- 提交一个最小 DatasetExport、evaluation-task 或 inference-task，确认任务会被独立 worker 消费

## 同目录 Python 运行时启动

当前仓库已经提供 Python launcher 和最薄的 bat/sh wrapper：

当前 `full` 发布目录的默认入口已经切到根目录一键启动脚本：`start-amvision-full.bat`、`start-amvision-full.sh`。
本页保留 `launchers/worker/` 的调用方式，主要用于只拉起单个 worker 或拆分排障。

- `runtimes/launchers/worker/start_backend_worker.py`
- `runtimes/launchers/worker/start-backend-worker.bat`
- `runtimes/launchers/worker/start-backend-worker.sh`

仓库根目录中的开发态调用方式为：

```powershell
.\runtimes\launchers\worker\start-backend-worker.bat --python-executable .\python\python.exe --worker-profile-file runtimes/manifests/worker-profiles/inference.json
```

发布目录中的等价调用方式为：

```powershell
.\launchers\worker\start-backend-worker.bat --worker-profile-file manifests/worker-profiles/inference.json
```

如果已经通过 `assemble-release` 生成固定 profile wrapper，也可以直接执行：

```powershell
.\launchers\worker\start-inference-worker.bat
```

说明：

- Python launcher 会把工作目录切到应用根目录，并自动补齐 `PYTHONPATH` 后再执行 `backend.workers.main`
- 如果提供 `--worker-profile-file`，launcher 会把 profile 内的消费者集合、并发数和轮询间隔注入 worker 环境变量
- 仓库里的 `runtimes/manifests/worker-profiles/*.json` 会在发布时复制到 `manifests/worker-profiles/*.json`
- 发行目录下由 `assemble-release` 额外生成 `launchers/worker/start-<profile_id>-worker.bat` 与 `start-<profile_id>-worker.sh`

## full 发布中的 worker 角色

- 当前 `runtimes/manifests/release-profiles/full.json` 会生成 `dataset-import`、`dataset-export`、`training`、`conversion`、`evaluation`、`inference` 六个独立 worker profile
- 如果只需要单进程联调，也可以继续使用 `config/backend-worker.json` 里的全量 `enabled_consumer_kinds`
- 如果后续要做推理专用发布，可复制 `release/full/` 后只保留需要的 worker launcher 与对应依赖，不需要改项目源码

## 当前最小验收建议

1. 先通过 `backend-service` 创建任务，再确认队列目录有新任务写入。
2. 启动目标 worker profile，确认任务状态能从 `queued` 推进到 `running` 或 `succeeded`。
3. 针对 inference profile，先通过 deployment 控制面启动 async deployment，再创建异步 inference task。
4. 如果 inference-task 无法消费，先检查 worker 是否启用了 `yolox-inference`，再检查 async deployment supervisor 配置。