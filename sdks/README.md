# Amvision SDK

本目录用于存放外部调用方 SDK。SDK 面向设备上位机、MES、采集程序、现场桥接进程和调试脚本，不属于 backend-service 内部实现。

## 边界

- SDK 通过公开 REST API、WebSocket 或 ZeroMQ TriggerSource 协议访问 backend-service。
- SDK 不直接访问数据库、LocalBufferBroker、workflow worker、deployment worker 或对象存储。
- SDK 不直接导入 `backend/`、`frontend/`、`custom_nodes/` 的运行时代码。
- 跨语言共享内容放在 `sdks/contracts/`，以 JSON schema、示例 payload 和错误码说明为准。

## 建议结构

当前已实现 `contracts/` 和 C# / .NET SDK。Python、Go 和 C SDK 仍处于规划状态，暂不提供代码。

```text
sdks/
├─ contracts/
├─ dotnet/
├─ python/
├─ go/
├─ c/
└─ examples/
```

## 实现顺序

1. C# / .NET SDK：优先覆盖 .NET Framework 上位机和 .NET Core / .NET 应用，当前已支持 `net461;net472;netstandard2.1;net10.0`。首版在 [sdks/dotnet](dotnet/)。
2. Python SDK：服务于调试脚本、测试和轻量桥接。
3. Go SDK：服务于边缘代理和本地桥接服务。
4. C SDK：服务于 C/C++ 上位机、厂商接口和需要稳定 C ABI 的系统。

详细规划见 [docs/api/trigger-source-sdks.md](../docs/api/trigger-source-sdks.md)。