# Amvision.Workflows

C# / .NET SDK 用于设备上位机、MES、采集程序和调试工具管理 WorkflowAppRuntime、发起 WorkflowRun，并通过 ZeroMQ TriggerSource 调用 backend-service。

## 当前实现

- SDK 项目：`src/Amvision.Workflows`
- 源码结构：`Http/` 放 Workflow 管理 API client、请求和响应模型，`ZeroMq/` 放 TriggerSource REQ/REP 调用，`Internal/` 放 SDK 内部 JSON/HTTP helper
- 目标框架：`net461;net472;netstandard2.1;net10.0`
- ZeroMQ 依赖：NetMQ
- 支持 ZeroMQ 图片 REQ/REP 调用和纯事件 REQ/REP 调用
- 支持 TriggerResult 和 ZeroMQ error reply 解析
- 支持 Workflow 管理 API HTTP client：WorkflowAppRuntime create/list/get/events/start/stop/restart/health/instances/delete，WorkflowRun create/invoke/upload/get/events/cancel，TriggerSource list/get/create/enable/disable/delete/health，SystemConfig get
- HTTP client 保留 raw `AmvisionWorkflowApiResponse` API，同时提供 runtime、run、app-result、trigger-source、system config 的 typed response 方法
- `invoke app runtime` 和 `get workflow run` 默认按平台页面使用 `response_mode=run`；现场同步调用只取公开结果时使用 `InvokeWorkflowAppRuntimeAppResultResponseAsync`、`InvokeWorkflowAppRuntimeAppResultAsync<T>`、`GetWorkflowRunAppResultResponseAsync` 或 `GetWorkflowRunAppResultAsync<T>`

SDK 只负责第三方程序对已有 WorkflowAppRuntime、WorkflowRun 和 TriggerSource 的使用与控制；`Save Template`、`Save Application` 仍属于平台准备动作。

`net461` 和 `net472` 用于 .NET Framework 上位机程序，`netstandard2.1` 用于 .NET Core 3.0+，`net10.0` 用于现代运行时。仓库根目录 `global.json` 固定 .NET SDK 基线为 10.0，语言版本固定为 C# 14。`net461` 目标使用 NetMQ 4.0.1.10 和 System.Text.Json 6.0.10，其余目标使用当前较新的 NetMQ/System.Text.Json 组合。

## 构建

```powershell
dotnet build sdks/dotnet/src/Amvision.Workflows/Amvision.Workflows.csproj
dotnet run --project sdks/dotnet/tests/Amvision.Workflows.Tests/Amvision.Workflows.Tests.csproj
```

`sdks/dotnet/tests` 默认只运行 SDK 协议、HTTP URL/body/query、schema fixture 和 transport 逻辑测试。真实 backend-service smoke 测试通过环境变量启用：

```powershell
$env:AMVISION_DOTNET_SDK_SMOKE_BASE_URL = "http://127.0.0.1:8000"
$env:AMVISION_DOTNET_SDK_SMOKE_TOKEN = "amvision-default-user-token"
$env:AMVISION_DOTNET_SDK_SMOKE_PROJECT_ID = "project-1"
dotnet run --project sdks/dotnet/tests/Amvision.Workflows.Tests/Amvision.Workflows.Tests.csproj
```

## 真实 backend-service 调试

06/07 的 ZeroMQ 调试应使用 `docs/examples/workflows/*_zeromq.*.json` 中的双入口 workflow app。原始 04/05 JSON 仍保留给 HTTP base64 invoke 调试。

服务侧准备顺序：保存 06/07 的 template 和 application，创建并启动 WorkflowAppRuntime，按 `docs/api/examples/workflows/06-detection-deployment-infer-opencv-health-zeromq-image-ref/trigger-source.create.request.json` 或 `docs/api/examples/workflows/07-opencv-process-save-image-zeromq-image-ref/trigger-source.create.request.json` 创建 TriggerSource，调用 enable，并确认 health 中 `adapter_running=true`。如果 06 的 template 已升级到返回 `detections + annotated_image + health`，需要重新执行 Save Template、Save Application，并重新创建或重建对应的 WorkflowAppRuntime；旧 runtime 继续运行时，返回结果仍会停留在旧图接口模型。

