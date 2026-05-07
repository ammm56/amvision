# 后端服务说明

## 文档目的

本文档用于说明后端服务在整个平台里的位置、边界、当前启动流程、层级关系，以及它和 QueueBackend、workers、公开接口之间的关系。

本文档同时收敛 FastAPI 框架的实现方向，回答六个问题：backend-service 做什么、不做什么、REST API 和 WebSocket 怎么拆、数据库会话和持久化边界怎么落、用户与权限要不要从一开始纳入、代码目录怎么避免塞进单文件实现。

## 适用范围

- 后端服务的职责和非职责边界
- API 层、application 层、domain 层、infrastructure 层的分工
- 任务状态模型与状态迁移约束
- 执行调度、QueueBackend、状态回写和取消/重试机制
- 后端服务与浏览器前端、外部系统、workers、对象存储和插件体系之间的接口规则
- FastAPI 应用装配、路由分包、依赖注入、中间件和错误映射策略
- API schema、领域对象、持久化实体之间的分层关系
- 用户、角色、Project membership、service token 和权限 scope 的规划边界

## 后端服务的位置

backend-service 是平台的统一后端入口，处理元数据、任务安排、公开接口和状态流。

backend-service 不是训练、推理、转换或流程执行本体，也不直接处理硬件驱动和模型运行细节。它的价值在于把任务定义、任务状态、资源引用和公开接口规则收在一个清楚、可审计、可回滚的边界里。

对标 Roboflow 这类产品时，backend-service 更接近“资源管理 + 任务编排 + 状态分发”的统一服务层，而不是把训练器、推理运行时、模型文件和上传解析逻辑塞进单个 FastAPI 文件。

## 后端服务做什么

- 对浏览器前端、上位机和其他外部系统暴露统一的公开接口边界
- 装配当前已经公开的 system、datasets imports、tasks 三组 REST API，以及 system、tasks 两组 WebSocket 入口
- 管理 DatasetImport、DatasetVersion、TaskRecord、TaskEvent、Model 等当前已落地的元数据
- 通过 SQLAlchemy Unit of Work 和 Repository 管理数据库事务边界
- 管理本地 DatasetStorage、LocalFileQueueBackend 和当前进程内托管的 BackgroundTaskManager
- 把 DatasetImport 这类长于请求生命周期的处理从 REST 请求链路里隔离出去
- 为 DatasetImport 创建正式 TaskRecord，并通过 tasks API 和 WebSocket 暴露状态变化
- 在应用生命周期内启动、停止当前 backend-service 托管的后台任务宿主
- 处理版本管理、权限检查、异常映射和最小审计

## 后端服务不做什么

- 不在请求处理器中直接运行训练、推理、转换或流程执行
- 不直接持有模型运行时、硬件 SDK 或算法实现细节
- 不把任务实际执行状态存放在前端内存或外部系统中
- 不让 worker 绕开后端服务直接成为前端或外部系统的主入口
- 不把数据库方言、文件系统路径规则和消息中间件实现泄漏到公开接口层

## 后端服务内部层次

### api 层

- 处理 REST API、WebSocket 和外部系统接入边界
- 处理鉴权、输入校验、响应包装、订阅会话和错误映射
- 不负责业务编排和持久化细节

### application 层

- 处理任务创建、状态迁移、事务边界和用例编排
- 协调 DatabaseBackend、ObjectStore、QueueBackend、NodeCatalogRegistry 和其他稳定接口
- 把请求转换成领域命令和任务提交动作

### domain 层

- 定义 DatasetImport、DatasetVersion、Model、TaskRecord、TaskAttempt、TaskEvent、ResourceProfile 等核心对象
- 定义允许的状态迁移、任务筛选语义和聚合边界
- 不依赖具体数据库、消息实现或 HTTP/WebSocket 细节

### infrastructure 层

- 接数据库、对象存储、队列、缓存、ZeroMQ 和协议适配器
- 把外部技术实现适配到 application 层要用的稳定接口

## FastAPI 框架目标

- 保持资源型 REST API 与任务型异步执行分离
- 保持 REST 查询与 WebSocket 状态流分离
- 保持 API schema、领域对象和数据库实体分离
- 保持 route、use case、repository、worker 调用边界分离
- 用户与权限从第一天预留清楚边界，但不要求第一阶段一次做完完整 IAM 平台

