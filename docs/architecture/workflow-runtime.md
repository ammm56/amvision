# Workflow 运行时设计

## 文档目的

本文档用于定义 workflow 编辑态试跑和已保存 FlowApplication 稳定运行的最小运行时设计。

本文档只收敛当前建议的资源模型、队列划分、worker 拓扑和 API 草案，不展开实现细节、部署脚本或迁移步骤清单。

## 当前问题

- 当前 REST execute 路由仍在 backend-service 当前进程里执行已保存 FlowApplication。
- 编辑态试跑是高频、短时、易出错的执行面，主要诉求是进程独立、快速失败和互不影响。
- 已保存 FlowApplication 的正式调用更接近长期运行的 runtime 单元，主要诉求是稳定、隔离、健康检查、重启和多应用并存。
- 训练、转换、验证、导出、异步推理已经通过 worker 和队列隔离，workflow 运行面还没有进入同一层级的独立运行时设计。

## 设计结论

- workflow 执行面应拆成编辑态试跑和已发布应用运行两类路径，不继续共用同一条 execute 语义。
- 编辑态试跑默认采用一请求一子进程，不进入长期运行 worker。
- 已发布 FlowApplication 应引入专用 workflow-runtime-worker，由它管理长期运行的 workflow app runtime。
- 每个 workflow app instance 默认独占一个子进程，实例之间不共享 Python 运行时、不共享节点模块状态、不共享执行上下文。
- backend-service 保持控制面职责，负责资源创建、查询、健康观察、同步等待和权限校验，不再直接执行 workflow 图。
- workflow runtime 不替代训练、转换、评估、导出和推理 worker；workflow 内部的 service 节点仍继续调用现有服务边界和任务系统。

## 当前阶段边界

- 当前设计只覆盖本地单机部署，不展开多机调度或跨主机实例迁移。
- 当前设计不引入通用集群调度器，不做 CPU、RAM、显存和 NUMA 的统一资源编排。
- 当前设计默认一个 workflow app instance 同时只处理一个 run；并发优先通过增加 instance 数量实现。
- 当前设计不要求把所有 preview run 和 workflow run 都映射成 TaskRecord。
- 当前设计不把 workflow runtime 做成新的 deployment runtime 平台；模型部署、训练、转换、评估仍复用现有子系统。

## 两类执行面

### 编辑态试跑

编辑器里的试跑面向模板调试、参数校验、custom node 开发和节点链路联调。

这类执行建议采用下面的规则：

- 每次试跑都在独立子进程里执行。
- 子进程执行完成、失败或超时后立即退出，不保留长期实例。
- 默认同步等待结果，优先返回 outputs、template_outputs、node_records 和错误摘要。
- 失败不触发自动重启，不把试跑进程纳入长期 supervisor。
- 这一路径默认不进入后台队列，避免界面调试被排队延迟放大。

### 已发布应用运行

已保存 FlowApplication 的正式调用面向稳定运行、持续接收请求和多应用并存。

这类执行建议采用下面的规则：

- backend-service 只创建和查询 runtime，不直接执行图。
- workflow-runtime-worker 负责拉起、停止、监控和重启 workflow app instance。
- 每个 runtime 默认至少对应一个独立 instance，每个 instance 对应一个独立子进程。
- 已发布应用运行时必须固定到不可变快照，而不是直接追随可变的 application 保存文件。
- 同步调用和异步调用都落到 WorkflowRun 资源，再由 runtime instance 执行。

## 资源模型

## 资源总览

| 资源 | 作用 | 生命周期 |
| --- | --- | --- |
| WorkflowPreviewRun | 表示一次编辑态隔离试跑 | 短时、可过期 |
| WorkflowAppRuntime | 表示一份已发布应用的长期运行配置和期望状态 | 长期存在 |
| WorkflowAppInstance | 表示某个 runtime 当前实际运行的独立实例 | 跟随 runtime 存活 |
| WorkflowRun | 表示已发布应用的一次正式调用 | 按运行记录保留 |

