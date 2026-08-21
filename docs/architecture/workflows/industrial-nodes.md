# 工业视觉与集成节点

## 定位

工业能力通过可组合节点进入 Workflow，不把现场协议、相机驱动或行业规则膨胀到平台资源主链。平台提供稳定的图、payload、Runtime、版本与审计边界；具体设备和算法由 Core Node 或受控 Custom Node Pack 实现。

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

## 相关文档

- [节点系统](node-system.md)
- [节点分类](node-taxonomy.md)
- [PLC Modbus 联调](../../operations/plc-modbus.md)
- [ROI 节点边界](editor.md)
- [节点包开发](../../nodes/README.md)
- [Workflow 示例](../../examples/workflows/README.md)