## 推荐的 FastAPI 目录骨架

```text
backend/service/
├─ api/
│  ├─ app.py
│  ├─ bootstrap.py
│  ├─ deps/
│  │  └─ auth.py
│  ├─ middleware/
│  │  └─ request_context.py
│  ├─ rest/
│  │  ├─ router.py
│  │  └─ v1/
│  │     ├─ router.py
│  │     └─ routes/
│  │        ├─ system.py
│  │        ├─ datasets.py
│  │        ├─ models.py
│  │        └─ tasks.py
│  └─ ws/
│     └─ router.py
├─ application/
│  ├─ datasets/
│  ├─ models/
│  └─ tasks/
├─ domain/
│  ├─ datasets/
│  ├─ models/
│  ├─ files/
│  └─ tasks/
└─ infrastructure/
	├─ db/
	│  ├─ session.py
	│  ├─ schema.py
	│  └─ unit_of_work.py
	└─ persistence/
	   ├─ base.py
	   ├─ dataset_orm.py
	   ├─ dataset_import_orm.py
	   ├─ task_orm.py
	   ├─ dataset_repository.py
	   ├─ dataset_import_repository.py
	   ├─ task_repository.py
	   └─ resource_profile_repository.py
```

### 目录职责

- api/app.py：装配 FastAPI 实例、基础中间件、REST 根路由和 WebSocket 根路由
- api/bootstrap.py：装配 settings、SessionFactory、DatasetStorage、QueueBackend 和 HostedBackgroundTaskManager
- api/rest：只组织公开 REST 边界，不写业务编排和数据库事务
- api/ws：只处理订阅、连接、主题绑定和事件推送协议
- api/deps：放鉴权主体、Project scope、分页、数据库会话等依赖注入边界
- api/middleware：放 request id、审计上下文、异常映射、耗时统计等通用管道
- application：放 use case、任务提交、状态汇聚、Unit of Work 和跨聚合编排
- domain：放 Dataset、Model、Task、Deployment、Membership 等领域对象和规则
- infrastructure/db：放 SQLAlchemy engine、session 和聚合式 Unit of Work
- infrastructure/persistence：放 ORM 实体与 DatasetImport、DatasetVersion、TaskRecord、Model 等聚合的 Repository 实现
- infrastructure 其余目录：继续放 ObjectStore、QueueBackend、CacheBackend、ZeroMQ 和外部协议适配

## 当前启动流

当前 backend-service 的真实启动流如下：

1. `backend.service.api.app.create_app` 创建 `BackendServiceBootstrap`
2. bootstrap 先读取 `BackendServiceSettings`
3. bootstrap 构建 `BackendServiceRuntime`，其中包含：
	- `SessionFactory`
	- `LocalDatasetStorage`
	- `LocalFileQueueBackend`
	- sync / async deployment supervisor
	- 可选的 `HostedBackgroundTaskManager`
4. `create_app` 把这些运行时对象绑定到 `FastAPI.application.state`
5. FastAPI lifespan 启动时执行：
	- `bootstrap.initialize(runtime)`
	- `bootstrap.start_runtime(runtime)`
6. `initialize` 当前固定执行三个步骤：
	- 初始化数据库缺失表
	- 运行显式传入的 service seeders
	- 执行插件目录元数据预留步骤
7. `start_runtime` 在 `task_manager.enabled=true` 时启动当前进程托管的后台任务宿主
8. 关闭应用时执行：
	- `bootstrap.stop_runtime(runtime)`
	- 停止后台任务宿主
	- 停止 sync / async deployment supervisor
	- `dispose` 数据库 engine

当前进程内托管的后台任务宿主目前只注册 dataset-import、dataset-export、yolox-training 和 yolox-conversion 四类轻量消费者；evaluation 和 inference 已迁到独立 worker 配置，用于降低 backend-service 同时承担控制面和执行面的耦合。

## REST API 与 WebSocket 的拆分方式

### REST API

