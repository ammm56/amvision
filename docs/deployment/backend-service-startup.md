# backend-service 启动说明

## 文档目的

本文档用于说明当前仓库里的 FastAPI backend-service 怎么启动、启动后能看到什么、默认会使用哪些本地目录，以及当前还没有自动完成的初始化步骤。

本文档只覆盖 backend-service 本身；独立 worker、maintenance 和发布 profile 见本目录其他专题文档。

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
- 当前公开任务事件订阅：/ws/v1/tasks/events
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
- 默认 task manager 配置：enabled=false、max_concurrent_tasks=16、poll_interval_seconds=1.0
- 默认 deployment supervisor 配置：max_running_process_count=32、warmup_dummy_inference_count=6、warmup_dummy_image_size=[64,64]、keep_warm_enabled=true、keep_warm_interval_seconds=0.1、tensorrt_pinned_output_buffer_enabled=true、tensorrt_pinned_output_buffer_max_bytes=8388608

常见示例：

- config/backend-service.json

```json
{
  "app": {
    "app_name": "amvision backend-service",
    "app_version": "0.1.3"
  },
  "database": {
    "url": "sqlite:///./data/amvision.db",
    "echo": false
  },
  "dataset_storage": {
    "root_dir": "./data/files"
  },
  "queue": {
    "root_dir": "./data/queue",
    "lease_timeout_seconds": 86400.0,
    "completed_retention_seconds": 86400.0,
    "failed_retention_seconds": 604800.0,
    "response_queue_retention_seconds": 3600.0
  },
  "task_manager": {
    "enabled": false,
    "max_concurrent_tasks": 16,
    "poll_interval_seconds": 1.0
  },
  "async_inference_gateway": {
    "service_id": "backend-service-main"
  },
  "workflow_runtime": {
    "operator_thread_count": 1,
    "decoded_image_cache_max_entries": 8,
    "decoded_image_cache_max_bytes": 268435456,
    "raw_result_cache_ttl_seconds": 900.0,
    "raw_result_cache_max_items": 64
  },
  "local_buffer_broker": {
    "enabled": true,
    "root_dir": "./data/buffers",
    "startup_timeout_seconds": 60.0,
    "request_timeout_seconds": 5.0,
    "shutdown_timeout_seconds": 5.0,
    "expire_interval_seconds": 5.0,
    "default_pool_name": "image-4k",
    "pools": [
      {
        "pool_name": "image-4k",
        "slot_size_bytes": 134217728,
        "slot_count": 16,
        "flush_on_write": false
      },
      {
        "pool_name": "image-1080p",
        "slot_size_bytes": 16777216,
        "slot_count": 16,
        "flush_on_write": false
      },
      {
        "pool_name": "image-640x640",
        "slot_size_bytes": 4194304,
        "slot_count": 16,
        "flush_on_write": false
      }
    ]
  },
  "deployment_process_supervisor": {
    "auto_restart": true,
    "monitor_interval_seconds": 0.5,
    "startup_timeout_seconds": 180.0,
    "request_timeout_seconds": 30.0,
    "shutdown_timeout_seconds": 5.0,
    "max_running_process_count": 32,
    "operator_thread_count": 1,
    "warmup_dummy_inference_count": 6,
    "warmup_dummy_image_size": [64, 64],
    "keep_warm_enabled": true,
    "keep_warm_interval_seconds": 0.1,
    "keep_warm_yield_timeout_seconds": 1.0,
    "tensorrt_pinned_output_buffer_enabled": true,
    "tensorrt_pinned_output_buffer_max_bytes": 8388608
  }
}
```

