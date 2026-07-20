# OpenCV 圆检测与圆测量节点

本文档说明 `Hough Circles`、`Circle Measure` 和 `Quadrilateral From Circle Centers` 的职责、参数语义和组合方式。三个节点都是通用基础节点，不包含托盘或特定 Workflow App 的业务约定。

## 节点职责

| 节点 | 主要职责 | 适用输入 |
| --- | --- | --- |
| `Hough Circles` | 在 `Search ROI` 内执行位置无关的圆搜索；可使用 `Reference Circle` 定义目标尺寸，并对候选执行径向边缘精定位和质量验证 | 圆的位置会在 ROI 内大范围变化，需要稳定搜索 |
| `Circle Measure` | 围绕已知近似圆建立径向测量带，执行亚像素边缘采样和 robust circle fitting | 圆的大致位置和半径已知，重点是稳定精测 |
| `Quadrilateral From Circle Centers` | 按显式的 Top Left、Top Right、Bottom Right、Bottom Left 输入构造凸四边形 | 已获得四个具有明确角点语义的圆结果 |

`Circle Measure` 与 `Hough Circles` 不重复。前者是“已知近似几何体后的测量”，后者是“在区域内发现候选”。`Hough Circles` 内置的 `Refine Candidates` 适合用一个节点完成搜索和精定位；需要把候选发现、参考来源和精测质量门限分开控制时，可连接 `Hough Circles → Circle Measure`，也可由其他 `circles.v1` 节点提供参考圆。

## Search ROI 与 Reference Circle

- `Search ROI` 固定写入 `search_bbox_xyxy`，只定义算法允许搜索或测量的矩形范围。
- `Hough Circles` 的 `Reference Circle` 只写入 `reference_radius_px` 和 `radius_tolerance_px`。绘制时的圆心只用于本次取参，不保存到节点，也不参与运行时筛选。
- Search ROI 是目标允许出现的全部位置范围。只要目标圆仍位于 ROI 内，即使相对取参图片偏移几十或几百像素，算法仍会重新搜索，而不是在旧圆心附近测量。
- `reference_radius_px ± radius_tolerance_px` 会自动收紧 Hough 搜索半径和最终尺寸验证；Reference Circle 因此表示目标形状尺寸，而不是绝对位置模板。
- `maximum_refinement_center_shift_px` 只限制 robust fitting 相对当前 Hough 候选的修正量，防止精定位跳到邻近纹理；它不限制目标在 Search ROI 内的整体位移。
- `Circle Measure` 仍保存参考圆心和半径，因为它的职责是围绕已知近似位置做精测。需要全 ROI 搜索时应使用 `Hough Circles`，两者不能混用语义。
- `Circle Measure` 的显式参考参数优先于可选 `Reference Circles` 输入。两者都未提供时返回 `configuration_state=reference-required` 的结构化空结果，Debug 图片页仍可先画 Search ROI，再画 Reference Circle，不会中断 Preview Run。
- Reference Circle 位于 Search ROI 外时返回 `reference_circle_outside_search_roi`，不执行 OpenCV 测量。

## Debug 图片中的几何信息

交互式图片页使用原图坐标显示以下信息：

- Search ROI：在矩形左上角以 CAD 标注方式显示 `X / Y / W / H`，单位为原图像素。
- Reference、Detected、Selected 和当前绘制圆：使用圆心标记、半径尺寸线和自动避让引出框显示 `X / Y / R / Ø`，单位为原图像素。
- Search ROI 使用蓝色虚线矩形；Hough Circles 取参草稿使用紫色虚线圆；Detected Circle 使用橙色实线圆；Selected Circle 使用绿色粗实线和圆心十字；Rejected Candidate 使用诊断色虚线。

Rejected Candidate 默认不绘制，也永远不会进入正式 `circles.v1` 输出。只有排查参数时显式启用 `Show Rejected Candidates` 才显示红色诊断圆；候选较多时不绘制尺寸文字，避免遮挡原图。

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
| `Illumination Normalization` | 默认使用 CLAHE 缓解 Search ROI 内不均匀光照；纹理被过度增强时可关闭 |
| `Reference Radius / Radius Tolerance` | 定义目标圆尺寸范围，不限制圆心位置 |
| `Processing Max Long Edge (px)` | Search ROI 的算法处理长边预算；缩小检测后结果会还原到原图坐标 |
| `Maximum Candidates` | OpenCV 候选进入质量计算前的上限 |
| `Max Results` | 稳定排序和拒绝规则之后最终输出的上限，默认 10 |
| `Sort By` | 按 Quality Score、参考半径偏差、半径或坐标等稳定排序 |

Reference Circle 不保存圆心。换图后的目标位置完全由当前输入图片重新计算，Search ROI 是唯一的位置边界。

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
| `Minimum Edge Support Ratio` | 达到梯度阈值的径向采样比例，拒绝只在少量方向偶然成圆的纹理 |
| `Minimum Polarity Consistency` | 圆周灰度变化方向的一致性，抑制高光、文字和交叉边缘 |
| `Minimum Quality Score` | 综合圆弧覆盖、边缘支持、拟合内点、极性、残差和半径匹配后的最低分 |
| `Maximum Fit Error (px)` | 拟合 RMSE 的质量上限 |

建议先收紧 Search ROI 和半径范围，再调 Canny 与投票阈值；候选稳定后再启用精定位，最后按现场位置波动、遮挡和反光设置容差与质量门限。

## 四圆构造四边形

`Quadrilateral From Circle Centers` 的输入顺序固定为：

1. `Top Left`
2. `Top Right`
3. `Bottom Right`
4. `Bottom Left`

节点不会根据坐标猜测角点。接错输入时会通过左右、上下顺序和凸性校验拒绝执行，避免静默生成自交或镜像四边形。节点标题区域保持固定高度，即使英文标题换行，连线端点仍与对应输入圆点对齐。
