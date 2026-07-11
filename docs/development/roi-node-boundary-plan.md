# ROI 节点边界整理规划

## 背景

当前 workflow 中 ROI 相关能力已经可以串起来使用，但节点职责开始混在一起。典型问题是 `custom.opencv.crop` 既可以直接填写 `x/y/width/height`，又可以接 `roi.v1`，还挂了图像交互式取参；这会让用户误以为 Crop 是 ROI 创建节点。

ROI 相关节点需要按“创建 ROI、转换 ROI、使用 ROI、绘制 ROI、规则判断 ROI、编辑时取参”重新分层。开发阶段不保留旧实现兼容，旧的混合职责直接删除或迁移到正确节点。

## 基本原则

- `roi.v1` 是单 ROI 的平台核心 payload，`roi-list.v1` 是多个 ROI 的正式列表 payload；创建、转换、规则判断应放在 core 节点体系。
- OpenCV 节点只做图像算法执行、图像裁剪、图像绘制，不负责定义 ROI 数据结构边界。
- 图像交互式取参只属于 ROI 创建类节点或算法参数取参节点，不属于 Crop、Draw ROI 这类消费节点。
- 生产 runtime 默认不生成调试图，不做额外 PNG/Base64 编码；编辑 Preview Run 时由节点参数打开调试图。
- 节点名称要表达“做什么”，不要让一个节点同时承担创建、执行、渲染三类职责。

## 目标分层

### 1. ROI 创建节点

位置：`backend/nodes/core_nodes/vision/roi/`

这些节点负责产出标准 `roi.v1` 或 `roi-list.v1`，不直接修改图像。

| 节点 | 目标位置 | 职责 | 交互取参 |
| --- | --- | --- | --- |
| `core.vision.roi-create` | `roi_create.py` | 创建单个 bbox / polygon ROI | 是 |
| `core.vision.roi-grid-create` | `roi_grid_create.py` | 创建规则网格 `roi-list.v1` | 是 |
| `core.vision.roi-from-contour` | 已实现 | 从 contour item 创建 ROI | 是，点选已有 contour 并写回 `selected_contour_index` |
| `core.vision.roi-from-region` | 新增 | 从 region / detection 的 bbox 或 polygon 创建 ROI | 否 |
| `core.vision.roi-list-create` | `roi_list_create.py` | 把多个 ROI 或 value 列表规整为 `roi-list.v1` | 否 |

`roi-create` 应成为矩形和多边形取参的主要入口。用户在图上画框或点选多边形，最终写回的是 `roi-create` 的参数；普通 polygon ROI 至少 3 点。四点透视也使用 polygon 工具，但透视节点必须声明 `min_points=4` 和 `max_points=4`，避免把任意多边形误写成透视四点。

`roi-grid-create` 应成为槽位网格取参入口。用户在图上拖拽网格区域、调整 rows/columns/step，最终输出 `roi-list.v1`。

### 2. ROI 转换节点

位置：优先 `backend/nodes/core_nodes/vision/roi/`，只有强依赖 OpenCV 特定算法时才放 custom node。

| 节点 | 目标位置 | 职责 |
| --- | --- | --- |
| `core.vision.roi-from-contour` | core ROI | 从 contour 转 ROI |
| `core.vision.roi-to-region` | core ROI 或 vision.regions | ROI 转 region，用于后续统一规则节点 |
| `core.vision.regions-to-rois` | core ROI | regions / detections 批量转 ROI 列表 |
| `core.logic.value-to-roi` | 保留或并入 ROI | 仅做 value 到 roi.v1 的通用转换 |

`core.vision.roi-from-contour` 是 contour 到 ROI 的唯一入口；ROI 生成能力统一归到 core ROI 边界内。该节点使用 `selected_contour_index` 表示 `contours.v1.items[].contour_index` 的真实编号，不使用列表下标，避免 Contour Filter、Min Area Rect 和 ROI From Contour 的点选语义不一致。

### 3. ROI 使用节点

位置：按算法归属保留在各自节点包。

这些节点消费 `roi.v1` 或 ROI 列表，执行图像算法或数据处理，不再负责交互取参。

| 节点 | 位置 | 职责 | 调整 |
| --- | --- | --- | --- |
| `custom.opencv.crop` | `custom_nodes/opencv_basic_nodes/backend/nodes/crop.py` | 按输入 ROI 裁剪图片 | 删除 `x/y/width/height` 直接取参路径，删除交互取参 |
| `custom.opencv.crop-export` | `custom_nodes/opencv_basic_nodes/backend/nodes/crop_export.py` | 批量导出 detection / ROI crop | 已支持 `roi-list.v1`，ROI polygon 会按外接矩形裁剪并填充 polygon 外部背景 |
| `custom.opencv.template-match` | OpenCV matching | 可选 ROI 作为搜索区域 | 只消费 ROI，不创建 ROI |
| `custom.opencv.orb-keypoints` | OpenCV matching | 可选 ROI mask | 只消费 ROI |
| `custom.opencv.caliper-edge` | OpenCV measurement | 在 ROI 内找边 | 只消费 ROI |
| `core.model.sahi-inference` | core model | 内部窗口切片 | 不属于 ROI 节点，不混入 ROI 创建体系 |

Crop 节点后续应只有两个输入：`image` 和必填或可选 `roi`。如果没有 ROI 就裁整图，或者明确报错，不能再把 Crop 当作手填矩形创建器。

### 4. ROI 绘制节点

位置：`custom_nodes/opencv_basic_nodes/backend/nodes/`

这些节点只负责把 ROI/regions/detections/lines/circles 画到图上。

