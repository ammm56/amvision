# SDK 配置包生成接口

## 文档目的

本文档固定 SDK `config_*.json` 配置包的生成入口、后端生成边界、zip 内容结构和前端交互位置，避免把配置生成能力散到部署页、应用详情页或集成页。

SDK 和 `sdks/dotnet/apps/Amvision.Workflows.Console` 面向现场使用，不负责创建平台资源。WorkflowAppRuntime、TriggerSource 和模型 DeploymentInstance 仍由前端图形化界面创建和维护；配置包只是把当前项目已经创建好的可调用资源导出成第三方程序可直接使用的 `Config/config_*.json`。

## 总结

- 配置包生成主入口只放在“项目工作台”页面右上角。
- 不在部署页面、应用详情页面、集成页面或设置页面增加快捷入口。
- 前端只负责触发生成、显示预览和下载 zip，不在浏览器端拼装 SDK 配置 JSON。
- 后端统一扫描当前 Project 的 WorkflowAppRuntime、TriggerSource 和模型 DeploymentInstance，并生成配置文件。
- .NET SDK 和 Console 只读取 `Config/config_*.json`，不依赖前端页面状态，也不重新实现资源创建。
- 生成结果不写数据库，`preview` 返回摘要，`download` 直接返回 zip 文件。

## 前端入口

入口位置固定为：

```text
项目工作台 / projects
  页面右上角操作区
    生成 SDK 配置包
```

按钮使用当前项目工作台已有 Button 风格，图标使用打包语义的 lucide 图标。按钮文案使用“生成 SDK 配置包”。

当前实现点击后按固定默认参数调用 `preview`，有可导出文件时立即调用 `download` 并保存 zip，同时在页面中显示本次生成的摘要：

- 显示将要导出的 Project id。
- 显示 workflow runtime 数量、TriggerSource 数量、模型 deployment 数量。
- 默认写入当前请求的 user token，便于现场直接使用。
- 默认只为模型 deployment 生成 `sync` 调用 key。
- 默认导出已创建但未启用的 TriggerSource。
- 显示后端返回的 warning，例如没有可导出的 runtime、TriggerSource 或 deployment。

前端不需要在以下位置加入口：

- 模型部署页面。
- 推理页面。
- Workflow 应用列表。
- Workflow 应用详情。
- TriggerSource 集成页面。
- 设置页面。

原因是这些页面只维护某一类资源，不能代表完整 Project 的可调用面。配置包是 Project 级导出，入口集中在项目工作台更清楚。

## 后端接口

当前实现位置：

```text
backend/service/api/rest/v1/routes/projects/sdk_config_packages.py
backend/service/application/sdk_config_packages/
```

接口：

```text
POST /api/v1/projects/{project_id}/sdk-config-packages/preview
POST /api/v1/projects/{project_id}/sdk-config-packages/download
```

`preview` 返回生成摘要，不返回 zip：

```json
{
  "project_id": "project-1",
  "workflow_runtime_count": 1,
  "trigger_source_count": 1,
  "model_deployment_count": 2,
  "files": [
    {
      "path": "Config/config_workflow_yolo11m_barqrcode_20260708153000.json",
      "kind": "workflow-runtime",
      "count": 1,
      "runtime_key": "yolo11m_barqrcode",
      "trigger_source_count": 1
    },
    {
      "path": "Config/config_model_deployment_20260708153000.json",
      "kind": "model-deployments",
      "count": 2,
      "runtime_key": null,
      "trigger_source_count": 0
    }
  ],
  "warnings": []
}
```

`download` 返回 zip：

```text
Content-Type: application/zip
Content-Disposition: attachment; filename="amvision_sdk_configs_project-1_20260708153000.zip"
```

请求体规划：

```json
{
  "include_access_token": true,
  "model_runtime_modes": ["sync"],
  "include_disabled_trigger_sources": true
}
```

字段说明：

- `include_access_token`：是否把当前请求的 user token 写入配置文件。默认 `true`；需要交付不带 token 的配置包时可显式传 `false`。
- `model_runtime_modes`：模型 deployment 生成哪些调用 key。默认 `["sync"]`；需要 async 现场调用时可选 `["sync", "async"]`。
- `include_disabled_trigger_sources`：是否导出已创建但未启用的 TriggerSource。默认 `true`，因为现场可能先导出配置，再由程序或界面启用。

权限：

- 需要当前主体可访问 Project。
- 读取 workflow runtime 和 TriggerSource 需要 `workflows:read`。
- 读取模型 deployment 需要 `models:read`。
- 如果写入当前 token，接口会在 manifest 中明确记录。

## 后端扫描规则

