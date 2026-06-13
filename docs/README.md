# 文档体系总览

## 文档目的

本文档作为仓库文档总入口，用于定义文档分层、保存位置和推荐阅读路径。

本文档解决的问题不是系统实现，而是文档如何长期存放、如何被检索以及如何避免不同类型的信息混在同一份文件中。

## 文档分层

- 根目录 [AGENTS.md](../AGENTS.md) 说明项目长期约束、技术基线、agent 路由和文档入口
- [docs/documentation-remediation-roadmap.md](documentation-remediation-roadmap.md) 说明文档整改顺序和维护规则
- [docs/architecture/README.md](architecture/README.md) 汇总架构和模块边界文档
- [docs/architecture/current-implementation-status.md](architecture/current-implementation-status.md) 汇总当前主干已经落地的整体框架、代码落点和下一步收敛重点
- [docs/architecture/next-stage-roadmap.md](architecture/next-stage-roadmap.md) 汇总当前阶段判断、本轮已收口事项、固定开发环境与下一阶段五条主线
- [docs/architecture/model-platform-plan.md](architecture/model-platform-plan.md) 汇总多模型平台化路线、任务分类拆分和各模型分类接入顺序
- [docs/architecture/model-support-matrix.md](architecture/model-support-matrix.md) 汇总当前主干代码里 `model_type × task_type × 导入/导出/训练/验证/评估/转换/部署/推理/workflow/前端` 的真实支持矩阵
- [docs/architecture/training-parameter-support.md](architecture/training-parameter-support.md) 汇总训练参数的真实支持清单，分开说明公开接口、执行层实际使用参数、当前前端已暴露参数和缺口
- [docs/architecture/model-task-naming-boundaries.md](architecture/model-task-naming-boundaries.md) 固定公开入口、模型实现层、模型系列共享层和通用值对象的命名边界
- [docs/architecture/model-core-implementation-plan.md](architecture/model-core-implementation-plan.md) 固定 YOLOv8 / YOLO11 / YOLO26 / RF-DETR 在本项目中的完整 core 实现边界，并集中维护 YOLO full core 目录、任务拆分、参考映射和验收规则
- [docs/architecture/yolo-model-plan.md](architecture/yolo-model-plan.md) 汇总 YOLO 系列模型的参考源码边界、层级关系、任务分类拆分、模型分类适配和进入顺序
- [docs/architecture/model-workflow-boundaries.md](architecture/model-workflow-boundaries.md) 汇总模型接入、数据集、部署长期运行服务、workflow app 和 TriggerSource 之间的正式边界
- [docs/architecture/yoloe-sam3-node-assets.md](architecture/yoloe-sam3-node-assets.md) 汇总 YOLOE 与 SAM3 custom node 的磁盘资产规则、manifest.json 字段和 payload 规则 约定
- [docs/architecture/video-workflow-node-plan.md](architecture/video-workflow-node-plan.md) 汇总通用视频 payload 规则、core 视频节点、SAM3 视频/多帧分层边界和实现顺序
- [docs/architecture/industrial-rule-node-plan.md](architecture/industrial-rule-node-plan.md) 汇总工业现场单帧判定优先的规则节点、结果回传节点和输入接入节点分批规划
- [docs/architecture/industrial-extension-node-plan.md](architecture/industrial-extension-node-plan.md) 汇总工业扩展节点体系规划，重点细化相机、PLC、工业缺陷核心节点和 OpenCV 常用算子路线
- [docs/architecture/plc-modbus-field-debug-checklist.md](architecture/plc-modbus-field-debug-checklist.md) 汇总当前 PLC Modbus 已实现能力、未实现能力和推荐现场联调顺序
- [docs/architecture/yoloe-sam3-workflow-app-operations.md](architecture/yoloe-sam3-workflow-app-operations.md) 汇总 YOLOE 与 SAM3 在 workflow app 中的默认启用策略、接入顺序、观测入口和 phase / enabledByDefault 解释
- [docs/architecture/websocket-architecture.md](architecture/websocket-architecture.md) 汇总 WebSocket 子系统的职责、路由分层、重连规则和资源流规划
- [docs/api/websocket-usage.md](api/websocket-usage.md) 汇总第三方系统、HMI、嵌入式 UI 和前端界面接入公开 WebSocket 的连接顺序与恢复流程
- [docs/architecture/execution-sequences.md](architecture/execution-sequences.md) 汇总训练、转换、部署推理和 workflow execute 四条关键调用顺序图
- [docs/architecture/workflow-runtime.md](architecture/workflow-runtime.md) 汇总 workflow 编辑态试跑、已发布应用运行、队列划分、worker 拓扑和 API 草案
- [docs/architecture/local-buffer-broker.md](architecture/local-buffer-broker.md) 汇总 LocalBufferBroker 本机高性能数据交换层、mmap 文件池、ring buffer 和 workflow 推理调用边界
- [docs/architecture/frontend-web-ui-structure.md](architecture/frontend-web-ui-structure.md) 汇总浏览器前端 Web UI 的工程骨架、目录分层、LiteGraph 接入位置和组件层边界
- [docs/architecture/frontend-web-ui-startup-session.md](architecture/frontend-web-ui-startup-session.md) 汇总浏览器前端 Web UI 的本地启动、默认用户、自动进入、登录页和退出规则
- [docs/architecture/frontend-web-ui-development-readiness.md](architecture/frontend-web-ui-development-readiness.md) 汇总浏览器前端 Web UI 真实编码前的准备检查、剩余缺口和开工顺序
- [docs/architecture/frontend-web-ui-workflows.md](architecture/frontend-web-ui-workflows.md) 汇总浏览器前端 Web UI 的节点映射、业务页面流程、workflow app 调用和事件通信规则
- [docs/api/README.md](api/README.md) 汇总 REST API、WebSocket、ZeroMQ 和公开接口文档
- [docs/api/trigger-source-sdks.md](api/trigger-source-sdks.md) 汇总 TriggerSource 外部调用方 SDK 的目录、流程和语言实现边界
- [docs/examples/workflows/README.md](examples/workflows/README.md) 说明 workflow template/application 源 JSON 与 LocalBufferBroker 输入形状的关系
- [docs/deployment/README.md](deployment/README.md) 汇总开发环境、运行时、打包、安装和部署文档
- [docs/operations/README.md](operations/README.md) 汇总现场运维、排障和受控上线手册
- [docs/operations/release-full-troubleshooting.md](operations/release-full-troubleshooting.md) 汇总 `release/full/` 的日志入口、worker profile 检查点和现场排障顺序
- [docs/nodes/README.md](nodes/README.md) 汇总 node pack、custom node 和 runtime hook 专题文档
- [docs/architecture/node-system.md](architecture/node-system.md) 汇总 node pack、custom node 和扩展机制文档
- [docs/decisions/README.md](decisions/README.md) 汇总架构决策记录

