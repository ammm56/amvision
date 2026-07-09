# 高性能图片数据面规划

## 文档目的

本文档固定上位机、ZeroMQ TriggerSource、LocalBufferBroker、workflow app 节点和模型推理节点之间的大图高速传递规则，避免后续实现时再次把现场高帧率链路退回到 JPEG、PNG、Bitmap 或 base64 转换路径。

这里讨论的是本机高速图片数据面，不替代 HTTP API、workflow app 管理接口、SDK 配置包、模型 DeploymentInstance 管理页面或普通调试示例。

## 现场目标

典型现场上位机从工业相机获得 2000 万像素左右的图片，常见分辨率约为 5000x4000。每秒几十帧调用时，图片传输和 workflow 节点处理的额外耗时必须控制在可接受范围内，除模型推理本身外，数据面和节点桥接目标应尽量控制在 50ms 到 100ms 以内。

HTTP JSON、base64、PNG、JPEG 和 Bitmap 转换可以继续作为低频调试、远程调用、结果查看和兼容输入使用，但不应作为本机高频 TriggerSource 的默认链路。

## 当前观察结论

当前直接模型 multipart 调用在功能上可用，耗时主要集中在模型推理和图片解码：

- 1920x1080 输入：总耗时约 110ms，decode 约 5.5ms，preprocess 约 7.9ms，infer 约 96ms。
- 3840x2160 输入：总耗时约 125ms，decode 约 18.5ms，preprocess 约 9.3ms，infer 约 97ms。

当前 ZeroMQ TriggerSource 的主要性能问题不是 ZeroMQ 第二帧本身，而是后续 workflow 图和结果返回重新引入了昂贵转换：

- 当前调试图把 `request_image_ref` 经过 `Image Base64 Encode -> Image Base64 Coalesce -> Image Base64 Decode` 后再送入 Detection，这会把本来已经是 LocalBufferBroker 引用的图片重新转成 base64。
- 当前结果中如果返回 `core_output_image_body_body`，且 `transport_kind=inline-base64`、`media_type=image/png`，会把全分辨率图片编码成 PNG 再塞进 JSON reply。分辨率越大，编码、base64 和 JSON 序列化越慢。
- 如果 TriggerSource 没有明确 `result_binding`，结果分发不应兜底返回所有 outputs；高频 TriggerSource 默认只返回小 JSON 结果。

因此，ZeroMQ 已经把外部图片 bytes 作为 multipart 第二帧传入，但完整高速路径还没有收口。需要把 SDK、adapter、LocalBufferBroker、workflow 节点、模型 runtime 和前端默认图一起改成 raw image-ref 优先。

## 数据模式

| 模式 | 适用场景 | 规则 |
| --- | --- | --- |
| `image-base64.v1` | HTTP 调试、低频远程调用、旧系统桥接 | 可用但不是高频默认路径 |
| encoded image bytes | JPEG/PNG/BMP 文件上传、模型直接 HTTP multipart | 需要解码，适合普通同步调用和调试 |
| storage `image-ref.v1` | 已落盘图片、长期文件引用 | 用于可复现和审计，不代表内存高速 |
| buffer/frame `image-ref.v1` | 本机高速 TriggerSource、workflow runtime、deployment worker | 默认高性能路径 |
| raw BGR24 BufferRef | 工业相机高频图片输入 | 默认高速图片格式 |

高性能链路中的图片应尽量保持为 buffer/frame `image-ref.v1`，只在明确需要预览、保存、HTTP 响应或外部系统要求时编码成 PNG、JPEG 或 base64。

## BGR24 输入约定

ZeroMQ 高性能图片输入的默认像素格式为 BGR24：

```json
{
  "media_type": "image/raw",
  "pixel_format": "bgr24",
  "dtype": "uint8",
  "layout": "HWC",
  "shape": [2160, 3840, 3],
  "width": 3840,
  "height": 2160
}
```

约束如下：

- 字节长度必须等于 `width * height * 3`。
- 通道顺序为 B、G、R，每通道 8 bit。
- 新代码和文档统一使用 `pixel_format=bgr24`，不要继续新增 `BGR`、`BGR24` 等大小写变体。
- 第一阶段要求连续内存，不处理行填充。后续如需支持工业相机 pitch/stride，应增加 `row_stride_bytes`，而不是隐式猜测。
- SDK 在发送前必须校验宽、高、shape、dtype、layout、pixel_format 和 bytes 长度。
- 后端写入 LocalBufferBroker 时必须保留 shape、dtype、layout、pixel_format 和 media_type。

