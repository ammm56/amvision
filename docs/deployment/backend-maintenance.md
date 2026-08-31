# backend-maintenance 说明

## 文档目的

本文档用于说明当前最小 maintenance CLI 的入口、可执行命令和与发布 launchers 的对应关系。

当前 maintenance 还不是完整运维平台，但已经提供统一入口来查看版本、输出配置、迁移数据库、校验运行时布局和组装 release 目录。

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
- 发布目录中会按 manifest 校验目标平台、`README.md`、Windows bundled Python、Windows FFmpeg 和根 launcher
- CPU 发布会把 TensorRT/cuDNN 目录视为非法混入；Windows 发布会把 Linux launcher、Linux FFmpeg 和 Linux Python 布局视为非法混入

### assemble-release

- canonical profile 为 `full-windows-x64-nvidia` 和 `full-windows-x64-cpu`
- NVIDIA 包复制并校验 Windows x64 TensorRT / cuDNN；CPU 包不复制这些资产，并拒绝 NVIDIA-only requirements
- profile id 必须使用完整目标名称；Ubuntu profile 仅预留，当前不允许组装
- 自动复制 backend 源码、配置模板、Python launcher 和 Windows bat wrapper
- 自动复制当前 profile 需要的全部 Worker Profile manifest；Worker 只由 full Supervisor 启动，不生成脱离 Topology 的固定 Profile wrapper
- 自动复制仓库根 `README.md`、`LICENSE`、`LICENSE.zh-CN` 和 `COMMERCIAL_LICENSE_REQUIRED.md`
- 自动复制仓库根目录的 `requirements.txt` 到发行目录里的 `app/requirements.txt`，并按 profile 过滤不适用依赖
- 当目标发行目录已经存在且传入 `--force`，当前会先把已有的 `python/` 目录临时移到旁路目录，完成目录重建后再移回
- 如果 release 组装中途失败，当前也会恢复原来的 `python/` 目录，避免 bundled Python 在失败时丢失
- 不自动复制或重建 Python 环境；bundled Python 由发布人员放入目标发行目录
- 如果当前发布目录没有可执行的 Python，会创建或保留占位目录并在 manifest 中标记 `placeholder-empty`；仅存在目录或标记文件不会被误报为已包含
- full 启动器只接受显式 `--python-executable` 或发布目录中的 `python/python.exe`，不会回退到系统 Python
- 当 release profile 要求包含前端时，自动复制 `frontend/web-ui/dist/` 到发行目录里的 `frontend/`
- 如果前端构建结果里没有 `runtime-config.json`，当前会优先使用 `runtime-config.local.json`，否则回退到 `runtime-config.template.json` 自动生成
- 自动生成发行目录内可直接使用的 `manifests/release-profiles/<profile_id>.json`

### migrate-database

- 按 `config/backend-service.json` 中的数据库 URL 执行 Alembic `upgrade head`
- 兼容历史上由 `create_all()` 建立但没有 `alembic_version` 的数据库
- SQLite 在实际迁移前使用 backup API 生成包含 WAL 最新内容的一致性备份
- schema 已经位于当前 head 时不会重复备份或写库
- full 根启动器会在 daemon、service、worker 启动前自动执行，失败时禁止继续启动

### rebuild-pycache

- 删除并重新生成 Python `__pycache__` 字节码缓存
- 默认只处理仓库内源码目录：`backend`、`custom_nodes`、`tests`、`scripts`
- 默认不处理整个 conda 或 bundled Python 的 `site-packages`
- 如需修复某个依赖包缓存，必须显式传入 `--python-package <包名>`
- `--clean-only` 只删除缓存，不重新编译
- `--compile-only` 只重新编译，不删除已有缓存

`__pycache__` 是 CPython 在导入 `.py` 文件时自动生成的字节码缓存目录。正常情况下可以安全删除，后续导入或 `compileall` 会重新生成。若源码与 `.pyc` 缓存出现不一致、磁盘缓存损坏或依赖包更新过程异常，可能出现导入时使用了错误字节码的情况。

依赖包缓存修复不作为默认行为，是为了避免维护命令无意中改动整个 Python 环境。现场发现类似 `sqlalchemy` 这类依赖包 `.pyc` 损坏时，可按包名精确修复。

### reset-development-workflow-state

