# SDK 配置包

SDK 配置包把一个 Project 已创建的 Workflow Runtime、TriggerSource 和模型 Deployment 整理为 `.NET` SDK 与 `AMVision.Console` 可直接读取的 `Config/config_*.json`。配置包只导出调用配置，不创建、修改或启动平台资源。

## 页面入口

前端入口位于 Project 列表的项目操作区。页面先请求预览，确认文件数、资源数、API 地址、token 状态和 warning，再下载 zip。

实现入口：

- 前端：`frontend/web-ui/src/modules/projects/pages/ProjectListPage.vue`
- 前端服务：`frontend/web-ui/src/modules/projects/services/project.service.ts`
- API：`backend/service/api/rest/v1/routes/projects/sdk_config_packages.py`
- 生成服务：`backend/service/application/sdk_config_packages/sdk_config_package_service.py`
- .NET 示例：`sdks/dotnet/apps/AMVision.Console`

## API

两个接口都要求当前 Project 可见，并同时要求 `workflows:read` 与 `models:read`：

```http
POST /api/v1/projects/{project_id}/sdk-config-packages/preview
POST /api/v1/projects/{project_id}/sdk-config-packages/download
```

请求体：

```json
{
  "include_access_token": true,
  "model_runtime_modes": ["sync"],
  "include_disabled_trigger_sources": true
}
```

字段含义：

- `include_access_token`：是否把当前 Bearer token 写入配置；默认 `true`。
- `model_runtime_modes`：为模型 Deployment 生成的调用模式，可选 `sync`、`async`。
- `include_disabled_trigger_sources`：是否包含当前未启用的 TriggerSource。

preview 返回包名、backend-service 地址、是否包含 token、各类资源数量、zip 文件清单和 warning。download 使用相同请求体并直接返回 `application/zip`，不在服务端保存生成包。

## 资源选择

生成服务读取当前 Project 的：

- 全部 WorkflowAppRuntime；
- 绑定这些 Runtime 的 ZeroMQ TriggerSource；
- 已登记的模型 DeploymentInstance。

非 ZeroMQ TriggerSource 不写入 Console 配置，并在 preview warning 中说明。模型配置按请求的 runtime mode 生成独立调用 key。

Workflow App 切换版本不会改变稳定的 `workflow_runtime_id`、TriggerSource id 或 endpoint。公开契约兼容时不需要重新生成配置包；输入输出契约发生破坏性变化时，第三方调用配置和代码必须同步更新。

## zip 内容

zip 包含：

```text
Config/
  config_<workflow-runtime>.json
  config_model_deployments.json
manifest.json
README.md
```

没有 Workflow Runtime 时不会生成对应文件；没有模型 Deployment 时不会生成模型文件。Project 没有任何可导出资源时，download 返回明确错误。

每个 Workflow 配置文件包含：

- backend API 地址、token 和 HTTP timeout；
- 稳定的 Workflow Runtime key 与 id；
- 同步/异步调用默认参数；
- 绑定的 ZeroMQ TriggerSource；
- 空的或实际的模型 Deployment 列表。

模型配置可以只包含 `backend` 与 `model_deployments`；SDK 不要求伪造 Workflow Runtime。

## 使用步骤

1. 在 Project 页面生成 preview，核对资源数量和 warning。
2. 按现场安全策略决定是否包含 access token。
3. 下载并解压 zip。
4. 将 `Config/` 放到 `AMVision.Console.exe` 或第三方程序集的输出目录。
5. 启动 Console 或在第三方程序中使用 `Amvar.Vision.dll` 加载配置。
6. 调用前分别检查 backend、Runtime/Deployment 和 TriggerSource health。

.NET 工程、构建命令和契约测试见 [.NET SDK](../../sdks/dotnet/README.md)。

## 安全边界

- 包含真实 token 的 zip 属于敏感文件，不能提交到 git、共享目录或日志。
- 跨机器部署时，必须把 preview 中的 backend 地址改为第三方机器可访问的实际地址；`127.0.0.1` 只适用于同机调用。
- 配置包是生成时快照。Runtime/Trigger/Deployment id 被删除或替换后，必须重新生成。
- 版本选择属于 Runtime 控制面；调用 SDK 不能在单次请求中绕过 Runtime 指定 revision。