- AMVISION_APP__APP_NAME=amvision backend-service
- AMVISION_APP__APP_VERSION=0.1.3
- AMVISION_DATABASE__URL=sqlite:///./data/amvision.db
- AMVISION_DATABASE__ECHO=false
- AMVISION_DATASET_STORAGE__ROOT_DIR=./data/files
- AMVISION_QUEUE__ROOT_DIR=./data/queue
- AMVISION_QUEUE__LEASE_TIMEOUT_SECONDS=86400.0
- AMVISION_QUEUE__COMPLETED_RETENTION_SECONDS=86400.0
- AMVISION_QUEUE__FAILED_RETENTION_SECONDS=604800.0
- AMVISION_QUEUE__RESPONSE_QUEUE_RETENTION_SECONDS=3600.0
- AMVISION_TASK_MANAGER__ENABLED=false
- AMVISION_TASK_MANAGER__MAX_CONCURRENT_TASKS=16
- AMVISION_TASK_MANAGER__POLL_INTERVAL_SECONDS=1.0
- AMVISION_ASYNC_INFERENCE_GATEWAY__SERVICE_ID=backend-service-main
- AMVISION_WORKFLOW_RUNTIME__OPERATOR_THREAD_COUNT=1
- AMVISION_WORKFLOW_RUNTIME__DECODED_IMAGE_CACHE_MAX_ENTRIES=8
- AMVISION_WORKFLOW_RUNTIME__DECODED_IMAGE_CACHE_MAX_BYTES=268435456
- AMVISION_WORKFLOW_RUNTIME__RAW_RESULT_CACHE_TTL_SECONDS=900.0
- AMVISION_WORKFLOW_RUNTIME__RAW_RESULT_CACHE_MAX_ITEMS=64
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__AUTO_RESTART=true
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__MONITOR_INTERVAL_SECONDS=0.5
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__STARTUP_TIMEOUT_SECONDS=180.0
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__REQUEST_TIMEOUT_SECONDS=30.0
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__SHUTDOWN_TIMEOUT_SECONDS=5.0
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__MAX_RUNNING_PROCESS_COUNT=32
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__OPERATOR_THREAD_COUNT=1
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__WARMUP_DUMMY_INFERENCE_COUNT=6
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__WARMUP_DUMMY_IMAGE_SIZE=[64,64]
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__KEEP_WARM_ENABLED=true
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__KEEP_WARM_INTERVAL_SECONDS=0.1
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__KEEP_WARM_YIELD_TIMEOUT_SECONDS=1.0
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__TENSORRT_PINNED_OUTPUT_BUFFER_ENABLED=true
- AMVISION_DEPLOYMENT_PROCESS_SUPERVISOR__TENSORRT_PINNED_OUTPUT_BUFFER_MAX_BYTES=8388608

说明：

