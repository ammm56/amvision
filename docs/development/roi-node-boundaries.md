# ROI 节点边界

ROI 使用 `roi.v1`，多个 ROI 使用 `roi-list.v1`。ROI 是独立的几何 payload，不等同于裁剪后的图片、检测结果或前端 overlay。

## 分层

### 创建

Core ROI 节点负责从明确参数或上游几何创建标准 payload，例如：

- `core.vision.roi-create`
- `core.vision.roi-grid-create`
- `core.vision.roi-from-contour`
- `core.vision.roi-from-rotated-rect`
- `core.vision.roi-list-create`

创建节点必须输出合法 `roi_id`、`roi_kind`、几何、面积和必要来源元数据。

### 转换与集合

- `roi-list-item-get` 从列表取一个 ROI。
- `value-to-roi`、`payload-to-value` 只做显式 payload 桥接。
- contour、rotated rect 等转 ROI 时保留可验证的坐标信息。

### 使用

Crop、测量、匹配、缺陷指标和规则节点消费 ROI。节点只能使用其声明支持的 ROI 类型；要求 bbox 的节点不能把 polygon 静默降级为 bbox。

### 绘制

Draw ROI / Draw ROIs 只生成可视化图片，不修改输入 ROI。输出图片的 `save_location` 可以是 ObjectStore 相对位置或磁盘绝对位置。

### 规则判断

inside、coverage、intersection、offset、密度和缺陷规则输出指标或 Boolean/Result，不承担 ROI 创建和图片渲染。

## 交互取参

图片上的 bbox、polygon、circle、line 或 template/search region 由统一 [图像交互取参](workflow-image-parameter-editor.md) 实现。编辑器将原图坐标写回节点参数，Runtime 再由 ROI 创建节点生成正式 payload。

## 数据不变量

- 坐标必须有限，面积大于零，几何不越过节点允许的边界。
- 来源图片尺寸、transform 或坐标系存在时必须显式传播和核对。
- `roi.v1` 与 `roi-list.v1` 不使用模糊字典或位置数组替代。
- For Each 中需要单 ROI 时显式取 item，再经 payload bridge 连接目标节点。
- 保存位置只决定图片或文件输出，不改变 ROI payload 本身。

## 验收

- ROI 创建、列表、转换、Crop、Draw 和规则链可在 Preview 与正式 Runtime 中得到一致结果。
- polygon、rotated rect 和 bbox 的能力边界会被执行层验证。
- 高分辨率图片缩放显示不改变原图坐标。
- 无效面积、NaN/Infinity、来源尺寸不一致和不支持的隐式转换返回明确错误。
