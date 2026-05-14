# backend-maintenance 说明

## 文档目的

本文档用于说明当前最小 maintenance CLI 的入口、可执行命令和与发布 launchers 的对应关系。

当前 maintenance 还不是完整运维平台，但已经提供统一入口来查看版本、输出配置、校验运行时布局和组装 release 目录。

## 当前入口

- Python 模块入口：`backend.maintenance.main`
- bootstrap：`backend.maintenance.bootstrap.BackendMaintenanceBootstrap`
- Python launcher：`runtimes/launchers/maintenance/invoke_backend_maintenance.py`
- wrapper：`runtimes/launchers/maintenance/invoke-backend-maintenance.bat`、`runtimes/launchers/maintenance/invoke-backend-maintenance.sh`

## 当前命令

### version

- 输出 `app_name`
- 输出 `app_version`
- 输出 `workspace_dir`

### show-config

- 输出当前 maintenance settings 的 JSON 视图
- 用于核对 `config/backend-maintenance.json` 是否生效

### validate-layout

- 校验当前工作目录下 `config`
- 校验当前工作目录下 `data`
- 校验 `launchers` 或 `runtimes/launchers`
- 校验 `manifests/release-profiles` 或 `runtimes/manifests/release-profiles`
- 校验 `manifests/worker-profiles` 或 `runtimes/manifests/worker-profiles`

### assemble-release

- 按指定 `release profile` 组装 `release/<profile_id>/` 发行目录；当前默认使用 `full`
- 自动复制 backend 源码、配置模板、Python launcher 和 bat/sh wrapper
- 自动复制当前 profile 需要的 worker profile manifest，并生成 `start-<profile_id>-worker.bat/sh`
- 自动复制仓库根目录的 `requirements.txt` 到发行目录里的 `app/requirements.txt`
- 自动创建空的 `python/` 目录，供后续手工复制 bundled Python
- 如果目标发行目录已经存在且传入 `--force`，当前会保留已有的 `python/` 目录内容，不会在覆盖时删除它
- 自动生成发行目录内可直接使用的 `manifests/release-profiles/<profile_id>.json`

## 开发环境调用

```powershell
conda activate amvision
python -m backend.maintenance.main version --output text
python -m backend.maintenance.main show-config --output json
python -m backend.maintenance.main validate-layout --output json
python -m backend.maintenance.main assemble-release --profile-id full --release-root ./release --force --output text
```

## 同目录 Python 运行时调用

```powershell
.\launchers\maintenance\invoke-backend-maintenance.bat -- validate-layout --output text
```

说明：

- 仓库里的 launcher 模板位于 `runtimes/launchers/maintenance/`
- `assemble-release` 会把 maintenance launcher 复制到发布目录里的 `launchers/maintenance/`
- 发布目录里如果已经把 Python 放到 `python/`，wrapper 会优先自动使用 `python/python.exe`

## 当前用途边界

- 当前 maintenance 只覆盖版本查看、配置输出、布局校验和最小 release 目录组装
- 当前还没有正式接入数据库修复、文件修复、缓存清理或自定义节点修复命令
- 后续如果增加修复类命令，应继续挂在 `backend.maintenance.main` 入口下，而不是再分散到多个临时脚本