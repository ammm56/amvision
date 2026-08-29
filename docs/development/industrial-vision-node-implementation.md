# 工业二维视觉节点实施基线

## 状态与目的

本文记录 [ADR-0011](../decisions/ADR-0011-industrial-vision-node-coverage.md) 已接受的节点补齐计划。阶段 0 已完成，业务节点尚未开始进入 Catalog。当前运行能力仍以 `GET /api/v1/workflows/node-catalog`、Core NodeDefinition 和 `custom_nodes/opencv_nodes/workflow/catalog.json` 为准；本文中的“新增”不得被解释为已进入 Catalog。

目标是补齐可复用的二维工业视觉基础节点与高频组合工具，减少常用流程的节点数量，同时不引入产品专用节点、Python Script 节点或新的视觉 Node Pack。

## 阶段状态

| 阶段 | 状态 | 已完成证据 |
| --- | --- | --- |
| 阶段 0：现状与契约 | 已完成 | 审计 133 个现有 OpenCV 节点；48 个规划 OpenCV node type 与现有 Catalog 无冲突；冻结四类 payload fixture、运行时校验和明确的 planar transform 方向。 |
| 阶段 1：Core 通用能力 | 进行中 | 按本实施基线逐项实现。 |
| 阶段 2–6 | 未开始 | 前一阶段完成独立门禁后依次进入。 |

## 不可变边界

- 所有新增能力只属于 Core Node 或现有 `opencv.nodes`。
- Python Script 节点和 Python Script Node Pack 不在范围内，不作为算法扩展或缺失能力的兜底。
- Core 不引入 OpenCV、相机、PLC、MES 或其他外部 SDK 依赖。
- `opencv.nodes` 继续使用现有两级 category，不按算子族拆新 pack。
- 原子节点负责单一操作；高频、稳定且需要多步算法的能力可以实现为常用组合工具。
- 组合工具复用共享算法函数，不嵌套执行 Workflow，不直接调用其他节点 handler。
- 图片、map 和 heatmap 保持 ImageRef、LocalBuffer 或 ObjectStore 引用；不内联 Base64 或大型数组。
- 算法节点输出 metrics、geometry、region 和 diagnostics；OK/NG 继续由 Core Rule 节点判定。
- 本轮只覆盖 2D。3D payload 和节点必须另立实施里程碑。

## 当前能力复用

以下能力已经存在，不因本轮规划重复创建专用节点：

| 能力 | 现有节点或算子族 |
| --- | --- |
| 二值化 | Binary/Adaptive/Otsu/Color Range Threshold |
| 图像增强与滤波 | Brightness Contrast、CLAHE、Gamma、Normalize、Gaussian/Median/Bilateral/Box/Filter2D/Gabor |
| 形态学与 mask | Morphology、Hit-Miss、Mask Logic、Fill Holes、Clear Border、Remove Small Components、Skeletonize |
| 裁剪、翻转、旋转、缩放、校正 | Crop、Flip、Affine/Perspective Transform、Rotation Correct、Resize、Remap、Undistort |
| 通道操作 | Color Convert、Grayscale、Channel Select/Split/Merge |
| 灰度与区域统计 | Histogram、ROI Intensity Statistics 及现有 Inspection Statistics |
| 直线、圆和椭圆基础检测 | Hough Lines/Circles、Fit Line/Ellipse、Min Enclosing Circle |
| 模板和配准 | Template Match、Multi-scale/Rotation-scale Template Match、Phase Correlation、ECC、Homography |
| 基础量测 | Measure、Caliper Edge、Point Distance、Point-to-Line Distance、Line Angle、Circle Measure/Diameter 等 |
| 单目标定与姿态 | Chessboard/Circle Grid、Corner Subpix、Camera/Fisheye Calibrate、Hand-Eye、SolvePnP、Project/Undistort Points、Undistort Image |
| 结果绘制 | Draw ROI/ROIs、Regions、Contours、Lines、Circles、Detections、Measurements |
| Core 逻辑和输出 | IF Else Select、Switch、Match Case、Parallel/For Each、变量、规则、JSON/CSV/Image 输出 |

现有节点可以完成的单一操作不再增加同义节点。新增常用组合工具必须说明相对于现有组合的操作简化、统一输出或诊断收益。

