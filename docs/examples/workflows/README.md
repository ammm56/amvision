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
| 单帧工业规则 | `industrial_single_frame_*` | ROI、测量、匹配、缺陷、连续性和质量门禁 |
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

示例中的 `save_location` 同时演示 ObjectStore 相对位置和明确支持的本机绝对位置；不能把普通 `object_key` 任意解释成磁盘路径。

## 验证

```powershell
python -m pytest tests/test_workflow_example_documents.py
python -m pytest tests/test_workflow_api_document_examples.py
```

运行环境还需要按场景准备 Node Pack、模型、Deployment、设备或本地目录。示例文件通过静态测试不等同于现场依赖已经就绪。