### Workflow 配置

后端按 Project 扫描：

- WorkflowAppRuntime 列表。
- WorkflowTriggerSource 列表。

分组规则：

- 以 WorkflowAppRuntime 为配置文件边界。
- 每个 runtime 生成一个 `config_workflow_{runtime_key}_{timestamp}.json`。
- 与该 runtime 绑定的 TriggerSource 写入同一文件的 `trigger_sources`。
- 同一 workflow app 如果有多个 runtime，就生成多个 workflow 配置文件，避免一个 key 对应多个 runtime。

生成内容只保留 Console 使用所需的最小字段：

```json
{
  "backend": {
    "base_api_url": "http://127.0.0.1:8000",
    "access_token": "amvision-default-user-token",
    "project_id": "project-1",
    "http_timeout_seconds": 60
  },
  "runtime": {
    "name": "yolo11m_barqrcode",
    "workflow_runtime_id": "workflow-runtime-xxx"
  },
  "invoke": {
    "image_path": "",
    "image_input_binding": "request_image_base64",
    "timeout_seconds": 30,
    "event_limit": 20,
    "event_preview_count": 5,
    "source": "amvision-workflows-console",
    "sync_scenario": "sync-invoke",
    "async_scenario": "async-run",
    "use_direct_input_bindings": false
  },
  "trigger_sources": [
    {
      "name": "zeromq_yolo11m_barqrcode",
      "trigger_source_id": "zeromq-workflow-runtime-xxx",
      "zero_mq": {
        "bind_endpoint": "tcp://127.0.0.1:5555",
        "default_input_binding": "request_image_ref",
        "timeout_seconds": 5
      }
    }
  ],
  "model_deployments": []
}
```

不写入以下创建和管理字段：

- `application_id`
- `execution_policy_id`
- workflow graph JSON。
- TriggerSource 创建 payload。
- `input_binding_mapping`。
- `result_mapping`。
- `transport_config` 完整原始对象。
- `pool_name`，除非 Console 当前模型明确需要该字段。ZeroMQ 调用阶段使用已经创建好的 TriggerSource，不重新创建 adapter。

### 模型 deployment 配置

后端按 Project 扫描已存在的模型 DeploymentInstance：

- detection：`/api/v1/models/detection/deployment-instances` 对应的数据源。
- classification、segmentation、pose、obb：统一模型任务 deployment 数据源。

所有模型 deployment 写入一个文件：

```text
Config/config_model_deployment_{timestamp}.json
```

该文件可以只包含 `backend` 和 `model_deployments`。实现生成接口时，必须同步确认 `sdks/dotnet/apps/Amvision.Workflows.Console` 的配置加载器支持 `runtime` 和 `invoke` 省略或为空。纯模型配置文件不能为了绕过校验写入假的 WorkflowAppRuntime。

文件结构：

```json
{
  "backend": {
    "base_api_url": "http://127.0.0.1:8000",
    "access_token": "amvision-default-user-token",
    "project_id": "project-1",
    "http_timeout_seconds": 60
  },
  "model_deployments": [
    {
      "name": "barcode_detector_sync",
      "task_type": "detection",
      "deployment_instance_id": "deployment-instance-xxx",
      "runtime_mode": "sync",
      "input_transport_mode": "memory",
      "score_threshold": 0.3,
      "save_result_image": false,
      "return_preview_image_base64": false,
      "default_image_path": "",
      "default_file_name": "image.jpg",
      "default_media_type": "image/jpeg"
    }
  ]
}
```

模型配置不写入创建部署相关字段：

- `model_version_id`
- `model_build_id`
- `runtime_backend`
- `runtime_precision`
- `device_name`
- `instance_count`
- `source_kind`
- 训练任务、转换任务和评估任务 id。

这些字段属于平台管理结果，不属于现场推理调用必需配置。

## zip 内容

下载包结构：

```text
amvision_sdk_configs_project-1_20260708153000.zip
├─ Config/
│  ├─ config_model_deployment_20260708153000.json
│  ├─ config_workflow_yolo11m_barqrcode_20260708153000.json
│  └─ config_workflow_other_runtime_20260708153000.json
├─ manifest.json
└─ README.md
```

`manifest.json` 用于给现场和测试程序快速确认导出内容：

```json
{
  "format_id": "amvision.sdk-config-package.v1",
  "generated_at": "2026-07-08T15:30:00+08:00",
  "project_id": "project-1",
  "base_api_url": "http://127.0.0.1:8000",
  "contains_access_token": true,
  "files": [
    {
      "path": "Config/config_model_deployment_20260708153000.json",
      "kind": "model-deployments",
      "count": 2
    },
    {
      "path": "Config/config_workflow_yolo11m_barqrcode_20260708153000.json",
      "kind": "workflow-runtime",
      "runtime_key": "yolo11m_barqrcode",
      "trigger_source_count": 1
    }
  ],
  "warnings": []
}
```