- 本地部署优先修改 config 目录 JSON 文件，而不是直接改代码
- 环境变量主要用于测试、调试、launcher 注入和临时覆盖
- 如果 config 文件和环境变量都未提供，当前服务会回退到仓库默认值
- `local_buffer_broker.default_pool_name` 是未显式指定 pool 时使用的默认 pool；仓库默认值为 `image-4k`
- `workflow_runtime.decoded_image_cache_max_entries` 和 `decoded_image_cache_max_bytes` 只限制单次 Workflow Run 内对 storage、buffer、frame 等输入图片的解码矩阵缓存。缓存采用 LRU 和同 key single-flight；Run 结束、失败或 cleanup 失败后都会清空，不跨 Run 持有现场图片。
- `decoded_image_cache_max_bytes` 是进程私有解码矩阵的硬上限。单张解码矩阵超过上限时仍可完成当前节点，并会共享给当时已经等待同一 single-flight 的并发分支，但不会进入 Run 级 LRU；这避免 16K BGR24 这类 768 MiB 矩阵因为“单张例外”长期突破 256 MiB 配置。broker raw BufferRef / FrameRef 在长期 worker 中直接借用只读 mmap view，不再复制一份等大的 Python bytes，且共享 view 不重复计入私有缓存字节数。
- 缓存中的共享解码矩阵为只读；需要原地修改输入的节点必须显式请求可写副本。OpenCV 中间输出继续使用 raw BGR24 memory handle，不因该缓存配置增加 PNG/JPEG 编解码。
- broker pool 和 decoded cache 不能合并为同一层：pool 管理跨进程 bytes、固定槽位、lease 和覆盖安全；decoded cache 管理当前 Run 中由 JPEG/PNG 等编码输入生成的进程内 OpenCV matrix。raw BGR24 broker 输入可以直接映射，编码图片仍必须有解码后的目标矩阵。
- `local_buffer_broker.pools` 应按现场相机分辨率、图像编码方式和并发量显式配置；`slot_size_bytes` 必须大于单帧最大 bytes，`slot_count` 是可同时占用的槽位数量
- 仓库默认创建 `image-4k`、`image-1080p` 和 `image-640x640` 三个 pool；`image-4k` 单槽 128MB 用于 5000x4000 级 20MP 工业相机 raw RGB/RGBA 输入；mmap 文件名按 `pool_name` 自动生成，总容量按 `slot_size_bytes * slot_count` 自动计算
- 默认 pool 使用 16 个槽位；低内存设备可以把每个 pool 的 `slot_count` 进一步改为 8 或 4。槽位减少只会降低同时占用容量，pool 满时会返回明确的容量不足错误，不会动态扩大 mmap 文件
- `image-8k` 单槽 256MB、默认 16 个槽位，仅作为现场可选大图 pool；需要更高分辨率、更多通道或相机专用大图输入时，手动把 `{"pool_name":"image-8k","slot_size_bytes":268435456,"slot_count":16,"flush_on_write":false}` 加到 `local_buffer_broker.pools`
- `local_buffer_broker.startup_timeout_seconds` 默认 60 秒；大 pool 首次创建和 mmap 可能超过原 5 秒，尤其是 Windows 和机械硬盘环境
- `local_buffer_broker.default_pool` 简化配置不再使用；配置文件应统一使用 `default_pool_name + pools`，仍出现旧字段时服务启动会直接失败，避免旧配置被静默忽略
- ZeroMQ TriggerSource 可以通过 `transport_config.pool_name` 选择目标 pool；不配置时使用 `local_buffer_broker.default_pool_name`
- 前端集成页面通过 `/api/v1/system/config` 读取当前后端实际配置，再从 `local_buffer_broker.pools` 生成 pool 下拉选项；页面不维护独立默认 pool 列表
- 如果使用 `config/backend-service.local.json` 覆盖 `local_buffer_broker`，建议把 `enabled/root_dir/default_pool_name/pools` 作为完整配置块一起写入，避免现场配置只覆盖部分字段后难以判断实际 pool 大小
- pool 的 `flush_on_write` 默认建议为 `false`，用于 ZeroMQ 和本机 workflow 临时图片输入；只有确实需要把 mmap 写入强制刷到文件系统时才改为 `true`
- `deployment_process_supervisor` 提供 deployment 子进程的启动确认、普通请求、warmup、keep-warm 和 TensorRT 输出 host buffer 行为；`startup_timeout_seconds` 是 start / warmup 等待 runtime 返回的最长时间，默认 180 秒；`request_timeout_seconds` 只用于 health、reset、infer 等普通运行期命令，默认 30 秒。
- `start` 只启动并确认子进程，不加载模型、不执行 dummy infer，也不激活 keep-warm。`warmup` 会加载全部实例、完成有限次数 dummy infer，再激活持续设备保活。真实推理只会暂时让 keep-warm 让出执行机会，不会隐式开启保活。
- DeploymentInstance 通过 `runtime_configuration.lifecycle` 显式覆盖 `warmup_dummy_inference_count`、`warmup_dummy_image_size`、`keep_warm_enabled` 和 `keep_warm_interval_seconds`；TensorRT pinned output 配置位于 `runtime_configuration.backend_options`。
- `deployment_process_supervisor.max_running_process_count` 限制当前 backend-service 进程内同时运行的独立 deployment 子进程总数，默认 32。这个限制不影响 DeploymentInstance 创建数量，也不限制单个子进程内的 `instance_count`，只在显式 start、warmup 或崩溃自动拉起真正启动子进程时生效。
- `tensorrt_pinned_output_buffer_max_bytes` 用于限制单实例允许长期驻留的 pinned output host buffer 上限；当前超过阈值后会自动回退到 pageable memory，避免多 deployment、多实例场景下 pinned memory 累积过大
- `async_inference_gateway.service_id` 是 async inference gateway 的稳定 owner id，会进入 inference task 的 `task_spec.async_inference_owner_id`；实际请求队列按 `service_id + deployment_instance_id` 构建为 `detection-ai-gw-{service_id}-{deployment_id}`，其中 `deployment-instance-` 前缀会在队列名中省略。同一 backend-service 内的多个 async deployment 也会使用独立 gateway 队列和 dispatcher 线程；一次性响应队列使用 `detection-ai-rsp-*`，响应被 worker 取走后会立即删除，TTL 清理只作为异常兜底

## 启动前要知道的事

### 当前仓库已经具备的能力

- FastAPI 服务可直接通过 uvicorn 启动
- REST 路由、WebSocket 路由、中间件和异常映射已装配完成
- /api/v1/system/health 可以直接返回最小健康状态
- /api/v1/tasks 和 /ws/v1/tasks/events 已经公开
- 当前默认配置下，backend-service 不再自动托管任何队列消费者；dataset import、dataset export、training、conversion、evaluation 和 inference 全部迁到独立 worker profile
- `task_manager` 字段当前仅保留兼容配置形态，service 启动链不会再创建进程内 BackgroundTaskManager

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
  - sync / async deployment supervisor
  - `PublishedInferenceGateway`
  - async inference gateway dispatcher registry，按当前 `async_inference_gateway.service_id` 和 DeploymentInstance id 为每个 async deployment 懒启动专属请求队列与 dispatcher 线程，并定期清理一次性响应队列
  - `background_task_manager_host=None`
