# Amvision.Workflows.Console

这个控制台程序用于 .NET Framework 4.6.1、.NET Framework 4.7.2 和 .NET 10 上位机或现场调试程序，通过 `Amvision.Workflows` SDK 控制和调用前端已经创建好的 WorkflowAppRuntime、WorkflowRun、TriggerSource 和 ZeroMQ 触发入口。

Workflow app、runtime 和 TriggerSource 的创建、参数绑定、pool 选择和 mapping 配置由前端图形化界面完成。本程序只保存调用所需的 id、endpoint 和输入参数，不重复实现前端创建流程。

程序按目录拆分调用边界：

- `Config`：读取 `config_*.json`，按 runtime 名称和 TriggerSource 名称建立字典。
- `Runtime`：封装已存在 WorkflowAppRuntime 的启动、停止、重启、health、instances、sync invoke、async run 和事件查询。
- `TriggerSource`：封装已存在 TriggerSource 的启用、停用、health 和列表查询。
- `TriggerSource/ZeroMQ`：封装 ZeroMQ 图片文件、图片 bytes、base64 图片和纯事件触发。
- `ModelDeployment`：封装已存在模型 DeploymentInstance 的启动、预热、重置、停止、状态、health、同步推理和异步 inference task 调用，不封装创建或删除部署实例。

## 配置

程序不读取环境变量。所有运行配置都放在项目根目录 `Config` 目录下，文件名使用 `config_*.json`。启动时会读取 `Config` 中全部配置文件，并保存到单例 `WorkflowConfigStore` 中。

手工维护时，每个配置文件通常描述一个 WorkflowAppRuntime 和它关联的 TriggerSource，也可以包含已有模型 DeploymentInstance 的调用配置。实际现场有多少组 runtime / TriggerSource，就放多少个 `config_*.json`。
后端自动生成的 SDK 配置包会把模型 deployment 单独写入 `config_model_deployment_*.json`；这类纯模型配置文件只保存 `backend` 和 `model_deployments`，不写假的 runtime。
配置读取会校验字段名单；出现 `application_id`、`cleanup`、`pool_name`、`input_binding_mapping` 这类创建或前端配置字段时会直接报错，避免旧配置被静默忽略。

前端在“项目工作台”右上角提供唯一的“生成 SDK 配置包”入口，由后端按当前 Project 自动扫描已有 WorkflowAppRuntime、TriggerSource 和模型 DeploymentInstance，生成可直接复制到本程序目录的 zip。部署页、应用页和集成页不单独提供配置包快捷入口。接口细节见 [docs/api/sdk-config-packages.md](../../../../docs/api/sdk-config-packages.md)。

```json
{
  "runtime": {
    "name": "yolo11m_barqrcode",
    "workflow_runtime_id": "workflow-runtime-xxx"
  },
  "trigger_sources": [
    {
      "name": "zeromq_yolo11m_barqrcode",
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
`zero_mq.max_image_bytes` 是可选防呆字段，默认 268435456，用于覆盖 20MP/4K 级工业相机 raw BGR24 输入；现场确实需要更大图片时再在对应 config 中显式调大。

## 模型部署调用配置

模型 DeploymentInstance 没有 WorkflowAppRuntime + TriggerSource 这种一组一文件的清晰边界，因此每个 `config_*.json` 都允许包含 `model_deployments` 列表。程序启动时从所有配置文件中合并 `model_deployments`，建立统一的 `ModelDeployments` 字典。

模型部署调用仍按 key 使用：

```csharp
var health = await runner.GetModelDeploymentRuntimeHealthAsync("yolo11_m_20260630190724_sync", cancellationToken).ConfigureAwait(false);

var result = await runner.InvokeModelDeploymentWithImageBytesAsync(
    "yolo11_m_20260630190724_sync",
    imageBytes,
    mediaType: "image/jpeg",
    cancellationToken: cancellationToken).ConfigureAwait(false);
