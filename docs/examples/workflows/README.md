# Workflow 示例源目录

## 文档目的

本目录保存 workflow template 和 FlowApplication 的源 JSON，作为 API 示例、Postman collection 和文档测试的上游材料。

## 与 LocalBufferBroker 的关系

本目录中的示例仍以公开、可复制的输入形状为主：

- HTTP JSON 调试和普通同步调用继续使用 `image-base64.v1`。
- ZeroMQ TriggerSource 端到端调试使用单独的 `*_zeromq.template.json` 和 `*_zeromq.application.json`；当前示例把 HTTP `image-base64.v1` 和 ZeroMQ `image-ref.v1` 两个入口同时发布在同一个 app 上，并通过图内显式转换节点汇入后续链路。
- 真实文件路径调试继续使用 `image-ref.v1` 的 `object_key` storage 引用。
- `BufferRef` 和 `FrameRef` 是本机短期引用，依赖当前 LocalBufferBroker 的 mmap 文件、offset、broker_epoch 和 generation，不适合作为 checked-in 示例中的固定请求体。

运行时链路已经按最新实现接入 LocalBufferBroker。`image-base64.v1` 进入 workflow 后会先变成 execution memory image-ref；YOLOX detection 节点在存在 broker writer 时会写入 LocalBufferBroker 并用 BufferRef 通过 PublishedInferenceGateway 调用已发布 deployment worker。OpenCV 和 Barcode/QR 自定义节点通过公共 `load_image_bytes` 读取图片，因此同一节点实现可以读取 memory、storage、buffer 和 frame 四类 image-ref。

TriggerSource 只负责把协议原生输入映射到图的公开 input binding，不负责替后续节点做跨 payload type 转换。当前 `*_zeromq` 示例已经在图里显式增加多个 input binding，并加入 `image-ref -> image-base64` 转换节点后再接入后续节点。PLC、IO 或寄存器值触发只有数值输入时，也应由图内节点决定是否去读本地图片、抓取相机帧或构造后续图片输入。

ZeroMQ TriggerSource 示例不把机器相关的 `path`、`offset` 和 `broker_epoch` 固定写入请求体；这些字段由 backend-service adapter 在收到 SDK 发送的图片 bytes 后临时生成，再映射到 runtime 的 `image-ref.v1` 输入。
