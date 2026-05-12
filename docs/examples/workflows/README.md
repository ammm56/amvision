# Workflow 示例源目录

## 文档目的

本目录保存 workflow template 和 FlowApplication 的源 JSON，作为 API 示例、Postman collection 和文档测试的上游材料。

## 与 LocalBufferBroker 的关系

本目录中的示例仍以公开、可复制的输入形状为主：

- HTTP JSON 调试和普通同步调用继续使用 `image-base64.v1`。
- 真实文件路径调试继续使用 `image-ref.v1` 的 `object_key` storage 引用。
- `BufferRef` 和 `FrameRef` 是本机短期引用，依赖当前 LocalBufferBroker 的 mmap 文件、offset、broker_epoch 和 generation，不适合作为 checked-in 示例中的固定请求体。

运行时链路已经按最新实现接入 LocalBufferBroker。`image-base64.v1` 进入 workflow 后会先变成 execution memory image-ref；YOLOX detection 节点在存在 broker writer 时会写入 LocalBufferBroker 并用 BufferRef 通过 PublishedInferenceGateway 调用已发布 deployment worker。OpenCV 和 Barcode/QR 自定义节点通过公共 `load_image_bytes` 读取图片，因此同一节点实现可以读取 memory、storage、buffer 和 frame 四类 image-ref。

后续本地 adapter 或 WorkflowTriggerSource 正式实现后，应新增单独的高速输入示例，而不是把机器相关的 `path`、`offset` 和 `broker_epoch` 固定写入现有 HTTP/Postman 示例。
