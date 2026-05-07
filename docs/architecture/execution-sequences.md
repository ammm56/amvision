# 关键执行顺序图

## 文档目的

本文档收敛当前主干中训练、转换、部署推理和 workflow execute 四条常用执行链的调用顺序，方便定位入口、任务状态回写点、文件写入点和进程边界。

本文档聚焦当前代码已经落地的顺序关系，不展开字段细节、部署步骤或历史方案。

## 适用范围

- YOLOX training task 提交与执行
- YOLOX conversion task 提交与执行
- DeploymentInstance 同步直返推理
- workflow application execute

## 当前边界

- 训练和转换都先创建 TaskRecord，再写入 LocalFileQueueBackend，由独立 worker 消费。
- 部署推理顺序图覆盖同步直返接口，不展开异步 inference task 链。
- 同步 deployment 推理接口不会自动启动 sync 子进程；未启动时会要求先调用 start 或 warmup。
- workflows execute 的 REST 入口当前复用 backend-service 当前进程运行时，不走 WorkflowApplicationProcessExecutor 子进程执行器。

## 训练链

- REST 入口：[backend/service/api/rest/v1/routes/yolox_training_tasks.py](../../backend/service/api/rest/v1/routes/yolox_training_tasks.py)
- 任务服务：[backend/service/application/models/yolox_training_service.py](../../backend/service/application/models/yolox_training_service.py)
- worker 入口：[backend/workers/training/yolox_training_queue_worker.py](../../backend/workers/training/yolox_training_queue_worker.py)

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as yolox_training_tasks.create_yolox_training_task
    participant TrainSvc as SqlAlchemyYoloXTrainingTaskService
    participant TaskSvc as SqlAlchemyTaskService
    participant DB as TaskRecord / TaskEvent
    participant Queue as LocalFileQueueBackend<br/>yolox-trainings
    participant Worker as YoloXTrainingQueueWorker
    participant Runner as SqlAlchemyYoloXTrainerRunner
    participant TrainProc as process_training_task
    participant Storage as LocalDatasetStorage
    participant ModelReg as ModelVersion 登记

    Client->>API: POST /api/v1/models/yolox/training-tasks
    API->>API: 校验 project scope 与请求体
    API->>TrainSvc: submit_training_task(request)
    TrainSvc->>TrainSvc: 解析 DatasetExport\n构建 task_spec
    TrainSvc->>TaskSvc: create_task(..., worker_pool=yolox-training)
    TaskSvc->>DB: 写入 TaskRecord
    DB-->>TaskSvc: created_task
    TaskSvc-->>TrainSvc: created_task
    TrainSvc->>Queue: enqueue(task_id)
    Queue-->>TrainSvc: queue_task
    TrainSvc->>TaskSvc: append_task_event(state=queued)
    TaskSvc->>DB: 写入 TaskEvent / 回写任务状态
    TrainSvc-->>API: submission
    API-->>Client: 202 Accepted(task_id, queue_task_id)

    loop worker 轮询
        Worker->>Queue: claim_next(yolox-trainings)
        Queue-->>Worker: queue_task
    end
    Worker->>Runner: run_training(training_task_id)
    Runner->>TrainProc: process_training_task(task_id)
    TrainProc->>DB: 读取 TaskRecord / TaskSpec
    TrainProc->>Storage: 读取 DatasetExport manifest
    TrainProc->>TaskSvc: append_task_event(state=running)
    TaskSvc->>DB: 写入 running 事件
    TrainProc->>TrainProc: _run_yolox_detection_training(...)
    TrainProc->>Storage: 写 best_ckpt/latest_ckpt/metrics/summary/labels
    TrainProc->>ModelReg: _register_training_output_model_version(best checkpoint)
    ModelReg->>DB: 写 ModelVersion / ModelFile 关联
    TrainProc->>TaskSvc: append_task_event(state=succeeded, result=...)
    TaskSvc->>DB: 写 succeeded 事件并回写状态
    TrainProc-->>Runner: YoloXTrainingTaskResult
    Runner-->>Worker: YoloXTrainingRunResult
    Worker->>Queue: complete(queue_task, metadata=...)
    Queue-->>Worker: completed