- REST API 负责资源读写、管理动作和任务创建
- 所有公开资源按版本组织，例如 /api/v1/system、/api/v1/datasets、/api/v1/tasks
- 当前已经公开的 REST 入口包括：
  - /api/v1/system/health
  - /api/v1/system/me
  - /api/v1/system/database
  - /api/v1/datasets/imports
  - /api/v1/datasets/{dataset_id}/imports
  - /api/v1/datasets/imports/{dataset_import_id}
  - /api/v1/tasks
  - /api/v1/tasks/{task_id}
  - /api/v1/tasks/{task_id}/events
  - /api/v1/tasks/{task_id}/cancel
- 上传 zip 数据集压缩包属于 REST API，因为它是明确的请求响应与资源创建动作
- 长任务创建后优先返回 accepted 或 queued 语义，以及 task id 或 import id
- 当前 models 路由已经预留，但还没有公开资源方法

### WebSocket

- WebSocket 只负责状态流、日志流和告警流
- WebSocket 不承担正式写入，不承担资源查询，不替代 REST 分页和详情查询
- 当前已经公开的 WebSocket 入口包括：
  - /ws/events：返回最小 system.connected 事件后关闭
  - /ws/tasks/events：按 task_id 订阅任务事件
- WebSocket 的权限检查应复用 REST 的主体与 scope 模型，而不是单独再造一套权限判断
- 当前 /ws/tasks/events 使用相同的主体请求头和 scope 规则，并通过轮询数据库事件表输出事件流

### 不建议的做法

- 不把上传、解析、训练状态流、管理动作、权限判断全部塞到单个 FastAPI 文件
- 不让 WebSocket 直接驱动数据库写入或任务状态跳转
- 不让 workers 直接对前端暴露 HTTP 或 WebSocket 端口

## API schema、领域对象与数据库实体的关系

### 三层对象必须分开

- API schema：Pydantic 请求和响应模型，只服务公开接口规则
- 领域对象：domain 层的规则对象，例如 DatasetVersion、ModelVersion、Task
- 持久化实体：SQLAlchemy ORM 模型，只服务数据库映射和查询

### 设计约束

- 不直接把 SQLAlchemy ORM 实体作为 REST 返回对象
- 不直接让路由层操作 ORM session 和事务提交
- 不直接把 Pydantic 输入模型穿透到 domain 作为长期规则对象
- application 层负责把 API schema 转成命令对象，再协调 Repository 和 Unit of Work

## 数据库操作与事务边界

### 数据库操作原则

- REST 路由只获取依赖，不直接拼装 SQL
- application 层拥有事务边界和提交时机
- Repository 只负责聚合的持久化读写，不负责 HTTP 语义
- Alembic 负责 schema 迁移，SQLAlchemy 2 负责 ORM 与 session 管理

### 推荐事务模型

- 普通资源查询：一个请求一个只读 session
- 普通管理动作：一个请求一个 Unit of Work
- 长任务创建：在 application 中完成元数据写入后提交，再把任务写入 QueueBackend
- worker 状态回写：走独立回写用例，不复用前端请求 session

### 当前阶段建议

- 第一阶段默认支持 SQLite，但 Repository 接口与 Unit of Work 设计必须兼容 MySQL 和 PostgreSQL
- 数据集 zip 上传后的原始包、解压 staging 和版本文件走本地文件存储，不直接把二进制内容塞进数据库

## 中间件与请求管道

### 必须先有的中间件

- request context middleware：补 request id、project hint、trace 线索
- exception mapping middleware：把领域错误、权限错误、状态冲突映射成稳定 HTTP 错误
- access log middleware：记录请求耗时、主体、路径和结果码

### 建议通过依赖处理而不是放进中间件的事情

- 数据库 session 获取与释放
- 当前主体和 Project scope 解析
- 细粒度权限判断
- 分页、排序和过滤参数归一化

### 推荐请求管道

1. 中间件生成 request id 并建立日志上下文
2. 鉴权依赖解析当前主体
3. Project scope 依赖检查资源归属与访问范围
4. 路由层校验请求并调用 application use case
5. application use case 持久化状态、提交任务或返回资源
6. 异常映射层把错误统一转成 API 响应

## 用户管理与权限是否要先考虑

答案是要先考虑边界，但不需要第一阶段就做成完整企业 IAM。

### 建议最小对象

