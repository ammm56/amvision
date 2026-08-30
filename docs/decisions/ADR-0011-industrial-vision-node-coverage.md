# ADR-0011：工业二维视觉节点覆盖与节点粒度

## 状态

已接受，已实现。阶段 0–6 的现状审计、Core 通用能力、二维几何与图片操作、质量量测与定位、标定、通用检查、绘制和 Workflow App 示例均已完成。详细范围、节点清单、实施顺序和门禁见[工业二维视觉节点实施基线](../development/industrial-vision-node-implementation.md)。

## 背景

现有 Workflow 已具备 Core Node、`opencv.nodes`、运行时 Catalog、版本化 Workflow App 和受控 Node Pack 边界，也已经覆盖较多 OpenCV 预处理、分割、特征、匹配、标定、测量和绘制节点。继续扩展工业视觉能力时，需要同时避免两种偏差：

- 只提供过细的原子算子，使灰度定位、轮廓偏差、胶路检查、标定诊断等高频任务必须重复搭建很长的流程；
- 为每个产品、工位或缺陷名称增加单用途节点，使 Catalog 变成不可复用的现场规则集合。

VisionMaster、HALCON 等工业视觉工具的可借鉴部分是稳定的算子族、通用量测工具和可诊断输出，不是逐项复制产品命名或所有 API。项目还需要保持本地优先、可信节点同进程执行、图片使用 ImageRef/LocalBuffer/ObjectStore，以及规则判断与算法计算分离等既有边界。

## 决策

### 1. 新能力只进入 Core 或现有 `opencv.nodes`

本轮不新增 Python Script 节点或 Python Script Node Pack，也不把脚本执行作为能力缺口的兜底方案。新增节点按职责只进入：

- Core Node：数值、控制流、字符串、变量和本地文本输出等与第三方视觉库无关的 Workflow 通用能力；
- `opencv.nodes`：二维图片处理、几何、定位、量测、标定、检查和结果绘制能力。

不为本轮能力新建 basic、geometry、measurement、inspection 等独立 Node Pack。这些名称继续作为 `opencv.nodes` 内的两级分类。

### 2. 节点粒度分为三层

```text
原子节点
  └─ 单一、可预测、容易组合的操作
常用组合工具节点
  └─ 高频且若只用原子节点会形成较长流程的稳定算法工具
Workflow App / Template
  └─ 产品、工位、阈值、判定和交付方式的场景编排
```

常用组合工具可以成为节点，但必须满足以下条件：

- 跨项目、跨产品可复用；
- 输入、输出、失败语义和诊断信息能够稳定定义；
- 仅用原子节点实现时会重复大量步骤、参数或中间 payload；
- 能通过共享算法函数实现，不在节点 handler 内嵌套调用另一个 Workflow 或另一个节点 handler。

胶路检查、轮廓偏差、斑点分析、特征定位和形状定位属于通用组合工具。特定产品的 OK/NG 规则、Mark 名称、工位补偿步骤和设备交付仍属于 Workflow App 或 Template。

### 3. 使用明确的算子语义

不新增语义不确定的“联合标定”“关联标定”“标定校正”“补正生成”“自动删除”和“Mark 查找”等节点。它们分别由明确的 Stereo Calibration、Hand-Eye Calibration、Transform Compose/Invert/Apply、变量删除，以及 Template/Feature/Shape Locate 等能力表达。

现有 `core.logic.if-else`、`core.logic.switch` 等值选择节点继续保留；真正改变图执行路径的条件分支和开关分支必须使用显式 start/end 控制节点及 Graph Executor 契约，不能用值选择节点冒充控制流。

### 4. 统一二维几何、定位和标定输出

二维几何继续使用 `lines.v1`、`circles.v1`、`ellipses.v1` 和 `planar-transform.v1`，补充 `points.v1`。直接表达单一目标姿态的 Locate 工具输出 `localizations.v1`，至少包含：

- 定位方法、中心、角度、尺度和 score；
- 坐标空间与 `planar-transform.v1`；
- 可选 region/ROI；
- 匹配数、内点率、残差、失败原因等诊断信息。

标定节点补充 `camera-calibration.v1` 和 `stereo-calibration.v1`。大型 rectification map 不内联到 Workflow JSON，通过 ObjectStore key 引用。Workflow JSON 只保存参数、对象引用和小型结构化结果。

`localizations.v1` 不替代所有匹配与配准结果。Template Match 的一对多候选继续使用 `regions.v1`；Phase Correlation、ECC 和 Homography 等图像关系计算继续使用 `planar-transform.v1` 或其原有小型 transform 输出。只有同时具备明确目标中心、角度、尺度和目标范围时才构造 localization，禁止为了表面统一推测不存在的姿态字段。

### 5. 算法输出与规则判定分离

定位、量测、标定和检查节点输出数值、几何结果、误差区域和诊断信息。OK/NG 阈值继续由 Core Rule 节点处理。通用组合工具不得写入某个产品的固定容差，也不得把 PLC、MES、HTTP 或文件交付隐藏在算法节点内。

### 6. 先完成二维工业视觉，三维另立里程碑

本轮只实施二维图片、二维几何、二维定位、二维量测和相机/双目标定。深度图、点云、三维变换、三维拟合、三维测量和三维配准需要独立 payload、内存与可视化边界，另立实施基线，不混入本轮节点清单。

## 未采用方案

- 新增 Python Script Node Pack：引入任意代码、依赖、超时和安全边界，且不能替代稳定节点契约。
- 只实现原子算子：会使高频工业任务产生大量重复节点和中间数据。
- 为胶路、毛刺、Mark 或具体工件建立单用途节点：复用边界不稳定，容易把产品规则写入算法层。
- 逐项复制 VisionMaster/HALCON API：会带入不适用于本项目 payload、Runtime 和依赖边界的表面积。
- 在本轮同时加入 3D：二维与三维的数据规模、坐标系和运行时成本不同，混合实施会扩大风险。

## 影响

- Core Catalog 将补齐通用数值、控制和文本能力，但不增加脚本运行时。
- `opencv.nodes` 将在现有分类内补齐二维几何、质量、量测、定位、标定、检查和绘制能力。
- 高频组合工具与原子节点共享算法实现、缓存和 payload，不复制计算逻辑。
- 前端继续消费动态 Catalog；只有图片交互、ROI、标定观察等确实需要画布操作的节点才增加专用编辑体验。
- 开发阶段按当前规则直接更新节点定义、模板、测试和文档，不保留隐藏兼容节点。
