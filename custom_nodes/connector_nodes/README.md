# Connector Nodes

二维连接器的行业扩展包，版本 0.1.8，依赖 `opencv.nodes >=0.1.8 <0.2`。默认禁用，工程验证阶段不表示已完成现场计量验收。

| 节点 | 输入 | 输出 | 职责 |
| --- | --- | --- | --- |
| Pin Array Locate | image、pose；显式 Layout | pins、features、checks、summary；可选 debug_preview | 固定身份、有限边缘和具名端点观测；配置候选带内的额外 PIN 检查；Preview 可选逐 PIN 剖面，Runtime 不生成 |
| Connector Measure | 同次观察的 pins、features | measurements、summary、annotations | Width、Pitch、Total Pitch、Gap、Offset、Length、Angle；不重新读图或检测 |

公差交给通用 Check Limits，图像显示及文件记录使用已有节点。普通二维采样、几何、标定和定位属于 OpenCV 包，共享函数从 `custom_nodes.opencv_nodes.shared.backend.metrology` 导入。Core 不依赖本包。

前端编辑器通过仓库可信注册表随 Vue 3 构建，不支持下载包任意注入浏览器代码。包禁用不影响原有 Core/OpenCV 工作流。

使用步骤、边界与剩余验收见 [实施基线](../../docs/development/connector-inspection-2d.md)；可生成的工作流见 [工程示例](../../docs/examples/workflows/connector-inspection.md)。
