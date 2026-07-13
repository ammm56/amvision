# 空盘检测 Workflow App 开发说明

## 适用范围

本文档固定 `workflow-app-20260710020359` 的开发目标、实现边界和节点组合规划，防止后续实现时把空盘检测、满盘检测、缺料检测和错位检测混在同一个应用里。

当前应用只回答一个问题：输入托盘图像是否为正常空盘。

## 当前应用

- Workflow App：`workflow-app-20260710020359`
- 应用名称：空盘检测应用
- Template：`workflow-graph-20260710020359`
- Template 文件：`data/files/workflows/projects/project-1/templates/workflow-graph-20260710020359/versions/1.0.0/template.json`
- Application 文件：`data/files/workflows/projects/project-1/applications/workflow-app-20260710020359/application.json`

当前应用输入：

- `request_image_ref`：生产默认输入，适合 ZeroMQ / LocalBuffer / BGR24 高性能链路。
- `request_image_base64`：HTTP 调试或前端 Preview Run 兜底输入。

## 唯一主线

当前 workflow 只保留一条主线，不再保留整图差分、圆模板、插槽模板或调试预览等并行分支。原因是现场图片存在相机截取误差、托盘定位误差和光照差异，整图直接比较不稳定；图面保留多条分支也会增加 Preview Run 和调试负担。

主线目标：先把托盘定位并透视归一到标准图，再按槽位 ROI 逐格判断是否为空槽。

```text
Image Ref Coalesce
 -> Otsu Threshold
 -> Morphology Close
 -> Contour
 -> Contour Filter
 -> Contour To ROI
 -> Perspective Transform
 -> Hough Circles 特征校验
 -> ROI Grid Create
 -> For Each Slot ROI
      -> Crop 当前槽位
      -> Crop 参考槽位
      -> Image Diff
      -> Absdiff Threshold
      -> Morphology Open
      -> Connected Components
      -> Regions Count / Regions Area Ratio
      -> Range Check
      -> Process Decision
      -> Create Slot Result
 -> Array Summary
 -> Process Decision
 -> Response Envelope
```

关键参数：

- 托盘轮廓：`core.vision.roi-from-contour`，`polygon_mode=min-area-rect`。
- 标准图尺寸：`1800 x 980`。
- 槽位网格：`6 x 6`，共 36 个槽位。
- 网格参数：`origin_x=105`、`origin_y=130`、`roi_width=185`、`roi_height=90`、`step_x=285`、`step_y=127`。
- 单槽异常阈值：`abnormal_region_count <= 6`。
- 单槽异常面积占比：`abnormal_area_ratio <= 0.025`。
- 圆特征数量校验：`40 <= hole_feature_count <= 500`。

## 当前实现状态

已补齐的通用基础节点：

- `core.vision.roi-from-contour`：把 contour 转成 `roi.v1`，支持 `contour-points`、`min-area-rect` 和 `bbox` 三种 polygon 生成方式。
- `core.vision.roi-grid-create`
- `core.logic.value-to-roi`
- `core.logic.array-summary`
- `core.logic.variable.get`
- `core.logic.payload-to-value` 已扩展支持 `boolean.v1` 和 `result-record.v1`

当前 workflow 不保留业务专用节点，不接 YOLO。后续如果 OpenCV 空槽判断稳定后还需要增强鲁棒性，再在每个槽位 ROI 后增加 YOLO 分类分支；该能力应作为后续明确需求实现，不在当前图里预留禁用分支。

## 托盘分割测试应用补充

当前用于验证“托盘轮廓 -> 透视矫正 -> ROI Grid -> 批量裁剪 -> OpenCV 空槽检查”的测试应用为：

- Workflow App：`workflow-app-20260712143843`
- Template：`workflow-graph-20260712143843`
- Template 文件：`data/files/workflows/projects/project-1/templates/workflow-graph-20260712143843/versions/1.0.0/template.json`