- User：平台用户
- Role：平台角色模板
- ProjectMembership：用户在 Project 下的角色与权限范围
- ServiceAccount 或 IntegrationIdentity：外部系统或自动化调用主体
- AccessToken：登录令牌或接口令牌

### 建议最小权限模型

- platform admin：平台级管理能力
- project admin：Project 内资源管理、任务创建、部署管理
- project operator：任务执行、结果查看、部分回滚操作
- readonly：只读查看和状态订阅
- integration scope：仅允许访问特定 API、特定 Project、特定回调范围

### 当前阶段实现建议

- 第一阶段可以先落本地用户、bootstrap admin 和 Project 级 RBAC
- WebSocket 与 REST 共享同一主体与 scope 体系
- 插件、集成端点和 service account 必须独立 scope，不复用普通用户的宽权限

## 面向 Roboflow 风格产品的资源模块建议

- system：健康检查、版本、运行环境状态
- auth：登录、刷新、当前主体、token 管理
- projects：Project 基本信息与成员管理
- datasets：数据集、导入记录、版本、导出记录
- models：模型、模型版本、预置预训练引用、build、发布信息
- tasks：训练、验证、转换、推理、流程执行任务
- deployments：部署实例、运行时绑定、回滚候选
- integrations：外部系统端点、回调策略、协议配置
- plugins：插件、节点定义、启停和兼容性状态

## 推荐的实现顺序

1. 先落 FastAPI app 装配、版本化 REST 根路由和 WebSocket 根路由
2. 再落 request context、中间件、异常映射和鉴权主体依赖
3. 再落 SQLAlchemy session、Unit of Work 和 Repository 接口
4. 再做 datasets zip 导入、导入记录和 DatasetVersion 生成链路
5. 再落 models、tasks、deployments 等资源模块
6. 最后扩展完整权限、审计、插件管理和外部系统集成

## 任务模型

统一任务实体、当前 tasks API、DatasetImport 与 TaskRecord 的绑定方式详见 [docs/architecture/task-system.md](task-system.md)。

### 统一任务类型

后端服务需要以统一任务模型覆盖以下执行类型：

- 训练任务
- 验证任务
- 转换任务
- 部署任务
- 推理任务
- 流程执行任务
- 插件驱动的触发、回调和后处理任务

### 统一任务记录的最小字段

- task id
- task kind
- requested by
- requested at
- input reference
- runtime profile reference
- queue lane
- current state
- progress snapshot
- result reference
- error summary
- retry metadata

## 任务状态模型

### 最终状态集合

- accepted：后端服务已接收请求并完成基础校验
- queued：任务已写入 QueueBackend，等待执行
- dispatched：任务已被调度到某个 worker 或执行槽位
- running：任务已开始执行，并可持续回写进度或日志
- retry_waiting：任务进入可重试等待状态
- cancel_requested：后端服务已登记取消请求，等待 worker 确认
- cancelled：任务已被取消
- succeeded：任务执行完成，结果引用已写回
- failed：任务执行失败，错误信息已写回
- timed_out：任务超时终止

### 状态迁移原则

- backend-service 是任务状态的唯一写入方
- workers 只能提交状态更新事件，不能自行定义新的最终状态
- 状态迁移必须单调前进，禁止从终态回退到运行态
- 重试不覆盖原始执行记录，而应产生新的调度尝试信息
- cancel_requested 和 retry_waiting 属于管理状态，不代表执行已经结束

## 执行调度模型

### 调度输入

- task kind
- runtime profile
- file compatibility
- queue lane
- plugin capability requirements
- local resource tags
- priority and retry policy

### 调度职责

- 由 application 层根据任务类型和运行条件决定进入哪个队列或 worker 通道
- 由 QueueBackend 提供可持久化的排队、出队、确认和失败重试能力
- 由 workers 根据自身能力声明和资源条件领取可执行任务
- 后端服务保留对取消、超时、重试和回滚的管理权

### 推荐调度路径

1. API 接收任务创建请求
2. application 完成输入校验、对象检查和任务定义持久化
3. 后端服务将任务写入 QueueBackend，并记录为 queued
4. dispatcher 或 worker consumer 从队列中领取任务，后端服务登记为 dispatched
5. worker 开始执行并持续回写 running/progress/log/error/result
6. 后端服务持久化最终状态，并向 WebSocket 和外部集成链路分发结果

