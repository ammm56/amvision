# Amvision.Workflows Net461 Console

这个控制台程序用于 .NET Framework 4.6.1 上位机或现场调试程序，通过 `Amvision.Workflows` SDK 控制和调用前端已经创建好的 WorkflowAppRuntime、WorkflowRun、TriggerSource 和 ZeroMQ 触发入口。

Workflow app、runtime 和 TriggerSource 的创建、参数绑定、pool 选择和 mapping 配置由前端图形化界面完成。本程序只保存调用所需的 id、endpoint 和输入参数，不重复实现前端创建流程。

程序按目录拆分调用边界：

- `Config`：读取 `config_*.json`，按 runtime 名称和 TriggerSource 名称建立字典。
- `Runtime`：封装已存在 WorkflowAppRuntime 的启动、停止、重启、health、instances、sync invoke、async run 和事件查询。
- `TriggerSource`：封装已存在 TriggerSource 的启用、停用、health 和列表查询。
- `TriggerSource/ZeroMQ`：封装 ZeroMQ 图片文件、图片 bytes、base64 图片和纯事件触发。

## 配置

程序不读取环境变量。所有运行配置都放在项目根目录 `Config` 目录下，文件名使用 `config_*.json`。启动时会读取 `Config` 中全部配置文件，并保存到单例 `WorkflowConfigStore` 中。

每个配置文件描述一个 WorkflowAppRuntime 和它关联的 TriggerSource。实际现场有多少组 runtime / TriggerSource，就放多少个 `config_*.json`。
配置读取会校验字段名单；出现 `application_id`、`cleanup`、`pool_name`、`input_binding_mapping` 这类创建或前端配置字段时会直接报错，避免旧配置被静默忽略。

```json
{
  "runtime": {
    "name": "yolo11m_barqrcode_runtime",
    "workflow_runtime_id": "workflow-runtime-xxx"
  },
  "trigger_sources": [
    {
      "name": "yolo11m_barqrcode_zeromq",
      "trigger_source_id": "zeromq-workflow-runtime-xxx",
      "zero_mq": {
        "bind_endpoint": "tcp://127.0.0.1:5555",
        "default_input_binding": "request_image_ref"
      }
    }
  ]
}
```

`runtime.name` 和 `trigger_sources[].name` 是程序内部字典 key，所有封装方法都支持直接传入这个 key。`workflow_runtime_id` 和 `trigger_source_id` 必须来自前端已创建好的资源；本程序不会创建或删除 runtime / TriggerSource，避免误改现场配置。

## 运行

```powershell
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj
```

常用命令：

```powershell
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- runtime-health yolo11m_barqrcode_runtime
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- runtime-use yolo11m_barqrcode_runtime
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- runtime-invoke yolo11m_barqrcode_runtime
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- runtime-submit-run yolo11m_barqrcode_runtime
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- triggersource-health yolo11m_barqrcode_zeromq
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj -- zeromq-image yolo11m_barqrcode_zeromq C:\data\sample.jpg
```