## 推荐高速调用链

```text
工业相机 / 上位机
  -> BGR24 byte[]
  -> .NET SDK AmvisionTriggerClient
  -> ZeroMQ multipart
       frame 1: JSON envelope
       frame 2: raw BGR24 bytes
  -> ZeroMQ TriggerSource adapter
  -> LocalBufferBroker BufferRef / FrameRef
  -> workflow app request_image_ref
  -> raw-aware image matrix loader
  -> Detection / OpenCV / Barcode / Preview / Export 节点
  -> 小 JSON result_binding
```

这条链路中，图片进入 backend-service 后不应默认转 base64，不应默认编码 PNG/JPEG，不应默认写 ObjectStore，不应默认把图片内容放进 Trigger reply。

## Workflow 图默认拓扑

高性能 workflow app 的默认双入口拓扑应按 image-ref 优先组织：

```text
request_image_ref --------------------\
                                       -> Image Ref Coalesce -> Detection / OpenCV / Barcode
request_image_base64 -> Base64 Decode /
```

当前 `request_image_ref -> Image Base64 Encode -> Image Base64 Coalesce -> Image Base64 Decode` 只能作为兼容调试路径，不应作为高频 TriggerSource 的默认模板。

前端图编辑和模板生成需要表达以下规则：

- `request_image_ref` 是 ZeroMQ 图片触发的默认输入。
- `request_image_base64` 是 HTTP/JSON 调试入口。
- 用户选择返回预览图、保存结果图或 inline-base64 时，界面应提示这会增加编码和传输耗时。
- `Response Envelope` 默认只绑定小 JSON 检测结果、判定结果或业务摘要，不默认绑定全分辨率图片。

## SDK 实现要求

.NET SDK 已经具备 ZeroMQ envelope、shape、dtype、layout、pixel_format 等字段，后续需要补齐面向现场的 BGR24 helper：

- `ImageTriggerRequest.FromBgr24(byte[] bytes, int width, int height, ...)`
- `InvokeZeroMqBgr24Async(...)` 或同等 Console 封装
- 配置 key 调用保持现有 `Config/config_*.json + key + 方法` 模式
- 高频调用时复用 `AmvisionTriggerClient` 和底层 socket，不要每帧创建和释放
- 高频调用方法不做 Bitmap、JPEG、PNG 或 base64 转换
- 如果现场相机 SDK 只能给出 RGB、Mono、Bayer 或带 stride 的 buffer，转换规则应在上位机侧显式完成，并在配置或方法名里表达清楚

现有 `FromFile`、`FromBase64`、`FromBytes(..., "image/jpeg")` 继续保留给低频调试和普通集成使用，但文档、Console 默认调用和高性能示例应优先展示 BGR24。

## 后端实现要求

### ZeroMQ adapter

ZeroMQ TriggerSource adapter 接收第二帧图片 bytes 后写入 LocalBufferBroker。写入时必须完整保存：

- `media_type`
- `shape`
- `dtype`
- `layout`
- `pixel_format`
- `pool_name`

如果没有第二帧，adapter 仍按纯事件触发执行 workflow app，满足 PLC、传感器和空参数触发场景。纯事件触发不应被 BGR24 规则限制。

### 图片读取 helper

需要新增或收口一个 raw-aware 图片矩阵读取 helper，统一给模型节点和 OpenCV 节点使用：

- encoded JPEG/PNG/BMP：继续 `cv2.imdecode`。
- raw `bgr24`：通过 `np.frombuffer(...).reshape(height, width, 3)` 获得 BGR matrix，不执行 decode。
- 节点只读时尽量使用 view；节点会修改像素时再 copy。
- helper 负责校验 shape、dtype、layout、pixel_format 和 bytes 长度。

不要让每个节点单独解析 BufferRef 或单独判断 BGR24，否则后续会再次出现行为分叉。

### 模型推理节点

YOLOX、YOLOv8、YOLO11、YOLO26、RF-DETR 的 detection、classification、segmentation、pose、obb 节点和 DeploymentInstance runtime 都应接入 raw-aware loader。

BGR24 输入下不应再走 `cv2.imdecode`。运行时指标可以把 encoded 输入的 `decode_ms` 与 raw 输入的 `raw_view_ms` 或等价指标分开记录。

### OpenCV 和显示节点

以下节点类型必须支持 BGR24 image-ref：

