# 图编辑节点、连线与分组设计依据

> 2026-10-29 最新范围：此前整页稿已撤回；以[当前实现基准](graph-editor-current-baseline.md)为准。本文的字段、参考研究和节点库内部规划保留，不作为重画导航、顶部、节点尺寸或整页布局的授权。

更新：2026-10-29。此表约束设计图，不改变节点接口。新增节点场景必须先核对相应Catalog和参数UI，不能从旧图推测参数。

## 1. 已核对的渲染行为

- 连线金色来自[主题Token](../../../frontend/web-ui/src/shared/styles/tokens/graph.css)，亮色#D99018、暗色#F2B84B。长边直接经过节点后方，不作避障路由。输入、输出及参数端口沿原有方向色，不统一染绿。
- [右下视图工具](../../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowGraphViewportControls.vue)顺序为缩小、百分比重置、放大、分隔、适配、小地图，使用ZoomOut/ZoomIn、Scan、Map图标。

- [连线几何](../../../frontend/web-ui/src/workflows/workflow-editor/geometry/useWorkflowGraphGeometry.ts)使用单段三次贝塞尔曲线，首尾控制点与端口同Y，水平切线。左右距离控制曲率，不能改画为直角、圆角折线或加箭头。[连线层](../../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowGraphLinksLayer.vue)没有marker-end；中点圆形命中柄不是箭头。
- [节点组件](../../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowGraphNode.vue)直接渲染端口行及参数；[参数组件](../../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowNodeParameterWidgets.vue)按Schema选择文本、数值、复选框、枚举、JSON、色表和专属编辑器。新设计保持完整直显，不添加更多端口或更多参数。
- 参数绑定输入时，连接点在该字段旁，连上后固定值编辑禁用并标注来源。不能把同一个Path端口在标题区和参数区重复画两遍。
- 普通参数全部在节点中可编辑。集合数据可使用直接可见的行表或JSON编辑框；大量条目可在专属编辑器编辑，但不能以此隐藏其他参数。缩放/裁剪视口不是参数折叠；视口外节点可虚拟化，不改变节点的完整布局。

## 2. 样例节点完整契约

五节点合计34参数、13输入端口、7输出端口，其中Path按参数绑定只呈现一次。示例值不等于默认值；下面明确区分。

| 节点及源码 | 输入 | 输出 | 参数（全部直接显示） |
| --- | --- | --- | --- |
| [Load Local Image](../../../backend/nodes/core_nodes/io/local/image_load_local.py) | File可选；Path绑定local_path | Image、Summary | missing_file_policy=error（可选blank）；local_path示例D:/samples/part_0042.jpg；use_blank_image_when_empty=false；blank_image_width=640；blank_image_height=480；max_bytes显示64 MB；max_pixels显示100 MP |
| [Detection](../../../backend/nodes/core_nodes/model/deployment/deployment_detection.py) | Image必填；Dependency、Request可选 | Detections | deployment_instance_id必填（显示名称+选择）；score_threshold默认0.3；auto_start_process示例true；save_result_image示例false；return_preview_image_base64示例false；extra_options示例{} |
| [Detections To Regions](../../../backend/nodes/core_nodes/vision/regions/detections_to_regions.py) | Detections必填；Image可选 | Regions、Summary | region_id_prefix默认det；class_id_default默认-1；class_name_default空字符串 |
| [Draw Regions](../../../custom_nodes/opencv_nodes/categories/render/workflow/catalog_sources/nodes/draw_regions.json) | Image、Regions，保留Catalog顺序 | Image | mask_alpha=0.35；line_thickness=2；font_scale=0.5；draw_masks=true；draw_polygons=true；draw_boxes=true；draw_labels=true；label_offset_x=0；label_offset_y示例-8（默认0）；draw_region_id=true；draw_class_name=true；draw_score=true；color_by示例class-name（默认region-id）；class_colors={}可添加颜色行；save_location空 |
| [Image Preview](../../../backend/nodes/core_nodes/io/image/image_preview.py) | Results、Display Data、Data Context可选；Image必填 | Body | title默认Image Preview；response_transport_mode默认inline-base64（另有storage-ref）；save_location默认空 |

Local Image的大小默认值来自[读取模块](../../../backend/nodes/core_nodes/support/local_io/reading.py)。Detection三个布尔字段Schema未给默认值；[请求构造](../../../backend/nodes/core_nodes/support/deployment_model.py)对未指定auto_start_process按非false处理，保存与Base64按显式true处理。设计图使用显式示例值，不冒称UI自动默认。