## 需求术语映射

下表是原始能力清单到本实施基线的权威映射。状态为“复用”的能力不得再建同义节点；状态为“明确算子”的术语不得按原模糊名称进入 Catalog。

| 能力组 | 原始术语 | 处理 |
| --- | --- | --- |
| 图像处理 | 形态学、二值化、增强、滤波、裁剪、翻转、旋转、缩放、校正、去畸变、通道提取/转换 | 复用现有 OpenCV 节点。 |
| 图像处理 | 平移 | 新增 `image-translate` 高频工具，底层复用 affine。 |
| 图像处理 | 拼接 | `image-concat` 处理规则排列，`image-stitch` 处理特征配准拼接。 |
| 图像处理 | 图片创建、类型转换、图片组合 | 分别新增 `image-create`、`image-type-convert`、`image-composite`。 |
| 标定 | 手眼标定 | 复用现有 Hand-Eye Calibrate。 |
| 标定 | 联合标定、关联标定 | 不保留模糊名称；按真实关系使用 Stereo Calibrate、Hand-Eye 或明确 Transform。 |
| 标定 | 标定校正 | 拆为 Stereo Rectify、Rectification Map 和 Image Rectify Stereo。 |
| 标定 | 精度诊断 | 新增 Observation Filter 与 Calibration Diagnose。 |
| 检查 | 胶路检测 | 新增通用 `bead-inspect`，产品阈值留在 Workflow Rule。 |
| 检查 | 毛刺检测 | 由通用 `contour-deviation-inspect` 输出正负轮廓偏差与候选区域。 |
| 检查 | 斑点分析 | 新增通用 `blob-analysis`。 |
| 检查 | 灰度统计 | 复用 Histogram、ROI Intensity Statistics；综合质量场景使用 `image-quality-metrics`。 |
| 定位 | 灰度匹配 | 复用 Template Match 算子族。 |
| 定位 | 特征点匹配、形状匹配 | 保留现有原子匹配并新增 `feature-locate`、`shape-locate` 高频工具。 |
| 定位 | 直线、圆、椭圆、边缘查找 | 复用现有检测/量测节点并补齐 Line/Ellipse Measure 与 Edge Pair Measure。 |
| 定位 | 径向直线查找 | 新增 `radial-line-search`。 |
| 定位 | Mark 提取、Mark 形状查找 | 不新增 Mark 专用节点；按输入使用 Template/Feature/Shape Locate。 |
| 运算 | 点点、点线、线线距离与夹角 | 复用现有距离、交点和角度节点；需要组合结果时使用 relation 节点。 |
| 运算 | 点圆、圆圆、线圆 | 新增明确的 geometry relation 节点。 |
| 运算 | 补正生成、对位计算 | 不保留模糊名称；使用 Localization Transform、Transform Compose/Invert/Apply。 |
| 运算 | 亮度、清晰度 | 亮度复用现有统计；清晰度和综合质量进入 `image-quality-metrics`。 |
| 运算 | 坐标系转换、坐标系生成 | 使用 Transform 2D Create/Compose/Invert、Transform Points、Pixel/World 转换。 |
| 运算 | 变量赋值 | 复用现有 Variable Set/Get/Delete。 |
| 逻辑 | IF、开关、并行、循环 | 并行与循环复用现有节点；补齐真正控制执行路径的 Conditional/Switch start/end。 |
| 逻辑 | 自动删除 | 不新增模糊节点；变量删除和文件生命周期分别使用现有明确能力。 |
| 逻辑 | 延时、格式化字符串、文本保存 | 新增 Core Delay、Format String、Text Save Local。 |
| 逻辑 | 图像保存 | 复用现有 Image Save。 |
| 逻辑 | Python Script | 明确排除，不创建节点或 Node Pack。 |

## Core Node 补齐

### 数值与单位

| 目标 node type | category | 语义 |
| --- | --- | --- |
| `core.logic.number-operation` | `core.logic.transform` | Add、Subtract、Multiply、Divide；除零快速失败，不隐式转换字符串。 |
| `core.logic.number-function` | `core.logic.transform` | Abs、Round、Clamp、Min、Max；Round 显式指定位数和舍入方式。 |
| `core.logic.unit-convert` | `core.logic.transform` | 只支持已登记的同量纲单位换算；不猜测单位。 |

