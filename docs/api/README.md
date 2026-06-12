# API 文档目录

## 文档目的

本目录用于存放对外公开接口文档，包括 REST API、WebSocket 消息、ZeroMQ TriggerSource 调用边界、SDK 使用边界和版本化接口说明。

## 当前文档

- [docs/api/current-api.md](current-api.md)：当前已经公开的 REST API、WebSocket 入口、鉴权头、本地鉴权输入、统一模型任务入口、workflow runtime 与 TriggerSource 规则的总览
- [docs/api/local-auth.md](local-auth.md)：本地用户、权限管理、session/refresh token、长期调用 user token、provider 目录和 auth.events 接口
- [docs/api/projects.md](projects.md)：system/bootstrap、Project 初始化、Project 目录项、Project summary 和公开文件读取接口
- [docs/architecture/websocket-architecture.md](../architecture/websocket-architecture.md)：当前 WebSocket 资源流、统一消息结构、控制事件和重连规则
- [docs/api/websocket-usage.md](websocket-usage.md)：第三方系统、HMI、嵌入式 UI 和前端界面接入公开 WebSocket 的连接顺序、恢复流程和最小客户端规则
- [docs/api/workflows.md](workflows.md)：workflow template/application、node catalog 和 workflow runtime 当前公开边界说明
- [docs/api/workflow-preview-runs.md](workflow-preview-runs.md)：WorkflowPreviewRun 的正式接口文档，覆盖编辑态快速试跑、sync/async wait_mode 和结果回查
- [docs/api/workflow-app-runtimes.md](workflow-app-runtimes.md)：WorkflowAppRuntime 的正式接口文档，覆盖长期运行单元的 create、list、get、delete、start、stop、restart、health、instances 和事件历史
- [docs/api/workflow-runs.md](workflow-runs.md)：WorkflowRun 的正式接口文档，覆盖 sync invoke、multipart invoke、async run create、multipart run create、事件历史和取消
- [docs/api/workflow-execution-policies.md](workflow-execution-policies.md)：WorkflowExecutionPolicy 的正式接口文档，覆盖 preview 和 runtime 的执行默认项
- [docs/api/workflow-runtime-drafts.md](workflow-runtime-drafts.md)：workflow runtime 当前公开文档和后续扩展草案的导航页
- [docs/api/workflow-trigger-sources.md](workflow-trigger-sources.md)：WorkflowTriggerSource 资源和 ZeroMQ adapter 的接口边界，覆盖外部触发入口、启停、health 和后续协议扩展
- [docs/api/trigger-source-sdks.md](trigger-source-sdks.md)：TriggerSource 外部调用方 SDK 规划，覆盖 C# / .NET、Python、Go 和 C SDK 的目录、调用流程和版本规则
- [docs/api/communication-contracts.md](communication-contracts.md)：REST API、WebSocket、ZeroMQ 的职责拆分与事件规则边界
- [docs/api/datasets-imports.md](datasets-imports.md)：DatasetImport 导入、详情查询、列表查询、task_id 关联和错误语义
- [docs/api/datasets-exports.md](datasets-exports.md)：DatasetExport 创建、详情查询、package/download/manifest 和 training 输入边界
- [docs/api/platform-base-models.md](platform-base-models.md)：平台基础模型列表、详情接口，以及 `warm_start_model_version_id` 的公开发现方式；当前目录登记已覆盖 YOLOX、YOLOv8/YOLO11/YOLO26 与 RF-DETR 预训练清单
- [docs/api/detection-training.md](detection-training.md)：当前 detection 训练、验证、转换、评估、部署和推理详细说明文档，统一模型任务入口以 [docs/api/current-api.md](current-api.md) 为准

### Workflow JSON 示例

- [docs/api/examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/save-template.request.json](examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/save-template.request.json)：workflow template save 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/save-application.request.json](examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/save-application.request.json)：FlowApplication save 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/preview-execution-policy.create.request.json](examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/preview-execution-policy.create.request.json)：preview-default WorkflowExecutionPolicy create 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/runtime-execution-policy.create.request.json](examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/runtime-execution-policy.create.request.json)：runtime-default WorkflowExecutionPolicy create 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/preview-run.request.json](examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/preview-run.request.json)：WorkflowPreviewRun create 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/app-runtime.create.request.json](examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/app-runtime.create.request.json)：WorkflowAppRuntime create 接口的真实路径 JSON 请求体示例
- [docs/api/examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/app-runtime.invoke.request.json](examples/workflows/00-short-dev-examples/detection_deployment_lifecycle_real_path/app-runtime.invoke.request.json)：WorkflowRun sync invoke 接口的真实路径 JSON 请求体示例

