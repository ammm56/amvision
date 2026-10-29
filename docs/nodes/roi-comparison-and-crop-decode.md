# 圆心定位、ROI 前景比较与裁剪读码

这些节点处理通用图像、ROI 和条码契约，槽位数量、产品形状、参考图、模型选择和业务规则由 Workflow 配置。

需要把缺失、多出、偏移、角度、超出允许 ROI 分开调试时，使用[按区域测量、判定与证据绘图](inspection-measurement-items.md)中的基础节点组合。集中式比较处理器保留；新拆分配方的在线验收状态见该文档链接的验证记录。

## Circle Pattern Locate

`custom.opencv.circle-pattern-locate` 接收 `circles.v1`，输出 `transform:planar-transform.v1` 和 `summary:value.v1`。参考点配置为带 `point_id/center_xy` 的数组，3–64 个；当前候选圆最多 200 个。参考与当前点都使用定位图像素。

- 以有界长基线假设匹配整个图案，通过一对一圆心对应和刚性最小二乘计算旋转、平移；不依赖候选列表顺序，不自动加入缩放、镜像或透视自由度。
- `minimum_match_ratio`、`match_tolerance_px`、`maximum_rmse_px`、`maximum_angle_degrees`、`maximum_translation_px` 是显式门槛。平移限制作用于矩阵平移向量，包含绕非原点旋转产生的分量。
- 参考共线、点距过近、匹配不足、超过假设上限或存在多个可用位姿均报错，不沿用上次结果，也不回退到固定 ROI。
- 输出矩阵从 `template-image-pixels` 到 `source-image-pixels`；`source_b_image` 为当前定位图，匹配记录保留明确的参考点名称。

周期性排列不能仅凭排列顺序确定物理槽位。配方应覆盖分布较开的稳定托盘特征；当同一组圆能匹配多个位置时，必须收紧实际允许范围或增加非重复定位特征，不能任选一个结果。匹配工件轮廓会把放歪的工件一起对齐，托盘定位应使用托盘自身结构。

## Mapped ROI Crop

`custom.opencv.mapped-roi-crop` 接收原图 `image`、上述参考到当前的 `transform`、可选 `selected_ids:value.v1`。裁剪区域必须且只能来自 `roi_items:value.v1` 或 `roi:roi.v1`。前者正文为 `{roi_id,bbox_xyxy}` 数组，后者可直接连接 Create ROI；多边形使用外接矩形，不隐式填充背景。最多 1024 项，标识不得重复。

- `selected_ids` 未连接时选择全部；显式 `[]` 选择零项；非法或未知名称报错。不会把空列表解释为全部。
- `coordinate_scale` 明确声明定位图到原图的等比倍率，并核对实际图像尺寸。采用 OpenCV resize 像素中心换算：`S=[[s,0,(s-1)/2],[0,s,(s-1)/2],[0,0,1]]`，原图变换为 `S H S⁻¹`。
- `roi_coordinate_scale` 单独声明输入 ROI 坐标到参考原图像素的倍率，默认1。乘倍率后左上向下取整、右下向上取整；与定位图的 `coordinate_scale` 不互相推断。允许交互框选的浮点坐标，拒绝布尔值、非数值及非有限值。
- 可选 `window_roi:roi.v1` 为父裁图中的矩形窗口，使用父裁图的原像素坐标，不乘 `roi_coordinate_scale`。直接组合父区域与窗口变换，只生成窗口图，避免先生成完整工件图再裁小窗口。窗口必须完整位于父矩形中，越界报错；`summary` 同时保留父矩形和窗口范围。
- 仅反向采样选中的局部矩形，输出尺寸为参考 bbox 宽高；不会先创建整幅原分辨率校正图。插值为显式 `nearest/linear/cubic`。
- 支持 uint8 图像；高位深输入明确拒绝，避免登记为8位内存图时发生隐式截断。高位深转换需要由上游明确处理。
- 奇异变换、投影越界、无效矩形以及输出总像素超过 `maximum_total_pixels` 均报错；不靠边界补色产生看似有效的裁剪结果。
- `crops:image-refs.v1` 每项保留 `roi_id/crop_index/reference_bbox_xyxy/mapped_source`。`mapped_source` 包含原图身份、原图多边形、`source_from_crop/crop_from_source`；不伪造只需平移的 `bbox_xyxy`。
- `summary:value.v1` 为每个定义的 ROI 保留 `cropped/skipped` 记录。未选择项为 `reason=not_selected`，Workflow 自行决定筛选规则。