### WorkflowPreviewRun

WorkflowPreviewRun 用于承接编辑器中的快速试跑。

建议最小字段：

- preview_run_id
- project_id
- source_kind，取值建议为 saved-application 或 inline-snapshot
- application_snapshot_object_key
- template_snapshot_object_key
- created_by
- state，取值建议为 queued、running、succeeded、failed、cancelled、timed_out、expired
- started_at
- finished_at
- timeout_seconds
- outputs
- template_outputs
- node_records
- error_message
- log_excerpt
- retention_until
- metadata

建议语义：

- preview run 默认只保留短期查询窗口，用于界面调试回看。
- preview run 不要求长期稳定重试，也不要求自动重启。
- preview run 的 application 或 template 可以来自尚未正式保存的 inline 快照。

### WorkflowAppRuntime

WorkflowAppRuntime 表示一份已发布应用的长期运行单元。

建议最小字段：

- workflow_runtime_id
- project_id
- application_id
- display_name
- application_snapshot_object_key
- template_snapshot_object_key
- activation_mode，取值建议为 on-demand 或 always-on
- desired_state，取值建议为 stopped 或 running
- observed_state，取值建议为 starting、running、degraded、stopped、failed
- min_instance_count
- max_instance_count
- request_timeout_seconds
- idle_shutdown_seconds
- restart_policy
- restart_backoff_seconds
- last_started_at
- last_stopped_at
- last_error
- health_summary
- metadata

这里的关键点是快照固定。

当前 FlowApplication 保存接口没有显式版本号，因此 runtime 创建时不应只保存 application_id，而应把当时引用的 application JSON 和 template JSON 固定为 runtime 自己的快照对象。这样后续继续编辑同名 application 时，不会直接影响已经运行的 runtime。

### WorkflowAppInstance

WorkflowAppInstance 表示 runtime 下面一个真正执行请求的独立实例。

建议最小字段：

- instance_id
- workflow_runtime_id
- worker_id
- host_id
- process_id
- state，取值建议为 starting、idle、busy、stopping、stopped、failed、restarting
- current_run_id
- started_at
- heartbeat_at
- restart_count
- last_error
- loaded_snapshot_fingerprint
- runtime_session_summary
- metadata

建议语义：

- 一个 instance 默认一次只处理一个 WorkflowRun。
- 多个 runtime 不共享 instance。
- 一个 runtime 需要并发时，优先增加 instance 数量，而不是在同一进程里并发执行多条图。

### WorkflowRun

WorkflowRun 表示已发布应用的一次正式调用。

建议最小字段：

- workflow_run_id
- workflow_runtime_id
- trigger_source，取值建议为 sync-invoke、async-invoke、schedule、integration
- state，取值建议为 queued、dispatching、running、succeeded、failed、cancelled、timed_out
- created_by
- created_at
- started_at
- finished_at
- assigned_instance_id
- input_payload
- outputs
- template_outputs
- node_records_object_key
- progress
- error_message
- result_summary
- metadata

建议语义：

- sync 调用和 async 调用都使用 WorkflowRun 作为统一执行记录。
- 如果节点输出过大，node_records 和详细结果应写文件，只在记录里保留 object key。
- WorkflowRun 是 workflow 领域自己的运行记录，不强制复用通用 TaskRecord。

## 队列划分

## 划分结论

- 编辑态 preview run 默认不走后台队列。
- 已发布应用运行至少拆成一条控制队列和一条运行队列。
- workflow runtime 队列与训练、转换、评估、导出、推理队列分开，避免长期 runtime 控制流和重任务执行流互相干扰。

### preview execute

- 默认不进入队列。
- backend-service 直接创建 WorkflowPreviewRun，拉起子进程，同步等待结果或超时。
- 如果后续需要削峰，可再补 preview 专用排队层，但不建议作为第一阶段前提。

