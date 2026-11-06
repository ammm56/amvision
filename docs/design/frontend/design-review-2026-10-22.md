# 前端设计文档与旧图审查（2026-10-22）

## 结论与范围

原设计的产品方向仍适合本项目：本地工业视觉工作台，资源、有限任务、常驻实例分层，图片和结构化结果优先，危险操作明确影响范围。问题在于旧图未遵守同一个外壳和组件基线，部分文档又把过时方案、设计目标和已实现能力混在一起。不能直接以旧图逐张重绘作为下一轮设计。

本次检查 9 份原设计文档、59 张旧图总览，并对项目、部署和流程编辑器代表图作原尺寸核对；同时对照当前路由、外壳、主题 token、关键页面和 Workflow 专题。它是静态设计与源码审查，不是所有线上页面的交互、性能或无障碍验收。没有更改应用草稿、生产配置、前端代码或执行链路，也没有生成新的设计图。

源码参考提交为 `3e146d6f`，检查期间工作区存在训练相关未提交修改；这些修改不属于本次审查和文档变更。

## 归档结果

旧目录全部内容移至 `generated/bak1/`，8 个子目录保持原相对结构。59 张 PNG 共 65,529,745 字节，移动前后逐文件 SHA-256 一致；清单见本地 [archive-manifest.json](generated/bak1/archive-manifest.json)。没有覆盖或删除原图。

`generated/` 被 Git 忽略，本机归档不等于异地或远程备份。图像审查索引位于本机 `data/development/frontend-design-review-20261022/`，含 11 张缩略联系表和原图尺寸清单，仅用于复核，不作为新设计稿。原图宽高为 1586×992 或 1366×768，不能将宽图笼统标为 1920×1080。

## 逐类覆盖

| 分类 | 图数 | 保留的方向 | 下一轮需要修正 |
| --- | ---: | --- | --- |
| 基础/系统入口 | 11 | 区分加载、空、错误，任务与服务状态分开 | 品牌、颜色和外壳统一；能力说明不冒充真实控件；离线缓存须有实现依据 |
| 项目/任务 | 8 | 列表与详情关联、失败后提供诊断 | 当时未规划独立项目概览；2026-10-23 已按列表“查看”需求补充[独立概览设计](project-overview-design.md)，仍非已有路由。窄屏不是整页同比缩小；项目页不加播放按钮 |
| 数据集 | 8 | 导入/导出来源可追溯，记录和产物分离 | 主页面不铺版本表；管理对话框承载版本；不画未注册样本浏览页 |
| 模型 | 13 | 训练曲线、转换产物与错误分层 | 导入区位置修正；独立评估中心等不进入当前页面清单；参数和目标来自 capability |
| 部署/推理 | 6 | 常驻实例控制、推理图像优先 | 导入运行配置与映射统一对齐；详情降噪；不复制虚构设备、队列或性能指标 |
| Workflow/集成/节点 | 11 | 编排、发布、运行与协议边界 | 增补应用模式/运行监视/节点专属编辑器；Preview 与 Runtime 显示时机分开 |
| 设置 | 1 | 分类查看设备和服务信息 | 沿用当前二级导航；增加外观、启动、权限、关于的代表状态 |
| 已否决历史图 | 1 | 保留否决记录 | 不以外部数据库、Redis/MQ 设置作为本地部署前提 |
| 合计 | 59 | 工业工作台定位保留 | 不把旧图中的字段和动作反推为产品需求 |

## 主要发现与修正

这里的优先级表示对下一轮设计的阻断程度，不表示已在运行环境复现的故障级别。

