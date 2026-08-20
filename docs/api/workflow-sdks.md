# Workflow 外部调用 SDK

## 当前交付

仓库当前提供 C#/.NET SDK：`sdks/dotnet/`。它面向 WinForms、WPF、MES 桥接、采集程序和现场服务，核心库为 `Amvar.Vision.dll`，默认交付工程支持 VS2019 + .NET Framework 4.7.2。

Python、Go 和 C SDK 当前没有实现，不能作为已交付能力使用。跨语言协议事实位于 `sdks/schemas/`。

## 能力

- Workflow Runtime 查询、启停、重启、健康与 revision 分页
- 停机选择 Workflow App Version
- Workflow App Version archive/restore 状态 CAS
- 同步 invoke、异步 run、Run/Event 查询和取消
- TriggerSource 查询、启停与健康
- ZeroMQ 图片、BGR24、Base64 和事件调用
- Model Deployment runtime 控制与同步/异步推理
- `Config/config_*.json` 加载和按 name/id 调用

SDK 不创建训练任务、修改模型资源、直接访问数据库/ObjectStore/LocalBuffer，也不读取 Workflow Worker 内部状态。

## 版本调用规则

- 设备侧长期保存稳定 Runtime/Trigger id，不保存 `latest`。
- Runtime 切换兼容版本后调用地址不变；破坏性契约变化必须先升级调用方或新建 Runtime。
- 每条 Run 返回固定的 Workflow App version、revision、generation、snapshot fingerprint 和 worker instance id。
- archive 请求的 `expected_state` 为 `published`，restore 为 `archived`。
- Runtime 创建时 version selector 必须且只能提供一个；新代码使用准确 `workflow_app_version_id`。

## 使用配置包

项目工作台统一生成 SDK 配置包。解压后的 `Config/config_*.json` 包含 Runtime、TriggerSource 或 Model Deployment 的稳定 id、HTTP/ZeroMQ 地址与调用参数。

```csharp
using (var client = AMVisionClient.CreateFromConfig())
{
    var result = await client
        .InvokeConfiguredWorkflowRuntimeByNameAsync("托盘空盘检测")
        .ConfigureAwait(false);
}
```

配置包接口见 [SDK 配置包](sdk-config-packages.md)。完整引用、依赖 DLL、name/id 规则、Console 示例和 VS2019 构建命令见 [sdks/dotnet/README.md](../../sdks/dotnet/README.md)。

## 高速图片调用

```text
SDK BGR24/image bytes
  → ZeroMQ envelope + content
  → TriggerSource adapter
  → LocalBufferBroker BufferRef
  → Workflow Runtime
```

SDK 不直接操作 mmap 文件或 slot。timeout、transport error 和后端非 2xx/错误 reply 必须保留原始状态与错误详情，调用方自行决定现场处置；SDK 不隐藏队列或无限重试。

## 门禁

.NET contract harness 使用真实 `net472` 编译，覆盖 selector 互斥、版本选择、archive/restore、revision 分页、Run 来源字段和 409 错误详情。命令见 [sdks/dotnet/README.md](../../sdks/dotnet/README.md)。
