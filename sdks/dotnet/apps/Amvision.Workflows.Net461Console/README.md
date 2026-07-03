# Amvision.Workflows Net461 Console

这个控制台程序用于 .NET Framework 4.6.1 上位机或现场调试程序，通过 `Amvision.Workflows` SDK 控制和调用 WorkflowAppRuntime、WorkflowRun、TriggerSource 和 ZeroMQ 触发入口。

程序按目录拆分调用边界：

- `Config`：读取 `config_*.json`，按 runtime 名称和 TriggerSource 名称建立字典。
- `Runtime`：封装 WorkflowAppRuntime 创建、启动、停止、重启、health、instances、sync invoke、async run 和事件查询。
- `TriggerSource`：封装 TriggerSource 创建、启用、停用、删除、health 和列表查询。
- `TriggerSource/ZeroMQ`：封装 ZeroMQ 图片文件、图片 bytes、base64 图片和纯事件触发。

## 配置

程序不读取环境变量。所有运行配置都放在项目根目录 `Config` 目录下，文件名使用 `config_*.json`。启动时会读取 `Config` 中全部配置文件，并保存到单例 `WorkflowConfigStore` 中。

每个配置文件描述一个 WorkflowAppRuntime 和它关联的 TriggerSource。实际现场有多少组 runtime / TriggerSource，就放多少个 `config_*.json`。

```json
{
  "runtime": {
    "name": "yolo11m_barqrcode_runtime",
    "workflow_runtime_id": "workflow-runtime-xxx",
    "application_id": "workflow-app-xxx"
  },
  "trigger_sources": [
    {
      "name": "yolo11m_barqrcode_zeromq",
      "trigger_source_id": "zeromq-workflow-runtime-xxx",
      "zero_mq": {
        "bind_endpoint": "tcp://127.0.0.1:5555",
        "pool_name": "image-1080p",
        "default_input_binding": "request_image_ref"
      }
    }
  ]
}
```

`runtime.name` 和 `trigger_sources[].name` 是程序内部字典 key，所有封装方法都支持直接传入这个 key。`workflow_runtime_id` 为空且 `application_id` 有值时，runtime 方法会创建 runtime；已有 runtime 默认不会在结束时停止，避免误停现场服务。

## 运行

```powershell
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj
```

常用命令：

```powershell
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- runtime-health yolo11m_barqrcode_runtime
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- runtime-invoke yolo11m_barqrcode_runtime
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- triggersource-health yolo11m_barqrcode_zeromq
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- zeromq-image yolo11m_barqrcode_zeromq C:\data\sample.jpg
```