原图仍需要正常载入内存。局部采样减少额外整图变换分配，不等于原图零内存或零拷贝。

## ROI Array 与可编辑范围

`custom.opencv.roi-array` 接收首个 `roi:roi.v1`，按 `rows/columns`、`row_step_xy/column_step_xy` 生成 `rois:roi-list.v1`，可直接连接比较、裁剪或绘制节点。矩形和多边形均支持；最多1024项，不内置产品形状、18槽或固定坐标。

- 不接 `frame` 时，首 ROI 与阵列使用父图坐标。接入 `frame:roi.v1` 时，Frame 必须是未缩放矩形裁图在父图中的范围，首 ROI 使用该裁图局部坐标。输出点 = 首 ROI 点 + Frame 整数裁剪起点 + 行号×行位移 + 列号×列位移。
- Frame 左上向下取整、右下向上取整，与 Crop Export 一致。首 ROI 带来源图片时核对其尺寸与 Frame 裁图一致；不自动缩放。可连接父图 `image` 校验尺寸并显示阵列调试图。
- 行列位移是二维向量，可描述基准图中的倾斜排列。多行/列的零步长、二维共线阵列、非有限坐标和越界均拒绝；不会截断超出范围的槽位。
- 标识为 `<roi_id_prefix>-r01-c01`，由明确行列产生。输出行优先排序仅用于展示，后续关联使用 `roi_id/item_id`，不使用画布位置或返回顺序。
- `summary:value.v1` 记录数量、位移、Frame 偏移和各项来源；`debug_preview` 使用现有图片取参面板机制。连接 Image 并启用调试图后，面板分别提供“列步距”“行步距”线段工具及行列数控件。线段起点与终点分别选相邻槽的同一特征，终点减起点写回对应二维向量；负分量保留。首 ROI 来自上游，须在上游修改，不在 Array 中隐藏覆盖。

需要复用上游 ROI 时使用 ROI Array。需要在一个节点内绘制首 ROI 并生成阵列时，优先使用下面的 ROI Grid Create，避免为了传递首 ROI 而增加裁图和类型转换链。首槽比较多边形与条码搜索矩形是不同用途的两个可编辑 ROI。

## ROI Grid Create 图片编辑

`core.vision.roi-grid-create` 保持原有矩形网格参数和 `rois:roi-list.v1` 输出，新增多边形首 ROI 与二维步距。原矩形配方不需要增加参数。

- `roi_kind=bbox`（默认）：`origin_x/origin_y/roi_width/roi_height` 定义首矩形。
- `roi_kind=polygon`：`polygon_xy` 定义首多边形，使用输入图片坐标，矩形原点与尺寸不参与多边形几何计算。
- 列向量为 `[step_x, column_step_y]`，行向量为 `[row_step_x, step_y]`。后两个交叉分量默认0；第 r 行第 c 列的点等于首 ROI 点 + c×列向量 + r×行向量，r/c 从0开始。支持有方向的负分量，拒绝重复方向的零向量和二维共线阵列。
- 图片面板打开时默认选当前形状工具。矩形可框选，多边形可移动、缩放和拖动顶点；两个步距工具分别画线取参。行列数和数值步距可直接调整。点击“应用参数”写入当前节点；“应用并预览”执行到该节点并刷新整组阵列。没有额外后台计算或自动修改上游节点。
- 重新框选首矩形保留已显式配置的步距，避免形状大小调整时意外覆盖槽间距离。未设置步距时仍使用矩形宽、高。
- 重复区域是派生显示，只有首 ROI 可以拾取写回。调试 overlay 的可选 `pickable=false` 明确关闭拾取；未设置时保持原有行为。只影响编辑预览，不改变业务输出。
- `bounds_policy` 的默认值仍为 `reject`。矩形支持 `reject/clip/allow`；多边形支持 `reject/allow`，不支持只裁剪 bbox 而保留原多边形的隐式 clip。
- ROI ID 仍为 `<prefix>-01-01`，可直接接 ROI List Item Get、比较、裁剪和绘制节点。下游按 `roi_id/item_id` 关联，画布坐标不参与执行。

