# 前端产品与界面设计

本目录保存当前有效的产品原则、信息架构、设计系统和页面规格。它是实现约束和评审基线，不保存图片生成提示词、工具操作流程或某轮生成结果。

## 文档

1. [产品原则](product-principles.md)：目标用户、产品边界、工作台原则和状态表达。
2. [信息架构](information-architecture.md)：导航、资源关系和端到端业务路径。
3. [设计系统](design-system.md)：色彩、字体、密度、组件、状态和响应式规则。
4. [页面规格](page-specifications.md)：项目、数据集、模型、Deployment、Workflow、集成和设置页面。

## Workflow 文档与版本管理（已实现）

[Workflow 文档导入、导出与统一载入器](workflow-document-import-export.md)：定义 `amvision.workflow-app-document.v1`、当前编辑内容导出、文件载入、目标身份处理和统一 Application/Template 载入路径；不包含 Runtime、Trigger、运行记录或二进制资源。

[Workflow 编辑器发布与历史版本载入](workflow-version-history.md)：复用导入/导出与统一载入器，提供 published/archived 分页列表，并把所选版本直接载入当前编辑画布；不建设历史专用只读画布、草稿备份或自动 Runtime 切版。

## 已实现

[Workflow Runtime 预览显示与应用模式](../../architecture/workflows/runtime-display.md)：同一 Workflow 的编辑、只读监视和应用视图均已实现。应用模式自动呈现发布版 App Entry 的全部公开输入，只选择 Preview 显示区域，并复用图片/JSON/表格/图库组件。显示选择随原 Workflow 发布，不建设独立页面设计器或界面版本体系；逐节点进度和强制终止终态不纳入当前范围。详细使用流程、通信边界和验收结论在该架构专题维护。

[Workflow 节点复制与粘贴](workflow-node-copy-paste.md)：节点右键第二项复制、空白画布第四项粘贴和 Ctrl+C / Ctrl+V，保留节点参数并生成新的节点 ID；实现与验证边界见专题。

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
