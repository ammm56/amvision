# 统一任务系统

## 文档目的

本文档用于定义本项目当前阶段需要的最小任务系统边界。

这里的 task-system 不是通用集群调度平台，也不是资源编排系统。它的核心目标只有三个：

- 把训练、验证、转换、导出等重任务从 API 请求链路里隔离出去
- 用统一任务记录保证状态稳定、执行隔离和错误可追踪
- 为后续并行扩展保留统一的 worker pool 与 runner 接口

## 当前阶段边界

- task-system 只负责任务登记、状态跟踪、执行尝试记录和事件汇聚
- task-system 不负责做完整的 CPU、RAM、显存和 NUMA 调度
- task-system 不负责做多机分布式调度
- task-system 不把 GPU 资源规则放进通用实体里
- 训练任务需要 1 张还是多张 GPU，应在具体 TrainingTaskSpec 中定义，而不是在通用任务实体里定义

## 设计原则

- 单入口启动，不等于单进程执行
- task-system 先解决稳定性、隔离和并行扩展，不先追求通用调度复杂度
- 通用任务实体只保留跨模块都需要的字段
- 长时任务默认进程隔离
- worker pool 表示逻辑执行池，不表示细粒度硬件资源分配器

## 最小拓扑

```text
backend-service
  -> TaskManager
     -> WorkerPool
        -> Runner
```

各层职责如下：

- backend-service：创建任务、查询任务、取消任务、查看日志和结果
- TaskManager：维护 TaskRecord、TaskAttempt、TaskEvent，并把任务送入对应 worker pool
- WorkerPool：负责按池类型并行执行任务，并保证模块隔离
- Runner：负责真正的训练、验证、转换、导出实现

## 为什么要精简

本项目当前不是做 Kubernetes、Ray 或 Slurm 这类通用资源编排器。

当前阶段真正需要的是：

- 训练不会把 FastAPI 拖死
- 一个模块崩掉不会把其他模块带崩
- 同类任务可以受控并行
- 任务状态、日志、错误和结果有统一记录

因此像下面这些内容现在都不应该放进通用任务实体：

- CPU 核数最小值和偏好值
- 内存最小值和偏好值
- 单卡显存预算
- NUMA 偏好
- 复杂 fairness class
- 通用 oversubscribe 策略
- 通用租约续期和多层恢复决策

## 核心实体

### TaskRecord

TaskRecord 是任务系统里的主记录，负责表达“这个任务是什么、现在到哪一步、最终结果如何”。

当前阶段只保留以下字段：

- task_id
- task_kind
- display_name
- project_id
- created_by
- created_at
- parent_task_id
- task_spec
- resource_profile_id
- worker_pool
- metadata
- state
- current_attempt_no
- started_at
- finished_at
- progress
- result
- error_message

这些字段已经足够覆盖：

- 任务创建
- 任务状态查询
- 父子任务链
- 当前进度展示
- 结果和错误回写

### TaskAttempt

TaskAttempt 表示任务的一次执行尝试，重点是记录隔离执行的信息，而不是复杂调度决策。

当前阶段只保留以下字段：

- attempt_id
- task_id
- attempt_no
- worker_id
- host_id
- process_id
- state
- started_at
- heartbeat_at
- ended_at
- exit_code
- result
- error_message
- metadata

这些字段已经足够覆盖：

- 哪个 worker 在跑
- 是哪个进程在跑
- 任务是否还活着
- 这次尝试成功还是失败

### TaskEvent

TaskEvent 用于统一任务日志、状态提示和进度片段，不再做过细的事件分型和 patch 结构。

当前阶段只保留以下字段：

- event_id
- task_id
- attempt_id
- event_type
- created_at
- message
- payload

### ResourceProfile

ResourceProfile 在当前阶段不是硬件资源画像，而是最小执行画像。

当前阶段只保留以下字段：

- resource_profile_id
- profile_name
- worker_pool
- executor_mode
- max_concurrency
- metadata

它表达的是：

- 这个任务默认去哪类 worker pool
- 这个池是进程隔离还是线程执行
- 这类任务建议并发上限是多少

它不表达的是：

- 需要多少 CPU
- 需要多少 RAM
- 需要多少显存
- 用哪几块 GPU

这些信息应在具体任务规格里定义。例如 TrainingTaskSpec 再单独定义 gpu_count 或 gpu_ids。

## 状态模型

### TaskRecord 状态