3913 正面草稿现使用“校正概览图 → ROI Grid Create → 放置检查/裁剪/绘制”。原托盘框保留用于整盘定位显示核对，首槽直接使用校正图坐标；修改托盘显示框不会移动网格。ROI List Item Get（index=0）直接提供条码编辑所需首槽。

Planar Transform Bridge 用于已有变换下的图片/ROI 坐标转换，不负责寻找位置。本例 Align 使用当前→参考方向校正概览图，托盘范围回绘使用参考→当前方向；不能对已校正坐标重复叠加位姿。固定参考圆心描述基准托盘，每次扫描检测到的圆心与变换是动态值。

## Image Decode

`custom.opencv.image-decode` 将 `image-ref.v1` 显式解码为当前 Run 的 memory/raw 图片，保留 uint8/uint16/float32 和1/3/4通道；实际可读类型由底层解码器决定。已有 memory/raw 输入验证后直接复用，不重复登记句柄。它不改变像素几何，保留已有 `mapped_source/roi_id`。

需要在循环中多次读取大图时，在循环外放置此节点，再把输出引用送入各次裁剪。原图内存随 Run 结束释放，不跨 Run 缓存，不修改平台256 MiB解码缓存上限。大图占用和读盘成本仍然存在。

## ROI Foreground Compare

`custom.opencv.roi-foreground-compare` 接收 `image`、`reference_image`（`image-ref.v1`）和 `rois`（`roi-list.v1`）。两图必须在同一坐标系且尺寸一致，按 uint8 灰度比较；节点不自动对齐、缩放或推断高度。

- 支持矩形与多边形 ROI，1–1024 项，`roi_id` 唯一。越界 ROI 拒绝执行，不静默裁剪。
- `foreground=dark` 使用灰度小于等于 `threshold` 的像素；`light` 使用大于阈值的像素。
- `tolerance_pixels` 是当前输入图的像素邻域半径。缩小图片后，参数也属于缩小图坐标。
- 缺失：参考前景在当前前景容差邻域外的面积。溢出：当前前景在参考前景容差邻域外的面积。两项比例均以参考前景面积为分母。
- 多边形是明确的比较域；默认关闭边界检查时，域外像素不参与判定。相邻工件外接矩形重叠时，可用多边形排除邻件。它不是物体分割模型。
- 参考前景小于 `min_reference_area` 时返回 `invalid_reference`，不会因为两张空图相同而通过。
- `check_pose` 默认关闭。启用后同时比较前景质心偏移和无向主轴角差，以 `max_centroid_shift_pixels/max_axis_angle_degrees` 判定。主轴采用二阶矩特征向量，近圆形（各向异性小于0.1）或前景不足时不可用，启用姿态检查时不能通过。角差范围0–90°，不能检测对称物体的180°翻转，也不是高度测量。
- `check_boundary` 默认关闭。开启后原 ROI 表示允许区域，按 `search_margin_pixels` 向外扩大观察域；余量必须大于 `tolerance_pixels`，且完整搜索框必须在图片内。超过允许区域及边缘容差的当前前景面积除以当前总前景面积，得到 `outside_ratio`，与 `max_outside_ratio` 比较。空前景不通过；参考图自身的越界比例超限时返回 `invalid_reference`。
- `emit_comparison_images` 默认关闭；启用时图像输出 `comparison_images:image-refs.v1` 保留各 ROI 的标识和局部差异图，绿色为匹配前景、红色为缺失、橙色为溢出、紫色为允许区域外的前景，灰线表示允许边界。关闭时为空图集，不分配差异彩图。