创建 ZeroMQ TriggerSource 前可通过 HTTP client 读取当前后端实际配置，选择与 `config/backend-service.json` 一致的 LocalBufferBroker pool：

```csharp
using var workflowClient = new AmvisionWorkflowClient(new AmvisionWorkflowClientOptions
{
    BaseApiUrl = "http://127.0.0.1:8000",
    AccessToken = "amvision-default-user-token"
});

var systemConfig = await workflowClient.GetSystemConfigResponseAsync();
var broker = systemConfig.LocalBufferBroker;
var poolName = broker?.DefaultPoolName ?? "image-1080p";
```

创建 TriggerSource 时把 `poolName` 写入 `WorkflowTriggerSourceCreateRequest.TransportConfig["pool_name"]`。SDK 不维护独立默认 pool 列表，现场如果新增 4K 或相机专用 pool，应以 `/api/v1/system/config` 返回为准。

上面这组 `Save Template`、`Save Application`、`Create TriggerSource`、`Create WorkflowAppRuntime` 仍然属于项目管理 API 或前端准备动作，不属于 SDK 对外提供的能力范围。

常见管理 API 错误：

- `trigger_source_id 已存在`：`POST /api/v1/workflows/trigger-sources` 是创建接口，不会覆盖已有资源。应先调用 `GET /api/v1/workflows/trigger-sources/{trigger_source_id}` 或 `.../health` 检查现有 TriggerSource 是否可直接复用。
- 如果现有 TriggerSource 已经绑定到正确的 `workflow_runtime_id`，直接对这个 runtime 执行 start，再调用 enable 即可，不需要重复 create TriggerSource。
- 如果因为重新创建 WorkflowAppRuntime 导致 `workflow_runtime_id` 已变化，先调用 disable，再调用 `DELETE /api/v1/workflows/trigger-sources/{trigger_source_id}` 删除旧 TriggerSource，然后重新 create；也可以直接换一个新的 `trigger_source_id`。
- `启用 TriggerSource 前必须先启动绑定的 WorkflowAppRuntime`：先调用 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/start`，再调用 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health` 确认 runtime 已进入 running，最后再调用 `POST /api/v1/workflows/trigger-sources/{trigger_source_id}/enable`。

`apps/Amvision.Workflows.Console` 提供 `net461;net472;net10.0` console 官方参考实现，面向前端已经创建好的 WorkflowAppRuntime 和 TriggerSource，按方法封装 list/get/start/stop/restart/health/instances、sync invoke、async run、run/event 查询，以及 TriggerSource/ZeroMQ 调用。真实联调也可以继续使用 SDK 测试工程的 smoke 测试，或按下面的最小调用代码嵌入现场上位机、MES、采集程序和调试工具。

## 最小调用

```csharp
using Amvision.Workflows;

using var client = new AmvisionTriggerClient(new AmvisionTriggerClientOptions
{
    Endpoint = "tcp://127.0.0.1:5555",
    TriggerSourceId = "zeromq-trigger-source-06",
    DefaultInputBinding = "request_image_ref",
    Timeout = TimeSpan.FromSeconds(5)
});

var request = new ImageTriggerRequest
{
    ImageBytes = File.ReadAllBytes("sample.jpg"),
    MediaType = "image/jpeg",
    Metadata =
    {
        ["line_id"] = "line-a",
        ["station_id"] = "station-1"
    }
};

request
    .WithDeploymentInstance("deployment-instance-1")
    .WithIdempotencyKey("line-a-20260702-0001");

var result = client.InvokeImage(request);

Console.WriteLine($"{result.State}: {result.WorkflowRunId}");
```

也可以使用 helper 明确表达输入来源，但最终都会转成 ZeroMQ multipart 第二帧 bytes：