- Image Preview
- Draw Detections / Draw Regions / Overlay 类节点
- Crop / Crop Export
- OpenCV preprocess、measure、matching、geometry、defect 节点
- Barcode / QR 节点
- image-ref / image-base64 桥接节点

节点输出规则：

- 中间链路默认继续输出 `image-ref.v1`。
- 只有用户选择预览、保存、HTTP 响应、外部回调或 ObjectStore 输出时才编码 PNG/JPEG/base64。
- `Crop Export` 写文件时可以编码输出；给后续节点使用时应优先输出 raw image-ref。
- `Draw Detections` 给后续节点使用时应优先输出 raw image-ref；给前端预览时才编码。

## 结果返回规则

TriggerSource 高频 reply 默认返回小 JSON：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "items": []
  }
}
```

不应默认返回：

- 全分辨率 inline-base64 图片
- PNG/JPEG 编码后的图片体
- 所有 workflow outputs
- 大型 node_records 或调试快照

如果用户确实需要返回图片，应通过 workflow 图和 TriggerSource `result_binding` 明确选择，并在前端和文档中标明这不是高帧率默认方式。

## 并发边界

当前 ZeroMQ SDK 和后端 adapter 的基本形态是 REQ/REP：

- 一个 `AmvisionTriggerClient` 复用一个 socket，适合单调用链顺序请求。
- 一个 TriggerSource adapter 使用 REP socket 时天然串行处理请求。
- 当前 WorkflowAppRuntime worker 内部仍有运行锁，单 runtime 默认一次处理一个 run。
- 模型 DeploymentInstance 可以配置多实例，但 workflow app trigger 不会自动把一个 runtime 的请求并行分发到多个 workflow worker。

因此，高并发高帧率不是“给同一个 runtime 多加几个 trigger”就能自动解决。后续如需并发，应规划以下方向之一：

- 多个 TriggerSource endpoint + 多个 WorkflowAppRuntime worker，按产线、相机或工位分片。
- ZeroMQ ROUTER/DEALER + worker pool。
- WorkflowAppRuntime 多 worker 实例和内部队列。
- 连续帧场景使用 LocalBufferBroker ring channel，并明确 latest、strict、drop-oldest、drop-newest 或 block-with-timeout 策略。

## 性能观测字段

高性能链路应补齐以下观测：

- SDK：相机取图后到发送前的 copy/convert 时间、send 等待时间、reply 等待时间。
- Adapter：ZeroMQ 收包、LocalBufferBroker 写入、WorkflowRun submit 时间。
- LocalBufferBroker：pool、slot、写入 bytes、等待、拒绝、覆盖、lease 生命周期。
- Workflow 节点：raw view、copy、encode、decode、节点执行耗时。
- 模型 runtime：decode/raw_view、preprocess、infer、postprocess、serialize。
- Result：reply payload bytes、是否包含 inline-base64、图片编码耗时。

没有这些指标时，不要只凭总耗时判断 ZeroMQ、模型或 workflow 节点谁慢。

## 验收规则

高性能图片链路完成时至少满足以下规则：

- .NET SDK 能直接发送 BGR24 bytes，并自动写入正确 envelope metadata。
- Backend ZeroMQ adapter 能把 BGR24 第二帧写入 LocalBufferBroker，并把 `request_image_ref` 映射给 workflow app。
- 模型推理节点和 OpenCV 节点能直接读取 BGR24 BufferRef，不执行 PNG/JPEG 解码。
- 默认高性能 workflow 模板不包含 `request_image_ref -> base64 encode -> base64 decode` 的绕路。
- TriggerSource 默认 `result_binding` 返回小 JSON，不默认返回 inline-base64 图片。
- 1080p、4K、20MP 图片都有端到端 fixture 或 smoke 测试，至少覆盖 SDK envelope、adapter 写入、workflow 节点读取和模型节点推理。
- 文档、Postman 示例和 Console 默认调用明确区分“高性能 BGR24 image-ref 路径”和“HTTP/base64 调试路径”。

## 相关文档

- [docs/architecture/local-buffer-broker.md](local-buffer-broker.md)
- [docs/architecture/workflow-runtime.md](workflow-runtime.md)
- [docs/architecture/node-system.md](node-system.md)
- [docs/api/workflow-trigger-sources.md](../api/workflow-trigger-sources.md)
- [docs/api/workflow-sdks.md](../api/workflow-sdks.md)
- [docs/api/examples/workflows/README.md](../api/examples/workflows/README.md)
- [sdks/dotnet/README.md](../../sdks/dotnet/README.md)
