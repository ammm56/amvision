# TriggerSource SDK 规划

## 文档目的

本文档定义 TriggerSource 外部调用方 SDK 的边界、标准调用流程、语言实现顺序和仓库落位。

SDK 面向设备上位机、MES、采集程序、现场桥接进程和调试脚本。SDK 不属于 backend-service 内部实现，也不属于 workflow node pack。SDK 只封装已经公开的 REST 管理接口、ZeroMQ 触发协议和稳定结果合同，降低外部系统接入成本。

## 结论

- 同机高速图片触发默认使用 ZeroMQ 调用 backend-service 暴露的 TriggerSource adapter。
- 低频调试、管理、创建 runtime、创建 trigger source、启停 trigger source 和 health 查询继续使用 REST API。
- 设备上位机软件不应直接拼 multipart 帧和错误解析逻辑，推荐通过 SDK 调用。
- SDK 应放在仓库根目录 `sdks/` 下，与 `backend/`、`frontend/`、`custom_nodes/` 明确分离。
- 第一优先级是 C# / .NET SDK，兼容 .NET Framework 和 .NET Core / .NET 运行时；首版已放在 `sdks/dotnet/`，随后再补 Python、Go 和 C。

## 调用方关系

```text
设备上位机 / MES / 采集程序 / 调试脚本
  |
  v
Amvision SDK
  |
  |-- REST 管理面：创建、启停、health、run 查询
  |
  `-- ZeroMQ 触发面：图片 bytes + envelope -> TriggerSource adapter
        |
        v
      WorkflowAppRuntime / WorkflowRun
```

SDK 不直接访问数据库、LocalBufferBroker、workflow worker、deployment worker 或对象存储。LocalBufferBroker 仍由 backend-service 内部 adapter 写入和管理，外部调用方只发送图片 bytes、metadata 和必要的业务字段。

SDK 和 TriggerSource 都只负责提交协议原生输入，不负责替 workflow 图做 `image-ref -> image-base64`、本地磁盘读图或相机取帧。是否需要把 ZeroMQ image-ref 汇入 HTTP base64 链路，应该由 workflow 图中的显式节点决定。

## 标准使用流程

### 服务侧准备

服务侧准备通常由部署脚本、前端界面、Postman 调试集或运维工具完成，不要求设备上位机每次启动时重复创建资源。

1. 创建或确认 WorkflowAppRuntime。
2. 启动绑定的 WorkflowAppRuntime。
3. 创建 `zeromq-topic` TriggerSource，配置 `bind_endpoint`、`default_input_binding`、`result_mapping` 和超时。
4. 调用 TriggerSource enable，启动 ZeroMQ adapter。
5. 查询 TriggerSource health，确认 `adapter_running=true`。

### 调用方准备

调用方只需要保存少量运行参数：

- `endpoint`：ZeroMQ endpoint，例如 `tcp://127.0.0.1:5555` 或受控的 `ipc://...`。
- `trigger_source_id`：目标 TriggerSource id。
- `input_binding`：ZeroMQ envelope 中保存图片引用的事件 payload 字段名；当前 SDK 示例默认使用 `request_image`，再由 TriggerSource 的 `input_binding_mapping` 映射到 workflow app 的 `request_image_ref`。
- `timeout`：发送和接收超时。
- `metadata`：line_id、station_id、camera_id、job_id 等业务字段。

### 单次图片触发

1. SDK 生成 `event_id` 和 `trace_id`。
2. SDK 构造 ZeroMQ multipart：第一帧是 JSON envelope，第二帧是图片 bytes。
3. backend-service ZeroMQ adapter 收到 bytes 后写入 LocalBufferBroker。
4. TriggerSource 按 `input_binding_mapping` 生成 WorkflowRuntime input_bindings，保持在协议原生 payload 边界内。
5. WorkflowRuntime 创建 sync invoke 或 async WorkflowRun。
6. SDK 解析 JSON reply，返回统一结果对象或抛出统一错误。

## ZeroMQ envelope 初版字段

当前 backend-service 已支持以下 envelope 字段：

```json
{
  "trigger_source_id": "zeromq-trigger-source-06",
  "event_id": "event-0001",
  "trace_id": "trace-0001",
  "occurred_at": "2026-05-13T00:00:00Z",
  "input_binding": "request_image",
  "media_type": "image/jpeg",
  "shape": [1080, 1920, 3],
  "dtype": "uint8",
  "layout": "HWC",
  "pixel_format": "BGR",
  "metadata": {
    "line_id": "line-a",
    "station_id": "station-1",
    "camera_id": "camera-1"
  },
  "payload": {
    "job_id": "job-1"
  }
}
```