| 优先级 | 证据 | 判断 | 本轮处理 |
| --- | --- | --- | --- |
| P1 | G01、P01、R01、W03 的外壳；总纲 232px 与设计系统 220px | 顶栏、导航分组、侧栏宽度和用户入口各不相同。当前只有侧栏+内容区，没有全局搜索顶栏 | 固定 220/64px 与 11 个平级入口；普通工作台、全幅图工作台和系统入口分别定义母版 |
| P1 | P02、M04/M05、D04、R02；当前 Router | 独立概览、评估、样本浏览、部署详情图不能视为已注册页面 | 页面地图以路由和组件为准；可复用内容归入现有页面区域，其余不进入首轮 |
| P1 | 原页面规格的 Preview/LocalBuffer 描述；现有 Preview 执行专题 | 混淆异步预览与正式同步数据面，可能诱导错误界面与实现 | 明确独立 Preview Worker、WebSocket/JPEG、临时内存；Runtime 完成后观察，不增加队列/重试 |
| P1 | D01/D04、W01、X01；当前业务组件 | 旧版本列表位置、应用 ID、触发诊断密度与既有简化要求冲突 | 版本进入管理对话框；ID/健康计数/最近错误进入详情；保留触发时间列 |
| P2 | G01、P01 窄版、R01 使用 AMVision/AMV/额外图形标志，R01 标有“1.6.0/专业版” | 品牌与版本示例不可信，多套绿色深浅不一 | 复用 AnimatedBrand、AM 图标和主题 token；不另画商标或授权版本 |
| P2 | G01/D01 紧密多栏，P01 窄版字号与密度显著不同 | 缩放阅读尚可不能替代目标屏幕可读性，表格/抽屉/按钮缺少统一密度 | 固定字号、间距、控件与行高母版；1366 宽度通过重排/局部滚动适配 |
| P2 | W03 仅暗色，含全局撤销/重做及大底部运行区；缺少当前亮色与应用模式图 | 旧图不能代表当前编辑体验，也未覆盖高频生产结果页 | 双主题、真实工具栏与专属编辑器补齐；不虚构通用撤销栈 |
| P2 | G03–G06 状态海报、原设计系统组件名 | 设计概念被写成已存在的公共组件；海报不是单页截图 | 概念状态与实际组件分开；状态板单列，业务页一图一状态 |
| P2 | 多图原始 ID、JSON、解释段落常驻首屏 | 工程信息有价值，但高频操作和图像被压缩 | 默认展示名称、结果、必要操作；诊断可查可复制，不散落主区域 |
| P2 | 原文“正文满足 AA”与品牌白字规则并存 | 可读性目标不能当作已经通过的结论 | 保留已确定的品牌配色，记录对比度取舍，后续针对实际控件验证 |

代表原图：

- [P01 窄屏项目页](generated/bak1/01-projects-tasks/P01_project-list_light_narrow-1366x768_v01.png)：额外全局顶栏、页面大标题、AMV 标志及项目播放按钮。
- [R01 部署工作台](generated/bak1/04-deployments-inference/R01_deployment-workbench_light_service-control_v01.png)：另一套图形商标、导航次序、专业版标记及密集常驻诊断。
- [W03 编辑器](generated/bak1/05-workflows-integrations/W03_workflow-editor_dark_preview-success_v01.png)：独立暗色外壳、未经当前工具栏支持的操作；节点图和 18.6ms 等示例值不能作为真实契约或性能证据。

## 已核对的实现依据

- 外壳：[WorkbenchShell.vue](../../../frontend/web-ui/src/shells/workbench/WorkbenchShell.vue)、[导航配置](../../../frontend/web-ui/src/config/navigation.config.ts)。自动折叠为 `max-width: 899px`，不是文档原写的 1024–1279px。
- 颜色与基础尺度：[tokens](../../../frontend/web-ui/src/shared/styles/tokens)；普通标题隐藏：[content.css](../../../frontend/web-ui/src/shared/styles/content.css)；设置标题隐藏：[settings.css](../../../frontend/web-ui/src/modules/settings/settings.css)。
- 数据集：原 DatasetOperationsPage 已于 2026-11-05 被[DatasetCatalogPage.vue](../../../frontend/web-ui/src/modules/datasets/pages/DatasetCatalogPage.vue)及版本工作区取代；模型区域次序：[ModelOperationsPage.vue](../../../frontend/web-ui/src/modules/models/pages/ModelOperationsPage.vue)。
- 页面边界：[Workflow 路由](../../../frontend/web-ui/src/workflows/workflow-editor/routes.ts)、[模型路由](../../../frontend/web-ui/src/modules/models/routes.ts)、[部署路由](../../../frontend/web-ui/src/modules/deployments/routes.ts)、[项目路由](../../../frontend/web-ui/src/modules/projects/routes.ts)。
- 显示关联：[应用模式配置](../../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowAppModeConfigDialog.vue)；执行边界：[Preview](../../architecture/workflows/preview-execution.md)、[Runtime 显示](../../architecture/workflows/runtime-display.md)。
- 连接器：[节点 UI 实施与验证](../../development/connector-usability-implementation.md)、[工程 Workflow](../../examples/workflows/connector-inspection.md)。合成开发验证不能作为实物计量验收。

