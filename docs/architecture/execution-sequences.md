# 关键执行顺序图

## 文档目的

本文档收敛当前主干中训练、转换、部署推理和 workflow runtime 四条常用执行链的调用顺序，方便定位入口、任务状态回写点、文件写入点和进程边界。

本文档聚焦当前代码已经落地的顺序关系，不展开字段细节、部署步骤或历史方案。

## 适用范围

- YOLOX training task 提交与执行
- YOLOX conversion task 提交与执行
- DeploymentInstance 同步直返推理
- WorkflowPreviewRun 编辑态试跑
- WorkflowAppRuntime 同步调用

## 当前边界

- 训练和转换都先创建 TaskRecord，再写入 LocalFileQueueBackend，由独立 worker 消费。
- 部署推理顺序图覆盖同步直返接口，不展开异步 inference task 链。
- 同步 deployment 推理接口不会自动启动 sync 子进程；未启动时会要求先调用 start 或 warmup。
- workflow runtime 当前公开接口已经拆成两条路径：preview-runs 走隔离子进程；app-runtimes/{workflow_runtime_id}/invoke 走单实例 worker。

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

## Workflow Runtime 链

- preview 控制面：[backend/service/api/rest/v1/routes/workflow_runtime.py](../../backend/service/api/rest/v1/routes/workflow_runtime.py)
- runtime 服务：[backend/service/application/workflows/runtime_service.py](../../backend/service/application/workflows/runtime_service.py)
- preview 子进程执行器：[backend/service/application/workflows/snapshot_execution.py](../../backend/service/application/workflows/snapshot_execution.py)
- runtime worker 管理器：[backend/service/application/workflows/runtime_worker.py](../../backend/service/application/workflows/runtime_worker.py)

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as workflow_runtime routes
    participant RuntimeSvc as WorkflowRuntimeService
    participant Storage as LocalDatasetStorage
    participant DB as WorkflowRuntimeRepository
    participant PreviewProc as WorkflowSnapshotProcessExecutor
    participant WorkerMgr as WorkflowRuntimeWorkerManager
    participant RuntimeProc as workflow runtime worker process
    participant SnapshotExec as SnapshotExecutionService

    alt 编辑态 preview run
        Client->>API: POST /api/v1/workflows/preview-runs
        API->>RuntimeSvc: create_preview_run(request)
        RuntimeSvc->>Storage: write application/template snapshot
        RuntimeSvc->>DB: save WorkflowPreviewRun(state=running)
        RuntimeSvc->>PreviewProc: execute(snapshot request)
        PreviewProc->>SnapshotExec: execute(snapshot)
        SnapshotExec-->>PreviewProc: outputs + template_outputs + node_records
        PreviewProc-->>RuntimeSvc: execution_result
        RuntimeSvc->>DB: update WorkflowPreviewRun(state=succeeded|failed|timed_out)
        RuntimeSvc-->>API: WorkflowPreviewRun
        API-->>Client: 201 WorkflowPreviewRun
    else 已发布 runtime sync invoke
        Client->>API: POST /api/v1/workflows/app-runtimes/{id}/start
        API->>RuntimeSvc: start_workflow_app_runtime(id)
        RuntimeSvc->>WorkerMgr: start_runtime(runtime)
        WorkerMgr->>RuntimeProc: spawn worker process
        RuntimeProc-->>WorkerMgr: runtime-state(running)
        RuntimeSvc->>DB: save WorkflowAppRuntime(observed_state=running)
        Client->>API: POST /api/v1/workflows/app-runtimes/{id}/invoke
        API->>RuntimeSvc: invoke_workflow_app_runtime(id, request)
        RuntimeSvc->>DB: save WorkflowRun(state=dispatching)
        RuntimeSvc->>WorkerMgr: invoke_runtime(...)
        WorkerMgr->>RuntimeProc: invoke-run
        RuntimeProc->>SnapshotExec: execute(snapshot)
        SnapshotExec-->>RuntimeProc: outputs + template_outputs + node_records
        RuntimeProc-->>WorkerMgr: run-result + worker_state
        RuntimeSvc->>DB: update WorkflowRun / WorkflowAppRuntime
        RuntimeSvc-->>API: WorkflowRun
        API-->>Client: 200 WorkflowRun
    end
```

workflow runtime 链的关键点是编辑态试跑和已发布应用运行已经拆成两条公开路径。preview 通过固定 snapshot 在隔离子进程执行；已发布应用通过单实例 worker 进程执行 start、stop、restart、health、instances 和 sync invoke。

### Workflow Runtime 链异常分支

```mermaid
sequenceDiagram
    autonumber
    actor Client as 调用方
    participant API as workflow_runtime routes
    participant RuntimeSvc as WorkflowRuntimeService
    participant WorkerMgr as WorkflowRuntimeWorkerManager
    participant DB as WorkflowRuntimeRepository

    alt preview application 或 template 不存在
        Client->>API: POST /api/v1/workflows/preview-runs
        API->>RuntimeSvc: create_preview_run(request)
        RuntimeSvc-->>API: ResourceNotFoundError
        API-->>Client: 404
        Note over Client: 先保存或修正 application/template，再重新创建 preview run
    else preview 输入映射或节点执行失败
        API->>RuntimeSvc: create_preview_run(request)
        RuntimeSvc->>DB: save WorkflowPreviewRun(state=running)
        RuntimeSvc->>DB: update WorkflowPreviewRun(state=failed|timed_out)
        API-->>Client: 201 failed/timed_out WorkflowPreviewRun
        Note over Client: 根据 error_message 和 node_records 修复后重新创建 preview run
    else runtime 未启动或 worker 已失效
        Client->>API: POST /api/v1/workflows/app-runtimes/{id}/invoke
        API->>RuntimeSvc: invoke_workflow_app_runtime(id, request)
        RuntimeSvc-->>API: InvalidRequestError / ServiceConfigurationError
        API-->>Client: 400 / 500
        Note over Client: 先调用 start 或 restart，再重新 invoke
    else runtime 节点执行失败或同步等待超时
        API->>RuntimeSvc: invoke_workflow_app_runtime(id, request)
        RuntimeSvc->>WorkerMgr: invoke_runtime(...)
        WorkerMgr-->>RuntimeSvc: worker-error / timeout
        RuntimeSvc->>DB: update WorkflowRun(state=failed|timed_out)
        RuntimeSvc->>DB: update WorkflowAppRuntime(observed_state=failed)
        API-->>Client: 200 WorkflowRun(state=failed|timed_out)
        Note over Client: 读取 run/runtime 结果后，可调用 restart 恢复单实例 worker
    end
```

workflow runtime 当前没有独立 TaskRecord；preview 和 sync invoke 的失败信息通过 WorkflowPreviewRun、WorkflowRun 和 WorkflowAppRuntime 这三类资源稳定表达。

## 相关文档

- [docs/architecture/current-implementation-status.md](current-implementation-status.md)
- [docs/architecture/backend-service.md](backend-service.md)
- [docs/architecture/task-system.md](task-system.md)
- [docs/architecture/workflow-json-contracts.md](workflow-json-contracts.md)