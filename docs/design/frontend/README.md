# 前端产品与界面设计

本目录保存当前有效的产品原则、信息架构、设计系统和页面规格。它是实现约束和评审基线，不保存图片生成提示词、工具操作流程或某轮生成结果。

## 文档

1. [产品原则](product-principles.md)：目标用户、产品边界、工作台原则和状态表达。
2. [信息架构](information-architecture.md)：导航、资源关系和端到端业务路径。
3. [设计系统](design-system.md)：色彩、字体、密度、组件、状态和响应式规则。
4. [页面规格](page-specifications.md)：项目、数据集、模型、Deployment、Workflow、集成和设置页面。

## 已接受、待实现的扩展

amvar app 与独立运行界面的组件、布局、主题、四语言名称、命名来源与公开绑定、运行入口及人工/模型共用文档设计，统一见[amvar app 实施基线](../../development/workflow-views-and-app-packages-implementation.md)。设计预览只用标记的示例数据；生产页只展示在线收到的当前结果，不要求硬实时，不建设历史、固定结果或暂停恢复模式。按公开类型显示文本/JSON、WS Base64 图片或 HTTP 引用图片；新 WS 整条消息上限 64MB，显示失败不改变业务结果。独立前端可替换内置页面而不修改核心 Workflow/Runtime/Trigger。取舍依据见 [ADR-0012](../../decisions/ADR-0012-workflow-views-and-app-packages.md)。通过实现和验收前，不将这些规划写成现有页面规格。

登录用户拥有全部操作权限，沿用默认用户永久 token 与现有登录态，不增加角色/授权表单；monitor/interactive 只决定页面是否配置输入和执行控件。控件从完整公开结果选字段；手动请求通过既有 run 响应确认身份和状态，不覆盖后续 WS 画面，也不把图片失效或 token 失效显示成 Workflow 业务失败。

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
