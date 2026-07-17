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

JSON 统一使用 Newtonsoft.Json；ZeroMQ 统一使用 NetMQ。SDK 项目文件只保留上述直接引用，不使用 `PackageReference`，也不通过 NuGet 恢复依赖。

当前 `NetMQ.dll` 版本在 .NET Framework 4.7.2 下还会带出少量运行时传递依赖。使用 ZeroMQ Trigger 调用时，发布目录需要随 `Amvar.Vision.dll` 一起放置 `libs/net472` 中的 DLL。仅使用 HTTP workflow/model/runtime API 时，第三方项目可以只携带 `Amvar.Vision.dll`、`Newtonsoft.Json.dll` 和 .NET Framework 自带程序集；如现场项目已有同名依赖，应以最终程序输出目录中的同一版本为准，避免同目录放置多份不同版本 DLL。

## 功能边界

`Amvar.Vision` SDK 负责封装 Amvar Vision 后端的外部调用能力：

- Workflow App Runtime 查询、启动、停止、重启、健康检查
- Workflow App Runtime 同步 invoke、异步 run、run/event 查询
- Model Deployment runtime 查询、启动、停止、预热、重置和推理调用
- TriggerSource 查询、启用、禁用、健康检查
- ZeroMQ TriggerSource 图片、BGR24、Base64、事件触发调用
- 本地配置文件加载和按 key 调用已配置 runtime / deployment / trigger

Console 示例不是 SDK 边界的一部分，不能把核心封装写到 console 项目中。

## Config 自动加载

SDK 默认会自动查找 `Config/config*.json`，并把所有 runtime、TriggerSource、ModelDeployment 配置按 `name` 建立索引。生成的 `name` 优先保留前端用户维护的应用、触发源和部署实例展示名称。

`AMVisionOperationRunner` 高层 API 明确区分 name 与 id：原有不带 `ById` 后缀的方法只接收配置中的可读 `name`，对应的 `ById` 方法分别接收 `workflow_runtime_id`、`trigger_source_id` 或 `deployment_instance_id`。SDK 不在同一个字符串参数中猜测 name 或 id；模型 deployment 的管理类 `ById` 方法还要求显式传入 `sync` 或 `async` runtime mode，推理方法则由同步或异步方法语义确定 mode。

生成配置和 .NET SDK 的 HTTP 默认超时统一为 300 秒。Workflow invoke 和 ZeroMQ reply 的业务超时仍由各自配置字段独立控制，不与 HTTP 连接超时混用。

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
        using (var client = AMVisionClient.CreateFromConfig())
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

两个调用文件都按“Model deployment → Workflow App Runtime → TriggerSource”排列，具体请求默认保持注释，避免启动 Console 时意外启动、停止或触发现场资源。取消需要的调用行注释即可直接调试。

## 后续框架版本

`net461` 和 `.NET 10` 可以继续按单项目方式补齐，但不能重新引入多目标项目作为 VS2019 默认入口。每个框架版本都应是独立项目，第三方按自身运行环境选择对应项目或编译产物。
