# 开发环境完整启动

本文只说明源码仓库的开发启动。开发环境直接运行 `backend/`、`custom_nodes/` 和 `frontend/web-ui/` 中的源码，不组装或进入 `release/`。

生产发行包的组装、Bundled Python 和一键启动见 [生产环境](production-environment.md)。

## 完整进程关系

开发时需要同时运行以下进程：

1. backend-service：提供 REST API、WebSocket、Workflow Runtime、Trigger 和控制面，并持有唯一主 LocalBufferBroker。
2. inference daemon：托管 Deployment 和模型推理进程，直接访问 backend-service 创建的主 LocalBuffer。
3. backend-worker development supervisor：激活一代源码开发 Worker Topology，并启动数据集导入、数据集导出、训练、转换、评估、异步推理六个 Worker Profile。
4. Vue Vite：提供源码前端和 HMR。

`uvicorn` 只负责第 2 项，不会启动 inference daemon、Worker Supervisor 或 Vite。只启动 Uvicorn 不是完整开发环境。

## 前置条件

- 从仓库根目录执行后端命令。
- 已创建 `amvision` conda 环境，并按 `requirements.txt` 安装依赖。
- 已在 `frontend/web-ui/` 执行 `npm ci`。
- Python 版本为 3.12+；Node.js 版本满足 `frontend/web-ui/package.json` 的 `engines`。
- `config/backend-service.json` 和 `config/backend-worker.json` 中的数据库、ObjectStore、Queue 与 runtime 路径可写。

建议准备四个终端。每个运行 Python 的终端先执行：

```powershell
conda activate amvision
python -c "import sys; print(sys.executable)"
```

## 启动顺序

### 1. 升级数据库

先在仓库根目录执行一次：

```powershell
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
```

必须先完成迁移，再启动常驻进程。禁止用 `stamp`、ORM `create_all()` 或删除数据库绕过 migration chain。

### 2. 启动 backend-service

终端一：

```powershell
conda activate amvision
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 5600 --reload --reload-dir backend --reload-dir custom_nodes
```

backend lifespan 会先创建 LocalBuffer，再恢复现有 Workflow Runtime。恢复流程可能需要调用 inference daemon，因此此时不等待完整 HTTP health。另开临时终端只探测主 LocalBuffer：

```powershell
conda activate amvision
python -m backend.inference_daemon.main --probe-local-buffer
```

退出码为 `0` 表示主 LocalBufferBroker owner 和 arena layout 已就绪，可以启动 daemon。`--reload` 只监视后端源码，不会代替 daemon 或 Worker 的重启。

### 3. 启动 inference daemon

终端二：

```powershell
conda activate amvision
python -m backend.inference_daemon.main
```

看到 `inference-daemon ready` 后保持该终端运行。当前默认配置为 `inference_daemon.runtime_owner=daemon`；没有 daemon 时，Deployment、预热与推理链路不完整。

### 4. 探测 inference daemon

另开临时终端执行真实 probe：

```powershell
conda activate amvision
python -m backend.inference_daemon.main --probe
```

退出码为 `0` 后，再验证 backend-service 完整 health：

```powershell
Invoke-RestMethod http://127.0.0.1:5600/api/v1/system/health
```

daemon probe 同时验证 mailbox、主 LocalBuffer 依赖、首轮 Deployment 恢复以及全部实例预热结果，不再把仅能 ping 通误报为 ready。backend health 必须放在 daemon probe 后，避免包含模型节点的 Workflow Runtime startup 与 daemon 互相等待。

### 5. 启动完整 backend-worker Topology

终端三：

```powershell
conda activate amvision
python -m backend.workers.supervisor
```

这是源码开发入口。它使用当前 conda Python 和源码目录完成以下工作：

1. 获取唯一 Topology 锁并生成新的 generation/epoch。
2. 读取 `runtimes/manifests/worker-profiles/*.json`。
3. 启动 `dataset-import`、`dataset-export`、`training`、`conversion`、`evaluation`、`inference` 六个严格 Profile。
4. 等待六个 Profile 的当前 epoch heartbeat 全部进入 `running`。
5. 持续监督进程；任一 Profile 异常退出时明确失败并回收本代 Topology。

看到 `backend-worker development topology ready` 后保持终端运行。

不要直接执行 `python -m backend.workers.main`。该模块是单个 Profile 的内部入口，必须由 Supervisor 注入 topology id、generation、epoch、worker instance 和 profile manifest。

### 6. 启动 Vue 前端

终端四：

```powershell
Set-Location frontend/web-ui
npm run dev
```

默认地址：

- Web UI：`http://127.0.0.1:5601`
- API：`http://127.0.0.1:5600`
- OpenAPI：`http://127.0.0.1:5600/docs`

### 7. 编译和启动桌面启动器

从仓库根目录执行，构建机需要 .NET 10 SDK：

```powershell
dotnet build launcher/Amvar.Launcher.slnx
dotnet run --project launcher/src/Amvar.Launcher.Desktop/Amvar.Launcher.Desktop.csproj --no-build
```