4. `create_app` 把这些运行时对象绑定到 `application.state`
5. FastAPI lifespan 启动时执行：
  - 初始化数据库缺失表
  - 运行显式传入的 seeders
  - 执行 `custom_nodes` 目录元数据预留步骤
  - 启动 sync / async deployment supervisor
  - 启动 async inference gateway dispatcher
6. 应用关闭时停止 async inference gateway dispatcher、deployment supervisor，并释放数据库 engine

## 开发环境启动

以下步骤从仓库根目录执行。

### 1. 激活 conda 环境

```powershell
conda activate amvision
```

### 2. 启动 backend-service

开发调试使用：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 5600 --reload
```

性能测量或稳定性压测使用：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 5600
```

说明：

- --reload 只用于开发阶段
- 需要观察 TensorRT、PyTorch、OpenVINO 等 runtime 的真实延迟时，不应使用 --reload
- 如果 5600 端口被占用，可改为其他端口，例如 5610
- 服务日志当前默认输出到控制台

### 3. 访问健康检查

浏览器访问或直接调用：

- http://127.0.0.1:5600/api/v1/system/health

PowerShell 示例：

```powershell
Invoke-RestMethod http://127.0.0.1:5600/api/v1/system/health
```

预期结果示例：

```json
{
  "status": "ok",
  "request_id": "8a8c4eb0-b7d7-4ec1-a3ee-2a33f48e93d9"
}
```

### 4. 查看 OpenAPI 文档

- Swagger UI：http://127.0.0.1:5600/docs
- OpenAPI JSON：http://127.0.0.1:5600/openapi.json

### 5. 停止服务

在启动服务的终端里按 Ctrl+C。

## 同目录 Python 运行时启动

发布阶段应优先由项目同目录 Python 解释器启动 backend-service，而不是依赖系统 PATH。

当前 Windows 发布目录的默认入口已经切到根目录一键启动脚本 `start-amvision-full.bat`。Ubuntu 发布尚未实现，因此发布包当前不复制 `.sh` 根 launcher。
本页保留 `launchers/service/` 的调用方式，主要用于只拉起 service 或拆分排障。

如果发布目录结构类似下面这样：

```text
release/
├─ python/
├─ app/
├─ config/
├─ data/
└─ launchers/
```

则当前等价启动方式应优先通过 Python launcher 完成：

```powershell
.\launchers\service\start-backend-service.bat --host 0.0.0.0 --port 5600
```

说明：

- 当前仓库中的 launcher 模板位于 `runtimes/launchers/service/`；`assemble-release` 会把它们复制到发布目录里的 `launchers/service/`
- 发布阶段应优先以 launcher 启动，并配合独立 `backend-worker` 一起运行
- release 目录里如果直接执行 `python -m backend.service.api.app`，需要自行处理 `PYTHONPATH`；launcher 已经封装了这部分路径补齐逻辑

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
5. 如需实时观察任务事件，再建立 /ws/v1/tasks/events?task_id=... 订阅
6. 如果使用的是旧数据库文件，再检查是否存在 schema 不兼容问题

## 当前已验证的命令

当前仓库已实际验证下面这条命令可以启动服务，并通过健康检查：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 5610
```

对应健康检查接口：

- http://127.0.0.1:5610/api/v1/system/health

## 常见问题

### 1. 健康检查能通，但导入或查询接口报数据库错误

优先检查当前数据库文件是否是旧 schema。当前启动只会创建缺失表，不会自动补缺失列或改列类型。

### 2. data 目录出现了，但看不到 amvision.db

这是当前实现的正常行为。目录会在启动时创建，SQLite 文件通常在第一次数据库连接时创建。

### 3. 服务能启动，但没有文件日志

当前仓库还没有把 backend-service 的文件日志写入单独日志目录，默认先看控制台输出。

### 4. 为什么文档里没有 launcher 命令

当前仓库已经提交 service launcher，但在开发环境里直接执行 uvicorn 仍然是最短调试路径；发布形态应优先切到 launcher 调用。

## 推荐后续文档

- [docs/architecture/backend-service.md](../architecture/backend-service.md)
- [docs/deployment/bundled-python-deployment.md](bundled-python-deployment.md)
- [docs/architecture/runtime-packaging.md](../architecture/runtime-packaging.md)
- [docs/api/current-api.md](../api/current-api.md)
- [docs/api/datasets-imports.md](../api/datasets-imports.md)
