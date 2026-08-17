# 开发与完整启动说明

## 文档目的

本文档是仓库开发调试环境的完整启动入口，同时说明生产发布包的完整启动方式。项目实际使用时统一启动数据库迁移、inference daemon、backend-service、全量 backend-worker 和 Vue 前端，不把缺少任一常驻组件的局部启动作为完整运行状态。

## 完整进程关系

- inference daemon：托管 deployment、预热、sync/async 推理及其隔离子进程。
- backend-service：提供 REST API、WebSocket、静态前端和控制面能力。
- backend-worker：消费数据集导入导出、训练、转换、评估和异步推理任务。
- Vue 开发服务器：开发阶段提供前端 HMR；生产发布由 backend-service 提供已构建的静态资源。
- WorkflowAppRuntime：由 backend-service 按运行请求创建和监督，不需要额外手工启动独立 workflow 常驻入口。

## 开发环境完整启动顺序

所有后端命令都从仓库根目录执行。建议准备四个独立终端，并严格按下面的顺序启动。

### 1. 激活开发环境

在每个需要运行 Python 命令的终端中执行：

```powershell
conda activate amvision
```

确认当前解释器来自 `amvision` 环境：

```powershell
python -c "import sys; print(sys.executable)"
```

项目代码不得依赖系统 Python 的隐式状态。

### 2. 执行数据库迁移

在终端一执行：

```powershell
python -m backend.maintenance.main migrate-database --output text
```

该命令同时覆盖空数据库初始化、旧数据库接管和已有数据库升级。数据库已经位于最新 revision 时返回 `changed: False`，不会重复修改。

必须先完成迁移，再启动任何常驻后端进程。包含新 Alembic revision 的代码更新也按“停止完整进程组、迁移、重新完整启动”的顺序处理。

### 3. 启动 inference daemon

迁移成功后，在终端一继续执行并保持常驻：

```powershell
python -m backend.inference_daemon.main
```

看到下面的日志表示 daemon 已完成初始化：

```text
inference-daemon ready
```

当前默认配置为 `inference_daemon.runtime_owner=daemon`。daemon 未运行时，deployment、预热和推理链路不完整。

### 4. 探测 inference daemon

在终端二激活同一个 conda 环境，然后执行真实控制队列和 mmap 推理热路径双探测：

```powershell
python -m backend.inference_daemon.main --probe
```

命令退出码为 `0` 后才能继续启动 backend-service。探测失败时先检查终端一的 daemon 日志、`config/backend-service.json`、`data/queue/` 和 `data/buffers/inference-control/`，不要绕过探测继续启动。

数据库迁移、daemon 启动和 daemon probe 的开发命令只在本文档维护，其他文档只引用本页。

### 5. 启动 backend-service

daemon probe 成功后，在终端二执行并保持常驻：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 5600 --reload --reload-dir backend --reload-dir custom_nodes
```

也可以使用 VS Code Run and Debug 中的 `Python 调试程序: backend-service 热重载`。开发环境使用 `--reload` 时，只监视 `backend` 和 `custom_nodes` 两个源码目录；pytest 临时文件、数据资产、参考源码和发布生成物不会中断正在运行的 workflow runtime。热重载不会代替 daemon 或 worker 的重启。

等待启动日志完成后验证：

```powershell
Invoke-RestMethod http://127.0.0.1:5600/api/v1/system/health
```

预期 `status` 为 `ok`。

### 6. 启动全量 backend-worker

service health 成功后，在终端三激活同一个 conda 环境，然后执行并保持常驻：

```powershell
python -m backend.workers.main
```

完整开发环境始终启动全量 worker，不使用单一 worker profile 代替完整运行。VS Code 中可通过 `Tasks: Run Task` 选择 `amvision: 启动 backend-worker 全量`。

### 7. 启动 Vue 前端

在终端四执行：

```powershell
cd frontend/web-ui
npm run dev
```

前端默认地址为 `http://127.0.0.1:5601`，后端 API 默认地址为 `http://127.0.0.1:5600`。

### 8. 完整启动验收

下面各项同时满足，才视为开发环境完整启动：

