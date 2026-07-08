# 模型部署调用 SDK 规划

## 文档目的

本文档固定模型 DeploymentInstance 的外部调用 SDK 边界、配置方式和后续 .NET 实现清单，避免后续实现时把前端部署管理能力、workflow app 调用能力和模型直接推理调用混在一起。

模型 DeploymentInstance 的创建、选择模型、选择 ModelBuild、选择 Runtime backend、选择 precision、选择 device、设置 instance_count 和删除等管理动作由前端界面完成。SDK 只面向现场程序实际使用：控制已经存在的 deployment runtime，并向已经存在的 DeploymentInstance 提交同步或异步推理请求。

## 当前结论

- .NET SDK 当前已经实现 WorkflowAppRuntime、WorkflowRun、TriggerSource、ZeroMQ 触发和 SystemConfig 调用。
- .NET SDK 当前没有实现模型 DeploymentInstance 的 runtime 控制和模型直接推理调用。
- SDK 不需要实现 DeploymentInstance 的 `list/create/get/delete` 管理接口。
- SDK 需要实现已有 DeploymentInstance 的 `sync/async` runtime 启动、预热、重置、停止、状态、health 和推理调用。
- 参考实现应沿用现有 `Config/config_*.json + key + 方法` 模式，第三方程序只选择配置 key 和调用方法，不直接拼 `task_type`、`deployment_instance_id`、`runtime_mode` 等参数。

## 调用方关系

```text
现场上位机 / WinForms / WPF / MES 桥接程序 / 相机采集程序
  |
  v
Amvision.Workflows SDK
  |
  |-- 模型 deployment runtime 控制：start / warmup / reset / stop / status / health
  |
  |-- 模型同步推理：deployment-instances/{id}/infer
  |
  `-- 模型异步推理：inference-tasks create / get / result
        |
        v
      backend-service 模型 deployment runtime
```

SDK 不直接访问数据库、对象存储、deployment worker 内部对象、LocalBufferBroker 内部文件池或模型进程内队列。SDK 只调用已经公开的 REST API，并把常用图片输入方式封装成稳定方法。

## 不实现的管理能力

以下能力保持在前端界面、Postman 调试集或运维工具中，不放入现场调用 SDK：

- 创建 DeploymentInstance。
- 删除 DeploymentInstance。
- 列出和选择 DeploymentInstance。
- 选择模型、ModelVersion、ModelBuild。
- 设置 Runtime backend、Runtime precision、device、instance_count。
- 修改 deployment metadata。
- 处理训练、转换、部署来源选择等上游流程。

这样做的原因是现场程序通常只需要长期使用已经部署好的模型，不应该在运行时重新配置平台资源，避免误改生产部署。

## 需要实现的 REST 调用

### runtime 控制

后端已有公开路径：

```text
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/start
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/warmup
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/reset
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/stop
GET  /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/status
GET  /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/health
```

`task_type` 支持：

- `detection`
- `classification`
- `segmentation`
- `pose`
- `obb`

`runtime_mode` 支持：

- `sync`
- `async`

### 同步推理

```text
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/infer
```

SDK 需要封装以下输入来源：

- image bytes：现场相机采集后已经得到 JPEG / PNG / BMP bytes。
- image file：低频调试或磁盘图片输入。
- image base64：HTTP/JSON 调试、旧系统桥接或低频调用。
- 通用 request：允许调用方显式传 `input_file_id`、`input_uri`、`image_base64` 或 `extra_options`。

同步推理返回当前请求的模型推理结果，适合现场实时拿结果再做业务判断。

### 异步推理任务

```text
POST /api/v1/models/{task_type}/inference-tasks
GET  /api/v1/models/{task_type}/inference-tasks/{task_id}
GET  /api/v1/models/{task_type}/inference-tasks/{task_id}/result
```

异步推理任务适合低频离线调试、耗时较长或希望由任务系统记录结果的场景。创建任务时需要 `project_id` 和 `deployment_instance_id`，这两个值从配置文件读取。

## .NET SDK 底层 API 规划

SDK 底层仍保持通用 typed API，供需要直接使用 SDK 的开发者调用。

建议新增文件：

```text
sdks/dotnet/src/Amvision.Workflows/
  Http/
    AmvisionWorkflowClient.ModelDeployments.cs
    AmvisionWorkflowClient.ModelInference.cs
  Http/Requests/
    ModelTaskTypes.cs
    ModelDeploymentRuntimeModes.cs
    ModelDeploymentInferenceRequest.cs
    ModelDeploymentInferenceUploadRequest.cs
    ModelInferenceTaskCreateRequest.cs
  Http/Responses/
    ModelDeploymentProcessStatusResponse.cs
    ModelDeploymentRuntimeHealthResponse.cs
    ModelDeploymentInferenceResponse.cs
    ModelInferenceTaskResponse.cs
    ModelInferenceTaskResultResponse.cs