```csharp
var fromFile = ImageTriggerRequest.FromFile("sample.jpg");
var fromBase64 = ImageTriggerRequest.FromBase64("data:image/png;base64,...");
var fromCameraBytes = ImageTriggerRequest.FromBytes(cameraFrameJpegBytes, "image/jpeg");
```

这里的 `DefaultInputBinding = "request_image_ref"` 表示 ZeroMQ envelope 第一层事件 payload 中保存 LocalBuffer 图片引用的字段名。06/07 的 TriggerSource 会通过 `input_binding_mapping.request_image_ref.source = payload.request_image_ref` 把这份图片输入映射到 workflow app 的 `request_image_ref` binding。`request_image_base64` 入口只用于 HTTP/JSON 调试，不作为 ZeroMQ TriggerSource 的默认图片输入。

## HTTP app-result

同步调用如果只需要 workflow app 公开结果，使用 app-result 方法，SDK 会自动带上 `response_mode=app-result`：

```csharp
using var workflowClient = new AmvisionWorkflowClient(new AmvisionWorkflowClientOptions
{
    BaseApiUrl = "http://127.0.0.1:8000",
    AccessToken = "amvision-default-user-token"
});

var invokeRequest = new WorkflowRuntimeInvokeRequest();
invokeRequest.InputBindings["request_image_base64"] = new Dictionary<string, object?>
{
    ["image_base64"] = "...",
    ["media_type"] = "image/jpeg"
};

var appResult = await workflowClient.InvokeWorkflowAppRuntimeAppResultResponseAsync(
    "workflow-runtime-xxx",
    invokeRequest);

Console.WriteLine(appResult.BodyJson.ToString());
```

如果业务侧已有固定 DTO，可直接使用 `InvokeWorkflowAppRuntimeAppResultAsync<T>` 或 `GetWorkflowRunAppResultAsync<T>`。

## HTTP multipart upload

后端当前 multipart runtime 接口用于 `dataset-package.v1` 这类文件输入绑定，不作为现场大图高速推理主路径。大图本机高速输入仍优先使用 ZeroMQ 第二帧写入 LocalBufferBroker。

```csharp
var uploadRequest = new WorkflowRuntimeMultipartInvokeRequest
{
    TimeoutSeconds = 30
};
uploadRequest.InputBindings["job_id"] = "job-1";
uploadRequest.ExecutionMetadata["source"] = "dotnet-sdk";
uploadRequest.Files.Add(WorkflowRuntimeMultipartFile.FromFile(
    "dataset_package",
    "dataset.zip",
    "application/zip"));

var run = await workflowClient.CreateWorkflowRunUploadResponseAsync(
    "workflow-runtime-xxx",
    uploadRequest);
```

同步上传入口使用 `InvokeWorkflowAppRuntimeUploadAsync`、`InvokeWorkflowAppRuntimeUploadResponseAsync` 或 `InvokeWorkflowAppRuntimeUploadAppResultResponseAsync`。

## ZeroMQ 纯事件触发

ZeroMQ TriggerSource 的第二帧图片 bytes 是高性能图片输入，不是所有 TriggerSource 的硬性要求。PLC、传感器、空参数 HTTP 桥接等场景可以只发 envelope，让 workflow app 按图内节点读取磁盘、相机或执行无输入动作。

```csharp
using var triggerClient = new AmvisionTriggerClient(new AmvisionTriggerClientOptions
{
    Endpoint = "tcp://127.0.0.1:5555",
    TriggerSourceId = "zeromq-trigger-source-event",
    Timeout = TimeSpan.FromSeconds(5)
});

var eventResult = triggerClient.InvokeEvent(
    TriggerEventRequest.Empty()
        .WithPayload("plc_value", 1)
        .WithMetadata("line_id", "line-a")
        .WithIdempotencyKey("line-a-plc-0001"));

Console.WriteLine($"{eventResult.State}: {eventResult.WorkflowRunId}");
```
