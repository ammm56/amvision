# full 发布目录

## 文档目的

本文档用于说明当前仓库已经落地的 `full` 发布目录，包括目录结构、worker profile、launcher、release 组装命令和运维建议。

## 当前仓库落点

- profile manifest：`runtimes/manifests/release-profiles/full.json`
- worker profile：`runtimes/manifests/worker-profiles/*.json`
- service launcher：`runtimes/launchers/service/start_backend_service.py`
- worker launcher：`runtimes/launchers/worker/start_backend_worker.py`
- maintenance launcher：`runtimes/launchers/maintenance/invoke_backend_maintenance.py`
- release 组装入口：`python -m backend.maintenance.main assemble-release --profile-id full`

## 共用约定

- 当前只提供一个 `full` 发布目录，`backend-service` 不托管任何队列消费者，队列执行统一交给独立 worker profile
- `runtimes/launchers/` 和 `runtimes/manifests/` 是仓库内的模板来源；`assemble-release` 会把运行时必需内容复制到 `release/full/launchers/` 和 `release/full/manifests/`
- 发布根目录会额外生成 `start-amvision-full.*` 和 `stop-amvision-full.*`，作为生产环境默认的整套启动与停止入口
- 发布目录优先通过 bundled Python 启动 Python launcher；Windows 使用 bat wrapper，Linux 使用 sh wrapper
- 发布目录保留 maintenance launcher，用于版本输出、配置查看、布局校验和 release 组装
- 发布目录复制完整项目代码，不做源码裁剪；推理专用变体由复制 `full` 目录后手工修改 `requirements.txt` 和 `python/` 完成

## 当前默认行为

- `hosted_task_manager_enabled=false`
- worker 默认拆成 `dataset-import`、`dataset-export`、`training`、`conversion`、`evaluation`、`inference` 六个独立 profile
- 发布目录名默认为 `release/full/`
- 覆盖发布时会优先保留并回迁现有 `release/full/python/`
- 只有显式提供 bundled Python 来源目录时，才会重建发行目录里的 `python/`
- 如果当前发布目录原本没有 `python/`，发行目录中的 `python/` 才会退回空目录模式
- release 组装会复制 `frontend/web-ui/dist/`，并保证 `frontend/runtime-config.json` 存在
- 可选启用本地 ZeroMQ 作为内部 IPC 补充

## full release manifest

当前 `full` profile 由 `runtimes/manifests/release-profiles/full.json` 定义，关键约定如下：

| 项目 | 当前值 | 作用 |
| --- | --- | --- |
| service launcher | `runtimes/launchers/service/start_backend_service.py` | 启动 backend-service 控制面 |
| hosted task manager | `false` | service 不直接消费队列 |
| worker profile ids | `dataset-import / dataset-export / training / conversion / evaluation / inference` | full 一键启动时默认拉起的 worker 集合 |
| maintenance launcher | `runtimes/launchers/maintenance/invoke_backend_maintenance.py` | 发布目录自检、版本输出和 release 组装入口 |
| artifacts.include_frontend | `true` | 组装时复制前端 dist |

## worker profile 一览

`runtimes/manifests/worker-profiles/` 当前不是旧的 detection-only 清单，而是按真实平台能力拆分后的正式 profile：

| profile_id | enabled_consumer_kinds | 现场用途 |
| --- | --- | --- |
| `dataset-import` | `dataset-import` | zip 导入、解压、格式规范化、DatasetVersion 落盘 |
| `dataset-export` | `dataset-export` | 数据集导出、打包和训练输入文件生成 |
| `training` | `yolox-training`、`yolov8-training`、`yolo11-training`、`yolo26-training`、`rfdetr-training`、`classification-training`、`segmentation-training`、`pose-training`、`obb-training` | 各模型训练执行、产物写回和状态同步 |
| `conversion` | `yolox-conversion`、`yolov8-conversion`、`yolo11-conversion`、`yolo26-conversion`、`rfdetr-conversion` | ONNX、OpenVINO、TensorRT 构建输出 |
| `evaluation` | `detection-evaluation`、`classification-evaluation`、`segmentation-evaluation`、`pose-evaluation`、`obb-evaluation` | 数据集级评估和指标回写 |
| `inference` | `detection-inference`、`classification-inference`、`segmentation-inference`、`pose-inference`、`obb-inference` | async inference 队列消费和 gateway 转发 |