流程五边：Load.Image → Detection.Image；Detection.Detections → Detections To Regions.Detections；Detections To Regions.Regions → Draw Regions.Regions；Load.Image → Draw Regions.Image；Draw Regions.Image → Image Preview.Image。箭头仅用于文档表达方向，画布不画箭头。其余端口保持可见、未连。

样例不重复连接Detections To Regions的可选Image端口：其实现允许从detections.source_image解析图像引用，或在无来源图像时保留空来源；本图的Draw Regions仍明确接入原始图像。该可选端口完整显示为未连，不删除端口或更改接口。简化为五边不改变检测、区域转换和绘制的责任。

## 3. 节点组的五项操作

依据[分组组件](../../../frontend/web-ui/src/workflows/workflow-editor/components/WorkflowGraphGroupLayer.vue)和[分组逻辑](../../../frontend/web-ui/src/workflows/workflow-editor/graph/useWorkflowGraphGroups.ts)。

| 操作 | 设计与实际边界 |
| --- | --- |
| 启用/禁用 | 组标题常驻圆勾/禁用图标；支持混合状态。作用于成员节点，App Entry、App Result和group_toggle_protected成员受保护；部分跳过时短提示。不是服务启停，也不是预览成功标志。 |
| 锁定/解锁 | 独立锁按钮，阻止组拖动与缩放，隐藏缩放柄；不能显示为执行禁用。保持现有独立锁图标与tooltip，不增加一组解锁按钮。成员内部参数是否可编辑按节点权限，不把锁组宣称锁死整个工作流。 |
| 编辑名称 | 名称双击编辑，Enter/失焦提交、Esc取消，空名就地提示；沿用当前方式，不增加铅笔。 |
| 选择颜色 | 常驻色块，点击12色色板；选中色有清楚的描边或勾选。颜色只组织画布，不代表健康或业务OK/NG；组背景完整半透明着色，网格可见；标题条采用相同色相。 |
| 删除 | 常驻垃圾桶，提示“删除分组，保留节点”；现有逻辑只删除组，保留节点/便笺及连线。不能误画成删除组内全部节点。 |

五项操作具有文字tooltip及可访问名称，不仅悬停才出现。一般态只保留启用、锁定、组名、成员数、颜色、删除（改名通过双击）；不堆操作说明。组框全包含确定成员，拖动分组带动成员。当前样例两组均启用；组操作图第二组锁定但继续启用。

## 4. 字重、组间隔与工具栏

- 节点标题14px/400，端口、参数名和值13px/400；不全部加粗。节点标题无装饰图标，层次通过位置、色阶和分隔体现。
- 组标题条沿当前 `top:-32px`、高28px 的结构，条底与组框顶之间保留4px画布间隔；不得粘连或嵌入组框。标题条20%组色混合面板，组面7%组色混合透明，同色相而有主次；网格透出。
- 顶部当前四个浮动容器：节点组/刷新；应用模式/预览/保存/发布；属性面板；版本。容器42px、padding4px、圆角10px、间距10px；按钮32px、字号14px、Lucide图标16px/stroke2、图文间距7px。
- 节点库的前两列可以重新设计；采用旧稿短来源名和用途树。节点库内部优化不得改变现有导航、顶部、节点尺寸和画布布局。
- 静态栅格图表达视觉关系，生成像素可能与CSS有偏差。实施必须使用上述组件尺寸，不能测量PNG反推新尺寸。

## 5. 后续出图的统一准入检查

1. 先记录节点type、全部输入输出、参数名/类型/单位/默认值、参数输入绑定及明确的磁盘/外部副作用。
2. 节点的名称、字段、对象编辑器与节点库一致；端口与连线逐条核对，禁用/锁定/预览/健康状态分开。
3. 通用图像、规则、数据节点沿Core/OpenCV；连接器、异常检测、3D/点云专业工具归各自扩展包，不加入泛化万能节点。
4. 专业编辑器可以开大工作区，普通数值、选择和开关仍在节点内直显。短屏通过平移缩放和覆盖面板工作，不自动折叠几百个节点。
5. 图像生成是样式示意，Schema逐项表是实现依据；不能用静态图声称真实连线、性能或工业验收通过。
