# Amvision.TriggerSources

C# / .NET SDK 用于设备上位机、MES、采集程序和调试工具通过 ZeroMQ TriggerSource 调用 backend-service。

## 当前实现

- SDK 项目：`src/Amvision.TriggerSources`
- 目标框架：`net461;net472;netstandard2.1;net10.0`
- ZeroMQ 依赖：NetMQ
- 支持单张图片 REQ/REP 调用
- 支持 TriggerResult 和 ZeroMQ error reply 解析
- 支持 Workflow 控制面 HTTP client：`start app runtime`、`stop app runtime`、`get app runtime health`、`invoke app runtime`、`get workflow run`、`enable trigger source`、`disable trigger source`、`get trigger source health`

SDK 只负责第三方程序对已有 WorkflowAppRuntime 和 TriggerSource 的使用与控制，不负责 `Save Template`、`Save Application`、`Create Runtime` 这类创建面动作。

`net461` 和 `net472` 用于 .NET Framework 上位机程序，`netstandard2.1` 用于 .NET Core 3.0+，`net10.0` 用于现代运行时。`net461` 目标使用 NetMQ 4.0.1.10 和 System.Text.Json 6.0.10，其余目标使用当前较新的 NetMQ/System.Text.Json 组合。

## 构建

```powershell
dotnet build sdks/dotnet/src/Amvision.TriggerSources/Amvision.TriggerSources.csproj
dotnet run --project sdks/dotnet/tests/Amvision.TriggerSources.Tests/Amvision.TriggerSources.Tests.csproj
```

`sdks/dotnet/tests` 继续只保留 SDK 协议和 transport 逻辑测试，不承载真实 backend-service 联调。

## WinForms 调试器

真实 TriggerSource 调试使用独立的 WinForms 项目：`sdks/dotnet/examples/TriggerSourceDebugWinForms`。

```powershell
dotnet run --project sdks/dotnet/examples/TriggerSourceDebugWinForms/TriggerSourceDebugWinForms.csproj
```

界面当前提供以下能力：

- `06 Workflow App` 和 `07 Workflow App` 两个页签按不同 workflow app 分开，便于分别调试 06 与 07 的本地链路；页面分开只是为了清晰，不代表协议能力不同
- 两个页签现在都保留同一组按钮：`start runtime`、`stop runtime`、`get runtime health`、`invoke app runtime (HTTP base64)`、`enable trigger source`、`disable trigger source`、`get trigger source health`、`invoke trigger source (ZeroMQ)`、`GET WorkflowRun`
- `06 Workflow App` 页签默认对应 `06-yolox-deployment-infer-opencv-health-zeromq-image-ref`：既可预览 ZeroMQ envelope、执行真实 TriggerSource 调用，也可通过 SDK 调用 HTTP runtime invoke；HTTP 请求会自动带上 `request_image_base64` 和 `deployment_request.deployment_instance_id`
- `07 Workflow App` 页签默认对应 `07-opencv-process-save-image-zeromq-image-ref`：既可通过 SDK 调用 HTTP runtime invoke，也可直接执行真实 ZeroMQ TriggerSource 调用；HTTP 默认使用 `request_image_base64`，TriggerSource 事件层默认使用 `request_image`
- `07 Workflow App` 页签仍保留 `Request Override JSON`，用于复现缺字段、坏 base64、坏图片 bytes 等参数错误
- 两个页签都会保留 Request JSON / Request Envelope、Invoke / Trigger Result、Runtime Health、TriggerSource Health、WorkflowRun 和响应图片摘要；当响应返回 inline-base64 图片时，也会显示预览和原始 `image_base64`

## 真实 backend-service 调试

06/07 的 ZeroMQ 调试应使用 `docs/examples/workflows/*_zeromq.*.json` 中的双入口 workflow app。原始 04/05 JSON 仍保留给 HTTP base64 invoke 调试。

服务侧准备顺序：保存 06/07 的 template 和 application，创建并启动 WorkflowAppRuntime，按 `docs/api/examples/workflows/06-yolox-deployment-infer-opencv-health-zeromq-image-ref/trigger-source.create.request.json` 或 `docs/api/examples/workflows/07-opencv-process-save-image-zeromq-image-ref/trigger-source.create.request.json` 创建 TriggerSource，调用 enable，并确认 health 中 `adapter_running=true`。如果 06 的 template 已升级到返回 `detections + annotated_image + health`，需要重新执行 Save Template、Save Application，并重新创建或重建对应的 WorkflowAppRuntime；旧 runtime 继续运行时，返回结果仍会停留在旧图合同。