当前阶段只保留最小状态集：

- queued
- running
- succeeded
- failed
- cancelled

### TaskAttempt 状态

当前阶段只保留最小状态集：

- running
- succeeded
- failed
- cancelled

## worker pool 划分

当前阶段建议先按模块职责划分，而不是按复杂资源规则划分。

### dataset-import pool

- 处理数据集导入和解压校验
- 重点是 IO 隔离和失败隔离

### dataset-export pool

- 处理数据集导出
- 重点是和训练前置链路解耦

### training pool

- 处理训练任务
- 默认进程隔离
- 训练具体用几张 GPU，在 TrainingTaskSpec 中定义

### validation pool

- 处理验证和评估任务
- 默认进程隔离

### conversion pool

- 处理模型转换任务
- 默认进程隔离

### batch-inference pool

- 处理离线批量推理任务
- 和在线部署推理解耦

## 对训练 GPU 的处理原则

通用任务层只知道任务属于 training pool，不知道 CPU、RAM、显存这些细资源规则。

训练相关 GPU 约束放在训练任务规格里即可，例如：

- gpu_count = 1
- gpu_count = 4
- gpu_ids = [0, 1]

TaskManager 在当前阶段只需要把任务送到 training pool，由 training runner 决定如何消费这些 GPU 参数。

## 当前实现方向

当前代码层已经落下以下四个实体：

- TaskRecord
- TaskAttempt
- TaskEvent
- ResourceProfile

以及对应的四张表：

- tasks
- task_attempts
- task_events
- resource_profiles

这四个实体当前已经接入 repository 和 Unit of Work，并承担以下最小职责：

- 统一记录后台任务主状态
- 统一记录追加式任务事件
- 支撑任务查询、取消和事件订阅
- 把 DatasetImport 正式挂到 TaskRecord，而不是只停留在 queue_task_id

## 当前公开 tasks API

当前阶段已经公开以下 REST API：

- POST /api/v1/tasks：创建任务
- GET /api/v1/tasks：按筛选字段列出任务
- GET /api/v1/tasks/{task_id}：查询任务详情和当前状态
- GET /api/v1/tasks/{task_id}/events：查询指定任务的事件流
- POST /api/v1/tasks/{task_id}/cancel：取消任务

当前阶段已经公开以下 WebSocket API：

- /ws/tasks/events：按 task_id 订阅任务事件

当前 WebSocket 订阅采用本地最小轮询实现，目标是先把公开协议和事件读取面稳定下来，而不是先上复杂事件总线。

## 当前筛选字段

### 任务列表筛选字段

当前 REST 列表接口支持以下筛选字段：

- project_id
- task_kind
- state
- worker_pool
- created_by
- parent_task_id
- dataset_id
- source_import_id
- limit

其中：

- dataset_id 来自 task_spec.dataset_id
- source_import_id 优先来自 task_spec.dataset_import_id，其次兼容 metadata.source_import_id

### 任务事件筛选字段

当前事件查询与订阅支持以下筛选字段：

- task_id
- event_type
- after_created_at
- limit

## DatasetImport 与 TaskRecord 的当前绑定方式

DatasetImport 当前已经正式挂到统一任务系统，绑定方式如下：

- 提交导入请求时，同时创建 DatasetImport 和对应 TaskRecord
- DatasetImport metadata 中保存 task_id，公开查询接口也返回 task_id
- 入队时为任务追加 queued 状态事件
- worker 开始处理时为任务追加 running 状态事件
- 解压和校验阶段追加 progress 事件
- 完成时追加 succeeded 结果事件
- 失败时追加 failed 结果事件

这意味着 DatasetImport 不再只是“导入记录 + queue_task_id”，而是一个可通过统一 tasks API 查询和订阅状态的正式后台任务。

## 后续实现顺序

1. 保持当前 tasks API 稳定，再补事件广播或事件总线替换当前轮询订阅
2. 把 DatasetExport 接到统一 TaskRecord
3. 再把 TrainingTask、ValidationTask、ConversionTask 逐步接入统一任务系统
4. 最后再评估是否需要更细的 worker pool 管理和任务恢复策略

## 推荐后续文档

- [docs/architecture/backend-service.md](backend-service.md)
- [docs/architecture/data-and-files.md](data-and-files.md)
- [docs/architecture/yolox-module-design.md](yolox-module-design.md)
- [docs/api/current-api.md](../api/current-api.md)