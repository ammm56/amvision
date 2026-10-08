# Connector Nodes

二维连接器的行业扩展包，版本 0.1.8，依赖 `opencv.nodes >=0.1.8 <0.2`。已通过节点管理启用，用于连接器工程应用；启用不表示已完成现场计量验收。

| 节点 | 输入 | 输出 | 职责 |
| --- | --- | --- | --- |
| Pin Array Locate | image、pose；显式 Layout | pins、features、checks、summary；可选 debug_preview | 固定身份、有限边缘和具名端点观测；配置候选带内的额外 PIN 检查；Preview 可选逐 PIN 剖面，Runtime 不生成 |
| Connector Measure | 同次观察的 pins、features | measurements、summary、annotations、result_geometry | Width、Pitch、Total Pitch、Gap、Offset、Length、Angle；不重新读图或检测 |

公差交给通用 Check Limits，图像显示及文件记录使用已有节点。普通二维采样、几何、标定和定位属于 OpenCV 包，共享函数从 `custom_nodes.opencv_nodes.shared.backend.metrology` 导入。Core 不依赖本包。

`Image Encoding` 必须与输入来源一致：默认 `native` 保留原始强度；确定采用 sRGB 编码的图片选择 `srgb`，在采样前逐通道还原线性强度。该选项不改变图像坐标或显示图片，也不自动猜测相机 Gamma。相机存在另外的 Gamma、色调映射或饱和裁剪时，需要独立验证成像设置，不能简单套用 sRGB。

采样类型的 `Min Gradient` 是绝对梯度底线，`Relative Gradient` 是各扫描线最大绝对梯度的比例，实际门限取两者较大值；后者默认 0，范围为 0–1。阈值按采样类型显式保存，可为 PIN 所在行和背景候选带使用不同类型。已有原始强度配方不隐式启用新选项。合成示例显式选择 sRGB，并保留原始公差。

前端编辑器通过仓库可信注册表随 Vue 3 构建，不支持下载包任意注入浏览器代码。包禁用不影响原有 Core/OpenCV 工作流。

PIN 编辑器使用版本化参考图配置固定身份、扫描带和具名端点；尺寸编辑器从显式 Pins/Features 连线读取布局，支持批量预览、添加和恢复。公差由通用 Check Limits 表定义。需要图表联动时，将 `result_geometry` 接入 Value Preview 的 Geometry，并将其 Table 输出接入 Image Preview 的 Results；不按节点名称或位置自动绑定。详细契约和验证边界见 [编辑与结果解释实现记录](../../docs/development/connector-usability-implementation.md)。

使用步骤、边界与剩余验收见 [实施基线](../../docs/development/connector-inspection-2d.md)；可生成的工作流见 [工程示例](../../docs/examples/workflows/connector-inspection.md)。
