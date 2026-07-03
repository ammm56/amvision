# Amvision.Workflows Net461 Console Example

这个示例用于 .NET Framework 4.6.1 上位机或调试程序，演示通过 `Amvision.Workflows` SDK 控制和调用 WorkflowAppRuntime。

示例按方法封装 SDK 调用：

- 列出 Project 下的 WorkflowAppRuntime
- 复用已有 runtime，或按 application 创建 runtime
- 启动 runtime
- 查询 health
- 列出 runtime instances
- 同步 invoke 并读取 app-result
- 创建异步 WorkflowRun
- 查询 WorkflowRun 和事件
- 查询 runtime 事件
- 可选重启 runtime
- 按防呆规则停止或删除 runtime

## 配置

示例不读取环境变量。所有运行配置都放在本示例项目根目录的 `config.json` 中，启动时会自动载入，并保存到单例配置对象中供各个调用方法使用。

复用已有 runtime 时，填写：

```json
{
  "workflow_runtime": {
    "workflow_runtime_id": "workflow-runtime-xxx",
    "application_id": ""
  }
}
```

创建新 runtime 时，填写：

```json
{
  "workflow_runtime": {
    "workflow_runtime_id": "",
    "application_id": "workflow-app-xxx"
  }
}
```

常用配置项：

```json
{
  "backend": {
    "base_api_url": "http://127.0.0.1:8000",
    "access_token": "amvision-default-user-token",
    "project_id": "project-1",
    "http_timeout_seconds": 60
  },
  "invoke": {
    "image_path": "",
    "timeout_seconds": 30,
    "event_limit": 20,
    "event_preview_count": 5
  },
  "cleanup": {
    "stop_at_end": false,
    "delete_created_runtime": false
  }
}
```

`image_path` 为空时走普通 JSON 调用；填写图片路径时走 SDK 的图片调用 helper。已有 runtime 默认不会在结束时停止，避免误停现场服务。示例创建的 runtime 会在结束时停止；是否删除由 `cleanup.delete_created_runtime` 控制。

## 运行

```powershell
dotnet run --project sdks/dotnet/examples/Amvision.Workflows.Net461Console/Amvision.Workflows.Net461Console.csproj
```
