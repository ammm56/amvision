# 生产环境说明

## 文档目的

本文档用于给生产环境提供统一入口，说明 `release/<profile_id>/` 的生成方式、目录职责、bundled Python 处理方式，以及根目录一键启动和停止的推荐做法。

## 适用范围

- 通过 `assemble-release` 组装的 `release/full-nvidia/`、`release/full-cpu/` 或兼容入口 `release/full/`
- 同目录 Python 运行时
- Windows bat / Linux sh 根目录一键启动

## 当前推荐顺序

1. 在仓库根目录执行 `assemble-release`
2. 确认 `release/<profile_id>/python/`、`release/<profile_id>/frontend/`、`release/<profile_id>/frontend/runtime-config.json`、`release/<profile_id>/tools/ffmpeg/` 已经生成
3. NVIDIA profile 额外确认 `tools/tensorrt/`、`tools/cudnn/`；CPU profile 确认这两个目录不存在
4. 在 `release/<profile_id>/` 根目录执行一键启动脚本
5. 检查 health、OpenAPI 文档、前端静态资源和最小任务 smoke test

## 发布命令

NVIDIA GPU 工作站：

```powershell
conda activate amvision
python -m backend.maintenance.main assemble-release --profile-id full-nvidia --release-root ./release --force --output text
```

Intel CPU 工作站：

```powershell
conda activate amvision
python -m backend.maintenance.main assemble-release --profile-id full-cpu --release-root ./release --force --output text
```

说明：

- `full` 仍作为 NVIDIA 完整包兼容入口存在；新发布建议显式选择 `full-nvidia` 或 `full-cpu`
- `assemble-release --force` 会保留并回迁当前发行目录里的 `python/`，不会在覆盖发布时删除这个大体量目录
- 如果发行目录原本不存在 `python/`，且本次也没有显式提供 bundled Python 来源目录，发布目录只会生成空的 `python/` 占位目录
- 发布目录会复制 `frontend/web-ui/dist/`，并确保 `frontend/runtime-config.json` 存在
- 发布目录会复制 `custom_nodes/` 作为 workflow app 运行资源
- 发布目录会复制 `runtimes/third_party/ffmpeg/` 到 `tools/ffmpeg/`
- NVIDIA profile 会复制 `runtimes/tensorrt_bin/` 的 `bin/`、`python/`、`doc/` 到 `tools/tensorrt/`
- NVIDIA profile 会复制 `runtimes/cudnn_dll/` 的 `bin/` 和 `LICENSE` 到 `tools/cudnn/`
- CPU profile 不复制 TensorRT / cuDNN，并从 `app/requirements.txt` 中排除 `tensorrt-cu12`、`cuda-python`
- 使用本地 TensorRT SDK 时，发行目录 `python/` 中安装的 `tensorrt-cu12` 或本地 wheel 必须与 `tools/tensorrt/bin/` 中的 DLL 同版本
- NVIDIA 目标客户机默认要求安装可支持当前 CUDA/TensorRT 版本的 NVIDIA driver；TensorRT 和 cuDNN 用户态运行库随发布目录提供，CUDA Toolkit 不整体打包，按现场系统依赖单独安装
- 数据库文件、workflow templates/applications、预训练模型、数据集文件和其他开发数据不会随包复制；发布后的 `data/` 目录默认保持空目录
- 其他由发布流程生成的目录和脚本仍会按当前代码重新生成

## 根目录一键启动

进入发行目录后，默认推荐直接执行：

```powershell
.\start-amvision-full.bat
```

Linux 等价调用：

```bash
./start-amvision-full.sh
```

当前行为：

- 同时启动 backend-service 和当前 release profile 中声明的全部 worker
- 默认使用 `manifests/release-profiles/full.json`；如果发行目录中只有一个 release profile manifest，启动器会自动使用这个 manifest
- `custom_nodes/` 已随发布目录一起准备好，适合作为完整运行资源直接发出
- 子进程日志写到 `logs/full-stack/`
- 运行状态文件写到 `logs/full-stack/runtime-state.json`
- 根脚本保持前台运行，按 `Ctrl+C` 时会停止全部子进程

## 根目录一键停止

如果需要从另一个终端停止整套进程，进入发行目录后执行：

```powershell
.\stop-amvision-full.bat
```

Linux 等价调用：

```bash
./stop-amvision-full.sh
```

当前行为：

- stop 脚本会读取 `logs/full-stack/runtime-state.json`
- 按状态文件中记录的 pid 逐个停止 backend-service 和各 worker
- 停止后会清理运行状态文件

## 常用参数

```powershell
.\start-amvision-full.bat --host 0.0.0.0 --port 8000
.\start-amvision-full.bat --worker-profile-id inference
.\start-amvision-full.bat --worker-profile-id dataset-import --worker-profile-id inference
```

说明：

- 不传 `--worker-profile-id` 时默认启动当前 release profile 下全部 worker
- 传入一个或多个 `--worker-profile-id` 时，只启动指定 worker，适合现场裁剪和局部排障

## 细分文档入口

- 发布目录结构：`runtime-profiles.md`
- 同目录 Python 安装与替换：`bundled-python-deployment.md`
- 首次部署验收：`full-first-deploy-checklist.md`
- 现场日志与排障：`../operations/release-full-troubleshooting.md`

## 边界说明

- 一键启动是生产环境的默认入口，不再要求手工分开拉起 service 和 worker
- 当前发布目录包含代码、worker profile 和 custom_nodes，但不包含数据库内容、workflow 业务数据、预训练模型和开发期数据文件
- 如果一键启动后需要定位单一进程故障，再回退到 `launchers/service/` 和 `launchers/worker/` 的分开启动方式
