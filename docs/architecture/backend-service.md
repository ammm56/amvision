# Backend Service

## 定位

backend-service 是平台统一控制面和公开 API 入口，负责资源管理、权限校验、任务接纳、运行时控制、状态查询和事件分发。训练、转换、推理、Workflow 正式执行等重任务由独立 Worker 或常驻 Runtime 进程承担。

```text
Web UI / SDK / external system
              │ REST / WebSocket
              ▼
        backend-service
          │          │
          │          ├─ Database / ObjectStore / QueueBackend
          │          └─ LocalBufferBroker control client
          ▼
  task workers / deployment runtime / workflow runtime
```

## 分层

| 层 | 目录 | 职责 |
|---|---|---|
| API | `backend/service/api/` | FastAPI app、路由、依赖、中间件、契约映射 |
| Application | `backend/service/application/` | 用例编排、权限和状态机、事务边界 |
| Domain | `backend/service/domain/` | 领域记录、Repository/UoW 接口和业务不变量 |
| Infrastructure | `backend/service/infrastructure/` | SQLAlchemy、ObjectStore、Queue、进程、文件系统适配 |
| Contracts | `backend/contracts/` | 公开且版本化的请求、响应和格式契约 |

API 路由不直接执行训练、转换或模型推理，也不直接拼写数据库方言 SQL。应用层通过 Repository 与 Unit of Work 完成持久化，基础设施层负责 SQLite、MySQL 和 PostgreSQL 差异。

## 主要职责

- 用户、Project membership、service token 和 scope 校验；
- 数据集、任务、模型、构建、部署、Workflow、Trigger 等资源 API；
- QueueBackend 任务提交、取消和状态查询；
- deployment 与 Workflow Runtime 的控制面；
- WebSocket/事件查询和健康状态；
- ObjectStore、LocalBufferBroker 与本地文件链路装配；
- Workflow App 发布恢复、项目 mutation fence 与启动恢复；
- OpenAPI、统一错误结构和 SDK 配置包。

## 不承担的职责

- 不在 HTTP request handler 中运行训练、转换、长时验证或正式 Workflow；
- 不直接持有所有模型 session；
- 不把相机、PLC、传感器驱动写入核心服务；
- 不依赖外部 Redis、MQ、云对象存储或系统 Python 才能启动；
- 不用 `Base.metadata.create_all()` 代替生产 schema 迁移。

## 启动顺序

开发和发布都先通过 Alembic 把数据库升级到唯一 head。应用 lifespan 只执行运行期装配和可恢复状态收敛，不隐式修改 schema。

启动期关键顺序为：

1. 读取并校验 Settings、路径和数据库配置；
2. 构造 SessionFactory、Repository/UoW、ObjectStore 和 QueueBackend；
3. 装载模型目录、节点目录、Node Pack 与公开契约；
4. 恢复 Workflow bundle journal 和 Application lifecycle；
5. 恢复 publishing App Version、项目删除与其他可恢复控制操作；
6. 启动 deployment/workflow manager 和后台 monitor；
7. 等待 desired Workflow Runtime 恢复就绪；
8. 恢复 enabled Trigger Source；
9. 接收公开 API 流量。

恢复顺序不可交换：Trigger 不能早于目标 Runtime 可用，Application lifecycle claim 不能早于 durable journal 收敛而释放。

## 数据库与事务

- 默认开发数据库为 SQLite，schema 只由 Alembic 管理。
- MySQL/PostgreSQL 使用同一 ORM、Repository 和条件写语义。
- application service 定义短事务边界；文件 I/O、模型加载和进程启动不持有长数据库事务。
- generation、revision、operation id 和 worker instance id 用于 CAS/fence。
- 公开 mutation 在最终写入前重新校验 project ownership 和资源状态。

迁移命令和跨数据库门禁见 [开发环境](../deployment/development-environment.md) 与 [Workflow App 迁移跨库门禁](../development/workflow-app-version-cross-database-migrations.md)。

## API 与错误

- REST API 统一位于 `/api/v1`；
- OpenAPI 由 FastAPI 契约生成；
- WebSocket 只分发状态和事件，不承载大图片主数据面；
- 业务错误映射为稳定 `error_code`、message 和 details；
- Project 资源详情、输出和控制接口都必须校验 `project_id` 归属；
- 对外字段和协议一旦公开，通过版本化契约演进。

## 运行与发布

开发时可单独启动 backend-service 进行 API/UI 调试；完整 Worker、推理、Workflow Runtime 链路必须使用 full Supervisor，它会注入进程 topology identity 并统一管理日志、重启和停止。

发行模式日志写入 `logs/full-stack/`，文件名带 `YYYYMMDD`，同一天追加写入当天文件。完整步骤见：

- [Backend Service 启动](../deployment/backend-service-startup.md)
- [Backend Worker 启动](../deployment/backend-worker-startup.md)
- [发布与本地运行](../deployment/README.md)
- [运行状态和故障排查](../operations/README.md)

## 实现入口

- App：`backend/service/api/app.py`
- API bootstrap：`backend/service/api/bootstrap.py`
- 全局 bootstrap：`backend/bootstrap/`
- Settings：`backend/service/settings.py` 与 `backend/bootstrap/settings.py`
- Session/UoW：`backend/service/infrastructure/db/`
- REST 路由：`backend/service/api/rest/v1/routes/`
- 错误：`backend/service/application/errors.py`
- Supervisor：`runtimes/launchers/full/start_amvision_full.py`
