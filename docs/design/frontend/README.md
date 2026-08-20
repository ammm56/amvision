# 前端设计生成文档

## 目的

本目录保存 AMVision 前端视觉规范、页面参考和设计评审材料。它不维护路由或能力实现状态；当前页面以 Vue Router、[Web UI 架构](../../architecture/frontend-web-ui.md) 和实际代码为准。生成参考主要面向两类工具：

- OpenAI ChatGPT Image 2：生成高保真桌面端页面概念图、关键状态图和局部视觉方案。
- Google Stitch：生成具有明确页面结构、组件层级和交互关系的界面方案，便于继续进入原型或前端实现。

这些文档不是新的产品需求来源。后端资源边界、模型支持范围、数据格式和运行时能力仍以 `docs/architecture/` 下的正式架构文档和当前代码为准。

## 设计主题

整体风格为“人工、洁净、未来感”。

- 人工：强调人主导、可理解、可操作和可追溯的工程工具感。界面应像经过认真编排的专业工作台，不像自动生成的模板。
- 洁净：依靠稳定网格、明确分组、克制色彩和高信息密度实现清晰，不依靠大面积空白或过度卡片化。
- 未来感：来自实时数据、精密视觉叠加、工作流节点、状态反馈和细致动效，不使用廉价霓虹、全屏玻璃拟态或科幻驾驶舱装饰。

## 文档结构

1. [产品与设计总纲](01-product-design-brief.md)：产品目标、用户、设计原则、业务边界和生成约束。
2. [信息架构与业务路径](02-information-architecture.md)：导航层级、资源关系、端到端使用流程和页面清单。
3. [视觉与组件系统](03-visual-component-system.md)：色彩、字体、尺寸、组件、状态、数据可视化和响应式规则。
4. [逐页设计规格](04-page-specifications.md)：从系统入口到数据、模型、部署、推理、流程和设置的逐页说明。
5. [OpenAI Image 2 提示词](05-openai-image-2-prompts.md)：适合图片生成的总提示、逐页提示、负面约束和迭代方法。
6. [Google Stitch 提示词](06-google-stitch-prompts.md)：适合结构化界面生成的项目提示、页面提示和组件复用要求。
7. [生成、筛选与交付流程](07-generation-workflow.md)：两个工具的协作顺序、命名、评审和交付标准。
8. [ChatGPT Image 2 设计图](generated/README.md)：已生成并核对的浅色/深色基线、标准页面和状态变体。

## 推荐使用顺序

1. 先阅读设计总纲、信息架构和组件系统，固定产品语义与视觉方向。
2. 从逐页设计规格中选择目标页面，确认页面的业务阶段、主操作和关键状态。
3. 使用 OpenAI Image 2 生成整体视觉方向和少量关键页，优先确定工作台外壳、数据集页、训练详情页、推理页和流程编辑器。
4. 将已选视觉方向、组件规则和对应页面提示交给 Google Stitch，生成结构化页面。
5. 按生成与交付流程检查一致性、业务完整性和实现可行性。

## 基准画布

- 主要桌面画布：`1920 × 1200` 或等比例 `16:10`。
- 常见工作站画布：`1600 × 1000`。
- 窄桌面检查：`1366 × 768`。
- 不以手机端为主要设计目标；小于 `1024px` 时优先保证查看、监控和紧急操作，不强求完整图编辑体验。

## 事实来源

- [平台整体框架](../../architecture/system-overview.md)
- [模型支持清单](../../architecture/model-support-matrix.md)
- [模型数据集格式规范](../../architecture/model-dataset-format-contract.md)
- [模型、数据集、部署与流程边界](../../architecture/model-workflow-boundaries.md)
- [训练与评估规则](../../architecture/model-training-evaluation-contract.md)
- [部署运行时规则](../../architecture/model-deployment-runtime-policy.md)
- [前端结构](../../architecture/frontend-web-ui-structure.md)
- [节点系统](../../architecture/node-system.md)

## 状态标记

逐页规格使用以下标记：

- `现有`：当前 Vue 前端已有真实路由和页面。
- `现有增强`：当前已有页面，但设计稿应补强结构、状态或后端能力入口。
- `参考概念`：用于表达可能的独立页面结构，不代表当前路由或已承诺功能。
- `系统状态`：启动、离线、无权限、未找到等非业务页面。