当前每个 profile 默认 `max_concurrent_tasks = 1`。这是更保守、也更贴现场的默认值，先保证隔离和可观测，再按设备与任务类型调高。

## release/full 关键目录

默认 `assemble-release` 生成的 `release/full/` 当前至少应包含：

- `app/backend/`
- `app/requirements.txt`
- `config/backend-service.json`
- `config/backend-worker.json`
- `manifests/release-profiles/full.json`
- `manifests/worker-profiles/*.json`
- `launchers/service/`
- `launchers/worker/`
- `launchers/maintenance/`
- `frontend/`
- `custom_nodes/`
- `tools/ffmpeg/`
- `python/`
- `logs/`

其中 `python/`、`data/`、模型文件、数据库文件和现场业务数据都属于运行目录资产，不应回写到仓库源码目录。

## 日志与状态文件

full 一键启动当前统一把日志和运行状态写到 `logs/<subdir>/`，默认子目录是 `full-stack`：

| 路径 | 作用 |
| --- | --- |
| `logs/full-stack/service.log` | backend-service 主日志 |
| `logs/full-stack/worker-dataset-import.log` | dataset-import worker 日志 |
| `logs/full-stack/worker-dataset-export.log` | dataset-export worker 日志 |
| `logs/full-stack/worker-training.log` | training worker 日志 |
| `logs/full-stack/worker-conversion.log` | conversion worker 日志 |
| `logs/full-stack/worker-evaluation.log` | evaluation worker 日志 |
| `logs/full-stack/worker-inference.log` | inference worker 日志 |
| `logs/full-stack/runtime-state.json` | full 一键启动写入的运行状态文件，供 stop 脚本回收进程 |

如果使用 `--logs-subdir` 或 `--state-file`，这些默认路径会被覆盖。现场多套实例并存时，建议显式改 `logs-subdir`，避免日志和状态文件互相覆盖。

## 现场推荐用法

### 启整套

```powershell
.\start-amvision-full.bat
```

### 只起部分 worker

```powershell
.\start-amvision-full.bat --worker-profile-id inference
.\start-amvision-full.bat --worker-profile-id conversion --worker-profile-id inference
```

### 调整日志子目录

```powershell
.\start-amvision-full.bat --logs-subdir full-stack-gpu01
```

### 停整套

```powershell
.\stop-amvision-full.bat
```

## 读这个文档之后，下一份该看什么

- 首次部署顺序和最小验收：`full-first-deploy-checklist.md`
- 生产环境入口和根脚本参数：`production-environment.md`
- 现场日志和故障排查：`../operations/release-full-troubleshooting.md`

## 推荐启动顺序

1. 先执行 maintenance `validate-layout`
2. 在 `release/full/` 根目录执行 `start-amvision-full.bat` 或 `start-amvision-full.sh`
3. 检查 health、OpenAPI 文档和目标业务 smoke test
4. 如需排障，再拆回独立 service / worker launcher

完整的一页执行顺序见 [docs/deployment/full-first-deploy-checklist.md](full-first-deploy-checklist.md)。

默认的一键启动入口见 [docs/deployment/production-environment.md](production-environment.md)。

## 运维重点

- 核对 bundled Python 体积与磁盘空间
- 核对厂商 runtime、驱动和目标设备兼容性
- 核对各 worker profile 是否与现场职责匹配

## 当前建议

1. 开发联调继续可以在仓库根目录直接运行 launcher，并默认使用当前已激活的 `conda amvision` 解释器。
2. 发布打包时应通过 `assemble-release` 生成 `release/full/`，不要再手工拼接 launcher、manifest 或直接修改 `release/full/app/` 下的代码。
3. 如果需要调整发布目录中的 backend、config、docs 或 requirements，应先修改仓库源文件，再重新执行 `assemble-release` 覆盖生成 `release/full/`。
4. 如果要做推理专用变体，直接复制 `release/full/`，再手工调整 `app/requirements.txt` 与 `python/` 即可。
5. 发布验收优先跑 `launchers/maintenance/invoke_backend_maintenance.py -- validate-layout`、service health、目标 worker profile smoke test，再做业务联调。