1. inference daemon 终端持续运行，独立 probe 退出码为 `0`。
2. `http://127.0.0.1:5600/api/v1/system/health` 返回 `status=ok`。
3. backend-worker 日志显示全量 worker ready，任务队列能够被消费。
4. `http://127.0.0.1:5601` 可以打开并正常调用后端 API。
5. `http://127.0.0.1:5600/docs` 和 `http://127.0.0.1:5600/openapi.json` 可以访问。
6. 使用已登录身份访问 diagnostics 时，inference daemon 状态不是 `unavailable`。

## 开发环境停止顺序

开发环境按启动顺序的逆序停止：

1. 在终端四停止 Vue 前端。
2. 在终端三停止 backend-worker。
3. 在终端二停止 backend-service。
4. 在终端一停止 inference daemon。

每个终端使用 `Ctrl+C` 正常退出。确认没有遗留 Python 子进程后再迁移数据库、切换分支或替换运行时文件。

## 不同修改的重启规则

- Vue 页面修改：Vite HMR 自动更新；出现状态不一致时刷新页面。
- backend-service 修改：`--reload` 负责重载 service；涉及启动依赖或全局资源时完整重启全部进程。
- inference daemon、deployment runtime 或模型推理修改：重启 inference daemon，并重新 probe。
- inference daemon 与 backend-service 的本机调用协议、LocalBufferBroker 或 mmap 热路径修改：先停止 backend-service，再重启 inference daemon 并确认 probe 成功，最后重新启动 backend-service；不能只依赖 Uvicorn reload。
- backend-worker、训练、转换、数据集任务修改：重启全量 backend-worker。
- 配置、数据库 schema、进程监督或公共调用链修改：停止全部进程，执行数据库迁移，再按本文顺序完整启动。

## 生产发布包完整启动

生产环境不手工拆分启动 daemon、service 和 worker。进入实际发行目录后执行：

```powershell
.\start-amvision-full.bat
```

该入口自动按以下顺序执行：

1. 数据库迁移。
2. inference daemon 启动、ready 日志检查、真实控制队列和 mmap 推理热路径双 probe。
3. backend-service 启动和 health 检查。
4. release manifest 中声明的全部 backend-worker 依次启动和 ready 检查。
5. backend-service 提供随包构建的 Vue 静态资源。

任一步失败都会停止已经启动的组件并返回非零退出码。完整生产运行不传 `--worker-profile-id`，避免裁剪掉实际业务需要的消费者。

生产环境停止整套进程：

```powershell
.\stop-amvision-full.bat
```

停止入口按逆序回收完整进程树。仍有进程存活时会返回非零退出码并保留 `logs/full-stack/runtime-state.json`，不能手工删除状态文件后直接重复启动。

## 维护和回归命令

发布布局检查：

```powershell
python -m backend.maintenance.main validate-layout --output json
```

重新组装 Windows 发布目录：

```powershell
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-nvidia --release-root ./release --force --output text
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-cpu --release-root ./release --force --output text
```

`assemble-release --force` 会整体移动并恢复已有发行目录中的 `python/`，不会自动复制大体量 Python 环境。

后端最小回归：

```powershell
python -m pytest tests/test_release_assembly.py tests/test_bootstrap_chains.py tests/test_api_dependency_chain.py -k frontend_static
python -m pytest --collect-only -q
```

前端回归：

```powershell
cd frontend/web-ui
npm run test:unit
npm run build
```

`pytest.ini` 将默认临时目录固定为仓库根目录 `.tmp/pytest`，并把 pytest cache 固定为 `.tmp/pytest-cache`。并行长链或 Windows 文件句柄排查才使用独立的 `.tmp/<name>` 子目录。

## 细分文档入口

- service 启动和 health：`backend-service-startup.md`
- worker 进程与 profile：`backend-worker-startup.md`
- inference daemon 架构和恢复：`inference-daemon.md`
- maintenance 和数据库迁移：`backend-maintenance.md`
- 生产发布：`production-environment.md`
- 首次发布验收：`full-first-deploy-checklist.md`

## 运行边界

- 开发环境为了日志和断点调试而拆成多个终端，但这些终端共同组成一个完整项目实例。
- 生产环境统一使用根目录一键启动和停止入口，不以手工拆分进程作为正常运行方式。
- WorkflowAppRuntime 的隔离 worker 由 backend-service 按业务状态管理，不是需要额外手工启动的第五个固定后端入口。
