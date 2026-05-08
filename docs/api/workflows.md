# Workflow 接口文档

## 文档目的

本文档用于说明当前已经公开的 workflow template 与 FlowApplication 接口，以及 workflow runtime 第一阶段已经公开的资源边界。

本文档聚焦对外接口规则、真实存储路径和最小请求体例子，不展开执行器内部实现细节。

## 适用范围

- workflow template validate、save、get 接口
- FlowApplication validate、save、get 接口
- WorkflowPreviewRun、WorkflowAppRuntime、WorkflowRun 的第一阶段公开边界
- workflow 请求头鉴权规则
- workflow service 节点语义分组
- 真实 workflow object key 路径
- 独立 JSON 请求体示例

## 相关 runtime 文档

workflow runtime 控制面在第一阶段已经公开 preview-runs、app-runtimes 和 runs 三类路径；后续扩展设计继续保留在独立草案文档中。

当前公开接口与后续扩展的导航页见 [docs/api/workflow-runtime-drafts.md](workflow-runtime-drafts.md)。

- [docs/api/workflow-runtime-drafts.md](workflow-runtime-drafts.md)
- [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)
- [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md)
- [docs/api/workflow-runs.md](workflow-runs.md)
- [docs/api/workflow-execution-policies.md](workflow-execution-policies.md)
- [docs/api/workflow-persona-profiles.md](workflow-persona-profiles.md)
- [docs/api/workflow-tool-policies.md](workflow-tool-policies.md)

## service 节点语义

当前 workflow 中直接复用后端服务能力的节点分成两组：

- 任务节点：例如 core.service.yolox-training.submit、core.service.yolox-conversion.submit、core.service.yolox-evaluation.submit、core.service.dataset-export.submit、core.service.yolox-inference.submit。这组节点直接调用现有应用服务并提交后台任务，训练、转换、评估、导出和异步推理仍由独立 worker 与 queue backend 执行。
- deployment 资源与控制节点：core.service.yolox-deployment.create 负责创建 DeploymentInstance 资源；core.service.yolox-deployment.start、warmup、status、health、stop、reset 负责控制或观察已有 deployment 运行态。这组节点控制的是 backend-service 已装配的 deployment control plane，在 preview-run 或 app-runtime 固定 snapshot 内执行，不会临时发布另一套 deployment 服务。

## 接口入口

- FastAPI Swagger UI：/docs
- FastAPI OpenAPI JSON：/openapi.json
- 版本前缀：/api/v1
- 资源分组：/workflows

## 鉴权规则

### 最小请求头

- x-amvision-principal-id：调用主体 id
- x-amvision-project-ids：当前主体可访问的 Project id 列表，多个值用逗号分隔；为空时表示不按 Project 做可见性裁剪
- x-amvision-scopes：当前主体持有的 scope 列表，多个值用逗号分隔

### scope 要求

- template/application 的 validate、get，以及 preview-runs、app-runtimes、runs 的读取接口需要 workflows:read
- template/application 的 save，以及 preview-runs create、app-runtimes create/start/stop/invoke 需要 workflows:write
- 如果需要先查询可用 deployment_instance_id，还需要 models:read 和 models:write

## 真实 workflow 路径

当前 workflow 文件保存到 LocalDatasetStorage，路径规则固定如下：

- template：workflows/projects/{project_id}/templates/{template_id}/versions/{template_version}/template.json
- application：workflows/projects/{project_id}/applications/{application_id}/application.json
- preview snapshot：workflows/runtime/preview-runs/{preview_run_id}/
- app runtime snapshot：workflows/runtime/app-runtimes/{workflow_runtime_id}/

本文档配套的 deployment lifecycle detection 手工调试示例使用下面这组真实 object key：

- template object key：workflows/projects/project-1/templates/yolox-deployment-detection-lifecycle-real-path/versions/1.0.0/template.json
- application object key：workflows/projects/project-1/applications/yolox-deployment-detection-lifecycle-real-path-app/application.json

## 独立 JSON 示例

下面两份文件是可直接拷贝到 HTTP 客户端请求体中的独立 JSON 示例：

- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json)

上面这组 JSON 的特点是：

- template 与 application 使用真实 workflow object key 路径
- application.template_ref.source_uri 直接写成真实 template object key
- deployment_instance_id 保留为占位字符串，需要替换成真实可用实例 id
- 当前示例只覆盖 template/application 持久化输入边界，runtime 调用路径见 current-api 总览

## 接口清单

### POST /api/v1/workflows/templates/validate

- Content-Type：application/json
- 需要 workflows:read
- 请求体字段：
  - template