## QueueBackend 的职责边界

QueueBackend 是后端服务与 workers 之间的标准排队边界，不应被视为公开 API，也不应成为直接暴露给前端或外部系统的接口。

### QueueBackend 必须提供的能力

- enqueue：写入任务
- lease or consume：领取任务
- ack：确认完成
- nack or retry：失败重试或重新入队
- delay：延迟重试或定时任务支持
- dead-letter or failure holding：无法继续处理的失败隔离能力

### QueueBackend 不负责的内容

- 不负责定义业务状态模型
- 不负责存储完整任务元数据的正式版本
- 不负责直接向前端或外部系统广播状态
- 不负责替代 DatabaseBackend 或 ObjectStore

## 状态回写模型

### 回写来源

- worker 运行状态更新
- progress 或 metric snapshot
- log fragment
- file reference
- plugin callback result
- timeout、cancel acknowledgement 或 failure event

### 回写规则

- 所有状态回写都必须经过后端服务校验和归一化
- 后端服务负责验证状态迁移是否合法
- 后端服务负责将结果引用写入数据库，并将大对象内容留在 ObjectStore
- 后端服务负责把运行日志和进度转换为可供 WebSocket、REST 查询和审计使用的标准视图
- 外部系统结果回传、插件回调和后处理结果，也应先汇聚到后端服务再对外发布

### 状态回写后的分发

- 写入正式数据库状态
- 向 WebSocket 订阅端推送任务事件
- 更新 REST 查询可见的状态快照
- 必要时触发插件回调、集成端点通知或后续任务编排

## 取消、重试与超时

### 取消

- 前端或外部系统发起取消请求时，后端服务先登记 cancel_requested
- worker 必须通过受控信号确认取消完成，后端服务再转为 cancelled
- 若 worker 已进入不可中断阶段，后端服务需要明确展示取消未立即生效的状态

### 重试

- 重试由后端服务统一决定，不允许 worker 私自重试并覆盖既有结果
- 重试策略应绑定任务类型、错误类型和最大次数
- 重试后的尝试记录应可追踪，而不是覆盖原任务轨迹

### 超时

- timeout 规则由后端服务根据任务类型、运行时能力和插件约束统一设定
- 超时后的最终状态由后端服务登记为 timed_out，并决定是否进入 retry_waiting

## 接口边界

### 面向前端与外部系统的公开边界

- REST API：创建任务、查询详情、读取元数据、触发管理动作
- WebSocket：订阅任务状态、日志流、进度和系统事件
- 协议适配插件：按受控接口规则把外部触发和回传接入后端服务

### 面向 workers 的内部边界

- QueueBackend：任务分发与消费边界
- 状态回写通道：任务进度、日志、结果和错误的标准回传边界
- 可选 ZeroMQ：仅用于同机本地部署中的内部进程通信，不作为公开接口规则

### 面向基础设施的内部边界

- DatabaseBackend：正式元数据和状态存储
- ObjectStore：模型、数据、日志片段和结果文件等大对象引用存储
- CacheBackend：可选的查询优化和短时状态缓存，不替代正式状态存储

## 数据归属原则

- backend-service 拥有任务元数据和最终状态
- workers 拥有执行过程中的临时运行态，不拥有最终状态
- ObjectStore 持有大对象内容，数据库只保存引用和元数据
- WebSocket 和外部系统只消费状态视图，不拥有任务状态主副本

## 与插件体系的关系

- backend-service 负责插件 manifest、能力、启停状态和版本记录
- 插件触发器、回调器和后处理器必须通过后端服务注册和管理
- 插件可以扩展任务编排和状态分发，但不能绕开后端服务的状态模型

## 推荐后续文档

- [docs/architecture/system-overview.md](system-overview.md)
- [docs/architecture/project-structure.md](project-structure.md)
- [docs/architecture/task-system.md](task-system.md)
- [docs/architecture/data-and-files.md](data-and-files.md)
- [docs/deployment/backend-service-startup.md](../deployment/backend-service-startup.md)
- [docs/api/communication-contracts.md](../api/communication-contracts.md)