### workflow-runtime-control 队列

这条队列只承接 runtime 控制命令。

建议消息类型：

- create-runtime
- start-runtime
- stop-runtime
- restart-runtime
- reconcile-runtime
- scale-runtime
- refresh-runtime-snapshot

设计目的：

- 把运行控制和业务调用分开。
- 让 workflow-runtime-worker 以稳定节奏做状态收敛、拉起和回收。

### workflow-runtime-runs 队列

这条队列只承接已发布应用的异步调用。

建议消息载荷最小字段：

- workflow_runtime_id
- workflow_run_id
- requested_timeout_seconds
- trigger_source
- created_at

设计目的：

- 让 async 调用和控制命令分开。
- 保持一个 runtime 的实例选择、超时处理和失败重试都收口在 workflow-runtime-worker。

## worker 拓扑

最小拓扑建议如下：

```text
backend-service
  -> WorkflowPreviewService
     -> preview child process (one request / one process)
  -> WorkflowRuntimeControlService
     -> WorkflowAppRuntime / WorkflowRun persistence
     -> workflow-runtime-control queue
     -> workflow-runtime-runs queue
     -> sync invoke wait loop

workflow-runtime-worker
  -> control consumer
  -> run dispatcher
  -> instance supervisor table
     -> workflow app instance process A
     -> workflow app instance process B
     -> workflow app instance process C

workflow app instance process
  -> load pinned application snapshot
  -> load pinned template snapshot
  -> rebuild dataset storage / db session / queue backend / node catalog / runtime registry
  -> execute one WorkflowRun at a time
  -> write run events / outputs / heartbeat / error
```

## 为什么要单独的 workflow-runtime-worker

- 现有 backend-worker 主要处理 claim-next、执行完成、回写状态这一类后台任务。
- workflow app runtime 的核心职责是长期存活、实例监督、健康检查、重启和按实例分发调用，不是一次性任务消费。
- 如果把 runtime supervisor 直接塞进现有 backend-worker 进程，会把长期实例管理和训练、转换、评估这类重任务生命周期混在一起。
- workflow runtime 需要自己的启动、停止、重启和健康语义，更接近 deployment supervisor，而不是普通 task consumer。

因此建议新增独立进程入口 workflow-runtime-worker，而不是只在现有 backend-worker 里再挂一个 consumer kind。

## 实例执行规则

- 一个 WorkflowAppRuntime 默认 min_instance_count=0 或 1，由 activation_mode 决定。
- on-demand 模式允许空闲回收实例，首次请求时再拉起。
- always-on 模式保持至少 min_instance_count 个实例常驻。
- 一个 instance 默认串行执行一条 run，避免在同一 Python 进程里叠加多个 workflow 上下文。
- instance 失败只影响当前 runtime，不影响其他 runtime，也不影响 backend-service。
- instance 重启由 workflow-runtime-worker 负责，preview run 不参与这套重启机制。

## API 草案

## 设计原则

- 编辑态和正式运行态 API 分开。
- runtime 管理 API 和 run 调用 API 分开。
- 当前 execute 路由先保留兼容入口，不作为正式运行态长期接口。

### 编辑态试跑 API

#### POST /api/v1/workflows/preview-runs

用途：创建一次编辑态隔离试跑。

建议请求字段：

- project_id
- application，可选，允许 inline application 快照
- template，可选，允许 inline template 快照
- application_ref，可选，引用已保存 application
- input_bindings
- execution_metadata
- timeout_seconds
- wait_mode，取值建议为 sync 或 async

建议响应：

- wait_mode=sync 时直接返回 WorkflowPreviewRun 结果摘要、outputs、template_outputs、node_records
- wait_mode=async 时返回 preview_run_id、state 和查询链接

#### GET /api/v1/workflows/preview-runs/{preview_run_id}

用途：查询单条 preview run 状态、错误摘要和输出摘要。

#### GET /api/v1/workflows/preview-runs/{preview_run_id}/events

