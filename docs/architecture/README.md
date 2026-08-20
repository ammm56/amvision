# 架构文档

本目录说明当前系统结构、长期边界和公开契约。实施过程、阶段编号、临时审计结果和启动操作不属于架构正文。

## 建议阅读路径

1. [平台整体方案](system-overview.md)
2. [当前实现状态](current-implementation-status.md)
3. [项目结构](project-structure.md)
4. [关键执行顺序](execution-sequences.md)
5. 按需要进入下列专题

## 平台与运行时

- [后端服务](backend-service.md)：控制面职责、依赖注入、Repository 和 Unit of Work 边界。
- [统一任务系统](task-system.md)：Task、队列、Worker Profile 和状态回写。
- [运行时与打包](runtime-packaging.md)：开发运行时、发行目录和 bundled Python。
- [数据和文件](data-and-files.md)：ObjectStore、文件引用、版本和生命周期。
- [WebSocket](websocket-architecture.md)：版本化消息、订阅和恢复规则。
- [LocalBufferBroker](local-buffer-broker.md) 与 [高性能图片数据面](high-performance-image-data-plane.md)：本机图片引用、mmap 和 ZeroMQ 数据链。

## 模型平台

- [模型支持矩阵](model-support-matrix.md)：模型、任务和端到端能力的当前事实来源。
- [模型 Core 架构](model-core-architecture.md)：模型家族、平台应用层与 Runtime adapter 的职责。
- [模型工作流边界](model-workflow-boundaries.md)：数据集、训练、转换、Deployment、Workflow 和 Trigger 的关系。
- [模型数据集格式](model-dataset-format-contract.md)：分类、检测、分割、姿态和 OBB 的统一格式入口。
- [训练与评估契约](model-training-evaluation-contract.md)、[训练参数](training-parameter-support.md) 和 [输入尺寸规则](model-training-input-size-rules.md)。
- [模型产物来源](model-artifact-provenance.md) 与 [部署运行时配置](model-deployment-runtime-policy.md)。
- [模型实现审计基线](model-implementation-audit.md) 与 [full core 验收](model-full-core-audit-checklist.md)。

具体数据集格式按来源进入 `classification-*`、`coco-*`、`voc-*`、`yolo-*` 和 `dota-*` 文档。未出现在支持矩阵中的组合不属于已实现能力。

## Workflow 与节点

- [Workflow 运行时](workflow-runtime.md)：Preview、正式 Runtime、Run、进程和事件边界。
- [Workflow App 版本管理](workflow-app-versioning.md)：不可变版本、稳定 Runtime/Trigger id、revision、generation 和回滚。
- [Workflow JSON](workflow-json-contracts.md)：图、节点、端口、参数和应用契约。
- [模型 Session Runtime](workflow-model-session-runtime.md) 与 [Parallel 分支](workflow-parallel-branches.md)。
- [节点系统](node-system.md) 与 [节点分类](node-taxonomy.md)：Core、Custom、Node Pack 和 runtime hook。
- [Visual Prompt](visual-prompt-editor.md) 与 [YOLOE/SAM3 节点资产](yoloe-sam3-node-assets.md)。

编辑器中已经实现的图像交互取参、节点组和 ROI 边界放在 [开发指南](../development/README.md)，不再以实施计划形式保留。

## 前端

- [Web UI 架构](frontend-web-ui.md)
- [前端工程结构](frontend-web-ui-structure.md)
- [启动与会话](frontend-web-ui-startup-session.md)
- [Workflow 页面和节点通信](frontend-web-ui-workflows.md)

前端当前统一使用 Vue 3 + TypeScript + Vite。设计稿和组件视觉规范位于 [docs/design/frontend](../design/frontend/README.md)。

## 扩展与现场能力

- [工业视觉与集成节点](industrial-workflow-nodes.md)
- [视频 Workflow 节点](video-workflow-nodes.md)
- [PLC Modbus 联调](plc-modbus-field-debug-checklist.md)
- [YOLOE/SAM3 Workflow 运行](yoloe-sam3-workflow-app-operations.md)

节点是否可用以运行时 Catalog 为准；架构文档只说明稳定分层和使用边界。

## 写作边界

- 架构正文写当前不变量和模块关系，不累计修复批次、提交记录或日期流水账。
- 取舍原因进入 [ADR](../decisions/README.md)，执行命令进入 [development](../development/README.md) 或 [deployment](../deployment/README.md)。
- API 字段以 [API 文档](../api/README.md) 和 OpenAPI 为准。
- 当前能力以代码、迁移和自动化测试为最终证据；文档发现偏差时必须随代码修正。