### Postman 调试入口

根目录 `docs/api/postman/` 只放通用控制面和按 task_type 拆开的 full-chain collection。历史 `detection-training.postman_collection.json` 已由 `detection-full-chain.postman_collection.json` 取代；本地调试数据包统一放在 `data/files/postman-assets/`，不纳入 git。

#### 通用控制面

- [docs/api/postman/workflow-runtime.postman_collection.json](postman/workflow-runtime.postman_collection.json)：workflow runtime 通用控制面 Postman collection，覆盖 system/bootstrap、projects/bootstrap、projects 目录与文件读取、template/application save/get/list、execution-policies、preview-runs、app-runtimes、restart、instances、sync invoke、async runs 和 cancel 最小链路，并给主要列表请求补齐 offset/limit 示例
- [docs/api/postman/local-auth.postman_collection.json](postman/local-auth.postman_collection.json)：本地用户、权限管理、session/refresh token 和长期调用 user token 的 Postman collection，覆盖 provider 目录、bootstrap、login、refresh、用户管理、密码重置、token 管理、system/me 和 system/bootstrap 调试链路

#### Workflow 场景

- [docs/api/postman/workflows/README.md](postman/workflows/README.md)：按正式 workflow 与 TriggerSource 场景拆分的调试目录说明，包含依赖关系、建议联调顺序和对应 collection 清单
- [docs/api/postman/workflows/00-short-dev-examples/00-workflow-example-documents.postman_collection.json](postman/workflows/00-short-dev-examples/00-workflow-example-documents.postman_collection.json)：把 docs/examples/workflows 下现有 template/application 示例按目录分组的保存与读取调试 collection
- [docs/api/postman/workflows/01-detection-end-to-end-qr-crop-remap/01-detection-end-to-end-qr-crop-remap.postman_collection.json](postman/workflows/01-detection-end-to-end-qr-crop-remap/01-detection-end-to-end-qr-crop-remap.postman_collection.json)：第一类检测 workflow 场景链，串起导入、导出、训练、评估、转换、部署和 QR remap；更适合作为 workflow 编排联调，不替代根目录 detection 全链路 collection
- [docs/api/postman/workflows/02-detection-deployment-sync-infer-health/02-detection-deployment-sync-infer-health.postman_collection.json](postman/workflows/02-detection-deployment-sync-infer-health/02-detection-deployment-sync-infer-health.postman_collection.json)：第二类 start、warmup、sync infer、health 联调 collection
- [docs/api/postman/workflows/03-detection-deployment-qr-crop-remap/03-detection-deployment-qr-crop-remap.postman_collection.json](postman/workflows/03-detection-deployment-qr-crop-remap/03-detection-deployment-qr-crop-remap.postman_collection.json)：第三类检测、AOI crop、二维码识别和原图回绘联调 collection
- [docs/api/postman/workflows/04-detection-deployment-infer-opencv-health/04-detection-deployment-infer-opencv-health.postman_collection.json](postman/workflows/04-detection-deployment-infer-opencv-health/04-detection-deployment-infer-opencv-health.postman_collection.json)：第四类 sync infer、health 和 OpenCV 处理联调 collection
- [docs/api/postman/workflows/05-opencv-process-save-image/05-opencv-process-save-image.postman_collection.json](postman/workflows/05-opencv-process-save-image/05-opencv-process-save-image.postman_collection.json)：第五类 OpenCV 处理、图片保存和默认 HTTP 返回联调 collection
- [docs/api/postman/workflows/06-detection-deployment-infer-opencv-health-zeromq-image-ref/06-detection-deployment-infer-opencv-health-zeromq-image-ref.postman_collection.json](postman/workflows/06-detection-deployment-infer-opencv-health-zeromq-image-ref/06-detection-deployment-infer-opencv-health-zeromq-image-ref.postman_collection.json)：第六类同 app HTTP base64 + ZeroMQ image-ref 检测推理联调 collection
- [docs/api/postman/workflows/07-opencv-process-save-image-zeromq-image-ref/07-opencv-process-save-image-zeromq-image-ref.postman_collection.json](postman/workflows/07-opencv-process-save-image-zeromq-image-ref/07-opencv-process-save-image-zeromq-image-ref.postman_collection.json)：第七类同 app HTTP base64 + ZeroMQ image-ref OpenCV 处理联调 collection
- [docs/api/postman/workflows/08-plc-register-modbus-tcp-async-result-record/08-plc-register-modbus-tcp-async-result-record.postman_collection.json](postman/workflows/08-plc-register-modbus-tcp-async-result-record/08-plc-register-modbus-tcp-async-result-record.postman_collection.json)：第八类 `plc-register` Modbus TCP polling + async submit + result-record / http-post 回传联调 collection
- [docs/api/postman/workflows/09-industrial-local-directory-watch-detection-position-gate/09-industrial-local-directory-watch-detection-position-gate.postman_collection.json](postman/workflows/09-industrial-local-directory-watch-detection-position-gate/09-industrial-local-directory-watch-detection-position-gate.postman_collection.json)：第九类 `directory-watch` 目录事件监听 + 工业检测位置门控联调 collection
- [docs/api/postman/workflows/09-industrial-local-directory-watch-detection-position-gate/README.md](postman/workflows/09-industrial-local-directory-watch-detection-position-gate/README.md)：第九类 `directory-watch` TriggerSource collection 的变量说明、推荐联调顺序和现场排查重点
- [docs/api/postman/workflows/10-industrial-single-frame-glue-roi-delivery-bundle/10-industrial-single-frame-glue-roi-delivery-bundle.postman_collection.json](postman/workflows/10-industrial-single-frame-glue-roi-delivery-bundle/10-industrial-single-frame-glue-roi-delivery-bundle.postman_collection.json)：第十类工业单帧规则判定 + PLC/JSON/CSV/MES/local-db 结果交付联调 collection
- [docs/api/postman/workflows/10-industrial-single-frame-glue-roi-delivery-bundle/README.md](postman/workflows/10-industrial-single-frame-glue-roi-delivery-bundle/README.md)：第十类工业单帧结果交付 collection 的变量说明、联调顺序和现场落地说明
- [docs/api/postman/workflows/11-industrial-local-directory-poll-detection-position-gate/11-industrial-local-directory-poll-detection-position-gate.postman_collection.json](postman/workflows/11-industrial-local-directory-poll-detection-position-gate/11-industrial-local-directory-poll-detection-position-gate.postman_collection.json)：第十一类 `directory-poll` 固定周期目录轮询 + 工业检测位置门控联调 collection
- [docs/api/postman/workflows/11-industrial-local-directory-poll-detection-position-gate/README.md](postman/workflows/11-industrial-local-directory-poll-detection-position-gate/README.md)：第十一类 `directory-poll` TriggerSource collection 的变量说明、推荐联调顺序和现场排查重点
- [docs/api/postman/workflows/12-segmentation-deployment-sync-regions-gate/12-segmentation-deployment-sync-regions-gate.postman_collection.json](postman/workflows/12-segmentation-deployment-sync-regions-gate/12-segmentation-deployment-sync-regions-gate.postman_collection.json)：第十二类 segmentation direct model 同步推理、`segments.v1 -> regions.v1` 桥接和最小工业规则联调 collection
- [docs/api/postman/workflows/13-classification-deployment-sync-class-gate/13-classification-deployment-sync-class-gate.postman_collection.json](postman/workflows/13-classification-deployment-sync-class-gate/13-classification-deployment-sync-class-gate.postman_collection.json)：第十三类 classification direct model 同步推理、top class 判定和最小工业规则联调 collection
- [docs/api/postman/workflows/14-pose-deployment-sync-presence-gate/14-pose-deployment-sync-presence-gate.postman_collection.json](postman/workflows/14-pose-deployment-sync-presence-gate/14-pose-deployment-sync-presence-gate.postman_collection.json)：第十四类 pose direct model 同步推理、count/score presence 判定和最小工业规则联调 collection
- [docs/api/postman/workflows/15-obb-deployment-sync-angle-gate/15-obb-deployment-sync-angle-gate.postman_collection.json](postman/workflows/15-obb-deployment-sync-angle-gate/15-obb-deployment-sync-angle-gate.postman_collection.json)：第十五类 OBB direct model 同步推理、angle range 判定和最小工业规则联调 collection