| 节点 | 位置 | 职责 | 交互取参 |
| --- | --- | --- | --- |
| `custom.opencv.draw-roi` | OpenCV render | 把单个 ROI 画到原图 | 否 |
| `custom.opencv.draw-rois` | OpenCV render | 批量绘制 `roi-list.v1` | 否 |
| `custom.opencv.draw-regions` | 可新增 | 批量绘制 regions | 否 |
| `custom.opencv.draw-detections` | OpenCV render | 绘制 detection bbox | 否 |
| `custom.opencv.draw-lines` | OpenCV render | 绘制线 | 否 |
| `custom.opencv.draw-circles` | OpenCV render | 绘制圆 | 否 |

截图中的 `Draw ROI` 当前职责是正确的；它不应该打开图像交互取参，也不应该写回 ROI 参数。

### 5. ROI 规则判断节点

位置：`backend/nodes/core_nodes/vision/roi/`

已有节点继续保留在 core ROI：

- `regions_coverage_check.py`
- `regions_inside_check.py`
- `regions_intersection_metrics.py`
- `regions_offset_check.py`

这些节点面向工业规则判断，不依赖 OpenCV 节点包。后续可补充 `roi-contains-point`、`roi-overlap-check`、`roi-grid-empty-summary` 等，但必须保持输入输出是标准 payload，不直接处理图像矩阵。

## 图像交互式取参归属

图像交互式取参的目标是生成或调整节点参数，不是让任意图像节点都变成编辑器。

### 应该支持交互取参的节点

| 节点类型 | 工具 | 写回参数 |
| --- | --- | --- |
| `roi-create` | bbox / polygon | `bbox_xyxy`、`polygon_xy` |
| `roi-grid-create` | grid / bbox | `rows`、`columns`、`origin_x`、`origin_y`、`roi_width`、`roi_height`、`step_x`、`step_y` |
| `hough-circles` | circle + 参数滑块 | `min_dist`、`min_radius`、`max_radius`、`param1`、`param2` 等 |
| `hough-lines` | line / search ROI + 参数滑块 | `search_bbox_xyxy`、`min_line_length`、`threshold` 等 |
| `template-match` | template ROI / search ROI | `template_bbox_xyxy`、`search_bbox_xyxy` |
| `perspective-transform` | polygon 四点 | `source_points`、`output_width`、`output_height` |

### 不应该支持交互取参的节点

| 节点 | 原因 |
| --- | --- |
| `crop` | 它是 ROI 消费节点；取参应在 `roi-create` 完成 |
| `draw-roi` | 它只负责绘制，不创建或修改 ROI |
| `image-preview` | 它只负责查看图片，不写回业务参数 |
| `crop-export` | 它批量消费检测结果/ROI 列表，不适合手动取参 |

## 需要调整的现有实现

### 已完成的第一步调整

1. `custom.opencv.crop` 已删除 `x/y/width/height` 直接参数裁剪路径。
2. `custom.opencv.crop` 已删除 `debug_preview` 交互取参，只消费 `roi.v1`。
3. `core.vision.roi-create` 已增加调试图输出和 `interaction.tools[]`：bbox、polygon。
4. `core.vision.roi-grid-create` 保留 grid 交互取参，并作为槽位分割主入口。
5. `core.vision.roi-from-contour` 已实现，旧 custom bridge 已删除。

### 后续调整

1. 已完成：`crop-export` 增加 `roi-list.v1` 输入，支持按 ROI 列表批量裁剪。
2. 已完成：新增 `core.vision.roi-list-create`，统一收敛多个 ROI 到 `roi-list.v1`。
3. 已完成：新增 `custom.opencv.draw-rois`，专门批量绘制槽位 `roi-list.v1`。
4. 后续：继续更新 catalog 分类，ROI 创建类统一显示到 `vision.roi`，OpenCV render/filter 不再出现 ROI 创建参数。

## 推荐 workflow 链路

### 单 ROI 裁剪

```text
Image -> ROI Create -> Crop -> 后续图像算法
             |
             +-> Draw ROI -> Image Preview
```

### 规则网格槽位

```text
Image -> ROI Grid Create -> For Each ROI -> Crop -> OpenCV 空槽判断 -> Array Summary
             |
             +-> Draw ROIs -> Image Preview
```

### 托盘定位后透视矫正

```text
Image -> Contour / Hough / Template Match -> ROI From Contour -> Perspective Transform -> ROI Grid Create
```

## 实现顺序与状态

1. 已完成：`roi-create` 补 debug preview、bbox/polygon interaction、默认 polygon 参数。
2. 已完成：`crop` 删除手填矩形和交互取参，只消费 `roi.v1`。
3. 已完成：`core.vision.roi-from-contour` 作为 contour 到 ROI 的 core 节点。
4. 已完成：扩展 `crop-export` 支持 `roi-list.v1`。
5. 已完成：增加 `draw-rois` 批量绘制 `roi-list.v1`。
6. 已完成：新增 `roi-list-create` 合并多路 ROI / value.v1 ROI list，并输出明确的 `roi-list.v1`。
7. 后续：更新空盘检测 workflow：使用 `ROI Create / ROI Grid Create -> Crop / Draw ROI / Draw ROIs / Crop Export` 的新链路。
8. 后续：继续补充 ROI list 下游规则判断和槽位结果汇总测试。

## 验收标准

- ROI 创建类节点负责全部图像交互取参。
- Crop、Draw ROI、Crop Export 都不能写回 ROI 参数。
- 节点分类中 `vision.roi` 只放 ROI 创建、转换、规则判断；`opencv.filter` 只放图像处理；`opencv.render` 只放绘制节点。
- workflow 里用户能清楚看到：先创建 ROI，再使用 ROI。
- 生产 runtime 中未打开调试图时不产生额外图片编码。