反向核对也保留已有能力：应用详情确有“与草稿比较”，不能误判为完全没有版本比较；它与编辑器的任意历史图差异工具不同。TaskStateBadge、TaskProgress 已存在，而 ListStateBoundary 等原文概念名并非对应公共组件。不能统一按“旧文档都错误”处理。

## 本轮修订与后续入口

已同步修正总纲、信息架构、设计系统和页面规格；README 将权限标为已实现，单节点复制文档标为历史阶段并链接当前多节点方案。导入导出与历史版本专题保留既有契约和验证记录，本次不重新设计其行为。

下一轮按[设计图生成准备](image-generation-plan.md)先做统一母版，再做代表页面，最后扩展状态和页面覆盖。图像只是布局与视觉参考；文本、数据、连线和交互仍需逐项核对，不能用美观替代可执行性。

仍需在实际实现阶段验证：目标工控机字形与缩放、亮暗对比度、键盘和焦点、浮层遮挡、长名称/路径、多语言溢出及窗口缩小后的滚动。此次静态审查不把这些项目记为通过。

本轮检查结果：59 张归档图片的路径集合、字节数和 SHA-256 全部一致；8 份新增或修改文档的本地 Markdown 链接均可解析；`git diff --check -- docs/design/frontend` 通过。变更只有设计文档与本地图片归档，不以业务测试结果为本轮交付条件。

## 同日扩展：完整目标页面规划

随后按新增要求补齐[五组导航与全部页面](navigation-and-page-plan.md)、[数据集标准管理](dataset-management-plan.md)、[异常/连接器/3D 视觉扩展](workflow-vision-ui-plan.md)和[设计覆盖与实施步骤](frontend-design-roadmap.md)。先前“仅按现有平级导航出图”的限制收敛为当前事实记录，下一轮目标图允许使用明确标记的分组与未来功能规划。

浏览器只读检查数据集、管理对话框、设置、节点目录，截图位于 `data/development/frontend-design-review-20261022/navigation-planning/`。管理对话框截图是有筛选条件的无匹配状态，不能当作仓库没有数据集的证据；节点目录显示 487 个节点、10 个节点包。未执行训练、工作流、删除或发布操作。尚未生成新设计图，也未实施导航或新业务页面。

扩展检查结果：新增 4 份专题，覆盖 45 个设计场景；场景编号无重复，新增文档代码块与空白检查通过。本目录 15 份 Markdown 的 120 个本地链接全部可解析，`git diff --check -- docs/design/frontend` 通过。未创建本任务 `.tmp` 产物，其他正在进行的训练代码修改不属于此次设计工作。

## 首轮生成被否决后的纠正

`20261022-unified-ui-v1` 生成了 7 张图（包含修改稿）。错误在于把现有页面作为视觉模板，并把功能域分类直接搬到侧栏，形成过多分组。用户明确要求重新规划设计，这一批次全部否决，项目目录的 7 张生成 PNG 已删除。

后续依据[重新设计要求](redesign-brief.md)：现有实现用于功能核对，导航与视觉重新设计；撤销五组侧栏，保留完整页面功能规划。生成工具缓存的整批清理未执行；目录递归删除及仓库外副本清理命令被自动策略拦截，随后仅按明确文件清单完成项目内 7 张图的删除。旧 `bak1` 归档未改动。

## 2026-10-23 再次纠正（当前有效结论）

用户明确指出：`bak1` 中大部分设计正确，主要需要统一风格与修正少数错误；宽屏图最右侧是展开的抽屉，不是固定详情列。左导航应与当前产品类似、保持简洁，顶部没有独立栏。

此前将旧图整体降为问题参考、改成五入口合并和固定列表详情的判断不正确，相关方案已撤销。已重新查看 P01 项目抽屉图和 G01 亮色工作台图，按抽屉的关闭/展开状态修订约束，不宣称已重新审完全部旧图。

`20261022-redesign-v2` 只生成两张亮色图，未生成暗色版。两张生成源 PNG 及仓库中的一份副本均按明确文件路径删除。提示词保留为已否决记录，不能用于新图。`bak1` 59 张原图保持不变。后续按[修订要求](redesign-brief.md)和[修订方案](frontend-redesign-plan.md)，从合理旧稿继续，不在本轮自动出图或修改产品代码。
