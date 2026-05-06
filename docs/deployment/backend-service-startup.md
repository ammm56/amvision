# backend-service 启动说明

## 文档目的

本文档用于说明当前仓库里的 FastAPI backend-service 怎么启动、启动后能看到什么、默认会使用哪些本地目录，以及当前还没有自动完成的初始化步骤。

本文档只覆盖 backend-service 本身，不展开独立 worker、打包发布和前端分发。

## 适用范围

- conda 开发环境中的 backend-service 启动
- 同目录 Python 运行时中的 backend-service 启动
- 健康检查、OpenAPI 文档和最小验收步骤
- 当前默认数据库与文件目录
- 当前启动链路的已知限制

## 当前服务入口

- ASGI 应用入口：backend.service.api.app:app
- FastAPI app factory：backend.service.api.app.create_app
- 健康检查：/api/v1/system/health
- 当前公开任务接口：/api/v1/tasks
- 当前公开任务事件订阅：/ws/tasks/events
- OpenAPI JSON：/openapi.json
- Swagger UI：/docs

## 当前默认本地目录

当前服务未传自定义配置时会使用下面三个默认路径：

- SQLite 数据库目标路径：./data/amvision.db
- 数据集本地文件目录：./data/files
- 本地持久化队列目录：./data/queue

当前实现的行为是：

- 服务启动时会创建 ./data、./data/files 和 ./data/queue 目录
- SQLite 文件路径默认指向 ./data/amvision.db
- SQLite 数据库文件会在第一次真正建立数据库连接时创建
- 本地队列目录用于保存 DatasetImport 异步处理使用的 pending、claimed、completed、failed 任务文件

## 当前配置来源

当前服务通过统一 settings 模块读取启动配置。

- 配置入口：backend.service.settings.BackendServiceSettings
- 默认读取方式：config 目录 JSON + 环境变量覆盖 + 代码内默认值
- 环境变量前缀：AMVISION_
- 嵌套字段分隔符：__
- 默认主配置文件：./config/backend-service.json
- 可选本地覆盖文件：./config/backend-service.local.json
- 默认 task manager 配置：enabled=true、max_concurrent_tasks=2、poll_interval_seconds=1.0

常见示例：

- config/backend-service.json

```json
{
  "app": {
    "app_name": "amvision backend-service",
    "app_version": "0.1.0"
  },
  "database": {
    "url": "sqlite:///./data/amvision.db",
    "echo": false
  },
  "dataset_storage": {
    "root_dir": "./data/files"
  },
  "queue": {
    "root_dir": "./data/queue"
  },
  "task_manager": {
    "enabled": true,
    "max_concurrent_tasks": 2,
    "poll_interval_seconds": 1.0
  }
}
```

- AMVISION_APP__APP_NAME=amvision backend-service
- AMVISION_APP__APP_VERSION=0.1.0
- AMVISION_DATABASE__URL=sqlite:///./data/amvision.db
- AMVISION_DATABASE__ECHO=false
- AMVISION_DATASET_STORAGE__ROOT_DIR=./data/files
- AMVISION_QUEUE__ROOT_DIR=./data/queue
- AMVISION_TASK_MANAGER__ENABLED=true
- AMVISION_TASK_MANAGER__MAX_CONCURRENT_TASKS=2
- AMVISION_TASK_MANAGER__POLL_INTERVAL_SECONDS=1.0

说明：

- 本地部署优先修改 config 目录 JSON 文件，而不是直接改代码
- 环境变量主要用于测试、调试、launcher 注入和临时覆盖
- 如果 config 文件和环境变量都未提供，当前服务会回退到仓库默认值

## 启动前要知道的事

### 当前仓库已经具备的能力

- FastAPI 服务可直接通过 uvicorn 启动
- REST 路由、WebSocket 路由、中间件和异常映射已装配完成
- /api/v1/system/health 可以直接返回最小健康状态
- /api/v1/tasks 和 /ws/tasks/events 已经公开
- 在 task_manager.enabled=true 时，backend-service 生命周期会自动托管 DatasetImport 队列 worker

### 当前仓库还没有自动完成的事

- 当前服务启动时会自动创建缺失的数据表，但不会做 schema 迁移
- 当前仓库还没有正式接入 Alembic 初始化命令或 maintenance launcher
- 如果已有旧版本数据库文件且表结构落后，当前仍需要手动迁移或重建数据库

这意味着：

- 新环境下直接启动服务即可拿到当前代码对应的基础表结构
- 旧数据库如果缺列、列类型不同，当前不会在启动时自动修正

## 当前启动流

当前 backend-service 的启动链路如下：

1. `create_app` 创建 `BackendServiceBootstrap`
2. bootstrap 读取 `BackendServiceSettings`
3. bootstrap 构建 `BackendServiceRuntime`，其中包含：
  - `SessionFactory`
  - `LocalDatasetStorage`
  - `LocalFileQueueBackend`
  - 可选的 `HostedBackgroundTaskManager`
