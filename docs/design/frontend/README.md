# 前端产品与界面设计

本目录保存产品原则、信息架构、设计系统和页面规格，作为实现约束和评审基线。设计审查及出图要求单独记录，不能把设计图当作已经实现的功能或运行验收证据。
部署收尾复核：主流程和关键状态已覆盖，可开始推理分类设计；版本类别数、导入资源和协议入口8张图已修订，亮暗配对保留。见[收尾复核与推理衔接](deployment-design-review.md#13-收尾复核与推理分类衔接)。


**最新要求（2026-10-23）：以 `bak1` 中大部分合理设计为基础统一风格、修正局部错误。左侧导航参考现有简洁平级形式，顶部没有独立栏；旧宽屏图右侧是按需展开的抽屉。刚才的五入口合并和固定列表详情方案已否决，见[修订要求](redesign-brief.md)与[修订方案](frontend-redesign-plan.md)。**

2026-10-22 已核对文档、当前前端源码、开发页面与旧设计图，并补齐完整目标导航、数据集标准管理和新视觉能力的 UI 规划。本轮只更新设计文档和归档，不改变前端、节点或执行链路。

2026-10-23 已完成全部 59 张旧图的逐图审查，见[保留与修正清单](bak1-review-2026-10-23.md)。`bak1` 保持不变。项目当前设计与历史阶段记录分开，后续按页面类型命名。数据集管理、部署导入、触发详情的此前新稿已被否决，见[否决记录](resource-pages-review-2026-10-23.md)。设计确认不代表产品已实现。

## 文档

**当前推理设计：** 2026-10-27，累计67组134张亮暗图及134份中文规格。本轮补六类任务结果详情12张，修订四张短屏导航、两张实例分割长JSON页签及两张关键点主图。见[页面规划](inference-pages-design.md)、[任务详情定义](inference-result-details-design.md)、[中文提示词](prompts/推理.md)、[设计总览](generated/推理/设计总览.html)和[本轮复核](inference-design-review.md#18-任务详情与折叠导航复核)。当前清单中的独立布局已有对应图，同构状态有复用规则；真实交互、响应式和服务契约仍须实现验证。

**当前部署设计：** 2026-10-26，累计74组亮暗配对、148张静态图与148份中文规格，第四批已补11组22张交互收尾图。保留完整布局和操作，仅压缩冗余说明。待用户审阅。见[页面规划](deployment-pages-design.md)、[异常恢复与后端参数](deployment-closure-states-design.md)、[交互收尾](deployment-interaction-completion-design.md)、[中文提示词](prompts/部署.md)、[设计总览](generated/部署/设计总览.html)和[逐图复核](deployment-design-review.md)。指定的主要流程和恢复分支已补齐；真实交互及功能实现另行验证。

**当前模型设计：** 2026-10-26，模型分类共90组亮暗配对、180张静态图。本轮修订转换与导入列表，补7组操作去向和提交状态；中文规格与图稿已逐张核对，待用户审阅。见[页面规划](model-pages-design.md)、[操作去向与提交状态](model-flow-closure-design.md)、[中文提示词](prompts/模型.md)、[设计总览](generated/模型/设计总览.html)及[当前复核](model-design-review.md#12-操作闭环复核与当前结论)。静态范围可进入Vue 3原型，真实交互与可访问性另行验收。

**当前数据集设计：** 截至 2026-10-25，累计 **56 组亮暗配对、112 张静态稿**，待用户审阅。最新同名修订8图：编辑信息及文件关联样本抽屉整屏遮罩、空态重复入口、版本分组检查说明；同步纠正24份提示词中的遮罩范围错误。见[设计总览](generated/数据集/设计总览.html)、[页面方案](dataset-pages-design.md)、[工作区与状态规格](dataset-workspace-completion-design.md)、[管理规格](dataset-management-states-design.md)、[向导规格](dataset-wizard-states-design.md)、[复核记录第11节](dataset-design-review.md)和[中文提示词](prompts/数据集.md)。主要页面与代表状态已有设计，可以进入[模型分类设计准备](prompts/模型.md)；数据集真实滚动、焦点、权限和错误组合仍需交互原型验证。

**当前项目设计：** 15 组亮暗配对、共 30 张图，统一从[设计总览](generated/项目/设计总览.html)查看；图片直接放在 `generated/项目/` 根层。见[检查记录](project-complete-design-review.md)、[生成清单](generated/项目/生成清单.json)和[完整产品规格](project-complete-design.md)。本次补齐删除确认、依赖阻止的暗色稿，以及 SDK 长资源列表亮暗稿。目录只有 30 张 PNG、一个总览、一个清单，没有子目录；中文规格一图一份，共 30 份。新版待审阅，未修改产品代码。

**完整产品设计原则：** UI 面向未来完整实现，不由当前 API、字段或页面进度限定。当前代码检查只记录实现差距；目标规格决定需要补齐的服务能力。项目分类按[完整产品设计](project-complete-design.md)继续修订、补图和亮暗/短屏核对。

**当前中文提示词入口：[UI 设计提示词](prompts/README.md)。** 已从 Git 历史恢复旧 Image 2 / Google Stitch 提示词的页面内容，按最新规则修订并补齐各场景；[历史来源与对应关系](prompts/历史来源.md)区分原文、当前场景和新增规划。提示词正文使用中文，专有名称保持英文。先核对页面文档和提示词，再逐页生成，不直接沿用旧导航、顶栏或英文请求。

提示词恢复阶段为 13 份文档、45 个场景、61 段提示词，见[恢复与检查记录](prompt-restoration-review-2026-10-23.md)。补充项目概览和状态修订时为 15 份文档、49 个场景、88 段提示词；这些是历史阶段计数。数据集提示词现已按最新要求重写，当前范围以各页文档为准；此前数据集亮暗稿已否决并删除。

项目列表“查看”补充为独立[项目概览](project-overview-design.md)，保留旧 P02 的资源与运行主体，修正先前全部放入抽屉的规划；新建、编辑和补充信息仍用轻量容器。新查看页及其读取契约是目标设计，不代表当前产品已有路由。

项目概览当前[亮暗配对稿](generated/项目/设计总览.html#scene-2)按 P03 记录并等待审阅；旧 `bak1` 不变。

[项目分类完整设计](project-pages-design.md)定义查看后的操作容器与状态：项目信息/编辑项目为右侧抽屉，SDK/删除为居中对话框。当前图统一进入[设计总览](generated/项目/设计总览.html)；未出图的状态不能标记为视觉验收通过。

**项目分类审查：[UI 审查与补全](project-design-audit.md)。** 该记录对应当时 14 张稿和真实页面检查，确定 2 个主页面、3 类抽屉、2 类对话框及 40 项交互检查。后续使用[补充提示词](prompts/项目补充状态.md)，当前图片状态以[统一清单](generated/项目/生成清单.json)为准。

1. [产品原则](product-principles.md)：目标用户、产品边界、工作台原则和状态表达。
2. [信息架构](information-architecture.md)：导航、资源关系和端到端业务路径。
3. [设计系统](design-system.md)：色彩、字体、密度、组件、状态和响应式规则。
4. [页面规格](page-specifications.md)：项目、数据集、模型、Deployment、Workflow、集成和设置页面。
5. [2026-10-22 设计审查](design-review-2026-10-22.md)：旧图证据、文档冲突、已修正项与剩余验证边界。
6. [设计图生成准备](image-generation-plan.md)：统一母版、页面清单、样例数据、出图顺序和检查要求。
7. [完整页面内容规划](navigation-and-page-plan.md)：功能域、每页类别与内容；导航呈现以整体重设计方案为准。
8. [数据集完整管理设计](dataset-management-plan.md)：样本、标注查看、划分、质量检查、版本与来源、删除和外部标注边界。
9. [视觉工作流扩展设计](workflow-vision-ui-plan.md)：异常/瑕疵、连接器二维、3D/点云的用户流程、节点 UI、资源与结果查看器。
10. [设计覆盖与实施步骤](frontend-design-roadmap.md)：完整场景清单、出图顺序、代码步骤、依赖与验证门槛。
11. [后续页面规划](page-design-continuation-2026-10-23.md)：页面范围与能力边界；其中首批页面图已否决，布局方案需重新审查。

## 当前事实与目标设计

当前工作台使用 11 个平级入口，导航保持类似的简洁形式；本轮不擅自合并入口或增加项目选择栏。保留旧图中合理页面主体，右侧详情/配置按抽屉的关闭与展开状态设计。尚未实现的标准功能可以规划，不得标作当前功能。

异常检测、连接器计量和 3D/点云继续复用 Workflow Node App、Runtime、Trigger 与应用模式，通过通用组件、专业节点 UI 和对应扩展包提供能力；不增加独立行业业务系统。数据集标准管理单独补齐样本、标注审阅、划分、质量和版本来源，标注制作仍优先外部工具协作。

## Workflow 文档与版本管理（已实现）

[Workflow 文档导入、导出与统一载入器](workflow-document-import-export.md)：定义 `amvision.workflow-app-document.v1`、当前编辑内容导出、文件载入、目标身份处理和统一 Application/Template 载入路径；不包含 Runtime、Trigger、运行记录或二进制资源。

[Workflow 编辑器发布与历史版本载入](workflow-version-history.md)：复用导入/导出与统一载入器，提供 published/archived 分页列表，并把所选版本直接载入当前编辑画布；不建设历史专用只读画布、草稿备份或自动 Runtime 切版。

## 已实现

[Workflow Runtime 预览显示与应用模式](../../architecture/workflows/runtime-display.md)：只读监视和应用视图复用图片/JSON/表格/图库组件。应用模式自动呈现发布版 App Entry 的全部公开输入，显示区域随原 Workflow 发布，不建设独立页面设计器或界面版本体系。Runtime 观察在执行完成后交接结果，不提供逐节点进度或补造强制终止终态；编辑态的[Preview 执行](../../architecture/workflows/preview-execution.md)则由独立 Worker 逐节点推送。详细通信边界和验收结论在对应专题维护。

[Workflow 多节点复制](../../development/workflow-multi-node-copy.md)：Ctrl 框选、内部连线与完整节点组复制、整体粘贴及选择边界。稳定行为见[编辑器说明](../../architecture/workflows/editor.md)；本目录的[单节点复制文档](workflow-node-copy-paste.md)仅保留早期实现记录。

## 权限与启动页面（已实现）

[用户权限与启动页面设计](user-permissions.md)：管理员配置页面与操作，用户自行设置启动应用，复用原 App Mode；见[详细实施计划](../../development/user-access-implementation.md)。

## 旧设计图归档

`generated/bak1/` 保存本轮归档的全部 59 张旧 PNG，原有 8 个分类目录保持不变。`archive-manifest.json` 记录相对路径、字节数和 SHA-256，移动前后逐文件核对一致。原有 `90-archive/` 中已否决的图仍属于历史资料。

`generated/` 被 Git 忽略，图片和清单只保存在本机；本次操作不等同于远程备份。`bak1` 的合理页面设计作为修订基础，导航、顶部、少数错误字段及示例数据另行核对。后续新图按页面类型另建目录，不覆盖 `bak1`。版本库保存文字规范、中文提示词及审查结论。

`20261022-redesign-v2` 本轮两张生成图已否决，生成源图及仓库副本已删除，未生成暗色版。剩余提示词是误判记录，不能用作母版。

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

当当前事实与代码、OpenAPI 或运行时 Catalog 冲突时，先核对实现并修正文档。目标设计允许提出新能力，但必须标明规划状态、依赖和验证要求；不能以旧设计稿反向认定能力已存在。
