# Amvar Vision .NET SDK

`sdks/dotnet` 当前默认面向现场上位机和工业软件集成，优先支持 `VS2019 + .NET Framework 4.7.2`。SDK 代码集中在 `src/Amvar.Vision`，第三方项目只需要引用这个库和同目录依赖 DLL。

## 当前默认项目

- Solution：`sdks/dotnet/amvar-vision-vs2019-net472.sln`
- SDK 项目：`sdks/dotnet/src/Amvar.Vision/Amvar.Vision.vs2019.net472.csproj`
- Console 示例项目：`sdks/dotnet/apps/AMVision.Console/AMVision.Console.vs2019.net472.csproj`
- Target framework：`.NET Framework 4.7.2`
- Language version：`C# 8.0`
- Assembly：`Amvar.Vision.dll`

`apps` 和 `tests` 目录不承载 SDK 核心逻辑。Console 示例只保留调用样例和调试入口；HTTP、ZeroMQ、配置加载、Workflow runtime、Model deployment 等封装全部放在 `src/Amvar.Vision`。

## 依赖策略

VS2019 项目不依赖 NuGet 还原，不要求第三方使用者联网安装包。项目直接引用 `libs/net472` 下的 DLL：

- `Newtonsoft.Json.dll`
- `NetMQ.dll`
- `AsyncIO.dll`
- `NaCl.dll`
- `System.Runtime.CompilerServices.Unsafe.dll`（NuGet 6.1.2，AssemblyVersion 6.0.3.0）
- `System.Memory.dll`（NuGet 4.6.3，AssemblyVersion 4.0.5.0）
- `System.Buffers.dll`（NuGet 4.6.1，AssemblyVersion 4.0.5.0）
- `System.Numerics.Vectors.dll`（NuGet 4.6.1，AssemblyVersion 4.1.6.0）

JSON 统一使用 Newtonsoft.Json；ZeroMQ 统一使用 NetMQ。SDK 项目文件只保留上述直接引用，不使用 `PackageReference`，也不通过 NuGet 恢复依赖。

当前 `NetMQ.dll` 在 .NET Framework 4.7.2 下通过 `NaCl.Net`、`System.Collections.Immutable` 等组件依赖 `System.Memory`、`System.Buffers`、`System.Numerics.Vectors` 和 `System.Runtime.CompilerServices.Unsafe`。这些 DLL 必须使用上表列出的 AssemblyVersion。使用 ZeroMQ Trigger 调用时，发布目录需要随 `Amvar.Vision.dll` 一起放置 `libs/net472` 中的全部 DLL。仅使用 HTTP workflow/model/runtime API 时，第三方项目可以只携带 `Amvar.Vision.dll`、`Newtonsoft.Json.dll` 和 .NET Framework 自带程序集；如现场项目已有同名依赖，应以最终程序输出目录中的同一版本为准，避免同目录放置多份不同版本 DLL。

## 功能边界

`Amvar.Vision` SDK 负责封装 Amvar Vision 后端的外部调用能力：

- Workflow App Runtime 查询、启动、停止、重启、健康检查、revision 读取和停机版本选择
- Workflow App Runtime 同步 invoke、异步 run、run/event 查询
- Workflow App Contract v1 读取、请求 binding 校验和多类型 multipart 请求构建
- Model Deployment runtime 查询、启动、停止、预热、重置和推理调用
- TriggerSource 查询、启用、禁用、健康检查
- ZeroMQ TriggerSource 图片、BGR24、Base64、事件触发调用
- local-shared-memory 图片与无图片 event-only v1 调用
- 本地配置文件加载和按 key 调用已配置 runtime / deployment / trigger

Console 示例不是 SDK 边界的一部分，不能把核心封装写到 console 项目中。

新建 Runtime 时，`WorkflowAppRuntimeCreateRequest.WorkflowAppVersionId` 与兼容字段 `ApplicationId` 必须且只能设置一个。新控制面代码使用准确发布版本。`AMVisionClient` 提供 revision 列表、详情和 `SelectWorkflowAppRuntimeVersionResponseAsync`；设备侧常驻调用仍只保存稳定 Runtime/Trigger id，不指定 `latest` 或单次请求 revision。兼容契约切换后不需要重新下载配置包。