`summary:value.v1` 的正文为 `amvision.roi-foreground-comparison.v1`，包含 `count/passed/image_size/reference_image_size/coordinate_space/rules/items`。每项为 `item_id/source/result`，`item_id=roi_id`；`source` 保留几何信息，`result` 保留面积、缺失/溢出比例、IoU、状态及 `passed`。无参考面积时比例是 `null`，不是零。

`regions:regions.v1` 可直接接 Draw Regions；状态为 `within_tolerance/outside_tolerance/invalid_reference`。绘制用的 `score=1` 是规则结果标记，不是模型置信度。模板姿态或光照变化需要配方与采集条件验证；二维轮廓相同不能证明物体未翘起。

每项结果另含 `shape_passed/pose_passed/boundary_passed/reasons`，关闭的可选检查返回 `null`。质心坐标相对实际搜索框；边界检查开启时额外返回 `search_bbox_xyxy/pose_origin_xy/allowed_roi/reference_outside_ratio`。`source`、绘制 `regions` 仍指向原 ROI，不因搜索余量而改变后续裁剪坐标。偏移量属于输入图像素，不能直接解释为毫米。

比较域应覆盖本件及允许变化区域，同时避开邻件和塑盒暗结构。搜索余量有限，完全离开观察域的物体只能通过缺失等证据检出，不能定位其去向。工件侵入相邻槽的检查范围时，两个槽都可能失败，不代表关联错位。阈值前景不等于真实工件分割；反光、背景和材料变化必须使用现场样本标定。

## Crop Export 的裁剪来源

现有 `image + detections`、`image + rois` 接法保持原行为。增加两个可选来源：

| 输入 | 类型 | 行为 |
| --- | --- | --- |
| `roi_items` | `value.v1`，正文为 ROI 记录数组 | 保留每项 `roi_id`，允许空数组，输出空图集 |
| `regions` | `regions.v1` | 按外接矩形裁剪，保留 `region_id`；不自动以多边形填黑背景 |

连接新来源时不得同时连接其他裁剪来源，冲突直接报错。原有 `rois` 与 `detections` 同时连接时仍按已定义的 ROI 优先行为处理。`box_padding` 在裁剪前外扩并按图像边界裁剪，实际整数框记录在输出 `bbox_xyxy` 中。

大图的多个搜索区域宜一次 Crop Export，再用 Image Refs To Value List → For Each → Value To Image Ref 逐图处理，避免在循环内反复解码整张图片。裁剪图通过引用流转，不复制到 JSON 正文中。

若需要逐件在完整工件图中编辑搜索框，可使用 Image Decode → Mapped ROI Crop → Create ROI → ROI List Create → Crop Export。Create ROI 的 Image 输入连接工件图，开启调试图后可用已有矩形工具修改并应用坐标；裁剪尺寸来自框选值，不固定为1000×1000。Crop Export 在输入有 `mapped_source` 时组合 `父图到原图矩阵 × 当前裁剪平移矩阵`，输出更新后的正逆矩阵和原图四角。Gallery Preview 优先显示 `roi_id`，方便核对槽位。

完整工件很大时，可在 Create ROI 的显示输入前显式连接 Image Encode（JPEG），
减少编辑预览待处理矩阵的占用。Crop Export 的 Image 输入仍连接原始工件图；
显示编码保持原尺寸，不改变取参坐标，也不应用到模型或条码解析的像素链路。
循环中的同一个 Create ROI 参数会作用于所有迭代，图像显示当前或最后一次工件；
如需逐槽不同配置，应按 `roi_id` 提供显式配方映射，不能靠迭代顺序隐式对应。

性能优先的另一种明确接法：在循环外只裁一张参考工件图供 Create ROI 编辑；循环内将该 ROI 接入 Mapped ROI Crop 的 `window_roi`，从原图直接采样每件搜索区域。窗口位置和尺寸仍来自可编辑节点。图像编码只用于编辑显示，模型输入保持原像素。

同一部署的多张搜索图可使用现有 Detection Batch 一次提交；该节点在一个实例上顺序推理，不代表模型张量 Batch 或自动并行。输入和结果按 `roi_id/item_id` 关联：Batch To Items 校验唯一 ID，Group List 按 ID 分组，循环使用明确 ID 提取唯一结果。来源矩阵保留在搜索图引用中，不从结果列表顺序推断。空列表须通过 Conditional Start/End 显式绕过 Batch，随后空 For Each 自然返回空列表。