该应用用于开发调试，和正式生产 app 的边界不同：正式空盘检测和满盘检测应拆成两个独立 workflow app；该测试应用允许同时放置空槽检查、有料检查和统计判断分组，便于用同一批样本快速对照验证节点稳定性。

当前主链路保持通用基础节点组合，不新增业务专用节点：

```text
Perspective Transform
 -> ROI Grid Create
 -> Crop Export
 -> Image Refs Slot Metrics
 -> Image Refs Empty Check
 -> Image Refs Occupied Check
 -> Slot Batch State
 -> Value Preview / Response Body
```

`custom.opencv.image-refs-slot-metrics` 消费 `crop-export` 输出的 `image-refs.v1`，统一计算每个槽位的基础图像指标。该节点是槽位空/有料判断的基础层，负责把灰度、亮暗比例、边缘密度和暗连通域指标结构化输出为 `amvision.image-refs-slot-metrics.v1`。调试时可打开节点的 `debug_preview`，用 contact sheet 直接观察每个槽位的指标；生产 runtime 默认不生成调试图。

`custom.opencv.image-refs-empty-check` 必须消费 `image-refs-slot-metrics` 输出的 metrics，并按以下多指标组合判断每个槽位是否为空：

- `std_gray`：灰度标准差，拦截槽位内强纹理或物料变化。
- `dark_ratio`：暗像素比例，拦截黑色、深色或遮挡物料。
- `edge_density`：边缘密度，拦截额外结构、物料边缘或错位遮挡。
- `dark_component_area_ratio`：暗连通域总面积占比。
- `largest_dark_component_area_ratio`：最大单个暗连通域面积占比。

当前默认规则是所有启用规则都通过才判 `empty`。该策略对空盘更保守，避免单一指标被光照、高光或插槽纹理误导；现场如需适配不同托盘材质，应优先调整这些基础阈值，而不是新增业务专用节点。

`custom.opencv.image-refs-occupied-check` 同样必须消费同一份 metrics，按有料方向的规则判断每个槽位是否为 `occupied`：

- `std_gray_occupied_min`：有料槽位要求的最小灰度标准差。
- `dark_ratio_occupied_min`：有料槽位要求的最小暗像素比例。
- `edge_density_occupied_min`：有料槽位要求的最小边缘密度。
- `dark_component_area_ratio_occupied_min`：有料槽位要求的最小暗连通域总面积比例。
- `largest_dark_component_area_ratio_occupied_min`：有料槽位要求的最小单个暗连通域面积比例。
- `occupied_min_pass_count`：至少通过多少条启用规则才判 `occupied`，用于避免单一指标被光照、反光或纹理误导。

`custom.opencv.slot-batch-state` 合并 empty-check 和 occupied-check 的 summary，输出整批槽位状态：

- `empty-tray`：空槽比例达到 `empty_min_empty_ratio`。
- `full-tray`：有料比例达到 `full_min_occupied_ratio`。
- `partial-or-abnormal`：既不是正常空盘，也不是正常满盘，通常对应缺料、错位、定位失败或阈值未调稳。
- `failed`：槽位数量不一致或输入数量不符合 `expected_count`。

该统计节点只判断批量状态，不关心托盘、料盘或零件的具体业务语义，因此后续也可被其它阵列 ROI 检测 app 复用。

空槽/有料判断节点仍保留可选 `images` 输入，但它只用于编辑 Preview Run 的交互式参数图片面板和调试 contact sheet。判断计算必须复用 `metrics`，不能在规则节点里重新计算基础指标。这样节点边界更清楚：`Slot Metrics` 是指标层，`Empty Check` / `Occupied Check` 是规则层，后续新增其它规则也可以复用同一份指标。

## 明确不做