版本管理使用显式状态 CAS：`ArchiveWorkflowAppVersionResponseAsync` 的 `ExpectedState` 必须为 `published`，`RestoreWorkflowAppVersionResponseAsync` 必须为 `archived`。归档版本不再作为新 Runtime 或停机切版候选，但已有 Runtime revision 仍保持不可变和可追溯。

`WorkflowRunResponse` 会返回本次实际执行的 revision、Workflow App version、Runtime generation、snapshot fingerprint 和 worker instance id。这些字段用于运行结果溯源；不能用 Runtime 当前状态覆盖某条历史 Run 的来源。

## Config 自动加载

SDK 默认会自动查找 `Config/config*.json`，并把所有 runtime、TriggerSource、ModelDeployment 配置按 `name` 建立索引。生成的 `name` 优先保留前端用户维护的应用、触发源和部署实例展示名称。

## Workflow 输入调用边界

HTTP Runtime 与高性能 Trigger 是两套独立调用面：

- HTTP Runtime 支持 `request_image_ref`、`request_image_base64`、`request_json`、`request_text`、`request_file` 和 `request_files`；JSON 与 multipart 可以组合多个 binding。
- ZeroMQ 和 local-shared-memory Trigger 只支持 `request_image_ref`、`request_json` 和 `request_text`。图片通过 binary frame 或 LocalBuffer 生成 `image-ref.v1`，JSON/文本位于小型事件 payload。
- Trigger 不支持 `request_image_base64`、`request_file` 或 `request_files`，不增加文件 staging、普通文件图片帧、普通文件 LocalBuffer 或自动 HTTP fallback。

低层 `ImageTriggerRequest.Payload`、`SharedMemoryTriggerRequest.Payload` 和 event request 可以携带 JSON/文本。常用高层 API 通过 `CreateWorkflowTriggerInputsBuilder(triggerSourceName)` 或 `CreateWorkflowTriggerInputsBuilderById(triggerSourceId)` 创建 `WorkflowTriggerInputsBuilder`，只提供 `AddJson`、`AddText` 和 `Build`；生成的 inputs 可传给带 `WithInputs` / `WithInputsById` 后缀的 ZeroMQ/local-shared-memory 图片或 event-only 方法。

`InvokeZeroMqImageBase64` 和 `InvokeSharedMemoryImageBase64` 只表示调用方以 Base64 提供图片来源。SDK 解码后仍通过高性能图片通道绑定 `request_image_ref`，不会向 `request_image_base64` 发送 Base64。需要 Base64 binding、普通文件或多文件时使用 HTTP Runtime。

下载包同时包含 `Config/sdk-bootstrap.json`。默认 `configuration_sync.enabled=false`，继续使用手工放置的 `config*.json`。需要由 HTTP 检查最新配置时，配置 backend 地址、Project 配置路径和专用 token，启用开关，并使用 `CreateFromConfigAsync` 或 `CreateFromConfigDirectoryAsync`。SDK发送 ETag 条件请求，完整校验 revision、manifest、逐文件 SHA-256和配置语义后，把不可变快照发布到 `Config/.managed/<revision>/`；下载或校验失败时可按 `use_last_known_good` 使用最近有效快照。同步工厂只在 client 创建时执行，不在运行中替换已创建 client。

local-shared-memory 配置只保存同机受信 `data/buffers` 根目录、TriggerSource id/generation、默认 binding 和 timeout。SDK从 `local-buffer/state.mmap` header自动发现图片共享内存容量、descriptor/reader guard几何、broker epoch和layout fingerprint，因此后端调整容量或guard数量不要求修改SDK配置。该Trigger只适用于同一台机器；远程SDK即使能访问配置HTTP接口，也必须选择HTTP或ZeroMQ调用链路。

无图片的 JSON/文本事件使用 `SharedMemoryTriggerClient.InvokeEvent` 或 `AMVisionOperationRunner.InvokeSharedMemoryEvent`。该方法发布 `amvision.workflow-trigger-event-request.v1`，直接进入 mailbox REQUEST，不执行图片请求的 PREPARE、不申请 LocalBuffer、不创建假图片 lease。`Payload` 仍按 TriggerSource 的 `input_binding_mapping` 映射到 Workflow 公开 binding，最终由 Runtime 固定的 App Contract 权威校验；同步结果和 ACK 生命周期与图片调用共用 response v1。