## 保存原则

- 一类信息只放在一个稳定位置，避免相同内容在多个文档重复维护
- 长期参考文档与阶段性决策记录分开存放
- 入口文档保持简明，展开内容下沉到专题文档
- 文档按主题和边界组织，不按个人或临时任务组织
- 对版本敏感的内容必须明确适用范围或迁移说明

## 命名和写法规则

- 模块名、目录名、对象名尽量用短词和常见词，例如 models、files、datasets、tasks
- 少用偏抽象或偏绕的词，除非是在说明外部标准
- 句子直接写“做什么”“不做什么”“放什么”，尽量不要写得像汇报材料
- 中文说明尽量直白，英文命名也走同一规则，不为了显得正式去造复杂词
- 公开 API、文档标题、字段名和接口说明统一使用规则、训练输出文件、文件列表、摘要这类直白词，避免使用套话、空话和官话词
- Python 代码默认写中文注释，名词保持英文不变；模块、类、方法、参数、字段和属性都要说明
- Python 注释规则通过 [.github/instructions/python-comments.instructions.md](../.github/instructions/python-comments.instructions.md) 自动应用到 Python 文件

## 推荐阅读顺序

1. [AGENTS.md](../AGENTS.md)
2. [docs/architecture/README.md](architecture/README.md)
3. [docs/documentation-remediation-roadmap.md](documentation-remediation-roadmap.md)
4. [docs/architecture/system-overview.md](architecture/system-overview.md)
5. [docs/architecture/current-implementation-status.md](architecture/current-implementation-status.md)
6. [docs/architecture/next-stage-roadmap.md](architecture/next-stage-roadmap.md)
7. [docs/architecture/model-platform-plan.md](architecture/model-platform-plan.md)
8. [docs/architecture/model-support-matrix.md](architecture/model-support-matrix.md)
9. [docs/architecture/training-parameter-support.md](architecture/training-parameter-support.md)
10. [docs/architecture/model-core-implementation-plan.md](architecture/model-core-implementation-plan.md)
11. [docs/architecture/yolo-model-plan.md](architecture/yolo-model-plan.md)
12. [docs/architecture/model-task-naming-boundaries.md](architecture/model-task-naming-boundaries.md)
13. [docs/architecture/model-workflow-boundaries.md](architecture/model-workflow-boundaries.md)
14. [docs/architecture/yoloe-sam3-node-assets.md](architecture/yoloe-sam3-node-assets.md)
15. [docs/architecture/industrial-rule-node-plan.md](architecture/industrial-rule-node-plan.md)
16. [docs/architecture/industrial-extension-node-plan.md](architecture/industrial-extension-node-plan.md)
17. [docs/architecture/plc-modbus-field-debug-checklist.md](architecture/plc-modbus-field-debug-checklist.md)
18. [docs/architecture/yoloe-sam3-workflow-app-operations.md](architecture/yoloe-sam3-workflow-app-operations.md)
19. [docs/architecture/execution-sequences.md](architecture/execution-sequences.md)
20. [docs/architecture/workflow-runtime.md](architecture/workflow-runtime.md)
21. [docs/architecture/project-structure.md](architecture/project-structure.md)
22. [docs/architecture/backend-service.md](architecture/backend-service.md)
23. [docs/architecture/websocket-architecture.md](architecture/websocket-architecture.md)
24. [docs/architecture/task-system.md](architecture/task-system.md)
25. [docs/architecture/yolox-module-design.md](architecture/yolox-module-design.md)
26. [docs/architecture/frontend-web-ui.md](architecture/frontend-web-ui.md)
27. [docs/architecture/frontend-web-ui-structure.md](architecture/frontend-web-ui-structure.md)
28. [docs/architecture/frontend-web-ui-startup-session.md](architecture/frontend-web-ui-startup-session.md)
29. [docs/architecture/frontend-web-ui-development-readiness.md](architecture/frontend-web-ui-development-readiness.md)
30. [docs/architecture/frontend-web-ui-workflows.md](architecture/frontend-web-ui-workflows.md)
31. [docs/architecture/node-system.md](architecture/node-system.md)
32. [docs/architecture/workflow-json-contracts.md](architecture/workflow-json-contracts.md)
33. [docs/architecture/data-and-files.md](architecture/data-and-files.md)
34. [docs/architecture/local-buffer-broker.md](architecture/local-buffer-broker.md)
35. [docs/architecture/dataset-import-spec.md](architecture/dataset-import-spec.md)
36. [docs/architecture/dataset-export-formats.md](architecture/dataset-export-formats.md)
37. 根据任务继续进入 API、部署、节点扩展或决策文档

## 文档维护建议

- 仓库级入口文档控制在“约束与导航”范围内，不展开详细方案
- 架构文档聚焦结构边界、依赖方向和模块职责，不混入实现教程
- API 文档只写公开接口规则，不混入内部实现说明
- 部署文档聚焦运行环境、目录布局、启动方式和排障，不混入架构取舍背景
- 决策文档专门记录为什么做出某个方案选择，以及被放弃的备选方案

## 当前建议补齐的文档

- API 资源与事件清单
- 典型部署拓扑说明
- 节点包示例模板
- 运维排障手册已开始落地到 [docs/operations/README.md](operations/README.md)