- 成功状态码：200 OK
- 返回字段：
  - valid
  - template_id
  - template_version
  - node_count
  - edge_count
  - template_input_ids
  - template_output_ids
  - referenced_node_type_ids

### PUT /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version}

- Content-Type：application/json
- 需要 workflows:write
- 路径参数中的 template_id 和 template_version 必须与请求体中的 template 一致
- 成功状态码：201 Created
- 返回字段：
  - project_id
  - object_key
  - template
  - validate 接口中的同名校验摘要字段

### GET /api/v1/workflows/projects/{project_id}/templates/{template_id}/versions/{template_version}

- 需要 workflows:read
- 返回字段：
  - project_id
  - object_key
  - template
  - validate 接口中的同名校验摘要字段

### POST /api/v1/workflows/applications/validate

- Content-Type：application/json
- 需要 workflows:read
- 请求体字段：
  - project_id
  - application
  - template，可选
- 当 template 为空时，服务会按 application.template_ref 读取已保存 template
- 成功状态码：200 OK
- 返回字段：
  - valid
  - application_id
  - template_id
  - template_version
  - binding_count
  - input_binding_ids
  - output_binding_ids

### PUT /api/v1/workflows/projects/{project_id}/applications/{application_id}

- Content-Type：application/json
- 需要 workflows:write
- 路径参数中的 application_id 必须与请求体中的 application.application_id 一致
- 成功状态码：201 Created
- 服务保存 application 时会把 application.template_ref.source_uri 规范化为实际保存后的 template object key
- 返回字段：
  - project_id
  - object_key
  - application
  - validate 接口中的同名校验摘要字段

### GET /api/v1/workflows/projects/{project_id}/applications/{application_id}

- 需要 workflows:read
- 返回字段：
  - project_id
  - object_key
  - application
  - validate 接口中的同名校验摘要字段

## workflow runtime phase1 当前公开路径

- POST /api/v1/workflows/preview-runs：创建并同步执行一次 WorkflowPreviewRun
- GET /api/v1/workflows/preview-runs/{preview_run_id}：读取一条 WorkflowPreviewRun
- POST /api/v1/workflows/app-runtimes：创建一条 WorkflowAppRuntime
- GET /api/v1/workflows/app-runtimes：按 Project 列出 WorkflowAppRuntime
- GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}：读取一条 WorkflowAppRuntime
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/start：启动单实例 runtime worker
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop：停止单实例 runtime worker
- GET /api/v1/workflows/app-runtimes/{workflow_runtime_id}/health：查询 runtime 当前健康状态
- POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke：通过 runtime 发起一次同步调用
- GET /api/v1/workflows/runs/{workflow_run_id}：读取一条 WorkflowRun

这组路径的字段、状态和最小返回规则见 [docs/api/current-api.md](current-api.md) 与 [docs/architecture/workflow-runtime-phase1.md](../architecture/workflow-runtime-phase1.md)。

## 当前边界说明

- 旧的 FlowApplication execute 路由已经删除，不再作为公开兼容入口。
- 编辑态试跑与已发布应用运行已经拆成 PreviewRun、AppRuntime、WorkflowRun 三类资源。
- 第一阶段只支持单实例、start、stop、health、sync invoke；不展开异步 WorkflowRun 队列。

## 常见调试点

- Save Flow Application 成功后，如果返回体里的 application.template_ref.source_uri 与请求体不同，以返回体里的规范化 object key 为准
- PreviewRun 或 WorkflowRun 使用图片 object_key 失败时，优先检查 data/files 下是否真的有对应文件
- PreviewRun 和 WorkflowRun 都不会在 workflow worker 里重新发布 deployment 服务；如果 start、warmup、health、stop 行为异常，应优先检查 backend-service 当前进程里的 deployment supervisor 是否已经完成启动
- detection 节点当前把 auto_start_process 设为 false，目的是让 workflow 明确依赖前面的 start 节点；如果跳过 start 或 warmup，预期会在 detection 处暴露 deployment 运行状态问题
- 当前示例只覆盖 sync deployment detection 链路，不覆盖 async inference-tasks

## 相关文件

- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.preview-run.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.preview-run.request.json)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.create.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.create.request.json)
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.invoke.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.invoke.request.json)
- [docs/api/postman/workflow-runtime.postman_collection.json](postman/workflow-runtime.postman_collection.json)
- [docs/api/current-api.md](current-api.md)
- [docs/architecture/workflow-json-contracts.md](../architecture/workflow-json-contracts.md)
- [docs/architecture/workflow-runtime-phase1.md](../architecture/workflow-runtime-phase1.md)