`AMVisionOperationRunner` 高层 API 明确区分 name 与 id：原有不带 `ById` 后缀的方法只接收配置中的可读 `name`，对应的 `ById` 方法分别接收 `workflow_runtime_id`、`trigger_source_id` 或 `deployment_instance_id`。SDK 不在同一个字符串参数中猜测 name 或 id；模型 deployment 的管理类 `ById` 方法还要求显式传入 `sync` 或 `async` runtime mode，推理方法则由同步或异步方法语义确定 mode。

生成配置和 .NET SDK 的 HTTP 默认超时统一为 300 秒。Workflow invoke 和 ZeroMQ reply 的业务超时仍由各自配置字段独立控制，不与 HTTP 连接超时混用。

生成配置会在 `runtime.public_contract` 中携带该 Runtime revision 固定的 App Contract v1。`WorkflowRequestBuilder` 可以用这份契约对 binding、payload type、MIME、单文件大小、文件数量和必填输入进行快速校验；服务端仍执行完整 JSON Schema、ObjectStore identity 和 Project 范围校验。Runtime 没有契约快照时该字段为 `null`，SDK 不使用当前应用草稿补齐。

HTTP Builder 已提供 `AddImageBase64`、`AddImageReference`、`AddFileReference`、`AddFileReferences`、`AddImage`、`AddFile`、`AddFiles`、`BuildJson` 和 `BuildMultipart`。Runner 可按 name 使用 `CreateWorkflowRequestBuilder(runtimeName)`，也可按 id 使用 `CreateWorkflowRequestBuilderById(runtimeId)`；构建结果可对称传给同步 `InvokeRuntimeAppResult*Async` 或异步 `RunRuntime*Async`。`BuildJson` 拒绝上传 stream，`BuildMultipart` 通过 `input_bindings_json` 传递非文件输入并流式发送文件；不会自动选择 transport，也不会把 HTTP 文件能力塞入 Trigger API。

HTTP multipart 调用示例：

```csharp
var image = WorkflowUploadFile.FromFile(@".\images\tray.jpg", "image/jpeg");
var singleFile = WorkflowUploadFile.FromFile(@".\recipes\limits.json", "application/json");
var request = new WorkflowRequestBuilder(runtime.PublicContract)
    .AddJson("request_json", new { recipe = "3570", station = 2 })
    .AddText("request_text", "lot-20260830")
    .AddImage(
        "request_image_ref",
        image)
    .AddFile(
        "request_file",
        singleFile)
    .AddFiles("request_files", new[]
    {
        WorkflowUploadFile.FromFile(@".\files\a.txt", "text/plain"),
        WorkflowUploadFile.FromFile(@".\files\b.txt", "text/plain")
    })
    .WithTimeoutSeconds(30)
    .BuildMultipart();

var result = await client.InvokeWorkflowAppRuntimeUploadAppResultResponseAsync(
    runtime.WorkflowRuntimeId,
    request).ConfigureAwait(false);
```

`FromFile` 在 HTTP 发送阶段才打开文件并由 `StreamContent` 分块读取，不预先执行 `File.ReadAllBytes`。已有流使用 `FromStream`；需要重建请求时使用 `FromStreamFactory`，每次返回新的可读流。请求及 multipart content 释放时会关闭本次发送打开的流。Builder 不实现重试、排队或同步调用并发等待策略。

配置加载阶段会完成以下稳定性校验：

- name 使用忽略大小写的唯一索引；id 使用区分大小写的精确索引
- `deployment_instance_id` 与 `runtime_mode` 组成模型 deployment 的 id 复合索引
- 重复 runtime id、TriggerSource id 或模型复合 id 会在启动时直接报错
- 一个 Runner 加载的所有配置必须使用相同的 HTTP 地址、token 和 HTTP 超时；`project_id` 仍按每个资源独立保存

`AMVisionOperationRunner` 适合长期复用：内部只创建一个 HTTP client，并按 TriggerSource 缓存 ZeroMQ client；释放 Runner 时会释放其持有的 socket 和 HTTP 资源。Console 和现场常驻程序应通过 `runner.CallAsync(...)` 或 `runner.Call(...)` 执行具体操作。返回的 `AMVisionCallResult<T>` 不替调用方判断业务结果：`Data` 保留后端正常数据，`HttpResponse` 保留后端非 2xx 的原始状态码、正文和 JSON，`Exception` 保留没有后端响应时的配置、超时、网络或协议异常。调用方根据三个属性自行决定后续处理，单次错误不会中断整个程序。