```

建议方法：

```csharp
StartModelDeploymentRuntimeAsync(taskType, deploymentInstanceId, runtimeMode)
WarmupModelDeploymentRuntimeAsync(taskType, deploymentInstanceId, runtimeMode)
ResetModelDeploymentRuntimeAsync(taskType, deploymentInstanceId, runtimeMode)
StopModelDeploymentRuntimeAsync(taskType, deploymentInstanceId, runtimeMode)
GetModelDeploymentRuntimeStatusAsync(taskType, deploymentInstanceId, runtimeMode)
GetModelDeploymentRuntimeHealthAsync(taskType, deploymentInstanceId, runtimeMode)

InferModelDeploymentWithImageBytesAsync(taskType, deploymentInstanceId, request)
InferModelDeploymentWithImageBase64Async(taskType, deploymentInstanceId, request)
InferModelDeploymentWithImageFileAsync(taskType, deploymentInstanceId, request)
InferModelDeploymentAsync(taskType, deploymentInstanceId, request)

CreateModelInferenceTaskWithImageBytesAsync(taskType, request)
CreateModelInferenceTaskWithImageBase64Async(taskType, request)
CreateModelInferenceTaskWithImageFileAsync(taskType, request)
CreateModelInferenceTaskAsync(taskType, request)
GetModelInferenceTaskAsync(taskType, taskId)
GetModelInferenceTaskResultAsync(taskType, taskId)
```

底层方法需要保留 raw `AmvisionWorkflowApiResponse` API，同时提供 typed response 方法，保持与现有 WorkflowAppRuntime / TriggerSource client 风格一致。

## Console 参考实现配置方式

`sdks/dotnet/apps/Amvision.Workflows.Console` 是官方参考实现和现场可直接使用的 console 程序。模型部署调用也必须沿用现有配置模式：

- 程序启动时读取 `Config/config_*.json`。
- 每个 workflow app runtime + trigger source 仍可以保持一个单独的 `config_*.json`。
- 模型 deployment 没有 workflow app runtime + trigger source 这种一对一边界，因此每个 `config_*.json` 都可以包含 `model_deployments` 列表。
- 程序把所有配置文件中的 `model_deployments` 合并成统一 `ModelDeployments` 字典。
- 第三方程序只传入 deployment key 和方法参数，不需要知道具体 `task_type`、`deployment_instance_id`、`runtime_mode`、阈值和返回图配置。

配置示例：

```json
{
  "backend": {
    "base_api_url": "http://127.0.0.1:8000",
    "access_token": "amvision-default-user-token",
    "project_id": "project-1",
    "http_timeout_seconds": 60
  },
  "runtime": {
    "name": "yolo11m_barqrcode_runtime",
    "workflow_runtime_id": "workflow-runtime-xxx"
  },
  "trigger_sources": [
    {
      "name": "yolo11m_barqrcode_zeromq",
      "trigger_source_id": "zeromq-workflow-runtime-xxx",
      "zero_mq": {
        "bind_endpoint": "tcp://127.0.0.1:5555",
        "default_input_binding": "request_image_ref"
      }
    }
  ],
  "model_deployments": [
    {
      "name": "barcode_detector",
      "task_type": "detection",
      "deployment_instance_id": "deployment-instance-xxx",
      "runtime_mode": "sync",
      "input_transport_mode": "memory",
      "score_threshold": 0.3,
      "save_result_image": false,
      "return_preview_image_base64": false,
      "default_image_path": "Resources/Img/qrcode50.jpg"
    }
  ]
}
```

`model_deployments` 中不放以下字段：

- `model_version_id`
- `model_build_id`
- `runtime_backend`
- `runtime_precision`
- `device_name`
- `instance_count`
- `source_kind`
- 创建、删除或修改 deployment 所需的字段

这些字段属于前端部署管理结果，不属于现场调用配置。

## 配置 catalog 和重复 key 规则

启动后建议形成三个独立 catalog：

```csharp
public sealed class WorkflowConfigurationCatalog
{
    public IReadOnlyDictionary<string, ConfiguredRuntime> Runtimes { get; }
    public IReadOnlyDictionary<string, ConfiguredTriggerSource> TriggerSources { get; }
    public IReadOnlyDictionary<string, ConfiguredModelDeployment> ModelDeployments { get; }
}
```

key 规则：

- `runtime.name` 在 `Runtimes` 中必须唯一。
- `trigger_sources[].name` 在 `TriggerSources` 中必须唯一。
- `model_deployments[].name` 在 `ModelDeployments` 中必须唯一。
- key 比较建议使用 `StringComparer.OrdinalIgnoreCase`，避免大小写差异造成现场误用。
- 重复 key 不允许静默覆盖，也不随机保留某个配置。
- 加载时发现重复 key，应把重复项从有效 catalog 中排除，并抛出配置错误，列出 key、配置类型和来源文件。

示例错误：

```text
Config key duplicated: model_deployments.barcode_detector
files:
- Config/config_line_a.json
- Config/config_line_b.json
```

这种处理方式可以避免现场启动后调用到错误模型。配置错误应在程序启动阶段发现并修正，不应运行到推理调用阶段才暴露。

## Console 参考实现方法规划

建议新增目录：

```text
sdks/dotnet/apps/Amvision.Workflows.Console/
  ModelDeployment/
    ModelDeploymentOperations.cs
    StartModelDeploymentRuntimeAsync.cs
    StopModelDeploymentRuntimeAsync.cs
    ResetModelDeploymentRuntimeAsync.cs
    WarmupModelDeploymentRuntimeAsync.cs
    GetModelDeploymentRuntimeStatusAsync.cs
    GetModelDeploymentRuntimeHealthAsync.cs
    InvokeModelDeploymentWithImageBytesAsync.cs
    InvokeModelDeploymentWithImageBase64Async.cs
    InvokeModelDeploymentWithImageFromFileAsync.cs
    RunModelInferenceTaskWithImageBytesAsync.cs
    RunModelInferenceTaskWithImageBase64Async.cs
    RunModelInferenceTaskWithImageFromFileAsync.cs
    GetModelInferenceTaskAsync.cs
    GetModelInferenceTaskResultAsync.cs