4. `create_app` 把这些运行时对象绑定到 `application.state`
5. FastAPI lifespan 启动时执行：
  - 初始化数据库缺失表
  - 运行显式传入的 seeders
  - 执行插件目录元数据预留步骤
  - 启动当前进程托管的后台任务宿主
6. 当前后台任务宿主只注册 DatasetImport queue worker
7. 应用关闭时停止后台任务宿主并释放数据库 engine

## 开发环境启动

以下步骤从仓库根目录执行。

### 1. 激活 conda 环境

```powershell
conda activate amvision
```

### 2. 启动 backend-service

开发调试使用：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 8000 --reload
```

性能测量或稳定性压测使用：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 8000
```

说明：

- --reload 只用于开发阶段
- 需要观察 TensorRT、PyTorch、OpenVINO 等 runtime 的真实延迟时，不应使用 --reload
- 如果 8000 端口被占用，可改为其他端口，例如 8010
- 服务日志当前默认输出到控制台

### 3. 访问健康检查

浏览器访问或直接调用：

- http://127.0.0.1:8000/api/v1/system/health

PowerShell 示例：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/health
```

预期结果示例：

```json
{
  "status": "ok",
  "request_id": "8a8c4eb0-b7d7-4ec1-a3ee-2a33f48e93d9"
}
```

### 4. 查看 OpenAPI 文档

- Swagger UI：http://127.0.0.1:8000/docs
- OpenAPI JSON：http://127.0.0.1:8000/openapi.json

### 5. 停止服务

在启动服务的终端里按 Ctrl+C。

## 同目录 Python 运行时启动

发布阶段应优先由项目同目录 Python 解释器启动 backend-service，而不是依赖系统 PATH。

如果发布目录结构类似下面这样：

```text
release/
├─ python/
├─ app/
├─ config/
├─ data/
└─ launchers/
```

则当前等价启动方式应类似：

```powershell
.\python\python.exe -m uvicorn backend.service.api.app:app --host 0.0.0.0 --port 8000
```

说明：

- 当前仓库还没有正式提交 service launcher 脚本
- 在 launcher 落地前，发布包可以先用 bundled Python 直调 uvicorn
- 等后续补齐 launchers 后，应以 launchers/service 下的启动入口为准

## 数据库 schema 初始化

当前服务在启动时会自动执行缺失表初始化，等价于对当前 ORM 执行一次 `create_all`。

如果需要在不启动服务的情况下提前准备本地数据库，也可以手动执行一次建表命令：

```powershell
python -c "from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory; from backend.service.infrastructure.persistence.base import Base; session_factory = SessionFactory(DatabaseSettings()); Base.metadata.create_all(session_factory.engine); print('schema ready')"
```

说明：

- 这只是当前仓库状态下的临时开发命令
- 后续应收敛到 Alembic 或 maintenance launcher，而不是长期依赖 python -c

## 最小验收步骤

### 只验证服务能启动

1. 激活 conda 环境
2. 执行 uvicorn 启动命令
3. 访问 /api/v1/system/health
4. 打开 /docs
5. 确认 /api/v1/tasks 已出现在 OpenAPI 列表中

### 验证服务能处理持久化接口

1. 启动 backend-service
2. 访问 /api/v1/system/health
3. 调用 /api/v1/datasets/imports 提交导入任务
4. 用返回的 task_id 调用 /api/v1/tasks/{task_id}
5. 如需实时观察任务事件，再建立 /ws/tasks/events?task_id=... 订阅
6. 如果使用的是旧数据库文件，再检查是否存在 schema 不兼容问题

## 当前已验证的命令

当前仓库已实际验证下面这条命令可以启动服务，并通过健康检查：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 8010
```

对应健康检查接口：

- http://127.0.0.1:8010/api/v1/system/health

## 常见问题

### 1. 健康检查能通，但导入或查询接口报数据库错误

优先检查当前数据库文件是否是旧 schema。当前启动只会创建缺失表，不会自动补缺失列或改列类型。

### 2. data 目录出现了，但看不到 amvision.db

这是当前实现的正常行为。目录会在启动时创建，SQLite 文件通常在第一次数据库连接时创建。

### 3. 服务能启动，但没有文件日志

当前仓库还没有把 backend-service 的文件日志写入单独日志目录，默认先看控制台输出。

### 4. 为什么文档里没有 launcher 命令

因为当前仓库只有 launcher 设计文档，还没有正式提交 service launcher 脚本。这里先写当前已经能运行的真实命令，不把未实现能力写成现成入口。

## 推荐后续文档

- [docs/architecture/backend-service.md](../architecture/backend-service.md)
- [docs/deployment/bundled-python-deployment.md](bundled-python-deployment.md)
- [docs/architecture/runtime-packaging.md](../architecture/runtime-packaging.md)
- [docs/api/current-api.md](../api/current-api.md)
- [docs/api/datasets-imports.md](../api/datasets-imports.md)