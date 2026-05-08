# API 文档目录

## 文档目的

本目录用于存放对外公开接口文档，包括 REST API、WebSocket 消息和版本化接口说明。ZeroMQ 边界尚未形成当前公开协议面时，不在本目录展开。

## 当前文档

- [docs/api/current-api.md](current-api.md)：当前已经公开的 REST API、WebSocket 入口、鉴权头和任务事件订阅规则
- [docs/api/workflows.md](workflows.md)：workflow template/application validate、save、get 接口，以及 workflow runtime phase1 的当前公开边界说明
- [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)：WorkflowPreviewRun 的正式接口文档，覆盖编辑态快速试跑和结果回查
- [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md)：WorkflowAppRuntime 的正式接口文档，覆盖长期运行单元的 create、list、get、start、stop、restart、health 和 instances
- [docs/api/workflow-runs.md](workflow-runs.md)：WorkflowRun 的正式接口文档，覆盖 sync invoke 和 run 结果回查
- [docs/api/workflow-runtime-drafts.md](workflow-runtime-drafts.md)：workflow runtime 当前公开文档和后续扩展草案的导航页
- [docs/api/communication-contracts.md](communication-contracts.md)：REST API、WebSocket、ZeroMQ 的职责拆分与事件规则边界
- [docs/api/datasets-imports.md](datasets-imports.md)：DatasetImport 导入、详情查询、列表查询、task_id 关联和错误语义
- [docs/api/datasets-exports.md](datasets-exports.md)：DatasetExport 创建、详情查询、package/download/manifest 和 training 输入边界
- [docs/api/platform-base-models.md](platform-base-models.md)：平台基础模型列表、详情接口，以及 warm_start_model_version_id 的公开发现方式
- [docs/api/yolox-training.md](yolox-training.md)：YOLOX training 创建、列表、详情、训练控制、指标与输出文件读取接口，以及 validation-sessions 人工验证、conversion-tasks 模型转换、evaluation-tasks 数据集级评估、deployment-instances 和 inference-tasks 正式推理接口
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-template.request.json)：workflow template save 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.save-application.request.json)：FlowApplication save 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.preview-run.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.preview-run.request.json)：WorkflowPreviewRun create 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.create.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.create.request.json)：WorkflowAppRuntime create 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.invoke.request.json](examples/workflows/yolox_deployment_detection_lifecycle_real_path.app-runtime.invoke.request.json)：WorkflowRun sync invoke 接口的真实路径 JSON 请求体示例
- [docs/api/postman/workflow-runtime.postman_collection.json](postman/workflow-runtime.postman_collection.json)：workflow runtime 当前联调的独立 Postman collection，覆盖 preview-runs、app-runtimes、restart、instances 和 runs 最小链路
- [docs/api/postman/datasets-imports.postman_collection.json](postman/datasets-imports.postman_collection.json)：当前公开的 system、DatasetImport、tasks 接口 Postman collection
- [docs/api/postman/datasets-exports.postman_collection.json](postman/datasets-exports.postman_collection.json)：当前公开的 DatasetExport 接口 Postman collection
- [docs/api/postman/platform-base-models.postman_collection.json](postman/platform-base-models.postman_collection.json)：当前公开的平台基础模型 list/detail 接口 Postman collection
- [docs/api/postman/yolox-training.postman_collection.json](postman/yolox-training.postman_collection.json)：当前公开的 YOLOX training、validation-sessions、conversion-tasks、evaluation-tasks、deployment-instances 和 inference-tasks 接口 Postman collection
- [docs/architecture/backend-service.md](../architecture/backend-service.md)：FastAPI 应用分层、路由拆分、数据库会话、权限和中间件骨架

## 设计草案

下列文档用于承接 workflow runtime 的后续扩展设计。preview-runs、app-runtimes 和 runs 的当前实现已经转为正式文档，不再放在草案列表中。

- [docs/api/workflow-execution-policies.md](workflow-execution-policies.md)：WorkflowExecutionPolicy 资源的接口草案，覆盖 preview 和 runtime 的执行默认项
- [docs/api/workflow-persona-profiles.md](workflow-persona-profiles.md)：PersonaProfile 资源的接口草案，覆盖 AI 节点的人格、口吻和系统提示模板
- [docs/api/workflow-tool-policies.md](workflow-tool-policies.md)：ToolPolicy 资源的接口草案，覆盖 AI 节点可用工具集合和调用上限
- [docs/architecture/workflow-runtime-phase2.md](../architecture/workflow-runtime-phase2.md)：workflow runtime 第二阶段边界，收口 restart、instances、异步 runs 和 execution policies 的进入范围

## 建议内容

- REST 资源与版本说明
- WebSocket 事件类型与订阅主题清单
- ZeroMQ 本地 IPC 主题与消息约束
- 错误码、分页、鉴权和兼容性说明
- Postman collection 与最小调试示例

## 存放规则

- 只记录公开接口与规则，不展开内部实现细节
- 一旦接口公开，文档更新与行为变更同步进行
- 版本差异单独标注，不在同一段落混写多版本行为