用途：查询 preview run 的执行事件和日志片段。

#### POST /api/v1/workflows/preview-runs/{preview_run_id}/cancel

用途：取消尚未结束的 preview run，并终止对应子进程。

### 已发布应用运行管理 API

#### POST /api/v1/workflows/app-runtimes

用途：基于已保存 FlowApplication 创建一个长期运行的 WorkflowAppRuntime。

建议请求字段：

- project_id
- application_id
- display_name
- activation_mode
- min_instance_count
- max_instance_count
- request_timeout_seconds
- idle_shutdown_seconds
- restart_policy
- metadata

建议行为：

- 读取当前 application 和 template
- 固定为 runtime 快照
- 创建 WorkflowAppRuntime 记录
- 视 desired_state 是否为 running 决定是否发出 create-runtime 或 start-runtime 控制命令

#### GET /api/v1/workflows/app-runtimes

用途：列出某个 Project 下的 WorkflowAppRuntime 摘要。

#### GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}

用途：查询单个 runtime 的快照来源、期望状态、观察状态和健康摘要。

#### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/start

用途：把 runtime 的 desired_state 切到 running，并触发 supervisor 拉起实例。

#### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop

用途：把 runtime 的 desired_state 切到 stopped，并停止全部实例。

#### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart

用途：重启全部实例并刷新 runtime 健康状态。

#### GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health

用途：返回 runtime 的当前健康摘要、实例列表、重启计数和最近错误。

#### GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/instances

用途：返回 runtime 下面所有 instance 的观测状态。

### 已发布应用调用 API

#### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke

用途：发起一次同步调用。

建议行为：

- backend-service 创建 WorkflowRun
- 如果没有可用 instance，则按 activation_mode 决定等待拉起或直接返回不可用
- 把 run 交给 workflow-runtime-worker
- 在 request_timeout_seconds 内等待 run 结束
- 成功时直接返回 outputs 和 template_outputs
- 超时时返回 timed_out，并触发实例侧取消或回收

#### POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs

用途：发起一次异步调用。

建议响应：

- workflow_run_id
- state=queued
- queue_name=workflow-runtime-runs

#### GET /api/v1/workflows/runs/{workflow_run_id}

用途：查询单条 WorkflowRun 状态、错误摘要、实例归属和结果摘要。

#### GET /api/v1/workflows/runs/{workflow_run_id}/events

用途：查询单条 WorkflowRun 的事件流和节点级日志片段。

#### POST /api/v1/workflows/runs/{workflow_run_id}/cancel

用途：取消尚未结束的 WorkflowRun，并通知对应 instance 停止当前执行。

## 与现有 execute 路由的关系

- 当前 POST /api/v1/workflows/projects/{project_id}/applications/{application_id}/execute 可以继续保留，作为过渡期兼容入口。
- 过渡期建议把它收敛为编辑态试跑语义，而不是长期运行语义。
- 正式运行态应迁移到 WorkflowAppRuntime 和 WorkflowRun 这组新资源，不继续复用旧 execute 路由。

## 与现有任务系统的关系

- WorkflowPreviewRun 和 WorkflowRun 不强制落到 TaskRecord。
- workflow 内部如果调用训练、转换、评估、导出、异步推理节点，仍应提交到现有 task-system 和对应 worker pool。
- workflow-runtime-worker 管理的是 workflow app instance 和 WorkflowRun，不接管模型训练、转换或 deployment 的现有调度责任。

## 第一阶段建议落点

如果只做最小可执行闭环，建议优先完成下面四件事：

1. 把编辑态试跑切到一请求一子进程。
2. 新增 WorkflowAppRuntime、WorkflowRun 和 WorkflowAppInstance 三类资源。
3. 新增独立进程入口 workflow-runtime-worker，先实现 start、stop、health 和单实例运行。
4. 让已发布应用的正式调用先走 runtime 资源，不再直接复用当前 execute 路由。