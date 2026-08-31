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

三个接口都要求当前 Project 可见，并同时要求 `workflows:read` 与 `models:read`：

```http
POST /api/v1/projects/{project_id}/sdk-config-packages/preview
POST /api/v1/projects/{project_id}/sdk-config-packages/download
GET  /api/v1/projects/{project_id}/sdk-config-packages/current
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

preview 返回包名、backend-service 地址、是否包含 token、稳定 `configuration_revision`、各类资源数量、zip 文件清单和 warning。download 使用相同请求体并直接返回 `application/zip`，不在服务端保存生成包。

`current` 供 SDK 可选的 HTTP 自动同步使用，不接受请求体、不把请求 token 写回 zip，并返回 `ETag` 与 `X-AmVision-Config-Revision`。SDK 使用 `If-None-Match` 条件请求；未变化时返回 `304`。revision 是去除 secret 后的规范化配置 SHA-256，zip manifest 同时保存每个文件的 SHA-256。

## 资源选择

生成服务读取当前 Project 的：

- 全部 WorkflowAppRuntime；
- 绑定这些 Runtime 的 ZeroMQ 与 local-shared-memory TriggerSource；
- 已登记的模型 DeploymentInstance。

不受 SDK 支持的 TriggerSource 不写入 Console 配置，并在 preview warning 中说明。模型配置按请求的 runtime mode 生成独立调用 key。

Workflow App 切换版本不会改变稳定的 `workflow_runtime_id`、TriggerSource id 或 endpoint。公开契约兼容时不需要重新生成配置包；输入输出契约发生破坏性变化时，第三方调用配置和代码必须同步更新。

## zip 内容

zip 包含：

```text
Config/
  sdk-bootstrap.json
  config_<workflow-runtime>.json
  config_model_deployments.json
manifest.json
README.md
```

没有 Workflow Runtime 时不会生成对应文件；没有模型 Deployment 时不会生成模型文件。Project 没有任何可导出资源时，download 返回明确错误。

每个 Workflow 配置文件包含：

- backend API 地址、token 和 HTTP timeout；
- 稳定的 Workflow Runtime key 与 id；
- Runtime revision 固定的 `runtime.public_contract`；新版本为 App Contract v2，旧 Runtime 没有契约快照时为 `null`；
- 同步/异步调用默认参数；
- 绑定的 ZeroMQ TriggerSource；
- 绑定的 local-shared-memory TriggerSource；其配置只包含 `buffers_root`、路由 generation、默认输入 binding 和 timeout，不复制 arena 容量、mmap 路径、reader guard 数或图片上限；
- 每个 TriggerSource 的 `input_binding_mapping`；SDK 据此把强类型 JSON/文本输入写入确定的 event payload 路径；
- 空的或实际的模型 Deployment 列表。

模型配置可以只包含 `backend` 与 `model_deployments`；SDK 不要求伪造 Workflow Runtime。

`.NET` HTTP SDK 把 `runtime.public_contract` 传给 `WorkflowRequestBuilder`。Builder 已提供 `AddJson`、`AddText`、`AddImage`、`AddImageBase64`、`AddImageReference`、`AddFile`、`AddFileReference`、`AddFiles`、`AddFileReferences`，并显式区分 `BuildJson()` 与 `BuildMultipart()`。文件和图片在 HTTP 发送阶段以 stream 读取，不在 SDK 内预先复制完整文件。

ZeroMQ 与 local-shared-memory 配置只允许高性能输入 `image-ref.v1`、`value.v1` 和 `text.v1`。共用 `WorkflowTriggerInputsBuilder` 只提供 `AddJson` 和 `AddText`；图片由 transport 图片方法提供。配置包同时携带 Runtime 固定公开契约和 TriggerSource mapping，使 SDK 在调用前拒绝未映射 binding、Base64/file/files Trigger 输入和超限 payload。后端仍是完整契约校验的权威入口。

## 使用步骤

1. 在 Project 页面生成 preview，核对资源数量和 warning。
2. 按现场安全策略决定是否包含 access token。
3. 下载并解压 zip。
4. 将 `Config/` 放到 `AMVision.Console.exe` 或第三方程序集的输出目录。
5. 启动 Console 或在第三方程序中使用 `Amvar.Vision.dll` 加载配置。
6. 调用前分别检查 backend、Runtime/Deployment 和 TriggerSource health。

默认方式仍是手工下载、解压和加载。需要自动同步时，编辑 `Config/sdk-bootstrap.json`：保留 backend 地址、配置路径和专用 token，把 `configuration_sync.enabled` 改为 `true`，并通过 `CreateFromConfigAsync` 或 `CreateFromConfigDirectoryAsync` 创建 client。SDK 下载后先校验 revision、manifest、逐文件 SHA-256、路径和完整配置语义，再原子发布到 `Config/.managed/<revision>/`；失败时仅在 `use_last_known_good=true` 时使用最近有效快照或手工配置。同步工厂不会在启动后后台热改当前 client，下一次创建 client 才选用新快照。

.NET 工程、构建命令和契约测试见 [.NET SDK](../../sdks/dotnet/README.md)。

## 安全边界

- 包含真实 token 的 zip 属于敏感文件，不能提交到 git、共享目录或日志。
- 跨机器部署时，必须把 preview 中的 backend 地址改为第三方机器可访问的实际地址；`127.0.0.1` 只适用于同机调用。
- 配置包是生成时快照。Runtime/Trigger/Deployment id 被删除或替换后，必须重新生成。
- 自动同步默认关闭；token 应使用只具备所需 Project 与 `workflows:read`、`models:read` scope 的专用凭据。HTTP 自动同步不改变 local-shared-memory 只能同机访问 `data/buffers` 的物理边界；远程 SDK 仍使用 HTTP 或 ZeroMQ。
- 版本选择属于 Runtime 控制面；调用 SDK 不能在单次请求中绕过 Runtime 指定 revision。
