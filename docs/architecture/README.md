# 架构文档总览

## 文档目的

本目录用于存放长期稳定的架构参考文档，覆盖目录结构、层级关系、模块边界和关键子系统职责。

本目录不承担接口实现说明、部署步骤清单或临时讨论记录。

## 当前文档

- [docs/architecture/system-overview.md](system-overview.md)：平台整体框架、一级模块、端到端流程和所需功能总览
- [docs/architecture/current-implementation-status.md](current-implementation-status.md)：当前主干已经落地的整体框架、主要代码落点、运行时矩阵和下一步收敛重点
- [docs/architecture/next-stage-roadmap.md](next-stage-roadmap.md)：当前阶段判断、本轮已收口事项、固定开发环境与下一阶段五条主线
- [docs/architecture/model-platform-plan.md](model-platform-plan.md)：多模型平台化路线，说明通用层、任务分类层、模型分类适配层和各模型分类的最小接入范围
- [docs/architecture/model-support-matrix.md](model-support-matrix.md)：当前主干代码里 `model_type × task_type × 导入/导出/训练/验证/评估/转换/部署/推理/workflow/前端` 的真实支持矩阵
- [docs/architecture/training-parameter-support.md](training-parameter-support.md)：训练参数的真实支持清单，分开说明公开接口、执行层实际使用参数、当前前端已暴露参数和缺口
- [docs/architecture/model-training-input-size-rules.md](model-training-input-size-rules.md)：固定 YOLOX / RF-DETR / YOLOv8 / YOLO11 / YOLO26 的训练输入尺寸规则、常用尺寸和前端训练页面展示约束
- [docs/architecture/model-task-naming-boundaries.md](model-task-naming-boundaries.md)：固定公开入口、模型实现层、模型系列共享层和通用值对象的命名边界
- [docs/architecture/model-core-implementation-plan.md](model-core-implementation-plan.md)：固定 YOLOX / YOLOv8 / YOLO11 / YOLO26 / RF-DETR 完整 core 的实现范围，并集中维护 YOLO full core 目录、任务拆分、参考映射、层级边界和验收规则
- [docs/architecture/model-full-core-audit-checklist.md](model-full-core-audit-checklist.md)：固定 RF-DETR / YOLOX / YOLOv8 / YOLO11 / YOLO26 的 full core 审计状态、过渡残留分类和进入 custom node 前的真实全链路验收清单
- [docs/architecture/code-structure-cleanup-plan.md](code-structure-cleanup-plan.md)：固定模型 core / runtime 之外的代码结构收口顺序和目标目录
- [docs/architecture/model-workflow-boundaries.md](model-workflow-boundaries.md)：模型接入、数据集、部署长期运行服务、workflow app 和 TriggerSource 之间的正式边界
- [docs/architecture/model-deployment-runtime-policy.md](model-deployment-runtime-policy.md)：模型发布时的平台部署策略、OpenVINO CPU / GPU / NPU 和 TensorRT 运行参数边界、硬件迁移规则与实施顺序
- [docs/architecture/model-artifact-provenance.md](model-artifact-provenance.md)：训练和转换模型产物的统一来源元数据、格式写入位置和证据链边界
- [docs/architecture/yoloe-sam3-node-assets.md](yoloe-sam3-node-assets.md)：YOLOE 与 SAM3 作为 custom node 扩展时的磁盘资产规则、manifest.json 字段和 payload 规则 约定
- [docs/architecture/video-workflow-node-plan.md](video-workflow-node-plan.md)：通用视频 payload 规则、core 视频节点、SAM3 视频/多帧分层边界和实现顺序
- [docs/architecture/industrial-rule-node-plan.md](industrial-rule-node-plan.md)：工业现场单帧判定优先的规则节点、结果回传节点和输入接入节点分批规划
- [docs/architecture/industrial-extension-node-plan.md](industrial-extension-node-plan.md)：工业现场扩展节点体系规划，重点细化相机、PLC、工业缺陷核心节点与 OpenCV 常用算子路线
- [docs/architecture/plc-modbus-field-debug-checklist.md](plc-modbus-field-debug-checklist.md)：当前 PLC Modbus 已实现能力、未实现能力和推荐现场联调顺序的短清单
- [docs/architecture/yoloe-sam3-workflow-app-operations.md](yoloe-sam3-workflow-app-operations.md)：YOLOE 与 SAM3 在 WorkflowAppRuntime 中的默认启用策略、接入顺序、观测入口、排障路径，以及 `metadata.phase` / `enabledByDefault` 的当前建议
- [docs/architecture/yoloe-sam3-soak-baseline.md](yoloe-sam3-soak-baseline.md)：YOLOE 与 SAM3 本地 CPU/GPU soak / benchmark 的显式执行方式、目标机器基线结果和当前稳定性判断
- [docs/architecture/websocket-architecture.md](websocket-architecture.md)：WebSocket 子系统的职责边界、版本化路由、事件流组织和重连规则
- [docs/architecture/execution-sequences.md](execution-sequences.md)：训练、转换、部署推理和 workflow execute 四条关键调用顺序图
- [docs/architecture/workflow-runtime.md](workflow-runtime.md)：workflow 编辑态试跑、已发布应用运行、队列划分、worker 拓扑和 API 草案
- [docs/architecture/workflow-editor-backend-checklist.md](workflow-editor-backend-checklist.md)：workflow 图编排前端所需的后端接口现状、本轮已补齐项和下一批执行清单
- [docs/architecture/workflow-parallel-branches.md](workflow-parallel-branches.md)：通用 Parallel 分支、受控并发、资源边界和 80 ROI / 3 实例现场配置
- [docs/architecture/workflow-runtime-phase1.md](workflow-runtime-phase1.md)：workflow runtime 第一阶段实现清单，收口状态机、snapshot 规则和 worker 消息规则
- [docs/architecture/workflow-runtime-phase2.md](workflow-runtime-phase2.md)：workflow runtime 第二阶段边界，收口 restart、instances、异步 runs 和 execution policies 的进入范围
- [docs/architecture/high-performance-image-data-plane.md](high-performance-image-data-plane.md)：固定上位机、ZeroMQ TriggerSource、LocalBufferBroker、workflow 节点和模型 runtime 之间的 BGR24 高性能图片数据面规则
- [docs/architecture/project-structure.md](project-structure.md)：项目目录结构、层级关系、模块关系和禁止直接耦合关系总览
- [docs/architecture/backend-service.md](backend-service.md)：后端服务职责、任务状态、执行调度、QueueBackend 和状态回写边界
- [docs/architecture/task-system.md](task-system.md)：统一任务实体、资源调度模型、任务 schema 和 worker pool 划分
- [docs/architecture/detection-model-rules.md](detection-model-rules.md)：检测类模型的最小平台规则，以及正式对象与 metadata 的边界
- [docs/architecture/yolox-module-design.md](yolox-module-design.md)：YOLOX 在 amvision 里的模块拆分、目录位置、当前代码落点和后续收敛方向
- [docs/architecture/frontend-web-ui.md](frontend-web-ui.md)：浏览器前端 Web UI 的模块划分、路由结构、状态组织和交互边界
- [docs/architecture/frontend-web-ui-structure.md](frontend-web-ui-structure.md)：浏览器前端 Web UI 的工程骨架、目录分层、LiteGraph 接入位置和组件层边界
- [docs/architecture/frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md)：浏览器前端 Web UI 的本地启动、默认用户、自动进入、登录页和退出规则
- [docs/architecture/frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)：浏览器前端 Web UI 真实编码前的准备检查、剩余缺口和开工顺序
- [docs/architecture/frontend-web-ui-workflows.md](frontend-web-ui-workflows.md)：浏览器前端 Web UI 的节点映射、业务页面流程、workflow app 调用和事件通信规则
- [docs/architecture/node-system.md](node-system.md)：节点系统、node pack 边界、custom node 模型和 ComfyUI 对齐方向
- [docs/architecture/workflow-json-contracts.md](workflow-json-contracts.md)：NodeDefinition、payload 规则、图模板与流程应用 JSON 规则
- [docs/architecture/data-and-files.md](data-and-files.md)：关键对象、文件引用和版本关系
- [docs/architecture/local-buffer-broker.md](local-buffer-broker.md)：LocalBufferBroker 本机高性能数据交换层，规划 Broker、mmap 文件池、ring buffer 和 workflow 推理调用边界
- [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)：DatasetImport、通用数据格式、任务类型格式矩阵和数据集导出规范
- [docs/architecture/dataset-export-formats.md](dataset-export-formats.md)：数据集导出格式列表、格式命名和模型默认格式映射
- [docs/architecture/runtime-packaging.md](runtime-packaging.md)：开发运行时、同目录 Python 发布运行时和发行装配结构