`README.md` 写入最小使用说明：

- 将 `Config/` 目录复制到 `Amvision.Workflows.Console` 程序目录。
- 如需更换现场账号，打开 `config_*.json` 替换 `backend.access_token`。
- 按 `Program.MainAsync` 中的 key 调用对应方法。
- 如果现场 endpoint、图片路径或 token 变化，只改配置文件，不改 SDK。

## key 生成和重复规则

后端生成 key 时使用短、稳定、可读的规则：

- workflow runtime key 优先使用 runtime display name 的业务部分，并去掉末尾的 `runtime`、`workflow_runtime` 和技术 id。
- TriggerSource key 优先使用 TriggerSource display name 的业务部分，并去掉末尾的 `runtime`、`trigger_source` 和技术 id。
- 模型 deployment key 优先使用 deployment display name 或模型名规范化结果。
- 遇到重复时追加 `_2`、`_3` 这类短后缀。
- 如果 display name 没有可用英文、数字或下划线内容，使用资源 id 的短兜底 key。

Console 启动时仍执行二次校验：

- `runtime.name` 必须唯一。
- `trigger_sources[].name` 必须唯一。
- `model_deployments[].name` 允许完全一致的重复配置合并去重。
- `model_deployments[].name` 如果重复但字段不同，启动时报错，不静默覆盖。

## base_api_url 和 token 规则

`backend.base_api_url` 由后端按以下顺序生成：

1. 运行配置中明确设置的公开 API 地址。
2. 当前 HTTP 请求推导出的 scheme、host 和 port。

`backend.access_token` 默认写入当前请求的 Bearer token：

```json
"access_token": "amvision-default-user-token"
```

当请求显式传入 `"include_access_token": false`，或当前请求没有可读取的 Bearer token 时，后端写入占位值：

```json
"access_token": "<replace-with-user-token>"
```

配置中包含真实 token 时，`manifest.json` 中设置：

```json
"contains_access_token": true
```

## 不做的事情

配置包生成接口不做以下事情：

- 不创建 WorkflowAppRuntime。
- 不创建 TriggerSource。
- 不创建或删除 DeploymentInstance。
- 不启动 runtime。
- 不启用 TriggerSource。
- 不修改 Project 配置。
- 不把前端表单状态直接序列化成 SDK 配置。
- 不把完整后端 `config*.json` 打包给第三方程序。
- 不把数据库内部字段、worker 内部状态或对象存储路径泄漏到 SDK 配置。

## 当前实现清单

1. 后端已新增 `sdk_config_packages` 应用服务和 Project 子路由。
2. 已接入 workflow runtime、TriggerSource、模型 deployment 的 Project 级查询。
3. 已调整 `Amvision.Workflows.Console` 配置加载器，支持纯模型 deployment 配置文件省略 `runtime`、`invoke` 和 `trigger_sources`。
4. 已实现 `preview` 接口，返回文件列表、数量和 warning。
5. 已实现 `download` 接口，返回 zip。
6. 项目工作台右上角已新增“生成 SDK 配置包”按钮。
7. 前端已调用 `preview`，有可导出文件时继续调用 `download`。
8. 已更新 `sdks/dotnet/apps/Amvision.Workflows.Console` README，说明配置可以由项目工作台导出。
9. 已增加后端 API 测试，校验 zip 文件名、manifest、Config 文件和 token 默认占位行为。

## 后续优化

- 如果需要把 `include_access_token`、`model_runtime_modes` 等选项交给用户选择，可在项目工作台按钮下增加轻量弹窗；入口位置仍保持唯一。
- 可补充无资源、重复 key 和多 runtime / 多 TriggerSource 的专项测试。

## 验收规则

- 项目工作台是唯一前端入口。
- 生成 zip 后，解压得到的 `Config/config_*.json` 可以直接被 `Amvision.Workflows.Console` 加载。
- 没有 workflow runtime 时仍能导出模型 deployment 配置。
- 没有模型 deployment 时仍能导出 workflow runtime 配置。
- 没有任何可导出资源时，preview 返回明确提示，不生成空 zip。
- 默认包含当前请求的真实 access token；显式关闭时写占位符。
- 如果用户选择包含 token，manifest 必须标记 `contains_access_token=true`。
- 重复 key 不被静默覆盖。
- 后端和前端测试覆盖 preview、download、无资源、重复 key 和 token 选项。
