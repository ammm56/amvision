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

下列接口都要求当前 Project 可见，并同时要求 `workflows:read` 与 `models:read`：

```http
POST /api/v1/projects/{project_id}/sdk-config-packages/preview
POST /api/v1/projects/{project_id}/sdk-config-packages/download
GET  /api/v1/projects/{project_id}/sdk-config-packages/current
GET  /api/v1/projects/{project_id}/sdk-config-packages/resources
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

目录监听触发源（`directory-watch`、`directory-poll`）由后端自动执行，无需 SDK 调用配置，正常省略。preview 与 zip manifest 的 `notes` 数组提供普通说明，同类说明只显示一次，页面使用中性文字，不显示为警告。对应 Runtime 仍正常导出。

其他不受 SDK 支持的 TriggerSource 不写入 Console 配置，并在 `warnings` 中说明；配置问题继续使用警告样式。`notes` 是 v1 响应与 manifest 的新增说明字段，不改变调用配置和运行行为。模型配置按请求的 runtime mode 生成独立调用 key。

Workflow App 切换版本不会改变稳定的 `workflow_runtime_id`、TriggerSource id 或 endpoint。公开契约兼容时不需要重新生成配置包；输入输出契约发生破坏性变化时，第三方调用配置和代码必须同步更新。

## zip 内容

zip 包含：

```text
Config/
  sdk-bootstrap.json
  config_<application-id>.json
  config_<application-id>_<runtime-file-id>.json
  config_model_deployments.json
manifest.json
README.md
```

没有 Workflow Runtime 时不会生成对应文件；没有模型 Deployment 时不会生成模型文件。Project 没有任何可导出资源时，download 返回明确错误。

模型配置文件固定命名为 `config_model_deployments.json`。生成时间只用于包名和生成元数据，不进入配置文件路径，避免同一配置跨秒生成不同 revision、预览后下载误报 409 或 `current` 无法稳定返回 304。现有 .NET SDK 按 `config*.json` 读取，无需更新 SDK 接口。手工更新 Config 目录时应替换本次导出的配置集合，移除被替代的旧 `config_model_deployment_<timestamp>.json`，避免同一部署被重复登记；SDK 托管快照继续按完整 generation 替换。

一个应用只有一个 Runtime 时，文件名固定为 `config_<application-id>.json`。同一应用有多个 Runtime 时追加 Runtime 的 `sdk_config_file_id`；受控测试资源可以在 Runtime metadata 中显式设置该稳定短标识。未设置时回退真实 `workflow_runtime_id`，避免同名覆盖。配置文件中的 Runtime key 对多 Runtime 应用使用各自的 Runtime 展示名称，不能按随机资源 id 排序后生成含义不确定的 `_2`、`_3` 名称。

每个 Workflow 配置文件包含：

- backend API 地址、token 和 HTTP timeout；
- 稳定的 Workflow Runtime key 与 id；
- Runtime revision 固定的 `runtime.public_contract`；当前公开格式为 App Contract v1，没有契约快照时为 `null`；
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


## 项目页面的资源范围与预览核对

`resources` 返回可调用资源的 `id`、`name`、`kind`（runtime/trigger/deployment）及 Trigger 的 `runtime_id`，不返回凭据。目录监听由后端执行，不进入可选调用资源。

`GET /api/v1/projects/{project_id}/sdk-config-packages/resources` 使用 `offset`（默认 0）和 `limit`（默认及上限 200）分页。响应头为 `x-offset`、`x-limit`、`x-total-count`、`x-has-more`，有下一页时附 `x-next-offset`。只读取资源元数据，不为列表构建完整配置包。调用方须读取全部页面或明确使用分页结果，不能把第一页误认为全部。

当前生成容量为每类 10,000 项。列表和生成前先查询总数，任一类别超过容量返回明确的 400 错误；不静默截断模型部署。容量检查也包含已登记但无需 SDK 调用配置的触发源，控制整个配置快照的成本。前端分批加载并核对总数、重复 ID 和容量；当前范围列表与文件列表每页渲染 50 项，选择集合独立于搜索和显示页。读取期间发现总数变化、重复或缺项时要求刷新；同数量资源替换等并发变化还由生成时资源校验和预览 revision 核对处理。

preview/download 可增加 `runtime_ids`、`trigger_source_ids`、`deployment_ids`。未传或 null 为全量范围，空数组为该类不选。默认“全部资源”由服务端按生成时快照解析，前端不会用旧页面 ID 集合替代全量语义。所选 Trigger 自动包含必要 Runtime；失效或跨项目资源返回 400，不静默略过。普通目录监听省略说明仍进入 notes。

download 的可选 `expected_revision` 必须与同范围、同模式的预览一致，否则返回 409。页面每次修改范围、凭据选项或调用模式后重新预览；预览失败会禁用下载，避免下载与屏幕预览不一致。SDK current 的全量自动同步接口保持原语义，未增加执行队列或自动业务重试。

resources、preview、download 与 current 均要求 `workflows:read`、`models:read` 及项目可见权限；设置了页面范围的账号还须能读取运行实例和部署页面。前端入口使用相同规则。资源分页与 UI 调整不改变配置文件 JSON 结构或 .NET SDK 调用方式；本次无需更新 .NET 数据面实现。
