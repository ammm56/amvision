# 模型 Deployment SDK

模型 Deployment SDK 面向现场上位机、WinForms/WPF 程序、MES 桥接程序和采集程序。它控制已经创建的 DeploymentInstance，并调用同步或异步推理；模型登记、转换、Deployment 创建和运行策略配置仍由平台管理面完成。

## 能力边界

SDK 提供：

- start、warmup、reset、stop；
- status 与 health；
- 同步推理；
- 异步 inference task 创建、状态和结果读取；
- bytes、文件、base64、URI 和 file id 等输入封装。

SDK 不提供：

- 创建、删除或枚举 DeploymentInstance；
- 选择 ModelVersion、ModelBuild、backend、precision 或 device；
- 修改 instance count 和 runtime configuration；
- 训练、验证、评估或转换任务管理。

这种边界防止生产调用程序在运行时修改平台资源。

## 调用关系

```text
现场程序
  → Amvar.Vision SDK
    → backend-service REST API
      → 已登记的 DeploymentInstance
        → inference daemon
```

SDK 不直接访问数据库、ObjectStore、LocalBufferBroker 内部池或推理进程队列。

## 同步与异步

同步调用面向需要当前响应继续处理的现场流程，直接返回模型结果。异步调用创建持久化 inference task，适合调用端可以轮询结果或需要任务追溯的场景。

Workflow 图内的 `core.model.*` 节点调用已发布 Deployment 的同步推理面。它与外部 SDK 使用同一 Deployment 资源，但 Workflow 节点还负责图内类型转换、后处理和结果编排。

## REST 资源

Runtime 控制：

```text
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/start
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/warmup
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/reset
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/stop
GET  /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/status
GET  /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/{runtime_mode}/health
```

`task_type` 为 `detection`、`classification`、`segmentation`、`pose` 或 `obb`；`runtime_mode` 为 `sync` 或 `async`。

同步推理：

```text
POST /api/v1/models/{task_type}/deployment-instances/{deployment_instance_id}/infer
```

异步推理：

```text
POST /api/v1/models/{task_type}/inference-tasks
GET  /api/v1/models/{task_type}/inference-tasks/{task_id}
GET  /api/v1/models/{task_type}/inference-tasks/{task_id}/result
```

请求与响应字段以 OpenAPI 为准，不能从 Console 示例反推公共契约。

## 配置与 key

现场程序从 `Config/config_*.json` 加载：

- backend API 地址、token 和 timeout；
- Deployment key、task type、instance id 和 runtime mode；
- 阈值、结果图和预览图参数；
- Workflow Runtime 与 TriggerSource 配置（如果同一程序需要）。

`WorkflowConfigurationCatalog` 分别维护 Runtime、TriggerSource 和 ModelDeployment 字典。key 按不区分大小写比较；相同 key 且内容一致时合并，内容冲突时在启动阶段明确失败，不能静默覆盖。

Project 页面可以直接生成配置包，完整格式见 [SDK 配置包](sdk-config-packages.md)。

## .NET 实现入口

- SDK 工程：`sdks/dotnet/src/Amvar.Vision/Amvar.Vision.vs2019.net472.csproj`
- 模型调用：`sdks/dotnet/src/Amvar.Vision/ModelDeployment/`
- HTTP client：`sdks/dotnet/src/Amvar.Vision/Http/`
- Console：`sdks/dotnet/apps/AMVision.Console/AMVision.Console.vs2019.net472.csproj`
- 契约门禁：`sdks/dotnet/tests/Amvar.Vision.ContractTests/`

Console 只接收配置 key 和运行时输入；task type、DeploymentInstance id、runtime mode 与默认阈值从配置读取。

## 参数约束

- 一次请求只允许一个主图片来源。
- bytes、文件和 base64 输入不能为空；文件输入必须存在。
- `score_threshold` 如设置，范围为 `0..1`。
- 同步调用只能选择 sync Deployment；异步任务只能选择 async Deployment。
- API error code、HTTP 状态和 details 必须原样保留，便于现场诊断。

## 构建与验证

在 `sdks/dotnet` 目录执行：

```powershell
dotnet msbuild amvar-vision-vs2019-net472.sln /t:Rebuild /p:Configuration=Release
dotnet msbuild tests/Amvar.Vision.ContractTests/Amvar.Vision.ContractTests.vs2019.net472.csproj /t:Rebuild /p:Configuration=Release
tests/Amvar.Vision.ContractTests/bin/Release/net472/Amvar.Vision.ContractTests.exe
```

详细引用、配置和运行方式见 [.NET SDK](../../sdks/dotnet/README.md)。