Pixel-to-World 和 World-to-Pixel 依赖相机/平面标定，归入 `opencv.nodes`，不塞入通用单位换算。

### 控制与文本

| 目标 node type | category | 语义 |
| --- | --- | --- |
| `core.logic.conditional-start` / `core.logic.conditional-end` | `core.logic.branch` | 真正的条件执行分支，与现有值选择 `core.logic.if-else` 分开。 |
| `core.logic.switch-start` / `core.logic.switch-end` | `core.logic.branch` | 真正的多路执行分支，与现有值选择 `core.logic.switch` 分开。 |
| `core.logic.delay` | `core.logic.iteration` | 可取消、受 Workflow deadline 限制的延时；禁止不可中断的裸 `sleep`。 |
| `core.logic.format-string` | `core.logic.transform` | 使用受限占位符格式化 UTF-8 文本，不执行表达式或任意代码。 |
| `core.output.text-save-local` | `core.io.file` | 按现有本地保存双语义保存文本，支持明确的覆盖/追加模式和编码。 |

现有 Parallel、For Each、Loop Control 和变量节点继续复用。“自动删除”不形成新节点；明确的变量删除使用现有 `core.logic.variable.delete`，文件生命周期由对应存储节点和 Workflow 资源规则管理。

## `opencv.nodes` 补齐

### 图片基础与常用组合

| 目标 node type | category | 层级 | 说明 |
| --- | --- | --- | --- |
| `custom.opencv.image-create` | `opencv.image.transform` | 原子 | 按宽、高、通道、dtype 和填充值创建图片。 |
| `custom.opencv.image-type-convert` | `opencv.image.color` | 原子 | 显式转换 dtype、通道布局和数值范围，不与颜色空间转换混用。 |
| `custom.opencv.image-translate` | `opencv.image.transform` | 常用工具 | 封装高频平移参数与边界模式，底层复用 affine 实现。 |
| `custom.opencv.image-composite` | `opencv.image.transform` | 常用工具 | 按位置、mask 和 alpha 组合图片。 |
| `custom.opencv.image-concat` | `opencv.image.transform` | 常用工具 | 水平/垂直拼接同类图片并明确对齐与填充规则。 |
| `custom.opencv.image-stitch` | `opencv.matching.registration` | 常用工具 | 特征、配准、warp、blend 和诊断的通用图片拼接工具。 |
| `custom.opencv.image-quality-metrics` | `opencv.inspection.statistics` | 常用工具 | 一次输出亮度、对比度、清晰度、曝光裁剪、饱和度和噪声估计，可选 ROI。 |

`image-quality-metrics` 至少输出 mean/std、Laplacian variance、Tenengrad、low/high clipping ratio、HSV saturation statistics 和 robust noise estimate。已有 Brightness/ROI Intensity 节点保留，不复制为新的 Brightness 节点。

### 几何对象、选择与二维变换

新增 `points.v1`，沿用并补强 `lines.v1`、`circles.v1`、`ellipses.v1`、`planar-transform.v1`。所有几何 payload 必须携带明确 coordinate space；跨来源或跨坐标空间操作快速失败。

| 目标 node type | category | 说明 |
| --- | --- | --- |
| `custom.opencv.point-create` | `opencv.geometry.shape` | 创建规范 `points.v1`。 |
| `custom.opencv.line-create` | `opencv.geometry.shape` | 由两点或点角式创建 `lines.v1`。 |
| `custom.opencv.circle-create` | `opencv.geometry.shape` | 创建 `circles.v1`。 |
| `custom.opencv.ellipse-create` | `opencv.geometry.shape` | 创建 `ellipses.v1`。 |
| `custom.opencv.points-select` | `opencv.geometry.shape` | 按显式 index/filter 选择并保持 `points.v1`。 |
| `custom.opencv.lines-select` | `opencv.geometry.shape` | 按显式 index/filter 选择并保持 `lines.v1`。 |
| `custom.opencv.circles-select` | `opencv.geometry.shape` | 按显式 index/filter 选择并保持 `circles.v1`。 |
| `custom.opencv.ellipses-select` | `opencv.geometry.shape` | 按显式 index/filter 选择并保持 `ellipses.v1`。 |
| `custom.opencv.transform-2d-create` | `opencv.image.transform` | 创建刚体、相似、仿射或透视 `planar-transform.v1`。 |
| `custom.opencv.transform-2d-compose` | `opencv.image.transform` | 按明确顺序组合二维变换。 |
| `custom.opencv.transform-2d-invert` | `opencv.image.transform` | 反演并报告奇异或病态矩阵。 |
| `custom.opencv.transform-points` | `opencv.image.transform` | 变换 `points.v1` 并更新 coordinate space。 |
| `custom.opencv.pixel-to-world` | `opencv.calibration.pose` | 使用明确标定模型把像素点转换到平面世界坐标。 |
| `custom.opencv.world-to-pixel` | `opencv.calibration.pose` | 使用明确标定模型把平面世界坐标投影到像素坐标。 |

