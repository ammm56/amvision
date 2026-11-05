# Workflow 示例

本目录保存经过自动化测试的 Workflow Template 和 Application 源文档。示例用于说明节点组合与契约，不保存某次运行结果、固定数据库 id 或客户现场数据。

## 文件规则

- `<name>.template.json`：图、节点、边、分组、参数和公开端口。
- `<name>.application.json`：应用信息、template 引用、input/output bindings 和 runtime hints。
- `<name>.sqlite.sql`：少数交付示例需要的结果表结构。
- API 请求体与 Postman collection 位于 `docs/api/examples/workflows/` 和 `docs/api/postman/workflows/`。

保存顺序、Preview、发布、Runtime、Run 和 Trigger 调用见 [Workflow API](../../api/workflows.md)。

## 示例分类

| 分类 | 文件前缀或主要示例 | 目的 |
| --- | --- | --- |
| 数据集任务 | `dataset_import_*`、`dataset_export_*` | 上传、导出、打包与任务结果 |
| 模型任务 | `detection_training_*`、`detection_evaluation_*`、`detection_conversion_*` | 训练、评估、转换的提交与结果 |
| Deployment | `*_deployment_*` | detection、classification、segmentation、pose、OBB 的同步调用和健康检查 |
| OpenCV | `opencv_process_save_image*` | 图片处理和保存位置 |
| 工业二维视觉工具 | `industrial_vision_*` | 灰度/特征/形状定位、亚像素量测、双目标定诊断、胶路和轮廓偏差的可组合基础示例 |
| 二维连接器 | [连接器工程示例](connector-inspection.md) | 单/双排 PIN、不可变模板/标定、尺寸、公差及图片结果显示；由准备资源生成 |
| 单帧工业规则 | `industrial_single_frame_*` | ROI、测量、匹配、缺陷、连续性和质量门禁 |
| 数值三态 | `inspection_limits` | Check Limits → Result Record / Value Preview；同步/异步、App Mode 及无法判定传播 |
| 三维锂电工件 | [完整工件配方](lithium-workpiece.md) | 文件/同机数组、十二钢片与两半圆、50 项工程判定、完整证据显示及 JSON 保存 |
| 三维法向 | `metrology3d_normals` | ASCII PLY → Filter Valid → Estimate Normals → Preview；参数、容量与使用边界见[法向记录](../../development/3d-metrology-normals.md)，不自动插入工件配方 |
| 三维位姿 | `metrology3d_pose_ops` | 当前工件文件 → 五窗基准 → Build Frame → Invert / Compose → Transform Cloud → Preview；显式次序、原字段与来源沿用，见[位姿记录](../../development/3d-metrology-pose-operations.md)，不是自动定位或客户通用参数 |
| 本地目录 | `industrial_local_directory_*` | batch、poll、watch、cursor 和位置判定 |
| PLC / Modbus | `plc_*` | 等待、状态字、TriggerSource 和结果回传 |
| USB / UVC | `camera_usb_uvc_*`、`industrial_single_frame_usb_uvc_*` | 枚举、session、流预览和单帧处理 |
| YOLOE / SAM3 | `*_yoloe_*`、`*_sam3_*` | 文本/视觉提示、分割 overlay 与视频复用 |
| 条码结果 | `barcode_result_display` | 自定义节点结果到公开输出 |

目录中的文件名就是稳定示例 id；新增示例必须同时补文档契约测试，避免只增加无法保存或运行的 JSON。

## 图片传输

checked-in 请求体优先使用可替换的 ObjectStore 相对引用或小型示例值。真实运行可根据入口选择：

- ObjectStore `image-ref.v1`
- 磁盘绝对路径 `image-ref.v1`（仅明确支持本地磁盘的入口）
- LocalBufferBroker `BufferRef`
- 视频/流链路的 `FrameRef`
- 小图片兼容用 Base64

BufferRef 和 FrameRef 具有短生命周期并绑定本机 broker/epoch，不适合作为 checked-in 示例中的固定请求体。外部 ZeroMQ adapter 应先把图像或帧写入 LocalBufferBroker，再把引用提交给 Workflow。

## 使用前替换

- `project_id`、Application/Template/Version/Runtime/Deployment id
- 数据集、模型和训练产物引用
- ObjectStore 相对位置或本机绝对路径
- PLC 地址、寄存器、目录和回调地址
- token、用户名、密码与其他凭据

一般节点的 `save_location` 同时演示 ObjectStore 相对位置和明确支持的本机绝对位置；不能把普通 `object_key` 任意解释成磁盘路径。`Image Save` 单独使用 `save_directory` 和 `file_name`，目录仍遵循相同双路径规则；目录和文件名都复用通用日期时间模板，例如 `results/{YYYY}/{MM}` 与 `saveimage-{YYYY}-{MM}-{DD}-{hh}-{mm}-{ss}-{SSS}.jpg`。

## 验证

```powershell
python -m pytest tests/test_workflow_example_documents.py
python -m pytest tests/test_workflow_api_document_examples.py
```

运行环境还需要按场景准备 Node Pack、模型、Deployment、设备或本地目录。示例文件通过静态测试不等同于现场依赖已经就绪。

## 数值三态示例

[inspection_limits.template.json](inspection_limits.template.json) 与 [application](inspection_limits.application.json) 使用一个 d/mm 必检项，演示限值为闭区间 0.95–1.05。它不是锂电工件的图纸公差或产品验收标准。完整输入、状态和升级规则见[判定结果契约](../../api/workflow-inspection-results.md)。正式发布后，在 App Mode 提交 measurements；示例不引用本机文件、部署或开发数据库 id。

已有 PLC/HTTP/SQL 示例的来源字段已改为 state/passed。外部目标列名或字段名仍可由配方映射为 ok_ng/ok，但接收端应按显式映射理解小写三态及放行布尔，不能继续将 not passed 当作 NG。
