# 架构

本目录只说明当前系统结构、职责边界和长期不变量。API 字段、数据格式、启动命令、现场排障和阶段验收分别进入对应目录。

## 阅读顺序

1. [平台总览](system-overview.md)
2. [项目结构](project-structure.md)
3. [关键执行顺序](execution-sequences.md)
4. 按子系统进入下列专题

## 平台基础

专题索引见 [平台基础架构](platform/README.md)。

- [后端服务](platform/backend-service.md)：API 控制面、依赖注入、Repository 和 Unit of Work。
- [任务系统](platform/task-system.md)：持久队列、Worker Profile 和状态回写。
- [数据和文件](platform/data-and-files.md)：ObjectStore、文件引用与生命周期。
- [运行时与打包](platform/runtime-packaging.md)：源码运行、bundled Python 和发行目录。
- [WebSocket](platform/websocket.md)：消息版本、订阅、游标和恢复。
- [LocalBufferBroker](platform/local-buffer-broker.md)、[Inference mailbox v1](platform/inference-mailbox-v1.md) 与 [高性能图片数据面](platform/image-data-plane.md)：当前共享图片、结构化推理结果、ZeroMQ 和引用边界。
- [本机结构化消息通道 ADR](../decisions/ADR-0009-local-message-channel.md)与[实施基线](../development/local-message-channel-implementation.md)：已接受但尚未实现的结构化 mmap 统一框架；共享底层 engine，不合并物理 Channel、owner、epoch 或容量。

## 模型平台

专题索引见 [模型平台架构](models/README.md)。

- [模型 Core](models/model-core.md)：模型家族、应用层与 Runtime adapter。
- [模型工作流边界](models/workflow-boundaries.md)：数据集、训练、评估、转换、Deployment、Workflow 和 Trigger。
- [训练与评估契约](models/training-evaluation.md)
- [模型产物来源](models/artifact-provenance.md)
- [Deployment Runtime 配置](models/deployment-runtime.md)

模型能力、数据格式、参数和命名规则统一放在 [参考资料](../reference/README.md)，不在架构目录复制支持表。

## Workflow 与节点

专题索引见 [Workflow 与节点架构](workflows/README.md)。

- [Workflow Runtime](workflows/runtime.md)：Preview、正式 Runtime、Run 和进程边界。
- [Workflow App 版本管理](workflows/app-versioning.md)：不可变版本、稳定 id、revision、generation 和回滚。
- [Workflow App Entry 多类型输入实施基线](../development/workflow-app-entry-input-implementation.md)：JSON、文本、图片、文件、多文件、multipart、Trigger 和 SDK 的待实现统一输入边界。
- [Workflow JSON](workflows/json-contracts.md)：图、节点、端口、参数和应用契约。
- [Workflow 编辑器](workflows/editor.md)：App 保存、Preview、节点组、ROI 与图像交互取参。
- [amvar app 与独立运行界面 ADR](../decisions/ADR-0012-workflow-views-and-app-packages.md)及[实施基线](../development/workflow-views-and-app-packages-implementation.md)：已接受、待实现的多 Workflow 应用组成、命名来源、入口映射、公开输入输出界面、Workflow 文件交换、应用打包恢复与模型生成方案。
- [模型 Session Runtime](workflows/model-session-runtime.md)
- [Parallel 分支](workflows/parallel-branches.md)
- [节点系统](workflows/node-system.md) 与 [节点分类](workflows/node-taxonomy.md)
- [工业视觉与集成节点](workflows/industrial-nodes.md) 与 [视频节点](workflows/video-nodes.md)
- [Visual Prompt](workflows/visual-prompt.md) 与 [YOLOE/SAM3 资产](workflows/yoloe-sam3-assets.md)

## 前端

专题索引见 [前端架构](frontend/README.md)。

- [Web UI](frontend/overview.md)
- [工程结构](frontend/structure.md)
- [启动与会话](frontend/session.md)
- [产品与界面规范](../design/frontend/README.md)

## 边界

- 操作步骤进入 [部署](../deployment/README.md) 或 [运维](../operations/README.md)。
- endpoint、字段和错误进入 [API](../api/README.md)，以 OpenAPI 为最终事实来源。
- 模型支持组合和数据格式进入 [参考资料](../reference/README.md)。
- 设计取舍原因进入 [ADR](../decisions/README.md)。
- 经 ADR 接受但尚未落地的跨子系统步骤进入唯一的 [开发实施基线](../development/README.md)，架构专题在代码和门禁完成前仍只描述当前行为。
- 代码、迁移和自动化测试是实现状态的最终证据。
