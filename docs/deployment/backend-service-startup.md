# backend-service 启动

`backend-service` 提供 REST API、WebSocket、静态前端和平台控制面。它不消费数据集、训练、转换、评估或异步推理队列。

## 进程边界

正式完整拓扑：

- full Supervisor：数据库迁移、进程拓扑和恢复。
- inference daemon：DeploymentInstance 与推理进程。
- backend-service：API、Workflow 控制面、Trigger 和前端静态资源。
- six Worker Profiles：后台任务消费。

开发 API/UI 时可以单独启动 backend-service；生产和完整链路必须使用 full Supervisor。

## 配置

默认配置文件：

```text
config/backend-service.json
```

主要配置段：

- `app`
- `cors`
- `auth`
- `database`
- `dataset_storage`
- `queue`
- `training_telemetry`
- `workflow_runtime`
- `zeromq_trigger`
- `local_buffer_broker`
- `deployment_process_supervisor`
- `deployment_runtime_reconciler`
- `inference_daemon`

配置由 Pydantic 严格解析。删除或改名的字段不会被静默忽略；发现未知/旧字段时应修改配置，不增加双格式解析分支。

## 开发态启动

从仓库根目录执行。

### 1. 激活环境

```powershell
conda activate amvision
```

### 2. 数据库迁移

```powershell
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
```

禁止用 `stamp`、`create_all()` 或删除数据库绕过 migration chain。

### 3. 启动服务

热重载：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 5600 --reload --reload-dir backend --reload-dir custom_nodes
```

不带 reload 的诊断：

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 5600
```

`--reload` 只用于开发。性能、稳定性、进程恢复和 Workflow/Deployment 延迟测试必须使用完整 Supervisor 或至少不启用 reload。

### 4. 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:5600/api/v1/system/health
```

文档：

- `http://127.0.0.1:5600/docs`
- `http://127.0.0.1:5600/openapi.json`

### 5. 停止

在启动终端按 `Ctrl+C`，等待 lifespan 清理完成。

## 发行态启动

生产环境不单独启动 service：

```powershell
.\start-amvision-full.bat
```

低层 service launcher：

```text
launchers/service/start-backend-service.bat
```

它只供 full Supervisor 编排或受控诊断，不负责数据库迁移、daemon、Worker Profile 和完整回收。

## 启动期顺序

数据库已经由 Supervisor/Alembic 升级后，FastAPI lifespan：

1. 读取并验证配置。
2. 构建 SessionFactory、ObjectStore、Queue、LocalBuffer 和应用服务。
3. 登记 seed 数据和 Node Pack/Custom Node catalog。
4. 恢复 Workflow bundle journal 与 lifecycle。
5. 恢复 Workflow Runtime，等待实际 ready。
6. 恢复 enabled TriggerSource。
7. 接受 API 流量。

关闭时按依赖逆序停止 Trigger、Workflow worker、dispatcher、broker 和数据库 engine。

## 单实例和 LocalBufferBroker

同一 `local_buffer_broker.root_dir` 只能有一个有效 broker。开发态重复启动相同工作区的标准 Uvicorn 入口时，可按配置验证并接管较早实例；正常操作仍应优先在原终端优雅停止。

自动接管不是通用进程清理器，也不替代 full Supervisor 的状态文件。并行 backend-service 必须使用不同端口、数据库、队列和 LocalBuffer 根目录。

## 诊断

### health 不通

- 检查端口占用。
- 查看配置 JSON 与路径权限。
- 查看 Alembic migration 日志或开发终端。
- 检查 SQLite/WAL 文件是否可写。
- 检查 broker 锁是否属于另一个有效实例。

### health 正常但任务不推进

单独 service 不消费队列。必须使用完整 Supervisor，并检查目标 Worker Profile 心跳与日期日志。

### Deployment 不可用

检查 inference daemon 状态和 probe。不要在 backend-service 中启动第二套 embedded deployment owner。

### Workflow/Trigger 启动失败

检查 bundle journal、Application lifecycle、Runtime revision/generation、worker instance 和 Trigger recovery 错误。启动期恢复失败不能通过删除 runtime 文件或状态记录绕过。

## 相关文档

- [开发环境启动](development-environment.md)
- [Worker Topology](backend-worker-startup.md)
- [inference daemon](inference-daemon.md)
- [数据库与维护](backend-maintenance.md)
- [后端架构](../architecture/backend-service.md)