上面这组 `Save Template`、`Save Application`、`Create TriggerSource`、`Create WorkflowAppRuntime` 仍然属于项目控制面或前端准备动作，不属于 SDK 对外提供的能力范围。

常见控制面错误：

- `trigger_source_id 已存在`：`POST /api/v1/workflows/trigger-sources` 是创建接口，不会覆盖已有资源。应先调用 `GET /api/v1/workflows/trigger-sources/{trigger_source_id}` 或 `.../health` 检查现有 TriggerSource 是否可直接复用。
- 如果现有 TriggerSource 已经绑定到正确的 `workflow_runtime_id`，直接对这个 runtime 执行 start，再调用 enable 即可，不需要重复 create TriggerSource。
- 如果因为重新创建 WorkflowAppRuntime 导致 `workflow_runtime_id` 已变化，先调用 disable，再调用 `DELETE /api/v1/workflows/trigger-sources/{trigger_source_id}` 删除旧 TriggerSource，然后重新 create；也可以直接换一个新的 `trigger_source_id`。
- `启用 TriggerSource 前必须先启动绑定的 WorkflowAppRuntime`：先调用 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/start`，再调用 `GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health` 确认 runtime 已进入 running，最后再调用 `POST /api/v1/workflows/trigger-sources/{trigger_source_id}/enable`。

07 OpenCV 保存图片示例：

```powershell
dotnet run --project sdks/dotnet/examples/ZeroMqImageInvoke/ZeroMqImageInvoke.csproj -- tcp://127.0.0.1:5556 zeromq-trigger-source-07 data/files/validation-inputs/image-1.jpg image/jpeg
```

06 YOLOX 推理示例需要传入已有 `deployment_instance_id`：

```powershell
dotnet run --project sdks/dotnet/examples/ZeroMqImageInvoke/ZeroMqImageInvoke.csproj -- tcp://127.0.0.1:5555 zeromq-trigger-source-06 data/files/validation-inputs/image-1.jpg image/jpeg <deployment_instance_id>
```

如果省略 `media_type`，示例程序会按文件扩展名自动猜测；这时第四个可选参数会被当作 `deployment_instance_id`：

```powershell
dotnet run --project sdks/dotnet/examples/ZeroMqImageInvoke/ZeroMqImageInvoke.csproj -- tcp://127.0.0.1:5555 zeromq-trigger-source-06 data/files/validation-inputs/image-1.jpg <deployment_instance_id>
```

如果当前工作目录就是仓库根目录，示例程序现在也会把单独的 `image-1.jpg` 自动解析到 `data/files/validation-inputs/image-1.jpg`。其他目录下运行时仍建议传完整相对路径或绝对路径。

如果返回 `error_code=invalid_request` 且 `details` 里出现 `{"binding_id":"deployment_request","source":"payload.deployment_request"}`，通常说明命令行参数错位了：程序把 `deployment_instance_id` 当成了 `media_type`，所以没有构造 `deployment_request`。

成功时示例会打印：

```text
state=succeeded
workflow_run_id=<workflow_run_id>
event_id=<event_id>
```

## 最小调用

```csharp
using Amvision.TriggerSources;

using var client = new AmvisionTriggerClient(new AmvisionTriggerClientOptions
{
    Endpoint = "tcp://127.0.0.1:5555",
    TriggerSourceId = "zeromq-trigger-source-06",
    DefaultInputBinding = "request_image",
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

request.Payload["deployment_request"] = new Dictionary<string, object?>
{
    ["value"] = new Dictionary<string, object?>
    {
        ["deployment_instance_id"] = "deployment-instance-1"
    }
};

var result = client.InvokeImage(request);

Console.WriteLine($"{result.State}: {result.WorkflowRunId}");
```

这里的 `DefaultInputBinding = "request_image"` 表示 ZeroMQ envelope 第一层事件 payload 中保存图片引用的字段名。06/07 的 TriggerSource 会再通过 `input_binding_mapping.request_image_ref.source = payload.request_image` 把这份图片输入映射到 workflow app 的 `request_image_ref` binding。