完整的调用清单分别见 `apps/AMVision.Console/KeyNameSdkCalls.cs` 和 `apps/AMVision.Console/ResourceIdSdkCalls.cs`。

默认查找顺序：

- 程序输出目录下的 `Config`
- 当前工作目录下的 `Config`
- 程序输出目录逐级父目录下的 `Config`

示例：

```csharp
using System;
using System.Threading.Tasks;
using Amvar.Vision;

public static class Example
{
public static async Task Main()
    {
        using (var client = await AMVisionClient.CreateFromConfigAsync()
            .ConfigureAwait(false))
        {
            var runtimeResult = await client.InvokeConfiguredWorkflowRuntimeByNameAsync(
                "托盘分拣空盘检测应用").ConfigureAwait(false);

            var sameRuntimeResult = await client.InvokeConfiguredWorkflowRuntimeByIdAsync(
                "workflow-runtime-c57cd5e882f641ceb34d188cf19d2ab9").ConfigureAwait(false);

            var modelResult = await client.InvokeConfiguredModelDeploymentWithImageFileByNameAsync(
                "yolo11-s-20260713012828 model-build-2cac15bfc11d",
                @".\images\slot.jpg").ConfigureAwait(false);

            var triggerResult = client.InvokeConfiguredZeroMqImageFileById(
                "zeromq-workflow-runtime-c57cd5e882f641ceb34d188cf19d2ab9",
                @".\images\tray.jpg");

            Console.WriteLine(runtimeResult.State);
            Console.WriteLine(modelResult.RequestId);
            Console.WriteLine(triggerResult.State);
        }
    }
}
```

## VS2019 使用方式

1. 打开 `sdks/dotnet/amvar-vision-vs2019-net472.sln`。
2. 编译 `Amvar.Vision.vs2019.net472`。
3. 第三方项目引用输出的 `Amvar.Vision.dll`。
4. 将 `Config/config*.json` 放到第三方程序输出目录的 `Config` 子目录。
5. 将 `libs/net472` 中需要的 DLL 与第三方程序放在同一输出目录。

版本契约门禁位于 `tests/Amvar.Vision.ContractTests`，不使用 NuGet 包。它会真实编译
`net472` SDK，并验证 Runtime 创建来源互斥、停机选择版本请求、版本 archive/restore
状态 CAS、Runtime/revision/run 版本溯源字段以及 HTTP 409 冲突详情：

```powershell
dotnet msbuild tests/Amvar.Vision.ContractTests/Amvar.Vision.ContractTests.vs2019.net472.csproj /t:Rebuild /p:Configuration=Release
tests/Amvar.Vision.ContractTests/bin/Release/net472/Amvar.Vision.ContractTests.exe
```

示例代码：

```csharp
using System;
using System.Threading.Tasks;
using Amvar.Vision;

public static class Example
{
    public static async Task Main()
    {
        var options = new AMVisionClientOptions
        {
            BaseApiUrl = "http://127.0.0.1:5600",
            AccessToken = "amvision-default-user-token"
        };

        using (var client = new AMVisionClient(options))
        {
            var config = await client.GetSystemConfigResponseAsync().ConfigureAwait(false);
            Console.WriteLine(config.FormatId);
        }
    }
}
```

Console 示例项目采用代码内手动调试方式，不要求记忆命令行参数：

- `KeyNameSdkCalls.cs`：默认入口，修改用户可读的 deployment、应用和 TriggerSource key name
- `ResourceIdSdkCalls.cs`：稳定 id 兜底入口，修改 `deployment_instance_id`、`workflow_runtime_id` 和 `trigger_source_id`
- `SdkCallInputs.cs`：两种入口共用的图片、run id、task id 等测试输入
- `Program.cs`：只负责 Runner 生命周期；注释/启用两行 `RunAsync` 即可切换 name 或 id 语义

两个调用文件都按“Model deployment → Workflow App Runtime → TriggerSource”分类，所有具体调用默认逐行注释。开发调试时直接取消需要调用行的注释，不增加执行开关或额外调度层。HTTP Runtime 示例完整覆盖 image-ref、image-base64、JSON、text、file 和 files，Trigger 示例只覆盖其明确支持的 image-ref、JSON 和 text。

## 后续框架版本

`net461` 和 `.NET 10` 可以继续按单项目方式补齐，但不能重新引入多目标项目作为 VS2019 默认入口。每个框架版本都应是独立项目，第三方按自身运行环境选择对应项目或编译产物。