现有 Point Distance、Point-to-Line Distance、Line Intersection 和 Line Angle 继续复用。补充的关系量测为：

- `custom.opencv.line-line-relation`
- `custom.opencv.point-circle-relation`
- `custom.opencv.line-circle-relation`
- `custom.opencv.circle-circle-relation`

这些节点输出交点、距离、夹角、相切/相交状态等规范 `measurements.v1`，不输出产品判定。

### 二维量测

| 目标 node type | category | 说明 |
| --- | --- | --- |
| `custom.opencv.line-measure` | `opencv.measurement.edge` | 沿卡尺阵列寻找边缘并拟合直线，输出边缘点、直线、残差和有效率。 |
| `custom.opencv.ellipse-measure` | `opencv.measurement.geometry` | 沿椭圆法向采样并拟合椭圆，输出残差和覆盖率。 |
| `custom.opencv.rectangle-measure` | `opencv.measurement.geometry` | 量测四边位置、宽高、角度、平行度和矩形度。 |
| `custom.opencv.edge-pair-measure` | `opencv.measurement.edge` | 查找同极性或异极性的边缘对，输出宽度/间距分布。 |
| `custom.opencv.gray-profile-measure` | `opencv.measurement.edge` | 沿线、带状区域或法向输出灰度剖面及峰谷位置。 |
| `custom.opencv.radial-line-search` | `opencv.measurement.circle` | 从中心沿多条径向搜索边缘，输出点集、覆盖率和可选圆/椭圆拟合。 |

现有 `custom.opencv.circle-measure` 不重复创建，实施时统一其诊断字段、coordinate space 和 `measurements.v1` 输出。

### 定位统一

新增 `localizations.v1`。单项至少包含 `method`、`center`、`angle_degrees`、`scale`、`score`、`coordinate_space`、`transform`、可选 `region/roi` 和 `diagnostics`。

现有 Template Match、Multi-scale Template Match、Rotation-scale Template Match、Phase Correlation、ECC 和 Homography 节点补充或桥接为该统一输出。新增两个高频组合工具：

| 目标 node type | category | 说明 |
| --- | --- | --- |
| `custom.opencv.feature-locate` | `opencv.matching.feature` | 特征提取、匹配、几何验证和 transform/localization 输出，公开 matcher、ratio、RANSAC 等稳定参数。 |
| `custom.opencv.shape-locate` | `opencv.matching.template` | 轮廓/边缘形状建模、搜索、角度/尺度范围和 localization 输出。 |

不新增 Gray Match、Mark Extract 或 Mark Locate 同义节点。灰度定位使用现有 Template Match，Mark 只是 Workflow App 对 Template/Feature/Shape Locate 的场景命名。

### 标定完整链路

新增 `camera-calibration.v1` 和 `stereo-calibration.v1`。观察数据、内外参、坐标系、图像尺寸、误差摘要和来源 fingerprint 必须显式记录。