```

训练链的关键点是 REST 层只负责创建任务和入队，真正的训练、训练输出文件写入和 ModelVersion 登记都在 worker 消费阶段完成。

### 训练链异常分支

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as create_yolox_training_task
    participant TrainSvc as SqlAlchemyYoloXTrainingTaskService
    participant TaskSvc as SqlAlchemyTaskService
    participant DB as TaskRecord / TaskEvent
    participant Queue as LocalFileQueueBackend
    participant Worker as YoloXTrainingQueueWorker
    participant Proc as process_training_task

    Client->>API: POST /api/v1/models/yolox/training-tasks
    API->>TrainSvc: submit_training_task(request)
    alt DatasetExport / project scope / 请求体校验失败
        TrainSvc-->>API: InvalidRequestError
        API-->>Client: 400 / 403
        Note over Client: 修复输入边界后重新提交
    else TaskRecord 已创建但入队失败
        TrainSvc->>TaskSvc: create_task(...)
        TaskSvc->>DB: 写入 TaskRecord
        TrainSvc->>Queue: enqueue(task_id)
        Queue-->>TrainSvc: exception
        TrainSvc->>TaskSvc: append_task_event(state=failed)
        TaskSvc->>DB: 写 failed 事件并回写状态
        API-->>Client: 500
        Client->>API: GET /api/v1/models/yolox/training-tasks/{task_id}
        API-->>Client: failed + error_message
        Note over Client: 修复队列或配置后重新创建 training task
    else worker 执行阶段失败
        Worker->>Queue: claim_next(yolox-trainings)
        Queue-->>Worker: queue_task
        Worker->>Proc: process_training_task(task_id)
        Proc->>TaskSvc: append_task_event(state=running)
        TaskSvc->>DB: 写 running 事件
        Proc->>Proc: _run_yolox_detection_training(...)
        Proc-->>Proc: exception
        Proc->>TaskSvc: append_task_event(state=failed, result=partial outputs)
        TaskSvc->>DB: 写 failed 事件并回写状态
        Client->>API: GET /api/v1/models/yolox/training-tasks/{task_id}
        API-->>Client: failed + progress + output_object_prefix
        Note over Client: 修复数据、warm start 权重或运行环境后重新提交新任务
    end
```

训练失败态会把 `failed` 状态和当前可见输出路径写回 TaskRecord；`resume` 只用于 `paused` 任务，不用于已经 `failed` 的任务恢复。

## 转换链

