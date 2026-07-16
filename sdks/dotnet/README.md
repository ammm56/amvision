# Amvar Vision .NET SDK

`sdks/dotnet` 当前默认面向现场上位机和工业软件集成，优先支持 `VS2019 + .NET Framework 4.7.2`。SDK 代码集中在 `src/Amvar.Vision`，第三方项目只需要引用这个库和同目录依赖 DLL。

## 当前默认项目

- Solution：`sdks/dotnet/amvar-vision-vs2019-net472.sln`
- SDK 项目：`sdks/dotnet/src/Amvar.Vision/Amvar.Vision.vs2019.net472.csproj`
- Target framework：`.NET Framework 4.7.2`
- Language version：`C# 8.0`
- Assembly：`Amvar.Vision.dll`

`apps` 和 `tests` 目录不承载 SDK 核心逻辑。后续如果恢复 console 示例，也只放调用样例和调试入口；HTTP、ZeroMQ、配置加载、Workflow runtime、Model deployment 等封装全部放在 `src/Amvar.Vision`。

## 依赖策略

VS2019 项目不依赖 NuGet 还原，不要求第三方使用者联网安装包。项目直接引用 `libs/net472` 下的 DLL：

- `Newtonsoft.Json.dll`
- `NetMQ.dll`
- `AsyncIO.dll`
- `NaCl.dll`

JSON 统一使用 Newtonsoft.Json；ZeroMQ 统一使用 NetMQ。SDK 项目文件只保留上述直接引用，不使用 `PackageReference`，也不通过 NuGet 恢复依赖。

当前 `NetMQ.dll` 版本在 .NET Framework 4.7.2 下还会带出少量运行时传递依赖。使用 ZeroMQ Trigger 调用时，发布目录需要随 `Amvar.Vision.dll` 一起放置 `libs/net472` 中的 DLL。仅使用 HTTP workflow/model/runtime API 时，第三方项目可以只携带 `Amvar.Vision.dll`、`Newtonsoft.Json.dll` 和 .NET Framework 自带程序集；如现场项目已有同名依赖，应以最终程序输出目录中的同一版本为准，避免同目录放置多份不同版本 DLL。

## 功能边界

`Amvar.Vision` SDK 负责封装 AMVISION 后端的外部调用能力：

- Workflow App Runtime 查询、启动、停止、重启、健康检查
- Workflow App Runtime 同步 invoke、异步 run、run/event 查询
- Model Deployment runtime 查询、启动、停止、预热、重置和推理调用
- TriggerSource 查询、启用、禁用、健康检查
- ZeroMQ TriggerSource 图片、BGR24、Base64、事件触发调用
- 本地配置文件加载和按 key 调用已配置 runtime / deployment / trigger

Console 示例不是 SDK 边界的一部分，不能把核心封装写到 console 项目中。

## VS2019 使用方式

1. 打开 `sdks/dotnet/amvar-vision-vs2019-net472.sln`。
2. 编译 `Amvar.Vision.vs2019.net472`。
3. 第三方项目引用输出的 `Amvar.Vision.dll`。
4. 将 `libs/net472` 中需要的 DLL 与第三方程序放在同一输出目录。

示例代码：

```csharp
using System;
using System.Threading.Tasks;
using Amvar.Vision;

public static class Example
{
    public static async Task Main()
    {
        var options = new AmvisionWorkflowClientOptions
        {
            BaseUrl = new Uri("http://127.0.0.1:8000")
        };

        using (var client = new AmvisionWorkflowClient(options))
        {
            var config = await client.GetSystemConfigResponseAsync().ConfigureAwait(false);
            Console.WriteLine(config.FormatId);
        }
    }
}
```

## 后续框架版本

`net461` 和 `.NET 10` 可以继续按单项目方式补齐，但不能重新引入多目标项目作为 VS2019 默认入口。每个框架版本都应是独立项目，第三方按自身运行环境选择对应项目或编译产物。