当前 SDK envelope 不发送 `format_id`，因为 backend-service 的 `ZeroMqFrameEnvelope` 当前禁止额外字段。稳定 SDK v1 前建议按兼容方式补充两项能力：

- backend-service 先允许 envelope 可选 `format_id`，再由 SDK 发送 `amvision.zeromq-trigger-envelope.v1`。
- shared schema 已固定到 `sdks/contracts/`，后续各语言 SDK 使用同一份字段说明和测试样例。

## SDK 职责

SDK 应封装以下能力：

- 构造 ZeroMQ envelope 和 multipart 消息。
- 发送图片 bytes，避免调用方手写 JSON base64。
- 解析 `TriggerResultContract` 和 ZeroMQ error reply。
- 生成 event_id、trace_id 和可选 idempotency_key。
- 统一超时、重试、连接重建和错误码。
- 提供可选 REST control client，用于 health 检查、enable/disable 和 run 查询。
- 提供最小示例，覆盖 06 和 07 同 app HTTP base64 + ZeroMQ image-ref 双输入 workflow app 的真实图片触发，并说明图内节点负责转换。

SDK 不应承担以下职责：

- 不内置相机、PLC、IO 或传感器驱动。
- 不直接写 LocalBufferBroker。
- 不直接调用 workflow worker 或 deployment worker。
- 不复制 backend-service 的业务对象和持久化逻辑。
- 不把客户现场业务流程写入通用 SDK。

## 图级转换边界

- HTTP 调试入口如果公开的是 `image-base64.v1`，就继续由 HTTP 调用方直接传 base64 图片。
- ZeroMQ 调试入口如果公开的是 `image-ref.v1`，就继续由 SDK 发送图片 bytes，再由 backend-service adapter 写成 BufferRef / image-ref。
- 如果同一个 workflow app 需要同时接两类入口，应在图里显式提供多个 binding，或增加 `image-ref -> image-base64` 转换节点后再汇到公共下游节点。
- 如果触发源只有 PLC 寄存器值、IO 状态或其他数值输入，后续图片应由图里的本地图片加载节点、相机抓帧节点或 custom node 决定，不由 SDK 或 TriggerSource 补出。

## 目录结构

建议在仓库根目录增加 `sdks/`：

```text
sdks/
├─ README.md
├─ contracts/
│  ├─ zeromq-trigger-envelope.v1.schema.json
│  ├─ trigger-result.v1.schema.json
│  └─ errors.v1.md
├─ dotnet/
│  ├─ src/Amvision.TriggerSources/
│  ├─ examples/ZeroMqImageInvoke/
│  └─ tests/Amvision.TriggerSources.Tests/
├─ python/
│  ├─ amvision_trigger_client/
│  ├─ examples/
│  └─ tests/
├─ go/
│  ├─ amvisiontrigger/
│  ├─ examples/
│  └─ tests/
├─ c/
│  ├─ include/
│  ├─ src/
│  ├─ examples/
│  └─ tests/
└─ examples/
   ├─ 04-yolox-deployment-infer-opencv-health/
   └─ 05-opencv-process-save-image/
```

`sdks/contracts/` 保存外部调用协议的稳定合同，不直接导入 `backend/` Python 代码。需要共享字段时，以 JSON schema、Markdown 规则和跨语言测试样例为准。

## 语言实现顺序

### C# / .NET

C# / .NET SDK 是第一优先级，面向设备上位机默认接入方式。首版已实现 sync REQ/REP 单张图片调用、TriggerResult 解析、ZeroMQ error reply 解析和控制台示例。

包名：`Amvision.TriggerSources`。

当前目标框架：

- `net461`：覆盖仍停留在 .NET Framework 4.6.1 的上位机软件。
- `net472`：覆盖常见 .NET Framework 上位机软件。
- `netstandard2.1`：覆盖 .NET Core 3.0+ 和多数现代 .NET 应用。
- `net10.0`：用于现代 .NET 运行时。

说明：`net461` 目标使用 NetMQ 4.0.1.10 和 System.Text.Json 6.0.10，避免依赖包退回到未声明支持 net461 的资产。`net472`、`netstandard2.1` 和 `net10.0` 使用 NetMQ 4.0.4.1；非 `net10.0` 目标显式引用 System.Text.Json。

当前依赖：

- ZeroMQ：NetMQ，减少现场 native libzmq 部署成本。
- JSON：`System.Text.Json`。

构建和自测：

```powershell
dotnet build sdks/dotnet/src/Amvision.TriggerSources/Amvision.TriggerSources.csproj
dotnet run --project sdks/dotnet/tests/Amvision.TriggerSources.Tests/Amvision.TriggerSources.Tests.csproj
```