普通 Debug 输出位于 `launcher/src/Amvar.Launcher.Desktop/bin/Debug/net10.0/`，配置位于该目录的 `config/launcher.json`。开发服务由前述终端手动启动；启动器设置中关闭“启动并管理视觉服务”（`manage_service=false`）后重启，仅连接查看，不停止手动服务。未配置 Fixed Version WebView2 时，这种源码运行方式需要本机安装 Evergreen WebView2。

验证随包 .NET 和 WebView2 的发布运行方式：先将 Fixed Version WebView2 x64 解压到 `runtimes/third_party/webview2/win-x64/`，确保目录直接包含 `msedgewebview2.exe`，然后执行：

```powershell
$launcherPublishDirectory = Join-Path (Get-Location) ('launcher/bin/publish/dev-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
./launcher/publish-win-x64.ps1 -OutputDirectory $launcherPublishDirectory
& (Join-Path $launcherPublishDirectory 'amvar.launcher.exe')
```

发布输出仍在 `launcher/` 内，配置位于此次输出的 `launcher/config/launcher.json`。启动器地址固定为 `http://127.0.0.1:5600`，显示后端提供的静态前端，不使用 `5601` 的 Vite HMR；修改前端后需重新构建静态资源才能在启动器查看。启动器源码修改后退出托盘应用，再重新编译运行；已有发布目录不能覆盖，使用新的输出目录。

```powershell
dotnet test launcher/Amvar.Launcher.slnx
```

完整发行冷启动与退出回归需先停止开发后端、daemon 和 Worker，确保 5600 与共享内存无占用。以下测试使用指定发行目录自己的 Python 和 full 脚本，不使用 conda Python 执行服务；默认测试不会启动完整视觉栈：

```powershell
$env:AMVAR_LAUNCHER_RELEASE_TEST_ROOT = (Resolve-Path release/full-windows-x64-nvidia).Path
dotnet test tests/launcher/Amvar.Launcher.Infrastructure.Tests/Amvar.Launcher.Infrastructure.Tests.csproj --filter FullyQualifiedName~ReleaseStartupTests
Remove-Item Env:AMVAR_LAUNCHER_RELEASE_TEST_ROOT
```

CPU 验收时替换 profile 目录。测试会启动并停止其自身创建的服务，日志保留在发行目录的 `launcher/logs/release-acceptance/` 和 `logs/full-stack/`；测试不会把正常监听的外部服务接管为自己的服务。

完整产品发行需继续按 [生产环境](production-environment.md) 将启动器、bundled Python 和视觉服务组装在一起。

## 完整启动验收

以下条件同时满足才是完整开发环境：

1. backend-service health 可访问，主 LocalBufferBroker、API 与 OpenAPI 正常。
2. inference daemon 持续运行，独立 probe 返回 `0`。
3. Worker Supervisor 显示完整 Topology ready。
4. Settings 服务页显示六个 Worker Profile 属于同一 active generation/epoch 且状态为 `running`。
5. Vite 页面能完成登录和 API bootstrap。
6. 至少一个目标后台任务能从 `queued` 推进到终态。
7. 目标 Deployment 和 Workflow Runtime 能完成 start、health、invoke、stop。

## 停止顺序

按启动顺序的逆序停止，各终端使用 `Ctrl+C`：

1. 停止 Vite。
2. 停止 backend-worker development supervisor，等待六个子进程退出。
3. 停止 inference daemon，等待 deployment 子进程退出。
4. 停止 backend-service，等待 lifespan 和 LocalBufferBroker 清理完成。

确认没有遗留进程后再迁移数据库、切换分支或替换 runtime 文件。

## 修改后的重启范围

| 修改 | 开发环境动作 |
| --- | --- |
| Vue 页面 | Vite HMR；状态不一致时刷新页面 |
| REST/API 普通代码 | Uvicorn reload |
| backend-service bootstrap、Workflow Runtime、Trigger | 完整重启 backend-service |
| Worker、训练、转换、评估、数据集任务 | 重启 Worker Supervisor |
| inference daemon、Deployment、mmap、LocalBuffer | 停止 daemon，再停止 service；启动 service 并通过 health 后再启动 daemon 和 probe |
| Alembic、配置、公共进程协议 | 停止全部进程，迁移后按本文顺序完整启动 |

## 快速局部调试边界

仅调试 REST、页面或只读接口时，可以临时只启动 backend-service 和 Vite。此时 Settings 中 inference daemon/Worker 显示不可用或降级是符合实际状态的，不代表完整链路可用，也不能用来验收数据集、训练、转换、异步推理或 Deployment。

## 相关文档

- [backend-service 启动](backend-service-startup.md)
- [Worker Topology](backend-worker-startup.md)
- [inference daemon](inference-daemon.md)
- [数据库与维护](backend-maintenance.md)
- [生产环境](production-environment.md)
