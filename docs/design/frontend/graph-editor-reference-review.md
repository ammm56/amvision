# 图编辑参考研究与设计取舍

> 2026-10-29 最新范围：此前整页稿已撤回；以[当前实现基准](graph-editor-current-baseline.md)为准。本文的字段、参考研究和节点库内部规划保留，不作为重画导航、顶部、节点尺寸或整页布局的授权。

更新：2026-10-29。对象为现场工程师高频使用的 Workflow 编辑器。本文记录参考依据及本项目取舍，不表示参考产品功能已经在 AMVision 实现。

## 1. 已核对的依据

| 依据 | 可借鉴的做法 | AMVision 取舍 |
| --- | --- | --- |
| [MVTec MERLIC Tool Flow](https://www.mvtec.com/doc/merlic/26.03/manual/en-us/Content/Creator/User_interface_creator/tool_flow.html) | 工具连接、分组、执行状态与画布查找分别表达 | 保持节点、参数、结果的清楚关系；未执行、禁用和失败分开。缩放和地图集中在右下。 |
| [Cognex VisionPro ToolBlocks](https://docs.cognex.com/vpromx_1000/web/EN/visionpro/Content/Topics/users-guide/vision-tools-guide/toolblocks/toolblocks-intro.htm) | 按功能组织工具，明确图像输入与结果、参数之间的连接 | 复用工具组合思想；当前节点组仅组织画布，不能画成可执行 ToolBlock 或子工作流。 |
| [ComfyUI 官方设置说明](https://github.com/Comfy-Org/docs/blob/main/interface/settings/comfy.mdx)及本地前端参考源码 | 搜索、分类、用途预览，名称与说明形成层次 | 名称、短描述直接显示；默认卡片并可切列表。不要把说明全部藏在悬停中，也不增加“选中后再点添加”。 |
| [Unreal Blueprint Nodes](https://dev.epicgames.com/documentation/en-us/unreal-engine/nodes-in-unreal-engine)与[Palette](https://dev.epicgames.com/documentation/unreal-engine/palette-in-the-bleprints-visual-scripting-editor-for-unreal-engine?lang=en-US) | 明确的输入输出、端口兼容过滤、分类查找和多选 | 保留左入右出与兼容性提示；不照搬执行箭头、游戏事件语义、自动类型转换或折叠节点参数。 |

ComfyUI 本地参考为 `projectsrc/ComfyUI_frontend/src/components/sidebar/tabs/NodeLibrarySidebarTabV2.vue`、`components/sidebar/tabs/nodeLibrary/EssentialNodeCard.vue`、`components/node/NodePreviewCard.vue`。卡片名称存在正常字重，预览名称和说明分层；点击节点开始放置的行为不直接复制到 AMVision。参考目录不作为产品运行依赖。

本轮读取了官方文档与本地源码。外部参考网页的嵌入浏览器部分加载超时，未将该部分声称为交互实测。当前 AMVision 工具栏已通过浏览器截图和 DOM 尺寸核对，截图位于[参考目录](references/图编辑/)。

## 2. 复用现有实现与重新设计的范围

| 区域 | 本轮确定的设计 |
| --- | --- |
| 顶部工具 | 复用现有四个浮动操作组及实际 Lucide 图标、尺寸、间距；左侧只显示名称和编辑。没有独立顶部栏。 |
| 节点库第一列 | 保留旧稿的短来源名、来源图标、数量和选中层级。显示 Core、OpenCV、Barcode 等，不堆长包名或内部 ID。 |
| 节点库第二列 | 保留旧稿的用途分类树：例如 OpenCV 的图像、掩膜、分割、特征、匹配、几何、标定、测量、检查、输出；输出展开绘制和工作流。分类可浏览全部定义，不能仅展示一两个节点。 |
| 节点库第三列 | 默认双列卡片，名称＋一行短用途；可切紧凑列表，列表也有描述。单击即添加，没有底部按钮行。搜索贯通名称和用途。 |
| 节点组 | 半透明整组色面，标题条同色相。标题条在组框上方，底边与组框顶边保留 4px 可见间隔，不能粘连。启用、锁定、名称、成员数、颜色、删除集中于左上。 |
| 字体 | 节点标题 14px/400，参数名、端口名、值 13px/400；标题通过位置、分隔和色阶识别，不全用粗体。来源和类别 14px/400，卡片名称 14px/400，短用途 12px/400。页面名称可保持现有强调。 |
| 连线 | 现有单段三次贝塞尔、金色、4px 常态和中点圆柄；保留真实端口与拓扑，不绕顶避障。 |

第一、二列采用旧稿的信息组织方式，第三列按新的使用需求重做。分类树的展开用于导航；节点参数与端口始终完整显示，两者不能混淆。

## 3. 核对方式

先以当前实际页面作同视口、同缩放的基准，只处理一个明确局部；核对导航、顶部、节点尺寸和布局不变，再安排后续配对。此前整页批量生成路径撤回。

静态图是布局和视觉参考；精确字号、间隔、端口和交互以[节点契约](graph-editor-node-contracts.md)和[页面规划](graph-editor-pages-design.md)为实现依据。完整交互、键盘、短屏及高负载验证属于后续 Vue 实现验收。
