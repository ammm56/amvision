# 开发环境启动

本文给出当前代码可用的启动步骤。开发时按目标选择“API/UI 快速调试”或“完整业务链路”，不要把缺少 Worker 的局部启动误认为完整平台。

## 前置条件

- 从仓库根目录执行后端命令。
- 已创建并激活 `amvision` conda 环境。
- Python 版本为 3.12+，依赖已按 `requirements.txt` 安装。
- Node.js 满足 `frontend/web-ui/package.json` 的 `engines`，前端已执行 `npm ci`。
- `config/backend-service.json` 与 `config/backend-worker.json` 中的数据库、文件、队列和 runtime 路径可写。

## 模式 A：API/UI 快速调试

这种模式适合 REST API、页面、鉴权、只读查询和普通控制面开发。它不启动后台任务消费者，也不保证 Deployment 推理链完整。

### 1. 激活 Python 环境

```powershell
conda activate amvision
python -c "import sys; print(sys.executable)"
```

### 2. 升级数据库

```powershell
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
```

必须先迁移再启动服务。不要依赖 ORM `create_all()` 修补历史 schema。

### 3. 启动 backend-service

终端一：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 5600 --reload --reload-dir backend --reload-dir custom_nodes
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:5600/api/v1/system/health
```

### 4. 启动 Vue 前端

终端二：

```powershell
Set-Location frontend/web-ui
npm run dev
```

访问：

- Web UI：`http://127.0.0.1:5601`
- OpenAPI：`http://127.0.0.1:5600/docs`
- OpenAPI JSON：`http://127.0.0.1:5600/openapi.json`

### 5. 停止

先停止 Vite，再停止 Uvicorn；两个终端分别使用 `Ctrl+C`。

## 模式 B：完整业务链路

数据集导入导出、训练、转换、评估、异步推理、Deployment、Workflow Runtime 和 Trigger 必须使用 full Supervisor。当前源码目录不是发行目录，先组装本地 release。

### 1. 构建前端

```powershell
conda activate amvision
Set-Location frontend/web-ui
npm run build
Set-Location ../..
```

### 2. 组装本地发行目录

CPU 开发机：

```powershell
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-cpu --release-root .\release --force --output text
```

NVIDIA 开发机：

```powershell
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-nvidia --release-root .\release --force --output text
```

`assemble-release` 会复制本次源码、配置模板、前端 build、custom nodes、launcher 和 manifest。源码修改后要重新组装，发行目录不是手工维护的源码目录。

### 3. 指定开发解释器

开发验收可以让发行目录使用当前 conda Python，不必把环境复制到 `python/`：

```powershell
$env:AMVISION_PYTHON_EXECUTABLE = (Get-Command python).Source
```

这个环境变量只影响当前终端。正式交付仍使用发行目录中的 `python/python.exe`。

### 4. 校验发行布局

CPU 示例：

```powershell
Set-Location release/full-windows-x64-cpu
.\launchers\maintenance\invoke-backend-maintenance.bat -- validate-layout --output text
```

NVIDIA 环境把目录替换为 `release/full-windows-x64-nvidia`。

### 5. 启动完整拓扑

```powershell
.\start-amvision-full.bat --host 127.0.0.1 --port 5600
```

Supervisor 会依次完成：

1. Alembic `upgrade head`。
2. inference daemon 启动与 probe。
3. backend-service 启动与 health。
4. `dataset-import`、`dataset-export`、`training`、`conversion`、`evaluation`、`inference` 六个 Worker Profile 启动与心跳验证。

启动脚本保持前台运行。不要直接执行 `python -m backend.workers.main`；Worker 缺少 Supervisor 注入的 Topology id、generation、epoch 和 instance id 时会拒绝启动。

### 6. 可选：使用 Vite 调试 UI

保持完整拓扑运行，在新的终端回到仓库根目录：

```powershell
Set-Location frontend/web-ui
npm run dev
```

Vite 使用 `5601`，完整后端继续使用 `5600`。生产形态的静态前端仍以发行目录内 build 为准。

### 7. 验收

```powershell
Invoke-RestMethod http://127.0.0.1:5600/api/v1/system/health
```

同时检查：

- 设置页的 Worker Topology 只有一个 active epoch。
- 六个 Profile 均为 `running`。
- `logs/full-stack/` 已生成当天的 service、daemon、migration 和 Profile 日志。
- 至少一个目标业务任务从 `queued` 推进到终态。

### 8. 停止完整拓扑

在发行目录的另一个终端执行：

```powershell
.\stop-amvision-full.bat
```

停止成功后 `logs/full-stack/runtime-state.json` 会被清理。返回非零时先按状态文件和当日日志排查，不能直接删除状态文件后重复启动。

回到仓库根目录并清除开发解释器覆盖：

```powershell
Set-Location ../..
Remove-Item Env:AMVISION_PYTHON_EXECUTABLE -ErrorAction SilentlyContinue
```

## 修改后的重启范围

| 修改 | 最小动作 |
| --- | --- |
| Vue 页面 | Vite HMR；生产 build 需重新 `npm run build` 和组装 |
| REST/API 普通代码 | 快速模式由 Uvicorn reload；完整链需重新组装并重启 |
| Alembic/schema/config/bootstrap | 停止进程，迁移后完整重启 |
| Worker、训练、转换、评估 | 重新组装并由 full Supervisor 启动 |
| inference daemon、Deployment、mmap/LocalBuffer | 完整停止、重新组装和启动 |
| Workflow Runtime worker/Trigger | 完整重启并复跑版本、revision、epoch 相关测试 |

## 相关文档

- [开发指南](../development/README.md)
- [backend-service 启动](backend-service-startup.md)
- [Worker Topology](backend-worker-startup.md)
- [生产环境](production-environment.md)
- [首次部署清单](full-first-deploy-checklist.md)
