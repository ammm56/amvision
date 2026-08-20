# Amvision SDK

本目录用于存放外部调用方 SDK。SDK 面向设备上位机、MES、采集程序、现场桥接进程和调试脚本，不属于 backend-service 内部实现。

## 边界

- SDK 通过公开 REST API、WebSocket 或 ZeroMQ TriggerSource 协议访问 backend-service。
- SDK 不直接访问数据库、LocalBufferBroker、workflow worker、deployment worker 或对象存储。
- SDK 不直接导入 `backend/`、`frontend/`、`custom_nodes/` 的运行时代码。
- 跨语言共享内容放在 `sdks/schemas/`，以 JSON schema、示例 payload 和错误码说明为准。

## 当前结构

当前已实现 `schemas/` 和 C# / .NET SDK。Python、Go 和 C SDK 尚未交付，不属于当前能力。

```text
sdks/
├─ schemas/
└─ dotnet/
```

当前 SDK 说明见 [docs/api/workflow-sdks.md](../docs/api/workflow-sdks.md)，构建和引用见 [sdks/dotnet/README.md](dotnet/README.md)。
