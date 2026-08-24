# 发布 profile

## 文档目的

本文档说明当前仓库已经落地的发布 profile、硬件适用边界、worker profile、launcher、release 组装命令和运维建议。

## 当前仓库落点

- release profile：`runtimes/manifests/release-profiles/*.json`
- worker profile：`runtimes/manifests/worker-profiles/*.json`
- service launcher：`runtimes/launchers/service/start_backend_service.py`
- worker launcher：`runtimes/launchers/worker/start_backend_worker.py`
- maintenance launcher：`runtimes/launchers/maintenance/invoke_backend_maintenance.py`
- release 组装入口：`python -m backend.maintenance.main assemble-release --profile-id <profile_id>`

## 硬件 profile 边界

| profile_id | 当前状态 | 目标环境 | 运行时资产 | 默认 worker |
| --- | --- | --- | --- | --- |
| `full-windows-x64-nvidia` | 已实现，推荐 | Windows x64 NVIDIA | Windows FFmpeg、TensorRT、cuDNN | 全部六类 worker |
| `full-windows-x64-cpu` | 已实现，推荐 | Windows x64 CPU | Windows FFmpeg，不含 NVIDIA 资产 | 全部六类 worker |

发布只接受表中状态为“已实现”的完整 profile id，不提供缩写、别名或未验收 profile。其他值会明确失败，不生成看似可用的发行包。

## 组装命令

### NVIDIA GPU 工作站

```powershell
conda activate amvision
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-nvidia --release-root .\release --force --output text
```

生成目录：

- `release/full-windows-x64-nvidia/`

### Intel CPU 工作站

```powershell
conda activate amvision
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-cpu --release-root .\release --force --output text
```

生成目录：

- `release/full-windows-x64-cpu/`

## 共用约定

- `backend-service` 不托管队列消费者，队列执行统一交给独立 worker profile。
- `runtimes/launchers/` 和 `runtimes/manifests/` 是仓库内模板来源；`assemble-release` 会复制到发行目录。
- 发布根目录会复制仓库根 `README.md` 和授权文件，便于发布包独立交付和核对。
- 当前 Windows 包只生成 `.bat` wrapper，不复制 Linux `.sh` launcher 或 Linux FFmpeg。
- `python/` 默认只创建空目录，完整 bundled Python 由发布人员手工复制；`--force` 覆盖同一 profile 时会保留已有 `python/`。
- 发布目录保留 maintenance launcher，用于版本输出、配置查看、布局校验和 release 组装。
- 发布目录复制完整后端源码；不同硬件环境通过 release profile 区分，不通过手工修改发行目录区分。

## worker profile 一览

`runtimes/manifests/worker-profiles/` 当前按平台能力拆分：

| profile_id | enabled_consumer_kinds | 现场用途 |
| --- | --- | --- |
| `dataset-import` | `dataset-import` | zip 导入、解压、格式规范化、DatasetVersion 落盘 |
| `dataset-export` | `dataset-export` | 数据集导出、打包和训练输入文件生成 |
| `training` | `yolox-training`、`yolov8-training`、`yolo11-training`、`yolo26-training`、`rfdetr-training`、`classification-training`、`segmentation-training`、`pose-training`、`obb-training` | 各模型训练执行、产物写回和状态同步 |
| `conversion` | `yolox-conversion`、`yolov8-conversion`、`yolo11-conversion`、`yolo26-conversion`、`rfdetr-conversion` | ONNX、OpenVINO、TensorRT 构建输出 |
| `evaluation` | `detection-evaluation`、`classification-evaluation`、`segmentation-evaluation`、`pose-evaluation`、`obb-evaluation` | 数据集级评估和指标回写 |
| `inference` | `detection-inference`、`classification-inference`、`segmentation-inference`、`pose-inference`、`obb-inference` | async inference 队列消费和 gateway 转发 |

当前所有内置 profile 默认 `max_concurrent_tasks = 1`。Training 已具备跨进程 GPU/MIG `exclusive` lease；多 GPU 机器完成显存、功耗和持续负载验证后，可以提高 training profile 的并发数，`auto` 会选择可获得的可见 GPU。CUDA Conversion 使用同一独占协调边界，CUDA Deployment 持有常驻 shared reservation。具体规则见 [GPU 设备资源协调](../architecture/models/device-resource-coordination.md)。

## 发布目录关键路径

所有 profile 的目录名默认与 `profile_id` 一致，例如 `release/full-windows-x64-cpu/` 或 `release/full-windows-x64-nvidia/`。至少应包含：

- `app/backend/`
- `app/requirements.txt`
- `config/backend-service.json`
- `config/backend-worker.json`
- `manifests/release-profiles/<profile_id>.json`
- `manifests/worker-profiles/*.json`
- `launchers/service/`
- `launchers/worker/`
- `launchers/maintenance/`
- `frontend/`
- `custom_nodes/`
- `tools/ffmpeg/`
- `python/`
- `logs/`

NVIDIA profile 额外包含：

- `tools/tensorrt/`
- `tools/cudnn/`

CPU profile 不应包含 `tools/tensorrt/` 和 `tools/cudnn/`，`app/requirements.txt` 也不应包含 `tensorrt-cu12` 或 `cuda-python`。

## 日志与状态文件

一键启动默认写入 `logs/full-stack/`：

| 路径 | 作用 |
| --- | --- |
| `logs/full-stack/backend-service-YYYYMMDD.log` | backend-service 当日日志 |
| `logs/full-stack/inference-daemon-YYYYMMDD.log` | inference daemon 当日日志 |
| `logs/full-stack/backend-worker-<profile>-YYYYMMDD.log` | 指定 Worker Profile 当日日志 |
| `logs/full-stack/database-migration-YYYYMMDD.log` | Alembic 迁移当日日志 |
| `logs/full-stack/runtime-state.json` | full Supervisor 状态、完整进程身份、当前日志路径和日志模式 |
| `logs/full-stack/runtime-state.shutdown-request.json` | stop 临时写入、且只匹配当前 root process identity 的优雅停止请求；完成后自动删除 |

如果使用 `--logs-subdir` 或 `--state-file`，这些默认路径会被覆盖。现场多套实例并存时，建议显式改 `logs-subdir`，避免日志和状态文件互相覆盖。

## 现场完整启动

### 启动完整项目

```powershell
.\start-amvision-full.bat
```

启动器默认加载 release manifest 中声明的全部 worker。生产实际使用不裁剪 worker profile。

### 停止完整项目

```powershell
.\stop-amvision-full.bat
```

## 推荐启动顺序

1. 先执行 maintenance `validate-layout`
2. 在对应发行目录根目录执行 `start-amvision-full.bat`
3. 检查 health、OpenAPI 文档和目标业务 smoke test
4. Worker 排障通过设置页 Topology 明细、当前日期日志和 Supervisor 恢复记录完成，不脱离 Topology 单独启动

## 运维重点

- 发布前先确认目标机硬件类型，再选择 `full-windows-x64-nvidia` 或 `full-windows-x64-cpu`。
- CPU-only 目标机不能安装 NVIDIA 完整包后依赖现场手工裁剪。
- 核对 bundled Python 体积与磁盘空间。
- 核对厂商 runtime、驱动和目标设备兼容性。
- 核对各 worker profile 是否与现场职责匹配。

## 相关文档

- [首次部署顺序和最小验收](full-first-deploy-checklist.md)
- [生产环境入口和根脚本参数](production-environment.md)
- [现场日志和故障排查](../operations/release-full-troubleshooting.md)