建议 API：

```csharp
var client = new AmvisionTriggerClient(new AmvisionTriggerClientOptions
{
    Endpoint = "tcp://127.0.0.1:5555",
  TriggerSourceId = "zeromq-trigger-source-06",
  DefaultInputBinding = "request_image",
    Timeout = TimeSpan.FromSeconds(5)
});

var request = new ImageTriggerRequest
{
    ImageBytes = imageBytes,
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
```

真实 06/07 backend-service 调试使用 `sdks/dotnet/examples/ZeroMqImageInvoke`：

```powershell
dotnet run --project sdks/dotnet/examples/ZeroMqImageInvoke/ZeroMqImageInvoke.csproj -- tcp://127.0.0.1:5556 zeromq-trigger-source-07 <image_path> image/png
dotnet run --project sdks/dotnet/examples/ZeroMqImageInvoke/ZeroMqImageInvoke.csproj -- tcp://127.0.0.1:5555 zeromq-trigger-source-06 <image_path> image/jpeg <deployment_instance_id>
```

其中 06 示例需要把已有 `deployment_instance_id` 传入；如果省略 `media_type`，示例会按文件扩展名自动猜测，并把第四个可选参数当作 `deployment_instance_id`。示例最终会把它放入 envelope payload 的 `deployment_request.value.deployment_instance_id`，供 TriggerSource 的 `input_binding_mapping` 映射到 workflow app。

如果需要在 Windows 上手动查看 envelope、TriggerResult 和完整 WorkflowRun，当前也提供独立 WinForms 调试项目：

```powershell
dotnet run --project sdks/dotnet/examples/TriggerSourceDebugWinForms/TriggerSourceDebugWinForms.csproj
```

### Python

Python SDK 用于调试、脚本集成、测试夹具和现场轻量桥接。

建议包名：`amvision-trigger-client`。

建议依赖：`pyzmq`、`pydantic` 或标准库 dataclass。

建议提供 CLI：

```text
amvision-trigger invoke-image --endpoint tcp://127.0.0.1:5555 --trigger-source-id trigger-source-04 --image sample.jpg
```

### Go

Go SDK 面向边缘代理、轻量本地服务和跨平台桥接程序。

建议包名：`amvisiontrigger`。

ZeroMQ 依赖需要在纯 Go 实现和 libzmq/cgo 实现之间做取舍：

- 纯 Go 依赖便于发布，但需要验证 REQ/REP 兼容性和长期维护状态。
- libzmq/cgo 依赖更贴近标准 ZeroMQ，但 Windows 现场部署需要额外说明 native 依赖。

### C

C SDK 面向 C/C++ 上位机、厂商二次开发接口、LabVIEW 或其他需要稳定 C ABI 的场景。

建议结构：

- `include/amvision_trigger_client.h`
- `src/amvision_trigger_client.c`
- `examples/invoke_image.c`

建议依赖：`libzmq` 和一个轻量 JSON 实现。C SDK 应保持函数式 API，避免把 backend-service 规则嵌入复杂对象模型。

## 版本规则

- SDK package 使用 SemVer。
- wire contract 使用独立 `format_id` 和 schema 版本。
- SDK minor 版本可以增加字段；破坏字段、错误码或 reply 结构时必须升级 wire contract 版本。
- backend-service 可以继续接受旧 envelope 字段，至少保留一个稳定迁移窗口。

## 测试要求

- 每个 SDK 至少包含 envelope 序列化测试、错误 reply 解析测试和超时测试。
- 每个 SDK 至少包含一个本地 ZeroMQ fake server 测试。
- C# 和 Python SDK 优先增加真实 backend-service 联调脚本，覆盖 04 和 05 workflow app。
- 合同样例放在 `sdks/contracts/fixtures/` 后，可被各语言测试复用。

## 分期实现建议

1. 固定 ZeroMQ envelope 和 reply 的稳定 schema。
2. 增加 `sdks/README.md` 和 `sdks/contracts/`。
3. 实现 C# / .NET SDK，先覆盖 sync REQ/REP 单张图片调用。已完成首版。
4. 用 C# SDK 触发 06/07 双输入 workflow app 的 ZeroMQ image-ref 通道，形成端到端示例。当前已经新增 06/07 的双输入 workflow app 请求体、TriggerSource 创建请求体和 C# 示例命令，后续需要在真实 backend-service 进程中完成端到端截图或日志归档。
5. 实现 Python SDK 和 CLI，用于本地联调和回归测试。
6. 根据现场需求补 Go 和 C SDK。
7. 后续再补 async-report、ring frame、批量发送和更完整的重试策略。