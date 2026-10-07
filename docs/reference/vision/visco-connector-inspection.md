# ViSCO 二维连接器检查资料与功能核对

资料核对日期：2026-10-07。本文是外部产品参考，不是 AMVision 已支持功能表。项目设计和实施门禁见[二维连接器检查实施基线](../../development/connector-inspection-2d.md)。

跨厂商通用量测、成像与产品规范资料见[工业二维检查资料与能力边界](industrial-2d-measurement.md)；节点职责只在实施基线维护。

## 证据范围

本次使用厂商官方公开页面、官方资料的搜索索引内容，以及 OpenCV、MVTec 官方技术文档。ViSCO 部分页面和 PDF 在直接访问时返回 404；其官方 URL 的索引正文仍可读取。因此，以下功能可以作为公开资料中的描述核对，不能代替当前版本的软件实机操作、完整手册或性能验收。

没有取得全部检查项目清单、可操作的软件演示环境、完整连接器工具手册或用户连接器样品。没有核验 ViSCO 的逐个菜单、按钮位置和私有算法实现。不同语言的同一网页作为交叉核对，不作为独立性能证据。

## 官方资料索引

| 编号 | 官方资料 | 核对结论及使用边界 |
| --- | --- | --- |
| V01 | [连接器检查](https://www.visco-tech.com/application/exclusive/connector/)；[繁体中文对应页面](https://www.visco-tech.com/ct/application/exclusive/connector/) | 公布检查项选择、PIN 排列、基准设置和参数复用能力；公开页不是完整操作手册。 |
| V02 | [边缘检测](https://www.visco-tech.com/technical/gauging/edge/) | 检测线、边缘对距离与轮廓偏差是可核对的使用方式。 |
| V03 | [几何形状匹配 GradFinder](https://www.visco-tech.com/english/technical/guidance/patternmatch/) | 依据几何特征定位，强调成像变化下的稳定性；算法属于厂商实现，不能等同于本项目的模板匹配。 |
| V04 | [轮廓、毛边、缺损检查](https://www.visco-tech.com/ct/application/general/general-filter/) | 以基准线偏差、两线宽度和单边检查组织轮廓缺陷。 |
| V05 | [BLOB 检查](https://www.visco-tech.com/application/general/general-blob/) | 除面积外还使用形状比例；适合作为通用外观工具的参考。 |
| V06 | [DefFinder 系列](https://www.visco-tech.com/application/general/deffinderseries/) | 多个良品参考用于容纳正常外观差异；不据此推断其统计模型。 |
| V07 | [MatrixDefFinder](https://www.visco-tech.com/application/general/deffinderseries/matrixdeffinder/) | 同一检查配置展开至多个位置，连接器 PIN 是公开举例之一。 |
| V08 | [SegmentDefFinder](https://www.visco-tech.com/application/general/deffinderseries/segmentdeffinder/) | 区域划分后配置检查内容；可参考区域与规则的明确关联。 |
| V09 | [PC 集中监视 VTV-QCS](https://www.visco-tech.com/th/product/point/pc/) | 包含运行状态、结果、计数、时间和历史查询；属于运行管理，不是连接器算法本身。 |
| V10 | [VDA 数据分析](https://www.visco-tech.com/product/point/graph/) | 结果数据可用于图表、统计及离线分析；不能将过程统计直接当作测量准确度认证。 |
| V11 | [官方培训内容](https://www.visco-tech.com/product/viscosolution/program/) | 覆盖检查、任务、工具、输入输出与导入导出；完整工具操作仍需要手册或演示补证。 |
| V12 | [连接器检查指南 PDF](https://www.visco-tech.com/document/connector.pdf) | 索引显示覆盖成形、组装等不同工序的检查；本次未取得可逐页核对的 PDF，不把示意图当成测量定义。 |
| V13 | [VTV-9000 产品资料 PDF](https://www.visco-tech.com/document/vtv9000.pdf) | 用于识别定位、检查、计量等功能分类；本次未完成原 PDF 页面核验。 |
| V14 | [配置与操作画面定制](https://www.visco-tech.com/product/point/customize/) | 官方描述按 sheet 配置的 cell-flow 方式，以及图像、结果、文字和按钮控件的布局/外观调整；未实际操作软件。 |
| T01 | [MVTec measure_pairs](https://www.mvtec.com/doc/halcon/13/en/measure_pairs.html) | 参考边缘极性、边缘对选择及扫描方向约束；是公开算子文档，不代表 ViSCO 的算法。该链接为历史版本。 |
| T02 | [OpenCV 标定与坐标变换](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html) | 参考相机参数、畸变和坐标变换的数学定义；不据此承诺现场测量精度。 |

## ViSCO 连接器工具已确认的范围

V01 公开描述 70 余项检查，但未枚举完整定义；展示同类/相邻 PIN 的方向间距及偏移差。排列包括单排、双排、不同 PIN 类型及交错形式，允许设计留空。配置涉及基准、名义间距和数量，共享设置可用于针数变化，另有数值补正。页面所列 1/4～1/2 像素重复性及 0.2～0.5 ms/search 是厂商特定搜索描述，不能当作完整测量链路指标。

本项目从这组资料提取的设计要求是：检查对象有稳定编号；模板参数可展开；测量定义和基准必须明确；操作人员可以在图像和检查项表之间核对结果。以上是 AMVision 的设计判断，不是对 ViSCO 内部实现的还原。

## 可确认的使用思路与尚未确认的操作

| 使用环节 | 公开证据 | 本项目准备采用的交互 |
| --- | --- | --- |
| 建立定位对象 | V03 的形状特征匹配 | 选择参考图、定位区域、方向范围并检查候选；失败时不沿用上一帧姿态。 |
| 设置量测区域 | V02 的检测线与双边缘 | 图像上编辑扫描方向、带宽、极性；同步显示灰度剖面和选中边缘。 |
| 检查轮廓 | V04 的基准偏差/宽度 | 显示被采用和被排除的边缘点、容差带及无效原因。 |
| 多位置复用 | V07 的重复配置 | 配置一个 PIN 类型后按名义位置展开，必要的局部差异显式覆盖。 |
| 不同区域不同检查 | V08 的区域细分 | 检查项表明确列出区域、测量项与规则，避免隐藏绑定。 |
| 正常差异与缺陷区分 | V06 的多良品参考 | 首轮优先现有轮廓/BLOB/参考差分；多参考统计模型独立验证后再纳入。 |
| 运行与结果回看 | V09、V10 | 复用 Runtime、App Mode、显式文件记录和结果显示节点。 |
| 检查配置与操作员界面分开 | V14 的流程配置和画面控件 | 配方编辑保留在节点编辑器，现场结果展示保留在 App Mode；不为本轮引入独立页面设计器。 |

这张表给出的是功能使用关系，不是 ViSCO 软件逐屏教程。框选模型后的具体对话框、PIN 编号方向切换、检查项表字段、失败提示和模板版本规则，仍需官方手册或合法演示环境核对。

## 不照搬的部分

- ViSCO 的专用控制器、相机/光源直连和硬件同步不进入 AMVision 核心；输入仍来自外部系统或受控扩展节点。
- 共享参数编辑后自动影响其他任务，不适合作为 AMVision 已发布版本的行为；草稿可以复用，发布后必须冻结。
- 3D 高度、空间共面度、多视角重建不属于本轮。二维图像的端点偏差必须按其二维含义命名。
- 厂商的并行分配、缓冲方案不构成本项目增加 Runtime/Trigger 排队或自动重试的理由。
- 不使用 GradFinder、DefFinder 等名称命名自研算法，也不承诺性能等效。

## 后续资料收集清单

| 资料 | 用于确定什么 | 未获得时可继续的工作 |
| --- | --- | --- |
| 连接器原始图、采集分辨率/位深、光学条件 | 可见边缘、曝光变化、反光、景深与可测区域 | 契约、合成图测试、编辑器基础交互 |
| 尺寸图纸、测量基准、单位、公差、留空 PIN 表 | 每个检查项实际量的定义，防止计算了错误尺寸 | 通用类型与校验；不冻结现场默认阈值 |
| 良品、缺 PIN、偏位、弯曲、毛刺、临界样品 | 缺陷检出率、误判率、无效率 | 故障注入和流程行为测试 |
| 独立参考测量及其方法、重复上料数据 | 偏差、重复性、误差预算与放行规则 | 不声明真实精度验收通过 |
| PIN 数范围、单次节拍、CPU/内存、并行数 | 采样、缓存和执行预算 | 建立基准记录格式，不承诺固定耗时 |
| 官方完整工具手册或合法演示 | 具体操作、检查项定义、异常反馈 | 继续采用已确认的公开功能，不补写臆测菜单 |

优先收集一套单排连接器数据，完成“指定截面的 PIN 宽度 + 相邻中心距 + 缺 PIN”闭环，再扩展双排与交错。已有治具/塑盒分类图片可回归平台链路，但不能替代连接器计量数据。
