# Third-party notices for VS2019 local DLLs

本目录只用于 VS2019 `.NET Framework` 单框架项目的离线构建。DLL 来自 NuGet package cache，版本固定如下。

| Package | Version | Files | License metadata |
| --- | --- | --- | --- |
| NetMQ | 4.0.1.10 | `NetMQ.dll` | Upstream `licenseUrl`: `https://github.com/zeromq/netmq/blob/master/COPYING.LESSER` |
| AsyncIO | 0.1.69 | `AsyncIO.dll` | NuGet metadata points to `https://github.com/somdoron/AsyncIO`; package nuspec does not declare SPDX license |
| NaCl.Net | 0.1.13 | `NaCl.dll` | `MPL-2.0` |
| System.Text.Json | 6.0.10 | `System.Text.Json.dll` | `MIT` |
| Microsoft.Bcl.AsyncInterfaces | 6.0.0 | `Microsoft.Bcl.AsyncInterfaces.dll` | `MIT` |
| System.Text.Encodings.Web | 6.0.0 | `System.Text.Encodings.Web.dll` | `MIT` |
| System.Buffers | 4.5.1 | `System.Buffers.dll` | `MIT` |
| System.Memory | 4.5.4 | `System.Memory.dll` | `MIT` |
| System.Numerics.Vectors | 4.5.0 | `System.Numerics.Vectors.dll` | `MIT` |
| System.Runtime.CompilerServices.Unsafe | 6.0.0 | `System.Runtime.CompilerServices.Unsafe.dll` | `MIT` |
| System.Threading.Tasks.Extensions | 4.5.4 | `System.Threading.Tasks.Extensions.dll` | `MIT` |
| System.ValueTuple | 4.5.0 | `System.ValueTuple.dll` | `MIT` |

发布 SDK 包时应保留本文件。若后续替换 ZeroMQ transport 或 JSON runtime，应同步更新 DLL、项目引用和本文件。