- REST 入口：[backend/service/api/rest/v1/routes/yolox_conversion_tasks.py](../../backend/service/api/rest/v1/routes/yolox_conversion_tasks.py)
- 任务服务：[backend/service/application/conversions/yolox_conversion_task_service.py](../../backend/service/application/conversions/yolox_conversion_task_service.py)
- worker 入口：[backend/workers/conversion/yolox_conversion_queue_worker.py](../../backend/workers/conversion/yolox_conversion_queue_worker.py)
- 转换 runner：[backend/workers/conversion/yolox_conversion_runner.py](../../backend/workers/conversion/yolox_conversion_runner.py)

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as yolox_conversion_tasks._submit_yolox_conversion_task
    participant ConvSvc as SqlAlchemyYoloXConversionTaskService
    participant Planner as DefaultYoloXConversionPlanner
    participant TaskSvc as SqlAlchemyTaskService
    participant DB as TaskRecord / TaskEvent / ModelBuild
    participant Queue as LocalFileQueueBackend<br/>yolox-conversions
    participant Worker as YoloXConversionQueueWorker
    participant Proc as process_conversion_task
    participant Runner as LocalYoloXConversionRunner
    participant Storage as LocalDatasetStorage
    participant Script as OpenVINO/TensorRT 子进程脚本

    Client->>API: POST /api/v1/models/yolox/conversion-tasks/*
    API->>API: 校验 project scope
    API->>ConvSvc: submit_conversion_task(request)
    ConvSvc->>Planner: build_plan(source_model_version_id, target_formats)
    Planner-->>ConvSvc: YoloXConversionPlan
    ConvSvc->>ConvSvc: 校验目标格式\n解析 source runtime target
    ConvSvc->>TaskSvc: create_task(..., worker_pool=yolox-conversion)
    TaskSvc->>DB: 写入 TaskRecord
    ConvSvc->>Queue: enqueue(task_id)
    Queue-->>ConvSvc: queue_task
    ConvSvc->>TaskSvc: append_task_event(state=queued)
    TaskSvc->>DB: 写入 queued 事件
    ConvSvc-->>API: submission
    API-->>Client: 202 Accepted(task_id, target_formats)

    loop worker 轮询
        Worker->>Queue: claim_next(yolox-conversions)
        Queue-->>Worker: queue_task
    end
    Worker->>Proc: process_conversion_task(task_id)
    Proc->>DB: 读取 TaskRecord / TaskSpec
    Proc->>Proc: 解析 plan 与 source runtime target
    Proc->>TaskSvc: append_task_event(state=running, stage=planning)
    TaskSvc->>DB: 写入 running 事件
    Proc->>Storage: write conversion-plan.json
    Proc->>Runner: run_conversion(plan_steps, output_object_prefix)
    Runner->>Storage: 读取 checkpoint / 输出目录
    Runner->>Runner: export ONNX / validate / optimize
    opt 目标包含 OpenVINO IR
        Runner->>Script: subprocess build_openvino_ir.py
        Script-->>Runner: xml/bin 结果
    end
    opt 目标包含 TensorRT engine
        Runner->>Script: subprocess build_tensorrt_engine.py
        Script-->>Runner: engine 结果
    end
    Runner->>Storage: 写 builds 产物
    Runner-->>Proc: outputs + metadata
    Proc->>DB: 注册 ModelBuild / ModelFile
    Proc->>Storage: write conversion-report.json
    Proc->>TaskSvc: append_task_event(state=succeeded, result=...)
    TaskSvc->>DB: 写入 succeeded 事件
    Proc-->>Worker: YoloXConversionTaskResult
    Worker->>Queue: complete(queue_task, metadata=...)
    Queue-->>Worker: completed
```

转换链的关键点是规划阶段先在 service 层固化，真正的 ONNX、OpenVINO、TensorRT 构建发生在 worker 侧；其中 OpenVINO 和 TensorRT 进一步通过独立脚本子进程执行。

### 转换链异常分支

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as _submit_yolox_conversion_task
    participant ConvSvc as SqlAlchemyYoloXConversionTaskService
    participant Planner as DefaultYoloXConversionPlanner
    participant TaskSvc as SqlAlchemyTaskService
    participant DB as TaskRecord / TaskEvent
    participant Queue as LocalFileQueueBackend
    participant Worker as YoloXConversionQueueWorker
    participant Proc as process_conversion_task
    participant Runner as LocalYoloXConversionRunner
    participant Script as OpenVINO/TensorRT 子进程脚本

    Client->>API: POST /api/v1/models/yolox/conversion-tasks/*
    API->>ConvSvc: submit_conversion_task(request)
    alt source ModelVersion / target format / planner 校验失败
        ConvSvc->>Planner: build_plan(...)
        Planner-->>ConvSvc: InvalidRequestError
        API-->>Client: 400
        Note over Client: 修复来源版本、目标格式或 runtime 参数后重新提交
    else TaskRecord 已创建但入队失败
        ConvSvc->>TaskSvc: create_task(...)
        TaskSvc->>DB: 写入 TaskRecord
        ConvSvc->>Queue: enqueue(task_id)
        Queue-->>ConvSvc: exception
        ConvSvc->>TaskSvc: append_task_event(state=failed)
        TaskSvc->>DB: 写 failed 事件并回写状态
        API-->>Client: 500
        Client->>API: GET /api/v1/models/yolox/conversion-tasks/{task_id}
        API-->>Client: failed + error_message
        Note over Client: 修复队列或配置后重新创建 conversion task
    else worker 构建阶段失败
        Worker->>Queue: claim_next(yolox-conversions)
        Queue-->>Worker: queue_task
        Worker->>Proc: process_conversion_task(task_id)
        Proc->>TaskSvc: append_task_event(state=running, stage=planning)
        TaskSvc->>DB: 写 running 事件
        Proc->>Runner: run_conversion(...)
        opt OpenVINO / TensorRT 子步骤
            Runner->>Script: build_openvino_ir.py / build_tensorrt_engine.py
            Script-->>Runner: exception
        end
        Runner-->>Proc: exception
        Proc->>TaskSvc: append_task_event(state=failed, result=plan/report key)
        TaskSvc->>DB: 写 failed 事件并回写状态
        Client->>API: GET /api/v1/models/yolox/conversion-tasks/{task_id}
        API-->>Client: failed + plan_object_key + report_object_key
        Note over Client: 修复 OpenVINO、TensorRT 或来源 checkpoint 后重新创建 conversion task
    end
```

转换失败态会稳定回写 `plan_object_key`，并预留 `report_object_key`；如果失败发生在报告真正写出之前，`result` 接口可能返回文件缺失，此时应先查看任务详情和事件流定位失败阶段。

## 部署推理链

- REST 入口：[backend/service/api/rest/v1/routes/yolox_inference_tasks.py](../../backend/service/api/rest/v1/routes/yolox_inference_tasks.py)
- Deployment 服务：[backend/service/application/deployments/yolox_deployment_service.py](../../backend/service/application/deployments/yolox_deployment_service.py)
- 推理监督器：[backend/service/application/runtime/yolox_deployment_process_supervisor.py](../../backend/service/application/runtime/yolox_deployment_process_supervisor.py)

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as infer_yolox_deployment_instance
    participant DeploySvc as SqlAlchemyYoloXDeploymentService
    participant DB as DeploymentInstance / metadata
    participant SyncSup as YoloXDeploymentProcessSupervisor(sync)
    participant Child as deployment process worker
    participant Storage as LocalDatasetStorage
    participant Pred as run_yolox_inference_task

    Client->>API: POST /api/v1/models/yolox/deployment-instances/{id}/infer
    API->>API: 读取 JSON/multipart\n校验主体可见性
    API->>DeploySvc: get_deployment_instance(id)
    DeploySvc->>DB: 读取 DeploymentInstance
    DB-->>DeploySvc: deployment view
    API->>DeploySvc: resolve_process_config(id)
    DeploySvc->>DB: 从 metadata 反序列化 runtime_target_snapshot
    DeploySvc-->>API: YoloXDeploymentProcessConfig
    API->>SyncSup: ensure_deployment(process_config)
    SyncSup-->>API: 仅登记配置，不自动启动
    API->>SyncSup: get_status(process_config)
    alt 进程未 running
        SyncSup-->>API: process_state != running
        API-->>Client: 400 请先调用 sync/start 或 sync/warmup
    else 进程已 running
        API->>API: normalize_yolox_inference_input(...)
        API->>Pred: run_yolox_inference_task(...)
        Pred->>SyncSup: run_inference(process_config, prediction_request)
        SyncSup->>Child: 通过 request_queue 发送 infer 命令
        Child->>Child: 选择实例 / decode / preprocess / infer / postprocess
        Child-->>SyncSup: instance_id + detections + preview bytes + runtime info
        SyncSup-->>Pred: YoloXDeploymentProcessExecution
        Pred-->>API: execution_result
        opt save_result_image 为 true
            API->>Storage: write preview.jpg
        end
        opt 输入传输模式为 storage
            API->>Storage: write raw-result.json
        end
        API->>API: build_yolox_inference_payload\nserialize payload
        API-->>Client: 200 payload(detections, latency, preview/result uri)
    end
```

部署推理链的关键点是 DeploymentInstance 先解析出 process config，再由 supervisor 把推理请求转发到独立 deployment 子进程；同步直返接口本身不负责自动拉起进程。

### 部署推理链异常分支

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as infer_yolox_deployment_instance
    participant DeploySvc as SqlAlchemyYoloXDeploymentService
    participant SyncSup as YoloXDeploymentProcessSupervisor(sync)
    participant Child as deployment process worker

    Client->>API: POST /api/v1/models/yolox/deployment-instances/{id}/infer
    API->>DeploySvc: get_deployment_instance(id)
    alt DeploymentInstance 不存在或 project 不可见
        DeploySvc-->>API: 404 / 403
        API-->>Client: 404 / 403
        Note over Client: 修正 deployment_instance_id 或 project scope 后重试
    else sync 子进程未启动
        API->>SyncSup: get_status(process_config)
        SyncSup-->>API: process_state != running
        API-->>Client: 400 invalid_request + required_actions
        Client->>API: POST /sync/start 或 /sync/warmup
        API->>SyncSup: start_deployment / warmup_deployment
        API-->>Client: process_state=running
        Client->>API: 再次 POST /infer
    else 输入归一化失败
        API->>API: normalize_yolox_inference_input(...)
        API-->>Client: 400 invalid_request
        Note over Client: 修复 one-of 输入或图片内容后重试
    else 子进程推理失败或超时
        API->>SyncSup: run_inference(process_config, prediction_request)
        SyncSup->>Child: infer request
        Child-->>SyncSup: error / timeout / crashed
        SyncSup-->>API: ServiceConfigurationError
        API-->>Client: 500
        Client->>API: GET /sync/health
        API->>SyncSup: get_health(process_config)
        SyncSup-->>API: restart_count / keep_warm / last_error
        alt 进程仍存活但实例状态异常
            Client->>API: POST /sync/reset
            API->>SyncSup: reset_deployment(process_config)
            API-->>Client: reset 后 health 快照
        else 进程已退出或反复重启
            Client->>API: POST /sync/stop
            Client->>API: POST /sync/start 或 /sync/warmup
        end
        Client->>API: 再次 POST /infer
    end
```

同步直返推理没有 TaskRecord 回写点，恢复动作主要依赖 deployment 的 `status`、`health`、`reset`、`stop` 和 `start` 接口，而不是任务事件流。

## Workflow Execute 链

- REST 入口：[backend/service/api/rest/v1/routes/workflows.py](../../backend/service/api/rest/v1/routes/workflows.py)
- 应用执行器：[backend/service/application/workflows/process_executor.py](../../backend/service/application/workflows/process_executor.py)
- 图执行器：[backend/service/application/workflows/graph_executor.py](../../backend/service/application/workflows/graph_executor.py)
- 文件服务：[backend/service/application/workflows/workflow_service.py](../../backend/service/application/workflows/workflow_service.py)

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as workflows.execute_flow_application
    participant RuntimeExec as WorkflowApplicationRuntimeExecutor
    participant WFExec as _execute_workflow_application
    participant WFJson as LocalWorkflowJsonService
    participant Storage as LocalDatasetStorage
    participant Catalog as NodeCatalogRegistry
    participant RuntimeReg as WorkflowNodeRuntimeRegistry
    participant GraphExec as WorkflowGraphExecutor
    participant NodeHandler as Core / Custom Node Handler
    participant RTCtx as WorkflowServiceNodeRuntimeContext

    Client->>API: POST /api/v1/workflows/projects/{project_id}/applications/{application_id}/execute
    API->>API: 校验 project scope\n补 execution_metadata.created_by
    Note over API: 当前 REST execute 走当前进程执行器\n不是 WorkflowApplicationProcessExecutor
    API->>RuntimeExec: execute(request)
    RuntimeExec->>RuntimeExec: _normalize_execution_request()\n补 workflow_run_id
    RuntimeExec->>WFExec: _execute_workflow_application(...)
    WFExec->>WFJson: get_application(project_id, application_id)
    WFJson->>Storage: read application.json
    Storage-->>WFJson: FlowApplication
    WFExec->>WFJson: get_template(project_id, template_id, template_version)
    WFJson->>Storage: read template.json
    Storage-->>WFJson: WorkflowGraphTemplate
    WFExec->>WFExec: input binding_id -> template input_id 映射
    WFExec->>GraphExec: execute(template, input_values, execution_metadata, runtime_context)
    GraphExec->>Catalog: 已在启动期提供 node definitions
    GraphExec->>RuntimeReg: resolve_handler(node_type_id)
    loop 按拓扑顺序逐节点
        GraphExec->>GraphExec: 解析模板输入与上游输出
        GraphExec->>NodeHandler: handler(WorkflowNodeExecutionRequest)
        opt service node
            NodeHandler->>RTCtx: 取 queue/session/storage/supervisor
            RTCtx-->>NodeHandler: service runtime
        end
        NodeHandler-->>GraphExec: declared outputs
        GraphExec->>GraphExec: 记录 node_records / 缓存 node_output_values
    end
    GraphExec-->>WFExec: template_outputs + node_records
    WFExec->>WFExec: template output_id -> application output binding_id 映射
    WFExec-->>RuntimeExec: WorkflowApplicationExecutionResult
    RuntimeExec-->>API: execution_result
    API-->>Client: 200 outputs + template_outputs + node_records
```

workflow execute 链的关键点是 application 和 template 都从 LocalDatasetStorage 读取，真正的图执行按拓扑顺序在当前 backend-service 进程里完成，service node 再通过 WorkflowServiceNodeRuntimeContext 复用现有 queue、数据库会话、文件存储和 deployment supervisor。

### Workflow Execute 链异常分支

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as execute_flow_application
    participant RuntimeExec as WorkflowApplicationRuntimeExecutor
    participant WFExec as _execute_workflow_application
    participant WFJson as LocalWorkflowJsonService
    participant GraphExec as WorkflowGraphExecutor
    participant RuntimeReg as WorkflowNodeRuntimeRegistry
    participant NodeHandler as Core / Custom Node Handler

    Client->>API: POST /api/v1/workflows/projects/{project_id}/applications/{application_id}/execute
    API->>RuntimeExec: execute(request)
    RuntimeExec->>WFExec: _execute_workflow_application(...)
    alt application 或 template 不存在
        WFExec->>WFJson: get_application / get_template
        WFJson-->>WFExec: ResourceNotFoundError
        WFExec-->>API: 404
        API-->>Client: 404
        Note over Client: 先保存或修正 application/template，再重新 execute
    else input binding 或模板映射失败
        WFExec->>WFExec: _build_template_input_values(...)
        WFExec-->>API: InvalidRequestError
        API-->>Client: 400 invalid_request
        Note over Client: 修复 binding_id、template input_id 或节点连线后重新 save
    else handler 缺失或节点执行失败
        WFExec->>GraphExec: execute(...)
        GraphExec->>RuntimeReg: resolve_handler(node_type_id)
        alt handler 未注册
            RuntimeReg-->>GraphExec: missing handler
            GraphExec-->>API: ServiceConfigurationError
            API-->>Client: 500 failed node_type_id
            Note over Client: 安装或修复 custom node/runtime loader 后重试
        else 节点执行报错
            GraphExec->>NodeHandler: handler(request)
            NodeHandler-->>GraphExec: exception
            GraphExec-->>API: ServiceConfigurationError(node_id, execution_index)
            API-->>Client: 500 failed node details
            Note over Client: 根据 failed node details 修复节点参数、service 依赖或 deployment 状态后重试
        end
    end
```

workflow execute 当前没有独立 TaskRecord；失败信息直接通过同步响应返回，恢复动作依赖 template/application JSON 修正、runtime registry 修复或下游 service 状态恢复。

## 相关文档

- [docs/architecture/current-implementation-status.md](current-implementation-status.md)
- [docs/architecture/backend-service.md](backend-service.md)
- [docs/architecture/task-system.md](task-system.md)
- [docs/architecture/workflow-json-contracts.md](workflow-json-contracts.md)