- 不在正式空盘检测应用中实现满盘检测通过逻辑。
- 不在正式空盘检测应用中实现缺料检测通过逻辑。
- 不在正式空盘检测应用中实现独立错位检测应用逻辑。
- 不把托盘分割测试应用中的有料检查分组直接当作生产满盘检测 app。
- 不在本阶段接 YOLO 分类或检测模型。
- 不新增 `tray-empty-check`、`tray-slot-occupancy` 这类业务专用节点。
- 不新增专用节点包。
- 不把大量业务判断写死到 Python 节点代码里。

如果现有节点能力不足，只补通用基础节点。基础节点必须能被后续满盘检测、缺料检测、错位检测、阵列 ROI 检测等其他 workflow app 复用。

## 图像交互取参要求

ROI、找圆、找直线、找边、模板匹配等节点的参数不能长期只靠文本输入。它们应接近 VisionMaster / Halcon 的交互方式：在节点属性面板中显示输入图像，双击进入大图编辑，在图像上直接画 ROI、圆、直线或测量区域，完成后把参数写回节点 `parameters`。

该能力是 workflow graph editor 的通用能力，不属于空盘检测专用节点：

- 节点定义通过 `parameter_ui_schema` 或 `metadata` 声明需要的图像辅助取参工具。
- 前端根据节点输入端口和最近一次 Preview Run / 当前公开输入解析可用图像。
- 图像缩略图显示在节点底部，和现有图片预览节点一致；节点参数开关默认关闭，编辑调试时手动打开。
- 双击节点底部缩略图打开统一交互式图片面板，复用现有 Preview 大图查看能力，并增加 ROI、circle、line、point、polygon 等 overlay 工具。
- 用户确认后，前端把图像坐标转换成节点参数，例如 `source_points`、`roi`、`min_radius`、`max_radius`、`line_segment`、`search_region`。
- 后端节点只消费稳定参数，不依赖前端交互状态。

优先实现顺序：

1. ROI polygon / bbox 取参，用于 crop、perspective-transform、roi-grid-create。
2. Circle 取参，用于 hough-circles、圆孔定位和半径范围估计。
3. Line 取参，用于找线、边缘定位和角度校正。
4. Template 区域取参，用于模板匹配节点生成模板 ROI。

## Preview Run 性能要求

空盘检测主线包含 36 个槽位的 `for-each`，直接保留完整 `node_records` 会产生数百条节点记录。图编辑器 Preview Run 在没有 `*-preview` 节点或未打开节点调试图片面板时应默认关闭完整节点记录，只保留最终输出和失败信息；需要查看图像、表格或交互取参时，再手动打开对应节点的调试图片面板或放置 preview 节点。当前 Preview Run 默认执行超时调整为 120 秒，sync 等待约 140 秒，仍需避免用超时掩盖不必要的节点和中间结果开销。

## 样本用途

开发图片目录：

`data/files/developer/空盘满盘检测`

当前样本：

- `空盘_1080p_01.jpg`：空盘检测的正常样本和空盘参考图。
- `满盘_1080p_01.jpg`：空盘检测负样本。
- `缺料_1080p_01.jpg`、`缺料_1080p_02.jpg`、`缺料_1080p_03.jpg`：空盘检测负样本。
- `错位_1080p_01.jpg`：空盘检测负样本，用于验证定位或对齐失败。
- 720p 图片：分辨率缩放和鲁棒性辅助验证，不作为第一阶段主调参样本。

满盘、缺料和错位图片在本应用中只用于验证“不是正常空盘”能否被拒绝，不用于建立满盘应用的通过规则。

## 输出目标

正常空盘输出：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "format_id": "amvision.empty-tray-result.v2",
    "inspection_type": "empty-tray",
    "inspection_branch": "slot-roi-grid",
    "is_empty": true,
    "slot_summary": {
      "count": 36,
      "truthy_count": 36,
      "falsey_count": 0,
      "all_truthy": true
    },
    "hole_feature_count": 215
  }
}
```

非空盘、缺料、错位或其它异常输出：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "format_id": "amvision.empty-tray-result.v2",
    "inspection_type": "empty-tray",
    "inspection_branch": "slot-roi-grid",
    "is_empty": false,
    "slot_summary": {
      "count": 36,
      "truthy_count": 0,
      "falsey_count": 36,
      "all_truthy": false
    }
  }
}
```

