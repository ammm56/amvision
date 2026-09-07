# 工业视觉与集成节点

## 定位

工业能力通过可组合节点进入 Workflow，不把现场协议、相机驱动或行业规则膨胀到平台资源主链。平台提供稳定的图、payload、Runtime、版本与审计边界；具体设备和算法由 Core Node 或受控 Custom Node Pack 实现。

二维工业视觉节点的扩展只进入 Core 或现有 `opencv.nodes`。当前不规划 Python Script 节点或 Python Script Node Pack；缺失能力必须形成明确、可测试的节点契约，不能以任意脚本执行代替。

## 节点粒度

节点按三层组织：

1. 原子节点提供单一、可预测、容易组合的操作。
2. 常用组合工具覆盖跨项目高频能力；当原子节点组合会形成很长流程时，可以封装特征定位、形状定位、胶路检查、轮廓偏差和标定诊断等稳定工具。
3. Workflow App 与 Template 保存产品、工位、阈值、OK/NG 和交付方式等场景编排。

常用组合工具必须复用共享算法函数，不在 handler 内嵌套执行 Workflow 或其他节点 handler。产品专用名称和规则不进入节点 Catalog。

## 当前节点层次

### Core Node

`backend/nodes/core_nodes/` 保存跨项目稳定的数据和规则能力：

- ROI、Regions、Segments、Detections 和 Tracks 转换
- 面积、覆盖、位置、间距、连续性和形状规则
- 装配完整性、缺陷密度、参考差异和表面一致性
- 文件、目录、结果、循环、并行、逻辑和数据变换
- 视频读取、帧窗口、轨迹过滤、叠加和保存

Core Node 不直接持有相机、PLC、MES 或数据库连接。

### Custom Node Pack

`custom_nodes/` 当前按能力拆分：

| Node Pack | 能力 |
| --- | --- |
| `opencv_nodes` | 预处理、分割、特征、标定、测量、绘制和图片保存 |
| `barcode_nodes` | 一维码/二维码解码、过滤、摘要和绘制 |
| `camera_nodes` | USB UVC 枚举、打开、参数、采集、流窗口和关闭 |
| `plc_nodes` | Modbus TCP 读取、等待条件、写值和结果信号 |
| `http_nodes` | HTTP 请求与现场系统回调 |
| `database_nodes` | SQL upsert 等受控数据库交付 |
| `sam3_segment_nodes` | SAM3 checkpoint、交互/语义图片分割和视频分割 |
| `yoloe_open_vocab_nodes` | 文本、视觉提示和 prompt-free 检测 |

完整节点 id、端口和参数以运行时 `GET /api/v1/workflows/node-catalog` 为准，文档不复制整份 Catalog。

## 设计规则

- Node Pack 必须有 manifest、version、capabilities、schema、timeout 和禁用机制。
- 节点只能使用公开 payload；禁止用任意 dict 隐式传递进程对象或模型私有 tensor。
- 长期模型推理由 Deployment/Workflow Runtime 承担，节点只通过服务契约调用。
- 相机与 PLC 直连能力只存在于明确导入和启用的 Custom Node Pack，不进入平台 Core。
- 同一外部设备的 session 必须有明确打开、使用、关闭与异常回收边界。
- 本地图片输入与保存同时支持 ObjectStore 相对位置和明确的磁盘绝对路径；两种语义不能混用。
- 网络、数据库和设备节点必须设置 timeout；失败返回结构化错误，不能无限等待。
- 节点执行默认可信且同进程，避免无意义的跨进程开销；长期隔离由 Workflow/Deployment Worker 进程边界提供。
- 算法节点输出 metrics、geometry、regions 和 diagnostics，OK/NG 阈值由 Core Rule 节点处理。
- 大型图片、rectification map、variation model 和 heatmap 使用 ImageRef、LocalBuffer 或 ObjectStore 引用，不内联到 Workflow JSON。
- 二维定位统一输出位置、角度、尺度、score、坐标空间、二维变换和诊断信息；同一语义不因模板、特征或形状算法而使用互不兼容的松散对象。
- 语义不明确的“联合标定”“关联标定”“补正生成”“自动删除”和“Mark 查找”不形成节点；使用 Stereo/Hand-Eye Calibration、Transform、变量和 Locate 等明确能力表达。
- 当前工业视觉范围只覆盖二维；深度图、点云和三维量测另立里程碑。