#### 根目录全链路与模型入口

- [docs/api/postman/datasets-imports.postman_collection.json](postman/datasets-imports.postman_collection.json)：当前公开的 system/bootstrap、projects/bootstrap、Project 目录、DatasetImport、tasks 接口 Postman collection
- [docs/api/postman/datasets-exports.postman_collection.json](postman/datasets-exports.postman_collection.json)：当前公开的 DatasetExport 格式规则、导出创建、详情、打包和下载接口 Postman collection
- [docs/api/postman/platform-base-models.postman_collection.json](postman/platform-base-models.postman_collection.json)：当前公开的平台基础模型 list/detail 接口 Postman collection
- [docs/api/postman/detection-full-chain.postman_collection.json](postman/detection-full-chain.postman_collection.json)：detection 全链路 Postman collection，覆盖 dataset import、dataset export、training、validation、evaluation、conversion、deployment、infer 和 workflow invoke；当前支持 `yolox`、`yolov8`、`yolo11`、`yolo26`、`rfdetr`
- [docs/api/postman/segmentation-full-chain.postman_collection.json](postman/segmentation-full-chain.postman_collection.json)：segmentation 全链路 Postman collection，覆盖 dataset import、dataset export、training、validation、evaluation、conversion、deployment、infer 和 workflow invoke；当前支持 `yolov8`、`yolo11`、`yolo26`、`rfdetr`
- [docs/api/postman/classification-full-chain.postman_collection.json](postman/classification-full-chain.postman_collection.json)：classification 全链路 Postman collection，覆盖 dataset import、dataset export、training、validation、evaluation、conversion、deployment、infer 和 workflow invoke；当前支持 `yolov8`、`yolo11`、`yolo26`
- [docs/api/postman/pose-full-chain.postman_collection.json](postman/pose-full-chain.postman_collection.json)：pose 全链路 Postman collection，覆盖 dataset import、dataset export、training、validation、evaluation、conversion、deployment、infer 和 workflow invoke；当前支持 `yolov8`、`yolo11`、`yolo26`
- [docs/api/postman/obb-full-chain.postman_collection.json](postman/obb-full-chain.postman_collection.json)：OBB 全链路 Postman collection，覆盖 dataset import、dataset export、training、validation、evaluation、conversion、deployment、infer 和 workflow invoke；当前支持 `yolov8`、`yolo11`、`yolo26`
- [docs/api/postman/local-debug-assets.md](postman/local-debug-assets.md)：full-chain collection 本地调试数据包说明；默认路径使用 `data/files/postman-assets/`，不纳入 git
- `docs/api/postman/workflows/12-*` 到 `15-*` 继续只表示 segmentation / classification / pose / OBB 的 workflow/runtime 使用面，不替代上面的全生命周期联调集合
- [docs/architecture/backend-service.md](../architecture/backend-service.md)：FastAPI 应用分层、路由拆分、数据库会话、权限和中间件骨架

