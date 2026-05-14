# 生产环境说明

## 文档目的

本文档用于给生产环境提供统一入口，说明 `release/full/` 的生成方式、目录职责、bundled Python 处理方式，以及根目录一键启动和停止的推荐做法。

## 适用范围

- 通过 `assemble-release` 组装的 `release/full/`
- 同目录 Python 运行时
- Windows bat / Linux sh 根目录一键启动

## 当前推荐顺序

1. 在仓库根目录执行 `assemble-release`
2. 把 Python 手工放入 `release/full/python/`
3. 在 `release/full/` 根目录执行一键启动脚本
4. 检查 health、OpenAPI 文档和最小任务 smoke test

## 发布命令

```powershell
conda activate amvision
python -m backend.maintenance.main assemble-release --profile-id full --release-root ./release --force --output text
```

说明：

- 如果 `release/full/python/` 已经存在，`assemble-release --force` 会保留这个目录及其中内容，不会在覆盖发布时删除它
- 发布目录会复制 `custom_nodes/` 作为 workflow app 运行资源
- 数据库文件、workflow templates/applications、预训练模型、数据集文件和其他开发数据不会随包复制；发布后的 `data/` 目录默认保持空目录
- 其他由发布流程生成的目录和脚本仍会按当前代码重新生成

## 根目录一键启动

进入 `release/full/` 后，默认推荐直接执行：

```powershell
.\start-amvision-full.bat
```

Linux 等价调用：

```bash
./start-amvision-full.sh
```

当前行为：

- 同时启动 backend-service 和 full profile 中声明的全部 worker
- 默认使用 `manifests/release-profiles/full.json` 决定要拉起的 worker profile
- `custom_nodes/` 已随发布目录一起准备好，适合作为完整运行资源直接发出
- 子进程日志写到 `logs/full-stack/`
- 运行状态文件写到 `logs/full-stack/runtime-state.json`
- 根脚本保持前台运行，按 `Ctrl+C` 时会停止全部子进程

## 根目录一键停止

如果需要从另一个终端停止整套进程，进入 `release/full/` 后执行：

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

- 不传 `--worker-profile-id` 时默认启动 full profile 下全部 worker
- 传入一个或多个 `--worker-profile-id` 时，只启动指定 worker，适合现场裁剪和局部排障

## 细分文档入口

- 发布目录结构：`runtime-profiles.md`
- 同目录 Python 安装与替换：`bundled-python-deployment.md`
- 首次部署验收：`full-first-deploy-checklist.md`

## 边界说明

- 一键启动是生产环境的默认入口，不再要求手工分开拉起 service 和 worker
- 当前 full 发布目录包含代码、worker profile 和 custom_nodes，但不包含数据库内容、workflow 业务数据、预训练模型和开发期数据文件
- 如果一键启动后需要定位单一进程故障，再回退到 `launchers/service/` 和 `launchers/worker/` 的分开启动方式