| 目标 node type | category | 说明 |
| --- | --- | --- |
| `custom.opencv.calibration-observation-filter` | `opencv.calibration.camera` | 按角点数量、覆盖、姿态分布和单张重投影误差筛选观察。 |
| `custom.opencv.calibration-diagnose` | `opencv.calibration.camera` | 输出总体/单图重投影误差、覆盖、异常观察和稳定性诊断。 |
| `custom.opencv.stereo-calibrate` | `opencv.calibration.camera` | 计算双目内外参和左右相机关系。 |
| `custom.opencv.stereo-rectify` | `opencv.calibration.camera` | 计算校正旋转、投影矩阵、Q 和有效区域。 |
| `custom.opencv.rectification-map` | `opencv.calibration.camera` | 生成校正 map；大型 map 写入 ObjectStore 并返回 key。 |
| `custom.opencv.image-rectify-stereo` | `opencv.image.transform` | 使用已生成 map 校正左右图片，不在每帧重复计算 map。 |

“联合标定”必须拆解为具体的 stereo 或 hand-eye 操作；“标定校正”必须区分计算参数、生成 map 和应用 map。

### 通用检查工具

| 目标 node type | category | 说明 |
| --- | --- | --- |
| `custom.opencv.blob-analysis` | `opencv.inspection.statistics` | 二值区域连通分析、面积、位置、形状和灰度统计，输出 regions/measurements。 |
| `custom.opencv.bead-inspect` | `opencv.inspection.difference` | 对参考路径周围的胶路/焊道宽度、断裂、缺失、溢出和位置偏差进行通用检查。 |
| `custom.opencv.contour-deviation-inspect` | `opencv.inspection.difference` | 比较实测轮廓与参考轮廓，输出正负偏差、毛刺/缺口候选和误差区域。 |
| `custom.opencv.variation-model-build` | `opencv.inspection.difference` | 从正常样本建立均值/方差或稳健变化模型并写入 ObjectStore。 |
| `custom.opencv.variation-inspect` | `opencv.inspection.difference` | 使用变化模型输出异常热图、regions、statistics 和 diagnostics。 |

Bead 与 Contour Deviation 是跨产品通用工具；“胶路检测”“毛刺检测”等名称保留在 Workflow App 展示层，不形成额外 node type。

### 结果绘制

在现有 Draw ROI/Regions/Lines/Circles/Measurements 基础上补充：

- `custom.opencv.draw-ellipses`
- `custom.opencv.draw-localizations`
- `custom.opencv.draw-calibration-reprojection`
- `custom.opencv.draw-inspection-errors`

绘制节点只生成调试或展示图片，不修改结构化测量结果。

## 缓存、性能和执行边界

- shape model、template feature、rectification map 和 variation model 按内容 fingerprint 缓存在常驻 Workflow worker 内。
- 缓存是可丢失加速，不是事实源；事实源仍是 Workflow Version 参数和 ObjectStore 对象。
- 图片处理保持 ImageRef/LocalBuffer 的本机路径，禁止新增 Base64、完整 ndarray JSON 或无必要的图片复制。
- 可能阻塞的文件、模型构建或外部调用必须消费 Workflow deadline，并遵守 Node Pack timeout；普通纯 OpenCV 计算不引入每节点新进程。
- 组合工具不得在一次执行中隐式重复建立可缓存模型。
- 大 map、model 和 heatmap 原子写入 ObjectStore，成功后才发布 key。

## 前端边界

- 节点目录和普通参数表单继续由动态 Catalog 生成，不为每个新节点写专用页面。
- Point/Line/Circle/Ellipse、搜索 ROI、标定观察和误差区域可复用现有 Workflow 画布与图片预览交互。
- 只有通用 schema 无法表达的图片交互才增加前端控件；控件必须写回普通 Node parameters 或公开 payload。
- `localizations.v1`、标定诊断和 inspection diagnostics 提供统一预览，避免每个定位节点维护不同结果面板。

## 分阶段实施

### 阶段 0：冻结现状与契约 fixture

- 从运行时 Catalog 生成现有能力矩阵，确认本文每个“新增”没有同义现有节点。
- 冻结 `points.v1`、`localizations.v1`、`camera-calibration.v1`、`stereo-calibration.v1` 示例和非法 fixture。
- 冻结 coordinate space、角度单位、transform 方向、score 范围、ObjectStore key 和 diagnostics 字段。

### 阶段 1：Core 通用能力

- 实现数值、单位、受控格式化、可取消 delay 和本地文本保存。
- 单独设计并实现 Graph Executor 的条件/开关控制流 start/end 语义；不得只增加 Catalog 定义。
- 完成 Core NodeDefinition、handler、参数 schema、Catalog、前端动态表单和 Graph E2E。