## 典型链路

```text
Image/Frame Ref
  → OpenCV/Model Node
  → Regions/Measurements
  → Rule Check
  → Result Assembly
  → PLC / HTTP / SQL / File Output
```

规则计算与结果交付分离。同一检测结果可以同时生成 PLC 信号、JSON/CSV、MES 请求和数据库记录，但每个出口必须是显式节点。

## 二维能力与术语

## 需求术语映射

下表是原始能力术语到当前节点能力的权威映射。状态为“复用”的能力不得再建同义节点；状态为“明确算子”的术语不得按原模糊名称进入 Catalog。

| 能力组 | 原始术语 | 处理 |
| --- | --- | --- |
| 图像处理 | 形态学、二值化、增强、滤波、裁剪、翻转、旋转、缩放、校正、去畸变、通道提取/转换 | 复用现有 OpenCV 节点。 |
| 图像处理 | 平移 | 使用 `image-translate` 高频工具，底层复用 affine。 |
| 图像处理 | 拼接 | `image-concat` 处理规则排列，`image-stitch` 处理特征配准拼接。 |
| 图像处理 | 图片创建、类型转换、图片组合 | 分别使用 `image-create`、`image-type-convert`、`image-composite`。 |
| 标定 | 手眼标定 | 复用现有 Hand-Eye Calibrate。 |
| 标定 | 联合标定、关联标定 | 不保留模糊名称；按真实关系使用 Stereo Calibrate、Hand-Eye 或明确 Transform。 |
| 标定 | 标定校正 | 拆为 Stereo Rectify、Rectification Map 和 Image Rectify Stereo。 |
| 标定 | 精度诊断 | 使用 Observation Filter 与 Calibration Diagnose。 |
| 检查 | 胶路检测 | 使用通用 `bead-inspect`，产品阈值留在 Workflow Rule。 |
| 检查 | 毛刺检测 | 由通用 `contour-deviation-inspect` 输出正负轮廓偏差与候选区域。 |
| 检查 | 斑点分析 | 使用通用 `blob-analysis`。 |
| 检查 | 灰度统计 | 复用 Histogram、ROI Intensity Statistics；综合质量场景使用 `image-quality-metrics`。 |
| 定位 | 灰度匹配 | 复用 Template Match 算子族。 |
| 定位 | 特征点匹配、形状匹配 | 保留原子匹配，并使用 `feature-locate`、`shape-locate` 高频工具。 |
| 定位 | 直线、圆、椭圆、边缘查找 | 复用现有检测/量测节点并补齐 Line/Ellipse Measure 与 Edge Pair Measure。 |
| 定位 | 径向直线查找 | 使用 `radial-line-search`。 |
| 定位 | Mark 提取、Mark 形状查找 | 不新增 Mark 专用节点；按输入使用 Template/Feature/Shape Locate。 |
| 运算 | 点点、点线、线线距离与夹角 | 复用现有距离、交点和角度节点；需要组合结果时使用 relation 节点。 |
| 运算 | 点圆、圆圆、线圆 | 使用明确的 geometry relation 节点。 |
| 运算 | 补正生成、对位计算 | 不保留模糊名称；使用 Localization Transform、Transform Compose/Invert/Apply。 |
| 运算 | 亮度、清晰度 | 亮度复用现有统计；清晰度和综合质量进入 `image-quality-metrics`。 |
| 运算 | 坐标系转换、坐标系生成 | 使用 Transform 2D Create/Compose/Invert、Transform Points、Pixel/World 转换。 |
| 运算 | 变量赋值 | 复用现有 Variable Set/Get/Delete。 |
| 逻辑 | IF、开关、并行、循环 | 并行与循环复用现有节点；补齐真正控制执行路径的 Conditional/Switch start/end。 |
| 逻辑 | 自动删除 | 不新增模糊节点；变量删除和文件生命周期分别使用现有明确能力。 |
| 逻辑 | 延时、格式化字符串、文本保存 | 使用 Core Delay、Format String、Text Save Local。 |
| 逻辑 | 图像保存 | 复用现有 Image Save。 |
| 逻辑 | Python Script | 明确排除，不创建节点或 Node Pack。 |

## Core 通用能力

### 数值与单位

