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

- 托盘轮廓：`custom.opencv.contour-to-roi`，`polygon_mode=min-area-rect`。
- 标准图尺寸：`1800 x 980`。
- 槽位网格：`6 x 6`，共 36 个槽位。
- 网格参数：`origin_x=105`、`origin_y=130`、`roi_width=185`、`roi_height=90`、`step_x=285`、`step_y=127`。
- 单槽异常阈值：`abnormal_region_count <= 6`。
- 单槽异常面积占比：`abnormal_area_ratio <= 0.025`。
- 圆特征数量校验：`40 <= hole_feature_count <= 500`。

## 当前实现状态

已补齐的通用基础节点：

- `custom.opencv.contour-to-roi`：把 contour 转成 `roi.v1`，支持 `contour-points`、`min-area-rect` 和 `bbox` 三种 polygon 生成方式。
- `core.vision.roi-grid-create`
- `core.logic.value-to-roi`
- `core.logic.array-summary`
- `core.logic.variable.get`
- `core.logic.payload-to-value` 已扩展支持 `boolean.v1` 和 `result-record.v1`

当前 workflow 不保留业务专用节点，不接 YOLO。后续如果 OpenCV 空槽判断稳定后还需要增强鲁棒性，再在每个槽位 ROI 后增加 YOLO 分类分支；该能力应作为后续明确需求实现，不在当前图里预留禁用分支。

## 明确不做

- 不在本应用中实现满盘检测通过逻辑。
- 不在本应用中实现缺料检测通过逻辑。
- 不在本应用中实现独立错位检测应用逻辑。
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

## 后续扩展

- 若现场空盘图的托盘姿态变化更大，优先调 `contour-to-roi`、`perspective-transform` 和 ROI 网格参数。
- 若槽位内部误检较多，优先调单槽阈值、形态学核大小、连通区域面积过滤。
- 若需要更直观调参，优先实现图像交互取参能力，而不是继续新增业务专用节点。
- 满盘检测应用应新建独立 workflow app，不复用本应用作为满盘通过规则。