### 阶段 2：二维 payload、几何与图片操作

- 实现新 payload contract、adapter 和共享 geometry/transform helper。
- 实现创建、选择、transform、relation 及图片 create/type/translate/composite/concat/stitch。
- 对已有节点补 coordinate space 和 transform 输出时，必须同步更新模板与测试。

### 阶段 3：质量、量测与定位

- 实现 Image Quality Metrics、Line/Ellipse/Rectangle/Edge Pair/Gray Profile/Radial Search。
- 统一现有定位节点输出并实现 Feature Locate、Shape Locate。
- 完成亚像素、噪声、遮挡、角度/尺度、低纹理和退化几何测试。

### 阶段 4：标定链路

- 实现 observation filter、diagnose、stereo calibrate/rectify、map 和 apply。
- 验证单目重投影误差、双目极线误差、map fingerprint、ObjectStore 原子发布和缓存复用。

### 阶段 5：通用检查与绘制

- 实现 Blob、Bead、Contour Deviation、Variation Model 和四个绘制节点。
- 使用正常、断裂、缺失、溢出、毛刺、缺口和光照变化合成 fixture 验证输出，不把容差写死在算法中。

### 阶段 6：Workflow App 示例与完整门禁

- 提供灰度定位、特征定位、形状定位、亚像素量测、双目标定诊断、胶路检查和轮廓偏差的可组合示例。
- 示例只使用 Core 与 `opencv.nodes`，不依赖 Python Script 或私有 handler。
- 同步前端 Catalog、参数文案、多语言、预览和文档。

每个阶段必须独立完成实现、测试、Catalog/handler parity、链路审计和文档核对后，才能进入下一阶段。

## 验收门禁

- NodeDefinition、runtime handler、源 catalog fragment、生成 catalog 和 pack manifest 一致。
- `python -m custom_nodes.opencv_nodes.workflow.generate_catalog` 生成结果与 checked-in catalog 一致。
- Core 与 `opencv.nodes` payload contract 无冲突，非法 coordinate space、shape、dtype 和 transform 明确失败。
- 数值和几何节点使用确定性合成数据覆盖边界、退化和 NaN/Inf。
- 量测节点验证亚像素精度、重复性、有效采样率和残差。
- 定位节点验证位置、角度、尺度、score、transform 和 diagnostics 的统一语义。
- 标定验证重投影误差、双目极线误差、异常 observation 剔除和 map 可追溯性。
- Image Quality 指标在模糊、曝光、饱和和噪声单调变化 fixture 上符合预期。
- Bead/Contour/Variation 输出结构化误差区域和 metrics，Rule 节点可独立完成 OK/NG。
- 640、1024、1080p、4K 和大图链路不新增 Base64 或无必要完整图片复制，记录 P50/P95 与 working set 回归。
- Workflow Preview、Published App Runtime 和 Trigger 输入链均能执行代表性流程。
- 后端 pytest/ruff、前端 typecheck/unit/build 和文档链接门禁通过。

## 暂缓的三维里程碑

后续 3D 规划至少需要 `depth-image.v1`、`point-cloud.v1` 和 `transform-3d.v1`，再评估 Depth to Point Cloud、裁剪/降采样/离群点、平面/直线/圆拟合、Height/Flatness/Step/Gap/Volume、Stereo Disparity/Depth 和 3D Registration。该清单不属于当前实现，不得为了复用名称提前向本轮 Catalog 添加空节点。

## 设计参考

- [VisionMaster](https://www.hikrobotics.com/cn/machinevision/visionmaster/)
- [HALCON Operator Reference](https://www.mvtec.com/doc/halcon/2605/en/)
- [HALCON 2D Metrology](https://www.mvtec.com/doc/halcon/2205/en/toc_2dmetrology.html)
- [HALCON 2D Transformations](https://www.mvtec.com/doc/halcon/13/en/toc_transformations_2dtransformations.html)
- [HALCON Calibration](https://www.mvtec.com/doc/halcon/1911/en/toc_calibration.html)
- [HALCON Bead Inspection](https://www.mvtec.com/doc/halcon/2605/en/apply_bead_inspection_model.html)