| node type | category | 语义 |
| --- | --- | --- |
| `core.logic.number-operation` | `core.logic.transform` | Add、Subtract、Multiply、Divide；除零快速失败，不隐式转换字符串。 |
| `core.logic.number-function` | `core.logic.transform` | Abs、Round、Clamp、Min、Max；Round 显式指定位数和舍入方式。 |
| `core.logic.unit-convert` | `core.logic.transform` | 只支持已登记的同量纲单位换算；不猜测单位。 |

Pixel-to-World 和 World-to-Pixel 依赖相机/平面标定，归入 `opencv.nodes`，不塞入通用单位换算。

### 控制与文本

| node type | category | 语义 |
| --- | --- | --- |
| `core.logic.conditional-start` / `core.logic.conditional-end` | `core.logic.branch` | 真正的条件执行分支，与现有值选择 `core.logic.if-else` 分开。 |
| `core.logic.switch-start` / `core.logic.switch-end` | `core.logic.branch` | 真正的多路执行分支，与现有值选择 `core.logic.switch` 分开。 |
| `core.logic.delay` | `core.logic.iteration` | 可取消、受 Workflow deadline 限制的延时；禁止不可中断的裸 `sleep`。 |
| `core.logic.format-string` | `core.logic.transform` | 使用受限占位符格式化 UTF-8 文本，不执行表达式或任意代码。 |
| `core.output.text-save-local` | `core.io.file` | 按现有本地保存双语义保存文本，支持明确的覆盖/追加模式和编码。 |

现有 Parallel、For Each、Loop Control 和变量节点继续复用。“自动删除”不形成新节点；明确的变量删除使用现有 `core.logic.variable.delete`，文件生命周期由对应存储节点和 Workflow 资源规则管理。

### 通用数据契约

- `core.logic.conditional-start/end` 的 `if_true`、`if_false` 必须各自形成一条到 End `result` 的完整路径；运行时只构造和执行命中的分支子图。
- `core.logic.switch-start/end` 接受 1–8 个互不重复的 JSON scalar `case_values`，按 `case_1` 至 `case_8` 与 `default` 显式连线；boolean 与 number 不混同，未命中时只执行 `default`。
- Start/End 通过所有显式分支共同到达的最近同类型 End 配对，允许结构化嵌套；交叉连线、共享内部节点、越界输出和缺失分支在任何分支 handler 启动前失败。
- 未选分支不调用 handler、不产生节点记录、不执行文件或外部调用副作用。选择分支继续消费同一个 Workflow deadline、取消事件、运行时上下文和资源清理作用域。
- `core.logic.delay` 复用 Workflow 可中断等待，不使用裸 `sleep`；`core.logic.format-string` 只接受简单命名占位符，不执行属性访问、表达式或转换标记。
- `core.output.text-save-local` 沿用 ObjectStore 相对位置与本机绝对路径双语义；追加操作受跨线程/跨进程路径锁保护，并按节点 invocation journal 避免重复追加。
- Core 节点清单以动态 Catalog 为准；普通参数由前端动态 schema 表单渲染，无需为每个节点维护专用页面。

## OpenCV 二维能力

### 图片基础与常用组合

| node type | category | 层级 | 说明 |
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

当前使用 `points.v1`、`lines.v1`、`circles.v1`、`ellipses.v1` 和 `planar-transform.v1`。所有几何 payload 必须携带明确 coordinate space；跨来源或跨坐标空间操作快速失败。

| node type | category | 说明 |
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

| node type | category | 说明 |
| --- | --- | --- |
| `custom.opencv.line-measure` | `opencv.measurement.edge` | 沿卡尺阵列寻找边缘并拟合直线，输出边缘点、直线、残差和有效率。 |
| `custom.opencv.ellipse-measure` | `opencv.measurement.geometry` | 沿椭圆法向采样并拟合椭圆，输出残差和覆盖率。 |
| `custom.opencv.rectangle-measure` | `opencv.measurement.geometry` | 量测四边位置、宽高、角度、平行度和矩形度。 |
| `custom.opencv.edge-pair-measure` | `opencv.measurement.edge` | 查找同极性或异极性的边缘对，输出宽度/间距分布。 |
| `custom.opencv.gray-profile-measure` | `opencv.measurement.edge` | 沿线、带状区域或法向输出灰度剖面及峰谷位置。 |
| `custom.opencv.radial-line-search` | `opencv.measurement.circle` | 从中心沿多条径向搜索边缘，输出点集、覆盖率和可选圆/椭圆拟合。 |

