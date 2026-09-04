# 前端产品与界面设计

本目录保存当前有效的产品原则、信息架构、设计系统和页面规格。它是实现约束和评审基线，不保存图片生成提示词、工具操作流程或某轮生成结果。

## 文档

1. [产品原则](product-principles.md)：目标用户、产品边界、工作台原则和状态表达。
2. [信息架构](information-architecture.md)：导航、资源关系和端到端业务路径。
3. [设计系统](design-system.md)：色彩、字体、密度、组件、状态和响应式规则。
4. [页面规格](page-specifications.md)：项目、数据集、模型、Deployment、Workflow、集成和设置页面。

## 已接受、待实现的扩展

独立运行界面的组件、布局、主题、四语言、公开输入输出绑定及人工/模型共用文档设计，统一见[运行界面与 App 应用包实施基线](../../development/workflow-views-and-app-packages-implementation.md)。取舍依据见 [ADR-0012](../../decisions/ADR-0012-workflow-views-and-app-packages.md)。通过实现和验收前，不将这些规划写成现有页面规格。

## 设计方向

- 专业、清晰、克制，适合长时间使用的工业视觉工作台。
- 使用稳定网格、明确分组和适当信息密度，不依赖大面积空白或过度卡片化。
- 状态、错误、来源和可恢复动作必须可见；装饰不能压过任务和图像结果。
- 优先支持桌面工作站、工控机、大图、长列表、局域网和离线部署。
- 小于 `1024px` 时优先保证查看、监控和紧急控制，不强求完整图编辑体验。

## 事实来源

- [平台总览](../../architecture/system-overview.md)
- [Web UI 架构](../../architecture/frontend/overview.md)
- [前端工程结构](../../architecture/frontend/structure.md)
- [Workflow 编辑器](../../architecture/workflows/editor.md)
- [模型支持矩阵](../../reference/models/support-matrix.md)
- [数据格式参考](../../reference/datasets/README.md)
- 当前 Vue Router、组件实现和浏览器测试

当设计文档与代码、OpenAPI 或运行时 Catalog 冲突时，先核对当前实现，再在同一变更中修正文档；不得以旧设计稿反向定义不存在的能力。