## 设计草案

下列文档用于承接 workflow runtime 的后续扩展设计。preview-runs、app-runtimes 和 runs 的当前实现已经转为正式文档，不再放在草案列表中。

- [docs/api/workflow-persona-profiles.md](workflow-persona-profiles.md)：PersonaProfile 资源的接口草案，覆盖 AI 节点的人格、口吻和系统提示模板
- [docs/api/workflow-tool-policies.md](workflow-tool-policies.md)：ToolPolicy 资源的接口草案，覆盖 AI 节点可用工具集合和调用上限
- [docs/architecture/workflow-runtime-phase2.md](../architecture/workflow-runtime-phase2.md)：workflow runtime 第二阶段边界，收口 restart、instances、异步 runs 和 execution policies 的进入范围

## 建议内容

- REST 资源与版本说明
- WebSocket 事件类型与订阅主题清单
- ZeroMQ 高速触发和图片提交主题与消息约束
- 外部调用方 SDK 的协议规则、语言实现和示例
- 错误码、分页、鉴权和兼容性说明
- Postman collection 与最小调试示例

## 存放规则

- 只记录公开接口与规则，不展开内部实现细节
- 一旦接口公开，文档更新与行为变更同步进行
- 版本差异单独标注，不在同一段落混写多版本行为
