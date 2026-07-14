# VS2019 local DLL references

本目录保存 VS2019 `.NET Framework` 单框架项目使用的本地 DLL。目标是让第三方上位机、MES、工控机项目在离线环境中也能直接打开、编译和运行 SDK/Console 参考实现，不依赖 NuGet restore。

## 使用边界

- `sdks/dotnet/src/Amvision.Workflows/Amvision.Workflows.vs2019.net461.csproj`
- `sdks/dotnet/src/Amvision.Workflows/Amvision.Workflows.vs2019.net472.csproj`
- `sdks/dotnet/apps/Amvision.Workflows.Console/Amvision.Workflows.Console.vs2019.net461.csproj`
- `sdks/dotnet/apps/Amvision.Workflows.Console/Amvision.Workflows.Console.vs2019.net472.csproj`

以上项目在各自 `.csproj` 中直接通过 `Reference` + `HintPath` 引用本目录 DLL。这样第三方在 VS2019 中打开项目时可以直接看到磁盘 DLL 来源，后续新增 DLL 也只需要修改对应项目文件。现代多目标框架项目仍使用 NuGet `PackageReference`。

## 为什么移除 Microsoft.NETFramework.ReferenceAssemblies

`Microsoft.NETFramework.ReferenceAssemblies.net461/net472` 是编译期 targeting pack，不是运行时依赖。VS2019 环境下更清晰的交付边界是目标机器安装对应的 `.NET Framework Developer Pack / Targeting Pack`，项目本身不再通过 NuGet 拉取这些引用程序集。

如果 VS2019 打开项目时提示找不到 .NET Framework 4.6.1 或 4.7.2 targeting pack，应在开发机安装对应 Developer Pack。

## 为什么暂时保留 System.Text.Json

当前 SDK 的公开请求/响应模型和 helper 已经使用 `System.Text.Json.JsonElement`、`JsonSerializer` 和 `JsonDocument`。直接切换到 `Newtonsoft.Json` 会改变公开 API 类型和调用习惯，属于破坏性重构。

VS2019 单框架项目先通过本地 DLL 固定 `System.Text.Json` 6.0.10 及其依赖，解决离线打开和编译问题。后续如果要提供 `Newtonsoft.Json` 版本，应作为独立兼容层或新一组项目评估，不应在现有 API 上悄悄替换。

## DLL 版本

- NetMQ 4.0.1.10
- AsyncIO 0.1.69
- NaCl.Net 0.1.13
- System.Text.Json 6.0.10
- Microsoft.Bcl.AsyncInterfaces 6.0.0
- System.Text.Encodings.Web 6.0.0
- System.Buffers 4.5.1
- System.Memory 4.5.4
- System.Numerics.Vectors 4.5.0
- System.Runtime.CompilerServices.Unsafe 6.0.0
- System.Threading.Tasks.Extensions 4.5.4
- System.ValueTuple 4.5.0

第三方 DLL 来源和 license 信息见 `THIRD_PARTY_NOTICES.md`。
