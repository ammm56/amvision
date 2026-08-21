# 运行时与发行包

AMVision 开发态使用 conda，生产态使用发行目录同级 bundled Python。发行包由源目录统一组装，不把 `release/<profile-id>/app/` 当作手工维护源码。

## 两种运行时

### 开发运行时

- Python 3.12+ conda 环境 `amvision`
- 仓库根目录的 `backend/`、`custom_nodes/` 和 `frontend/web-ui/`
- SQLite、本地 ObjectStore、Local Queue 和 LocalBufferBroker
- Vite 提供 HMR

### 生产运行时

- `release/<profile-id>/python/` 中的同目录 Python
- `app/backend/` 源码副本与 `app/requirements.txt`
- 已构建的 `frontend/`
- `config/`、`manifests/`、`launchers/`、`custom_nodes/` 和 `tools/`
- full Supervisor 统一启动完整进程组

目标机器不需要另装 conda、系统 Python 或系统 Node.js。NVIDIA driver、CUDA 兼容边界和其他无法随包交付的系统依赖单独声明。

## 当前发布 profile

| Profile | 平台 | 加速 | 状态 |
| --- | --- | --- | --- |
| `full-windows-x64-cpu` | Windows x64 | CPU/OpenVINO | 已实现 |
| `full-windows-x64-nvidia` | Windows x64 | CUDA/TensorRT/OpenVINO | 已实现 |

只有表中两个 Windows profile 是公开发行目标；其他 profile id 会被组装命令拒绝。

## 发行目录

```text
release/<profile-id>/
├─ app/
│  ├─ backend/
│  └─ requirements.txt
├─ config/
│  ├─ backend-service.json
│  └─ backend-worker.json
├─ custom_nodes/
├─ data/
├─ frontend/
│  ├─ index.html
│  └─ runtime-config.json
├─ launchers/
│  ├─ inference/
│  ├─ maintenance/
│  ├─ service/
│  └─ worker/
├─ logs/
├─ manifests/
│  ├─ release-profiles/
│  └─ worker-profiles/
├─ python/
├─ tools/
│  └─ ffmpeg/
├─ start-amvision-full.bat
├─ start_amvision_full.py
├─ stop-amvision-full.bat
└─ stop_amvision_full.py
```

NVIDIA profile 额外包含 `tools/tensorrt/` 和 `tools/cudnn/`。CPU profile 不复制这些资产，并使用 `requirements_cpu.txt` 生成不含 TensorRT/CUDA Python 包的 `app/requirements.txt`。

## 组装

```powershell
conda activate amvision
Set-Location frontend/web-ui
npm run build
Set-Location ../..
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-cpu --release-root .\release --force --output text
```

NVIDIA 机器把 profile 替换为 `full-windows-x64-nvidia`。

组装器：

- 复制当前 backend、Custom Node、配置和 launcher。
- 只复制与目标 profile 匹配的 FFmpeg/GPU 资产。
- 复制 `frontend/web-ui/dist/`，并生成或校验 `runtime-config.json`。
- 生成发行态 release manifest，其中包含六个 Worker Profile 和日期日志模式。
- `--force` 重建目录时临时保留并回迁已有 `python/`。
- 不复制开发数据库、Workflow 业务数据、数据集、预训练权重或其他 `data/` 内容。

## bundled Python

首次组装只创建空 `python/` 占位目录。发布人员把经过验收的 Python 环境整体复制或移动到：

```text
release/<profile-id>/python/python.exe
```

TensorRT Python wheel、DLL 和 `trtexec` 必须同版本。开发态资产位于 `runtimes/tensorrt_bin/` 与 `runtimes/cudnn_dll/`，发行态由组装器复制到 `tools/`。

`assemble-release` 不自动创建或更新 Python 环境，也不接受 Python 来源目录。完整安装、升级和回滚见 [bundled Python](../../deployment/bundled-python-deployment.md)。

## 进程拓扑

`start-amvision-full.bat` 是生产入口：

```text
Alembic migration
  → inference daemon + probe
  → backend-service + health
  → six Worker Profiles + heartbeat
```

Supervisor 持有唯一 Topology 锁。单 Worker Profile 崩溃时只恢复该 Profile；service 或 daemon 失效时回收完整 stack。低层 service/daemon/worker launcher 不是生产编排入口。

## 日志与状态

```text
logs/full-stack/database-migration-YYYYMMDD.log
logs/full-stack/inference-daemon-YYYYMMDD.log
logs/full-stack/backend-service-YYYYMMDD.log
logs/full-stack/backend-worker-<profile>-YYYYMMDD.log
logs/full-stack/runtime-state.json
```

每天的输出 append 到当天文件，跨日自动切换。状态文件保存进程身份、Topology、当前日志路径和日志模式，供 stop 与诊断使用。

## 升级与回滚

1. 停止完整进程组。
2. 备份数据库和业务 `data/`。
3. 在新目录组装或解压新 profile。
4. 准备对应 `python/` 与硬件 runtime。
5. 执行 `validate-layout`。
6. 启动；Supervisor 在其他组件前执行 Alembic。
7. 完成 health、OpenAPI、前端和目标业务 smoke。

代码回滚不能盲目回退已提交的数据 migration。数据库 downgrade 仅在对应 revision 明确支持且已备份时执行。

## 验收入口

- [生产环境](../../deployment/production-environment.md)
- [首次部署清单](../../deployment/full-first-deploy-checklist.md)
- [现场排障](../../operations/release-full-troubleshooting.md)
- `tests/test_release_assembly.py`
- `tests/integration/test_release_full_stack_acceptance.py`