字段含义：

- `is_empty`：是否为正常空盘。
- `slot_summary`：36 个槽位逐格判断的汇总。
- `slots`：每个槽位的判断结果、异常连通区域数量和异常面积占比。
- `hole_feature_count`：透视标准图上的圆特征数量，用于托盘存在和定位可信度校验。
- `decision`：总判定结果。

## 当前烟测结果

本地使用 `WorkflowGraphExecutor` 直接执行 template，输入为 `request_image_base64`：

| 样本 | 期望 | 结果 | 槽位通过 |
| --- | --- | --- | --- |
| `空盘_1080p_01.jpg` | 正常空盘 | `is_empty=true` | 36 / 36 |
| `满盘_1080p_01.jpg` | 不是空盘 | `is_empty=false` | 0 / 36 |
| `缺料_1080p_01.jpg` | 不是空盘 | `is_empty=false` | 0 / 36 |
| `错位_1080p_01.jpg` | 不是空盘 | `is_empty=false` | 0 / 36 |

`workflow-app-20260712143843` 当前用 `image-refs-empty-check` 的本地验证结果：

| 样本 | 期望 | 结果 | 空槽 / 非空槽 |
| --- | --- | --- | --- |
| `空盘_1080p_01.jpg` | 正常空盘 | `state=ok` | 36 / 0 |
| `满盘_1080p_01.jpg` | 不是空盘 | `state=ng` | 2 / 34 |
| `缺料_1080p_01.jpg` | 不是空盘 | `state=ng` | 35 / 1 |
| `缺料_1080p_02.jpg` | 不是空盘 | `state=ng` | 30 / 6 |
| `缺料_1080p_03.jpg` | 不是空盘 | `state=ng` | 28 / 8 |
| `错位_1080p_01.jpg` | 不是空盘 | `state=ng` | 0 / 36 |
| `空盘_20mp_01.jpg` | 正常空盘 | `state=ok` | 36 / 0 |
| `满盘_20mp_01.jpg` | 不是空盘 | `state=ng` | 0 / 36 |

`workflow-app-20260712143843` 增加 `image-refs-occupied-check` 和 `slot-batch-state` 后，本地验证结果：

| 样本 | Empty Check 空槽 / 非空槽 | Occupied Check 有料 / 空 | Batch State |
| --- | --- | --- | --- |
| `空盘_1080p_01.jpg` | 36 / 0 | 0 / 36 | `empty-tray` |
| `满盘_1080p_01.jpg` | 2 / 34 | 36 / 0 | `full-tray` |
| `缺料_1080p_01.jpg` | 35 / 1 | 1 / 35 | `partial-or-abnormal` |
| `错位_1080p_01.jpg` | 0 / 36 | 36 / 0 | `full-tray` |

`错位_1080p_01.jpg` 的结果说明：仅靠槽位有料检查只能回答“槽位 ROI 内是否有物料特征”，不能判断物料是否错位。错位、偏移、姿态不一致应作为独立的几何一致性或定位质量分组实现，例如标准图边缘一致性、槽位中心特征偏移、关键轮廓位置偏差或模板匹配残差检查，不能塞进 `image-refs-occupied-check` 里混淆职责。

## 后续扩展

- 若现场空盘图的托盘姿态变化更大，优先调 `roi-from-contour`、`perspective-transform` 和 ROI 网格参数。
- 若槽位内部误检较多，优先调单槽阈值、形态学核大小、连通区域面积过滤。
- 若需要更直观调参，优先实现图像交互取参能力，而不是继续新增业务专用节点。
- 满盘检测应用应新建独立 workflow app，不复用本应用作为满盘通过规则。