```

参考实现方法只接收配置 key 和运行时输入：

```csharp
await runner.WarmupModelDeploymentRuntimeAsync("barcode_detector", cancellationToken);

var syncResult = await runner.InvokeModelDeploymentWithImageBytesAsync(
    "barcode_detector",
    imageBytes,
    mediaType: "image/jpeg",
    cancellationToken: cancellationToken);

var task = await runner.RunModelInferenceTaskWithImageFromFileAsync(
    "barcode_detector",
    "Resources/Img/qrcode50.jpg",
    cancellationToken: cancellationToken);

var taskResult = await runner.GetModelInferenceTaskResultAsync(
    "barcode_detector",
    task.TaskId,
    cancellationToken);
```

`task_type`、`deployment_instance_id`、`runtime_mode`、`score_threshold`、`save_result_image` 和 `return_preview_image_base64` 都从配置 key 对应的 `ConfiguredModelDeployment` 读取。

## 防呆规则

SDK 底层和 Console 参考实现都需要做参数校验：

- `task_type` 只能是 `detection/classification/segmentation/pose/obb`。
- `runtime_mode` 只能是 `sync/async`。
- `deployment_instance_id` 不能为空。
- `project_id` 在异步任务场景不能为空。
- 图片输入方法只接受一种主输入来源：bytes、file、base64、uri 或 file_id。
- image bytes 不能为空。
- image file 必须存在。
- image base64 不能为空。
- `score_threshold` 如设置，建议限制在 `0-1`。
- `default_image_path` 只用于调试或默认文件输入，不用于相机高频输入。

## 测试要求

.NET SDK 需要补充以下测试：

- runtime control URL、HTTP method 和 path segment 编码测试。
- `sync/async` runtime mode 参数测试。
- `task_type` 参数测试。
- 同步 infer multipart body 测试。
- image base64 request body 测试。
- 异步 inference task create URL/body 测试。
- get inference task 和 get result URL 测试。
- Console config `model_deployments` 读取测试。
- 多个 `config_*.json` 合并 catalog 测试。
- `runtime`、`trigger_source`、`model_deployment` 重复 key 配置错误测试。

## 与 workflow app SDK 的边界

WorkflowAppRuntime / TriggerSource SDK 面向可编排 workflow app，核心是按图执行，输入输出由 app binding 决定。

模型 DeploymentInstance SDK 面向已经部署好的模型 runtime，核心是模型推理服务控制和直接推理调用。

两条线可以共用 `AmvisionWorkflowClient`、HTTP helper、配置加载器和图片工具，但调用目录和配置模型需要保持分开，避免第三方开发者把 workflow app runtime key 和模型 deployment key 混用。