```

调用方不需要知道 `task_type`、`deployment_instance_id`、`runtime_mode`、`score_threshold`、`save_result_image` 和 `return_preview_image_base64` 等参数，这些都由对应 `config_*.json` 中的 `model_deployments[].name` 找到。

配置示例：

```json
{
  "model_deployments": [
    {
      "name": "yolo11_m_20260630190724_sync",
      "task_type": "detection",
      "deployment_instance_id": "deployment-instance-xxx",
      "runtime_mode": "sync",
      "input_transport_mode": "memory",
      "score_threshold": 0.3,
      "save_result_image": false,
      "return_preview_image_base64": false,
      "default_image_path": "Resources/Img/qrcode50.jpg",
      "default_file_name": "qrcode50.jpg",
      "default_media_type": "image/jpeg"
    }
  ]
}
```

`model_deployments` 不保存 `model_version_id`、`model_build_id`、`runtime_backend`、`runtime_precision`、`device_name`、`instance_count` 等创建部署相关字段。这些参数由前端界面完成配置，console 只保存调用已有部署所需的最小参数。

启动加载所有 `config_*.json` 时，`runtime.name` 和 `trigger_sources[].name` 必须在各自 catalog 中唯一。`model_deployments[].name` 允许跨文件重复；如果重复 key 的配置完全一致，程序会合并去重，只保留一份。如果重复 key 指向不同的 `deployment_instance_id`、task_type、runtime_mode 或阈值等配置，程序会在启动阶段抛出配置错误，列出冲突来源文件。

完整说明见 [docs/api/model-deployment-sdks.md](../../../../docs/api/model-deployment-sdks.md)。

## Visual Studio 2019

VS2019 不打开多目标框架 Console 项目。需要 .NET Framework 单框架项目时，直接打开当前目录下的固定框架 solution：

```text
sdks/dotnet/apps/Amvision.Workflows.Console/Amvision.Workflows.Console.vs2019.net461.sln
sdks/dotnet/apps/Amvision.Workflows.Console/Amvision.Workflows.Console.vs2019.net472.sln
```

这两个 solution 会引用对应框架的 `Amvision.Workflows.vs2019.net461` 或 `Amvision.Workflows.vs2019.net472` SDK 项目，适合 VS2019、老上位机项目和只使用 .NET Framework 的现场环境。VS2022/VS2026 可以继续使用多目标框架项目或这些固定框架 solution。

## 运行和调用

```powershell
dotnet run --project sdks/dotnet/apps/Amvision.Workflows.Console/Amvision.Workflows.Console.csproj --framework net10.0
```

本程序不使用命令行参数选择调用方法。现场调试时直接修改 `Program.MainAsync` 中的调用行：

```csharp
var runtimeHealth = await runner.GetRuntimeHealthAsync(RuntimeName, cancellationToken).ConfigureAwait(false);

// var appResult = await runner.InvokeRuntimeAppResultAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
// var workflowRun = await runner.RunRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
// var triggerResult = await runner.InvokeZeroMqConfiguredImageAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
```

`WorkflowOperationRunner` 是接入 WinForms/WPF 的主要入口。第三方程序可以直接调用 `WorkflowOperationRunner.CreateDefault()` 读取 `Config/config_*.json`，然后按业务按钮或菜单调用对应方法。每个方法都显式接收 runtime key 或 TriggerSource key，并在调用前从 `WorkflowConfigurationCatalog` 获取配置做防呆校验；不存在对应 key 时会直接抛出明确错误。
查询和调用方法会返回 SDK typed response、typed list 或组合检查结果，不在封装方法内部写控制台输出。调用方可以直接绑定到界面、继续参与业务判断，是否打印或记录日志由调用方决定。

现场高频推理调用时，应在程序启动后长期持有一个 `WorkflowOperationRunner`，在窗口关闭或进程退出时统一 `Dispose()`。ZeroMQ client 会按 TriggerSource key 复用底层 socket，并在 timeout 或 socket 异常后自动重建；相机内存帧优先调用 `InvokeZeroMqBgr24Async`，文件、JPEG/PNG bytes 和 base64 入口更适合调试或低频调用。