## Barcode Crop Decode

`custom.barcode.crop-decode` 接收 Crop Export 的 `image-refs.v1`。每张图必须携带正整数 `crop_index` 和整数 `bbox_xyxy`，裁剪宽高必须与 bbox 一致；缩放过的图不能直接按平移映射。一次最多 1024 张，顺序解码，检查取消和超时，不进行隐藏的参数轮询或重试。

- `format`：全部可读制式、Data Matrix、QR Code。
- `binarizer`：显式选用 ZXing 的局部均值、全局直方图、固定阈值或布尔转换；默认局部均值，不保证适合所有采集图像。
- `decode_scale`：默认 1，不插值；2–4 使用固定 cubic 插值后解码，插值后最多 1600 万像素。坐标按像素中心规则还原到原裁剪图，再平移到父图；`source_image` 不变。此选项只由裁剪读码节点显式传入，其他解码节点默认行为不变。颜色通道选择、增强由前置通用节点决定，不在解码器内自动搜索预处理参数。
- 标识优先使用 `roi_id`，其次 `region_id`，否则为 `crop-<crop_index>`；标识不得重复。
- `results:barcode-results.v1` 保留标准解码结果。位置映射到裁剪前的**直接父图**，不会猜测更上层原图坐标。
- `summary:value.v1` 正文为 `amvision.barcode-crops.v1`；每项为 `item_id/source/result`。零个有效码为 `unreadable`，一个为 `decoded`，多个为 `ambiguous`。没有候选图时为 `no_candidates`，有未读出或多码项时整体为 `incomplete`。

两层裁剪示例：整图 → 搜索区域 → 条码区域。解码输出坐标已经包含条码区域在搜索图内的偏移，映射到整图时只需再加搜索区域的左上角；不能把条码偏移重复加一次。Workflow 汇总时应保留搜索区域的 `roi_id` 和 bbox，不按返回列表位置猜测槽位。

若搜索图由 Mapped ROI Crop 生成，则使用 `mapped_source.source_from_crop` 对解码位置作齐次变换并除以第三分量，不能只加外接框左上角。解码倍率已在节点内还原，不应再次除以倍率。

## 验证边界

最小自动化检查覆盖：图案乱序、漏点、伪点、歧义位姿、假设上限、取消、像素中心倍率映射、局部采样像素、空选择、正常参考、空前景、偏移、旋转、多边形邻件排除、重复标识、越界、空候选、未读出、裁剪坐标不一致，以及已知文本的真实 Data Matrix 编解码与显式倍率回映射。

开发样本配置与正式 Preview 验证入口为 `scripts/configure_linescan_3913_workflow.py`、`scripts/validate_linescan_3913_workflow.py`。`scripts/validate_linescan_front_registration.py` 验证实际圆检测和已知位姿；`scripts/validate_linescan_front_cases.py` 验证整链运动、局部扰动、定位失败和异常槽跳过。当前草稿仅用于正面，反面须另建 Workflow。实际图片和报告位于开发数据目录，不作为通用节点运行时依赖。合成缺陷只验证流程响应，不替代真实缺陷、采集公差、读码真值及长期运行验收。

2026-10-29 正面草稿改用 `scripts/configure_linescan_front_array.py` 的可编辑托盘/首槽阵列配置；原配置命令也复用此步骤，避免重建18组静态 ROI。定位概览为原图1/8，托盘范围 `[30,60,2370,1760]`，3行6列，列位移 `[343,-3]`、行位移 `[4,500]`；数值属于当前开发样本配置，不属于通用节点默认值。比较启用形状、位姿、边界三项，条码框初始 `[1720,1000,2720,2000]`，作用于正常工件原分辨率裁图，可在节点中改尺寸和位置。阶段预览包含圆定位、校正、托盘范围、阵列编号、18槽裁图、逐槽差异、放置结果、条码搜索、检测框、条码裁图和解码结果。
