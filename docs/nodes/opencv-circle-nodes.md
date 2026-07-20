# OpenCV 圆检测与圆测量节点

本文档说明 `Hough Circles`、`Circle Measure` 和 `Quadrilateral From Circle Centers` 的职责、参数语义和组合方式。三个节点都是通用基础节点，不包含托盘或特定 Workflow App 的业务约定。

## 节点职责

| 节点 | 主要职责 | 适用输入 |
| --- | --- | --- |
| `Hough Circles` | 在 `Search ROI` 内发现一个或多个未知圆候选；可使用 `Reference Circle` 约束候选，并可对候选执行径向边缘精定位 | 圆的大致位置未知，需要先搜索 |
| `Circle Measure` | 围绕已知近似圆建立径向测量带，执行亚像素边缘采样和 robust circle fitting | 圆的大致位置和半径已知，重点是稳定精测 |
| `Quadrilateral From Circle Centers` | 按显式的 Top Left、Top Right、Bottom Right、Bottom Left 输入构造凸四边形 | 已获得四个具有明确角点语义的圆结果 |

`Circle Measure` 与 `Hough Circles` 不重复。前者是“已知近似几何体后的测量”，后者是“在区域内发现候选”。`Hough Circles` 内置的 `Refine Candidates` 适合用一个节点完成搜索和精定位；需要把候选发现、参考来源和精测质量门限分开控制时，可连接 `Hough Circles → Circle Measure`，也可由其他 `circles.v1` 节点提供参考圆。

## Search ROI 与 Reference Circle

- `Search ROI` 固定写入 `search_bbox_xyxy`，只定义算法允许搜索或测量的矩形范围。
- `Reference Circle` 写入 `reference_center_xy`、`reference_radius_px`、`center_tolerance_px` 和 `radius_tolerance_px`，不会覆盖 `Search ROI`。
- Reference Circle 是 Workflow 节点的持久参数，不是 Preview Run 的隐藏缓存。保存应用后会随图保存、复制和版本化。
- 输入图片位置变化后，Reference Circle 不会自动跟随。偏移在 `center_tolerance_px` 内时仍可选中；超出容差会被拒绝。位置变化范围较大时，应扩大 `Search ROI` 和中心容差，或在上游增加定位、配准节点。
- `Circle Measure` 的显式参考参数优先于可选 `Reference Circles` 输入。两者都未提供时返回 `configuration_state=reference-required` 的结构化空结果，Debug 图片页仍可先画 Search ROI，再画 Reference Circle，不会中断 Preview Run。
- Reference Circle 位于 Search ROI 外时返回 `reference_circle_outside_search_roi`，不执行 OpenCV 测量。

## Debug 图片中的几何信息

交互式图片页使用原图坐标显示以下信息：

- Search ROI：在矩形左上角以 CAD 标注方式显示 `X / Y / W / H`，单位为原图像素。
- Reference、Detected、Selected 和当前绘制圆：使用圆心标记、半径尺寸线和自动避让引出框显示 `X / Y / R / Ø`，单位为原图像素。
- Search ROI 使用蓝色虚线矩形；Reference Circle 使用紫色虚线圆；Detected Circle 使用橙色实线圆；Selected Circle 使用绿色粗实线和圆心十字；Rejected Candidate 使用诊断色虚线。

Rejected Candidate 只保留轮廓，不批量显示尺寸文字。候选较多时逐个绘制尺寸会遮挡原图，也会降低找错参数时的可读性；没有 Selected Circle 时只为稳定排序后的首个 Detected Circle 显示尺寸。引出框在接近图像边界时自动切换方向，避免跑出图像或覆盖 Search ROI 左上角标注。

这些读数和 overlay 只在节点启用 `Debug Image Panel` 且 Preview Run 允许调试图时生成。生产 Runtime、HTTP 和 ZeroMQ 调用不会为了显示尺寸而绘制、编码或保存预览图。

## Hough Circles 参数

| 参数 | 含义与调节方向 |
| --- | --- |
| `Accumulator Resolution Ratio` | Hough 累加器相对处理图的分辨率比例；较小值定位更细但计算量更高 |
| `Minimum Center Distance (px)` | 候选圆心最小间距；避免同一圆返回多个相邻候选 |
| `Canny High Threshold` | Hough 内部 Canny 的高阈值；过低会增加纹理和反光边缘，过高会漏掉弱边 |
| `Center Vote Threshold` | 圆心累加器最低投票；降低可增加候选，代价是误检增多 |
| `Minimum / Maximum Radius (px)` | 允许半径范围，使用原图像素；工业现场应尽量收紧 |
| `Median Blur Kernel Size` | 中值滤波核，必须为奇数；增大可抑制噪声，但会损失细边 |
| `Processing Max Long Edge (px)` | Search ROI 的算法处理长边预算；缩小检测后结果会还原到原图坐标 |
| `Maximum Candidates` | OpenCV 候选进入质量计算前的上限 |
| `Max Results` | 稳定排序和拒绝规则之后最终输出的上限，默认 10 |
| `Sort By` | 按 Quality Score、Reference 距离、半径等稳定排序 |

使用 Reference Circle 时，`Center Tolerance` 和 `Radius Tolerance` 是允许实际位置变化的范围，不是把检测结果锁死在参考位置。候选仍由当前输入图片计算；参考参数只负责约束、评分和选择。

## 径向精定位参数

`Hough Circles` 的 `Refine Candidates` 和 `Circle Measure` 共用以下工业测量语义：

| 参数 | 含义与调节方向 |
| --- | --- |
| `Edge Polarity` | 从圆心向外的灰度变化方向；已知极性时优先选择具体方向 |
| `Radial Sample Count` | 沿圆周建立的径向剖面数量；越高越稳，但耗时线性增加 |
| `Gradient Threshold` | 接受边缘的最低梯度幅度 |
| `Robust Loss` | Huber 适合一般噪声；Tukey 对强离群点抑制更强 |
| `RANSAC Iterations` | robust fit 初始化次数；遮挡严重时可提高，但必须保持有界 |
| `Fit Inlier Threshold (px)` | 边缘点到拟合圆的最大内点残差 |
| `Minimum Arc Coverage` | 有效边缘覆盖完整圆周的最低比例 |
| `Maximum Fit Error (px)` | 拟合 RMSE 的质量上限 |

建议先收紧 Search ROI 和半径范围，再调 Canny 与投票阈值；候选稳定后再启用精定位，最后按现场位置波动、遮挡和反光设置容差与质量门限。

## 四圆构造四边形

`Quadrilateral From Circle Centers` 的输入顺序固定为：

1. `Top Left`
2. `Top Right`
3. `Bottom Right`
4. `Bottom Left`

节点不会根据坐标猜测角点。接错输入时会通过左右、上下顺序和凸性校验拒绝执行，避免静默生成自交或镜像四边形。节点标题区域保持固定高度，即使英文标题换行，连线端点仍与对应输入圆点对齐。
