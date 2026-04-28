# 后端服务说明

## 文档目的

本文档用于说明后端服务在整个平台里的位置、边界、任务状态、调度方式，以及它和 QueueBackend、workers、公开接口之间的关系。

本文档不展开具体接口字段或类设计，只回答三个问题：backend-service 做什么、不做什么、任务状态怎么流转。

## 适用范围

- 后端服务的职责和非职责边界
- API 层、application 层、domain 层、infrastructure 层的分工
- 任务状态模型与状态迁移约束
- 执行调度、QueueBackend、状态回写和取消/重试机制
- 后端服务与浏览器前端、外部系统、workers、对象存储和插件体系之间的接口规则

## 后端服务的位置

backend-service 是平台的统一后端入口，处理元数据、任务安排、公开接口和状态流。

backend-service 不是训练、推理、转换或流程执行本体，也不直接处理硬件驱动和模型运行细节。它的价值在于把任务定义、任务状态、资源引用和公开接口规则收在一个清楚、可审计、可回滚的边界里。

## 后端服务做什么

- 对浏览器前端、上位机和其他外部系统暴露统一的公开接口边界
- 管理项目、数据集、模型、部署实例、流程模板、集成端点和插件记录等元数据
- 校验请求、配置、输入输出 schema 和依赖约束
- 创建任务、提交任务、取消任务、重试任务和查询任务状态
- 根据任务类型、运行时需求和资源约束进行调度决策
- 将任务分发到 QueueBackend，并协调 workers 消费
- 接收 workers 回写的状态、日志、指标、结果引用和错误信息
- 将权威状态持久化，并向 WebSocket 订阅端和集成链路分发状态变化
- 处理版本管理、权限检查、兼容性检查和最小审计

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
- 协调 DatabaseBackend、ObjectStore、QueueBackend、PluginLoader 和其他稳定接口
- 把请求转换成领域命令和任务提交动作

### domain 层

- 定义 Task、Deployment、PipelineTemplate、IntegrationEndpoint 等核心对象的规则
- 定义允许的状态迁移、取消约束、重试约束和版本兼容规则
- 不依赖具体数据库、消息实现或 HTTP/WebSocket 细节

### infrastructure 层

- 接数据库、对象存储、队列、缓存、ZeroMQ 和协议适配器
- 把外部技术实现适配到 application 层要用的稳定接口

## 任务模型

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

### 权威状态集合

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

- backend-service 是任务状态的唯一权威写入方
- workers 只能提交状态更新事件，不能自行定义新的权威状态
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
- 不负责存储完整任务元数据的权威版本
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

- 写入权威数据库状态
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
- 超时后的权威状态由后端服务登记为 timed_out，并决定是否进入 retry_waiting

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

- DatabaseBackend：权威元数据和状态存储
- ObjectStore：模型、数据、日志片段和结果文件等大对象引用存储
- CacheBackend：可选的查询优化和短时状态缓存，不替代权威状态存储

## 数据归属原则

- backend-service 拥有任务元数据和权威状态
- workers 拥有执行过程中的临时运行态，不拥有最终权威状态
- ObjectStore 持有大对象内容，数据库只保存引用和元数据
- WebSocket 和外部系统只消费状态视图，不拥有任务状态主副本

## 与插件体系的关系

- backend-service 负责插件 manifest、能力、启停状态和版本记录
- 插件触发器、回调器和后处理器必须通过后端服务注册和管理
- 插件可以扩展任务编排和状态分发，但不能绕开后端服务的权威状态模型

## 推荐后续文档

- [docs/architecture/system-overview.md](system-overview.md)
- [docs/architecture/project-structure.md](project-structure.md)
- [docs/architecture/data-and-files.md](data-and-files.md)
- [docs/api/communication-contracts.md](../api/communication-contracts.md)