## 建议后续文档

- integration-rules.md：集成端点、协议适配和回调规则
- logs-and-metrics.md：任务日志、指标和告警
- ui-schema-and-extension.md：前端节点 UI schema、节点面板和结果展示扩展规范

## 存放规则

- 一份文档只写一个稳定主题
- 结构总览文档优先引用专题文档，不在单文件持续膨胀
- 子系统变化如果影响长期边界，先更新这里的文档，不要只写在提交说明里
- 架构决策的取舍过程不写入本目录正文，统一下沉到 [docs/decisions/README.md](../decisions/README.md) 对应的决策记录

## 推荐阅读路径

1. [docs/architecture/system-overview.md](system-overview.md)
2. [docs/architecture/current-implementation-status.md](current-implementation-status.md)
3. [docs/architecture/next-stage-roadmap.md](next-stage-roadmap.md)
4. [docs/architecture/model-platform-plan.md](model-platform-plan.md)
5. [docs/architecture/model-support-matrix.md](model-support-matrix.md)
6. [docs/architecture/training-parameter-support.md](training-parameter-support.md)
7. [docs/architecture/model-training-input-size-rules.md](model-training-input-size-rules.md)
8. [docs/architecture/model-task-naming-boundaries.md](model-task-naming-boundaries.md)
9. [docs/architecture/model-core-implementation-plan.md](model-core-implementation-plan.md)
10. [docs/architecture/model-full-core-audit-checklist.md](model-full-core-audit-checklist.md)
11. [docs/architecture/code-structure-cleanup-plan.md](code-structure-cleanup-plan.md)
12. [docs/architecture/model-workflow-boundaries.md](model-workflow-boundaries.md)
13. [docs/architecture/model-deployment-runtime-policy.md](model-deployment-runtime-policy.md)
14. [docs/architecture/yoloe-sam3-node-assets.md](yoloe-sam3-node-assets.md)
15. [docs/architecture/industrial-rule-node-plan.md](industrial-rule-node-plan.md)
16. [docs/architecture/industrial-extension-node-plan.md](industrial-extension-node-plan.md)
17. [docs/architecture/plc-modbus-field-debug-checklist.md](plc-modbus-field-debug-checklist.md)
18. [docs/architecture/yoloe-sam3-workflow-app-operations.md](yoloe-sam3-workflow-app-operations.md)
19. [docs/architecture/yoloe-sam3-soak-baseline.md](yoloe-sam3-soak-baseline.md)
20. [docs/architecture/execution-sequences.md](execution-sequences.md)
21. [docs/architecture/workflow-runtime.md](workflow-runtime.md)
22. [docs/architecture/workflow-editor-backend-checklist.md](workflow-editor-backend-checklist.md)
23. [docs/architecture/workflow-runtime-phase1.md](workflow-runtime-phase1.md)
24. [docs/architecture/workflow-runtime-phase2.md](workflow-runtime-phase2.md)
25. [docs/architecture/project-structure.md](project-structure.md)
26. [docs/architecture/backend-service.md](backend-service.md)
27. [docs/architecture/websocket-architecture.md](websocket-architecture.md)
28. [docs/architecture/task-system.md](task-system.md)
29. [docs/architecture/detection-model-rules.md](detection-model-rules.md)
30. [docs/architecture/yolox-module-design.md](yolox-module-design.md)
31. [docs/architecture/frontend-web-ui.md](frontend-web-ui.md)
32. [docs/architecture/frontend-web-ui-structure.md](frontend-web-ui-structure.md)
33. [docs/architecture/frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md)
34. [docs/architecture/frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)
35. [docs/architecture/frontend-web-ui-workflows.md](frontend-web-ui-workflows.md)
36. [docs/architecture/node-system.md](node-system.md)
37. [docs/architecture/workflow-json-contracts.md](workflow-json-contracts.md)
38. [docs/architecture/data-and-files.md](data-and-files.md)
39. [docs/architecture/local-buffer-broker.md](local-buffer-broker.md)
40. [docs/architecture/high-performance-image-data-plane.md](high-performance-image-data-plane.md)
41. [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)
42. [docs/architecture/dataset-export-formats.md](dataset-export-formats.md)
43. [docs/architecture/runtime-packaging.md](runtime-packaging.md)
44. 按任务继续进入集成规则或日志专题文档