`custom.opencv.circle-measure` 保持圆量测专用契约，输出 `circles.v1`、`value.v1` summary 和可选调试预览；通用几何关系量测使用 `measurements.v1`。两类结果按语义分开，不创建 Circle Measure 同义节点。

### 定位统一

当前定位结果使用 `localizations.v1`。单项至少包含 `method`、`center`、`angle_degrees`、`scale`、`score`、`coordinate_space`、`transform`、可选 `region/roi` 和 `diagnostics`。

两个高频组合工具直接输出该统一结果：

| node type | category | 说明 |
| --- | --- | --- |
| `custom.opencv.feature-locate` | `opencv.matching.feature` | 特征提取、匹配、几何验证和 transform/localization 输出，公开 matcher、ratio、RANSAC 等稳定参数。 |
| `custom.opencv.shape-locate` | `opencv.matching.template` | 轮廓/边缘形状建模、搜索、角度/尺度范围和 localization 输出。 |

不新增 Gray Match、Mark Extract 或 Mark Locate 同义节点。灰度定位使用现有 Template Match，Mark 只是 Workflow App 对 Template/Feature/Shape Locate 的场景命名。

统一输出按语义边界实施，不把不同结果强塞进同一 payload：Template Match 和多尺度模板的一对多候选继续输出 `regions.v1`；Phase Correlation、ECC 与 Homography 继续输出变换。Feature Locate 与 Shape Locate 同时具备中心、角度、尺度、score、目标区域和变换，因此输出 `localizations.v1`。现有公开输出没有被删除或改写。

### 标定完整链路

当前标定结果使用 `camera-calibration.v1` 和 `stereo-calibration.v1`。观察数据、内外参、坐标系、图像尺寸、误差摘要和来源 fingerprint 必须显式记录。

| node type | category | 说明 |
| --- | --- | --- |
| `custom.opencv.calibration-observation-filter` | `opencv.calibration.camera` | 按角点数量、覆盖、姿态分布和单张重投影误差筛选观察。 |
| `custom.opencv.calibration-diagnose` | `opencv.calibration.camera` | 输出总体/单图重投影误差、覆盖、异常观察和稳定性诊断。 |
| `custom.opencv.stereo-calibrate` | `opencv.calibration.camera` | 计算双目内外参和左右相机关系。 |
| `custom.opencv.stereo-rectify` | `opencv.calibration.camera` | 计算校正旋转、投影矩阵、Q 和有效区域。 |
| `custom.opencv.rectification-map` | `opencv.calibration.camera` | 生成校正 map；大型 map 写入 ObjectStore 并返回 key。 |
| `custom.opencv.image-rectify-stereo` | `opencv.image.transform` | 使用已生成 map 校正左右图片，不在每帧重复计算 map。 |

“联合标定”必须拆解为具体的 stereo 或 hand-eye 操作；“标定校正”必须区分计算参数、生成 map 和应用 map。

### 通用检查工具

| node type | category | 说明 |
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

- rectification map 和 variation model 使用来源 fingerprint 与 ObjectStore key 作为事实源；运行时按引用读取，并复用操作系统文件页缓存。
- Shape Locate 和 Feature Locate 当前不增加独立模型缓存层。只有基准证明重复建模成为瓶颈后，才在常驻 worker 内增加按内容 fingerprint、有容量上限的可丢失缓存，避免提前引入失效和内存治理复杂度。
- Variation Model 构建使用单遍 Welford 统计，只保留均值、M2 和当前样本，不按样本数保留多份整图矩阵，也不写磁盘中间文件。
- Image Type Convert 的 identity 路径复用同一 Run 内连续矩阵；Image Composite 的普通 alpha 路径使用 OpenCV 同 dtype 运算，mask 路径使用 `float32` 工作矩阵，避免 `float64` 多份整图副本。

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


## 相关文档

- [节点系统](node-system.md)
- [节点分类](node-taxonomy.md)
- [PLC Modbus 联调](../../operations/plc-modbus.md)
- [ROI 节点边界](editor.md)
- [节点包开发](../../nodes/README.md)
- [Workflow 示例](../../examples/workflows/README.md)
- [ADR-0011：工业二维视觉节点覆盖与节点粒度](../../decisions/ADR-0011-industrial-vision-node-coverage.md)