- 仅用于开发数据库断代，不属于生产升级或回滚命令。
- 默认只输出 Workflow 表数量、活动资源数量和精确文件路径，不修改数据。
- 写入前必须停止全部 Workflow Runtime、Trigger、Run 和 Preview，并显式传入 `--confirm-workflow-reset`。
- 清除 App 草稿、Graph、发布版本、Runtime、Revision、Trigger、Run、Preview、Workflow 执行目录和 Workflow Trigger mailbox。
- 保留数据集、模型、Deployment、任务、推理 LocalBuffer、Inference mailbox 和 Training Telemetry。
- 文件先在同一受信根内改名暂存；数据库事务失败时恢复原路径，提交成功后再物理删除。
- 不删除 `amvision.db` 或数据库备份；备份清理由停服后的独立运维步骤执行。

### clear-development-workflow-history

- 仅用于开发验收完成后的执行记录清理。
- 默认只预览 Run、Preview 和对应目录，不修改正式资源。
- 写入前必须停止全部 Workflow Runtime 和 Trigger，并显式传入 `--confirm-workflow-history-clear`。
- 只删除 Workflow Run、Preview、运行目录和结果目录，同时清空 Runtime/Trigger 的调用诊断残留。
- 保留 App、Graph、发布版 v1、Runtime、Revision 和 Trigger id。

### rebuild_development_workflows.py

`scripts/rebuild_development_workflows.py` 从显式 baseline manifest 读取 Application 和 Template JSON，并通过公开 REST API 依次创建 App/Graph、首次发布版 v1、Runtime、ZeroMQ Trigger 和 Local Shared Memory Trigger。脚本拒绝在非空 Workflow 状态上叠加资源；`--validate-only` 只校验 manifest、命名、端口和高性能输入边界。

生成规则固定为：

- `workflow-app-<14位时间>` 与 `workflow-graph-<同一时间>`；
- `workflow-runtime-<UUID>` 由平台生成；
- `zeromq-<workflow-runtime-id>`；
- `local-shared-memory-<workflow-runtime-id>`；
- 高性能 Trigger 只绑定 Application 实际公开的 `request_image_ref`、`request_json`、`request_text`。

## 开发环境调用

```powershell
conda activate amvision
python -m backend.maintenance.main version --output text
python -m backend.maintenance.main show-config --output json
python -m backend.maintenance.main validate-layout --output json
python -m backend.maintenance.main migrate-database --output text
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-nvidia --release-root ./release --force --output text
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-cpu --release-root ./release --force --output text
python -m backend.maintenance.main rebuild-pycache --output text
python -m backend.maintenance.main rebuild-pycache --python-package sqlalchemy --output text
python -m backend.maintenance.main rebuild-pycache --clean-only --output text
python -m backend.maintenance.main reset-development-workflow-state --output json
python -m backend.maintenance.main reset-development-workflow-state --confirm-workflow-reset --output json
python -m backend.maintenance.main clear-development-workflow-history --output json
python -m backend.maintenance.main clear-development-workflow-history --confirm-workflow-history-clear --output json
python scripts/rebuild_development_workflows.py --manifest <baseline-manifest.json> --validate-only
```

## 同目录 Python 运行时调用

```powershell
.\launchers\maintenance\invoke-backend-maintenance.bat -- validate-layout --output text
.\launchers\maintenance\invoke-backend-maintenance.bat -- migrate-database --output text
.\launchers\maintenance\invoke-backend-maintenance.bat -- rebuild-pycache --output text
.\launchers\maintenance\invoke-backend-maintenance.bat -- rebuild-pycache --python-package sqlalchemy --output text
```

说明：

- 仓库里的 launcher 模板位于 `runtimes/launchers/maintenance/`
- `assemble-release` 会把 maintenance launcher 复制到发布目录里的 `launchers/maintenance/`
- 发布目录里如果已经把 Python 放到 `python/`，wrapper 会优先自动使用 `python/python.exe`

## 当前用途边界

- 当前 maintenance 覆盖版本查看、配置输出、数据库迁移、布局校验、release 目录组装、Workflow runtime 临时存储清理、开发期 Workflow 断代重置、开发期执行历史清理和 Python pycache 清理重建
- 当前还没有正式接入通用数据库数据修复、文件修复或自定义节点修复命令
- 后续如果增加修复类命令，应继续挂在 `backend.maintenance.main` 入口下，而不是再分散到多个临时脚本
