# 高性能图片数据面

## 文档目的

本文档固定上位机、ZeroMQ TriggerSource、LocalBufferBroker、workflow app 节点和模型推理节点之间的大图高速传递规则，防止维护中把现场高帧率链路退回到 JPEG、PNG、Bitmap 或 base64 转换路径。

这里讨论的是本机高速图片数据面，不替代 HTTP API、workflow app 管理接口、SDK 配置包、模型 DeploymentInstance 管理页面或普通调试示例。

## 实现状态

LocalBuffer raw/encoded 输入、ZeroMQ 图片请求和 Workflow 单次解码复用是当前已交付能力。多 `result_bindings`、`Image Encode`、统一 ZeroMQ binary attachments、output lease handoff 和 `local-shared-memory` Trigger 是 ADR-0007 已接受但尚未实现的目标；本页对应段落均显式标注，不能作为当前 API capability 使用。

## 现场目标

典型现场上位机从工业相机获得 2000 万像素左右的图片，常见分辨率约为 5000x4000。每秒几十帧调用时，图片传输和 workflow 节点处理的额外耗时必须控制在可接受范围内，除模型推理本身外，数据面和节点桥接目标应尽量控制在 50ms 到 100ms 以内。

HTTP JSON 内联 Base64 主要用于远程调用、调试和结果查看，不是本机高频 TriggerSource 的默认链路。.NET SDK 的 raw BGR24 与 JPEG/PNG/BMP encoded bytes 都是正式支持的本机输入；BGR24 省去后端解码，encoded 表示通常减少传输字节，调用方按现场性能和集成成本选择。

## 数据面规则

- SDK、adapter、LocalBufferBroker、workflow 节点和模型 runtime 以 raw image-ref 为本机高频默认路径。
- `BufferRef` / `FrameRef` 只跨进程传递 mmap 元数据；同步高频节点链不把图片读回后重新编码或落盘。
- workflow 图不得在模型推理前插入不必要的 Base64 编码、合并和解码节点。
- 目标 TriggerSource 必须显式声明 `result_bindings`；迁移完成前当前实现仍使用单个 `result_binding`。高频入口默认只返回小型结构化结果，不返回所有图输出。
- 只有预览、保存、HTTP 响应或外部系统协议明确要求时，才生成 PNG、JPEG、Bitmap 或 Base64。
- 同步推理热路径不使用持久化文件队列、ObjectStore 临时图片、目录扫描或轮询；backend-service 通过 mmap mailbox 调用 inference daemon，图片主体继续留在 LocalBufferBroker。持久异步任务只在必须跨重启的队列边界使用临时 ObjectStore 引用。

## 数据模式

| 模式 | 适用场景 | 规则 |
| --- | --- | --- |
| `image-base64.v1` | HTTP 调试、低频远程调用、小图片集成 | 可用但不是高频默认路径 |
| encoded image bytes | JPEG/PNG/BMP bytes、文件、Base64 还原结果 | 正式支持；首次矩阵消费时需要解码 |
| storage `image-ref.v1` | 已落盘图片、长期文件引用 | 用于可复现和审计，不代表内存高速 |
| buffer/frame `image-ref.v1` | 本机高速 TriggerSource、workflow runtime、deployment worker | 默认高性能路径 |
| raw BGR24 BufferRef | SDK 已有或转换后的连续 BGR24 | 默认高速图片格式 |

高性能链路中的图片应尽量保持为 buffer/frame `image-ref.v1`，只在明确需要预览、保存、HTTP 响应或外部系统要求时编码成 PNG、JPEG 或 base64。

## BGR24 高性能默认约定

图片来源与传输表示相互独立。SDK 调用方可以从相机、文件、网络或内存获得图片，并自行选择传输 BGR24 或 JPEG/PNG/BMP 等 encoded bytes。BGR24 是本机高性能默认表示，不是唯一允许格式。

高性能 BGR24 输入使用以下元数据：

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
- 当前 BufferRef 要求连续内存，不处理行填充。只有协议显式增加 `row_stride_bytes` 后才能接收带 pitch/stride 的工业相机内存，不能隐式猜测。
- SDK 在发送前必须校验宽、高、shape、dtype、layout、pixel_format 和 bytes 长度。
- 后端写入 LocalBufferBroker 时必须保留 shape、dtype、layout、pixel_format 和 media_type。

## 推荐高速调用链

```text
图片采集或上位机程序
  -> BGR24 byte[]
  -> .NET SDK AmvisionTriggerClient
  -> ZeroMQ multipart
       frame 1: JSON envelope
       frame 2: raw BGR24 bytes
  -> ZeroMQ TriggerSource adapter
  -> LocalBufferBroker BufferRef / FrameRef
  -> workflow app request_image_ref
  -> raw-aware image matrix loader
  -> OpenCV / Barcode / Preview / Export 节点
  -> Detection 节点
  -> 跨平台 mmap inference mailbox（图片只传 BufferRef / FrameRef 元数据）
  -> deployment worker 直接只读 mmap / raw NumPy view
  -> 结构化结果 bindings；直接结果图片仍使用 LocalBuffer
```

这条链路中，图片进入 backend-service 后不应默认转 base64，不应默认编码 PNG/JPEG，不应默认写 ObjectStore，不应默认把图片内容放进 Trigger reply。

## 独立 inference daemon 传输规则

功能隔离不能改变图片数据面的性能边界。正式 daemon 模式固定采用以下拆分：

| 通道 | 数据 | 持久化 | 用途 |
| --- | --- | --- | --- |
| deployment 控制队列 | start、stop、warmup、reset | 是 | 恢复、审计、低频变更控制 |
| inference mmap v1 mailbox | infer、ping、status、health、process config、BufferRef/FrameRef、结构化结果 | 否 | 同机低延迟推理和只读状态 |
| LocalBufferBroker pool | raw BGR24 / encoded 输入和结果图片 bytes | 短期 lease | 图片主体 |
| ObjectStore | 上传图片、保存结果、审计输入 | 是 | 低频和可追溯边界 |

约束如下：

- 每次 `infer` 不执行额外 daemon `ping`；本次 mailbox 请求本身就是可用性判断。
- `infer` 不创建一次性文件响应队列，不扫描 queue 目录。
- BufferRef/FrameRef 在同步调用返回前由 Workflow owner 保持 lease；deployment worker 复制完成或推理完成后，节点再释放临时 lease。
- raw BGR24 使用只读 mmap `memoryview -> np.frombuffer`，不执行 PNG/JPEG encode/decode。
- encoded JPEG/PNG/BMP 在 direct mmap reader 中同样保持为只读 `memoryview`，只在 `cv2.imdecode` 内部生成目标矩阵，不先复制一份 encoded bytes。
- mmap reader 只能打开 `LocalBufferBrokerSettings.pools` 明确配置的文件，并校验 offset、size 和 slot 边界，不能读取任意本地路径。
- storage/inline 同步输入由 backend-service 写入主 LocalBuffer；持久异步任务由 daemon 领取 ObjectStore 引用后写入私有短期 LocalBuffer。要求同步结果图片时由 backend-service 预分配 writing lease，daemon 直接写入；mmap 和模型进程 Queue 都不携带图片 bytes 或 base64。
- mmap 成功或收到 daemon 错误响应后立即释放临时 lease；传输状态不确定时保留 lease 到 TTL，由 Broker 回收，不能提前复用给下一请求。
- mailbox descriptor 请求和响应包含 server epoch、generation、owner、deadline 和 CRC32；大型 segmentation 等结构化结果使用固定溢出页池，每页也有 descriptor identity、next page、长度和 CRC32。
- 溢出页连续优先，碎片化时沿非连续 page chain 读取；client ACK 后由 daemon 回收。页池满载或单响应超过配置上限时返回 `mmap_response_capacity_exhausted`，不退回持久化队列、不动态扩文件。
- daemon 对 ACK、超时、取消、调用进程崩溃和 daemon 重启执行统一回收。
- 协议不得依赖 Windows named pipe、Unix domain socket 或 TCP loopback。Windows、Ubuntu x64/ARM64、macOS ARM 使用相同的 mmap 和原子槽位文件实现。

Descriptor、page header、压缩、发布顺序和异常恢复见 [Inference mailbox v1](inference-mailbox-v1.md)。

## Workflow 图默认拓扑

高性能 workflow app 的默认双入口拓扑应按 image-ref 优先组织：

```text
request_image_ref --------------------\
                                       -> Image Ref Coalesce -> Detection / OpenCV / Barcode
request_image_base64 -> Base64 Decode /
```

当前默认高性能模板不再包含 `request_image_ref -> Image Base64 Encode -> Image Base64 Coalesce -> Image Base64 Decode` 绕路。需要 base64 的场景应明确放在 HTTP 调试、预览、保存或外部回传边界，不进入高频 TriggerSource 热路径。

前端图编辑和模板生成需要表达以下规则：

- `request_image_ref` 是 ZeroMQ 图片触发的默认输入。
- `request_image_base64` 是 HTTP/JSON 调试入口。
- 用户选择返回预览图、保存结果图或 inline-base64 时，界面应提示这会增加编码和传输耗时。
- `Response Envelope` 默认只绑定小 JSON 检测结果、判定结果或业务摘要，不默认绑定全分辨率图片。

## SDK 当前实现

.NET SDK 已经具备 ZeroMQ envelope、shape、dtype、layout、pixel_format 等字段，并提供面向现场的 BGR24 helper：

- `ImageTriggerRequest.FromBgr24(byte[] bytes, int width, int height, ...)`
- `InvokeZeroMqBgr24Async(...)` 或同等 Console 封装
- 配置 key 调用保持现有 `Config/config_*.json + key + 方法` 模式
- 高频调用时复用 `AmvisionTriggerClient` 和底层 socket，不要每帧创建和释放
- 高频调用方法不做 Bitmap、JPEG、PNG 或 base64 转换
- 如果现场相机 SDK 只能给出 RGB、Mono、Bayer 或带 stride 的 buffer，转换规则应在上位机侧显式完成，并在配置或方法名里表达清楚

现有 `FromFile`、`FromBase64`、`FromBytes(..., "image/jpeg")` 是正式支持的 encoded 调用。文档、Console 的高性能默认示例优先展示 BGR24，但 SDK 开发者可以根据传输字节、后端解码开销、CPU 和内存带宽选择 encoded 路径。

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

当前已经收口 raw-aware 图片矩阵读取 helper，统一给模型节点和 OpenCV 节点使用：

- encoded JPEG/PNG/BMP：继续 `cv2.imdecode`。
- raw `bgr24`：通过 `np.frombuffer(...).reshape(height, width, 3)` 获得 BGR matrix，不执行 decode。
- 节点只读时尽量使用 view；节点会修改像素时再 copy。
- helper 负责校验 shape、dtype、layout、pixel_format 和 bytes 长度。

不要让每个节点单独解析 BufferRef 或单独判断 BGR24，否则后续会再次出现行为分叉。

### 模型推理节点

YOLOX、YOLOv8、YOLO11、YOLO26、RF-DETR 的 detection、classification、segmentation、pose、obb 节点和 DeploymentInstance runtime 都应接入 raw-aware loader。当前主要 YOLO runtime IO、YOLOE 自定义节点图片入口、SAM3 单图/视频节点、SAHI 切片节点、deployment worker 输入 payload 透传、regions/ROI mask helper 和 video overlay helper 已切到 raw-aware loader；后续新增或调整的独立图片入口必须继续按同一 helper 接入，并补专项回归。

BGR24 输入下不应再走 `cv2.imdecode`。运行时指标可以把 encoded 输入的 `decode_ms` 与 raw 输入的 `raw_view_ms` 或等价指标分开记录。

模型 predictor 的 `input_image_bytes` 接受非空 buffer protocol 内容，包括 `bytes`、`bytearray` 和 `memoryview`。不能用 `isinstance(value, bytes)` 判断图片是否存在，否则 daemon direct mmap 返回的合法 `memoryview` 会被错误判定为缺少输入。

### 核心节点与自定义节点同步矩阵

| 节点范围 | 当前高速实现 | 禁止回退 |
| --- | --- | --- |
| Detection、Classification、Segmentation、Pose、OBB | 原样传递 BufferRef/FrameRef 到 inference mmap mailbox | 在 workflow worker 读取、编码或写 ObjectStore |
| SAHI Inference | 每个 raw 切片临时写入 LocalBufferBroker，推理返回后立即释放 lease | 每个切片通过 memory bytes 和持久化文件队列中转 |
| OpenCV、Barcode/QR、ROI、regions、video overlay | 共用 raw-aware matrix loader 和单次执行 decode cache | 各节点自行读取 object path 或重复 decode |
| YOLOE、SAM3 | 共用 `load_image_content`，buffer/frame 输入借用只读 mmap view | 先复制整帧 bytes 再进入预处理 |
| Camera/ZeroMQ/视频帧入口 | Camera/OpenCV 帧默认输出 raw memory image-ref，跨进程入口输出 BufferRef/FrameRef，并保留 shape、dtype、layout、pixel_format | 默认生成 base64 或临时 PNG |
| model-inference-submit 等异步任务提交节点 | 使用 storage ref 作为可恢复任务输入 | 把短生命周期 BufferRef 持久化进异步队列 |

storage 输入属于持久化任务边界。短期 mmap 引用不能跨服务重启或长队列等待，异步任务必须使用可恢复的 ObjectStore 引用；daemon 真正领取任务后才写入私有 LocalBuffer，模型子进程仍只读取 BufferRef/FrameRef。

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

需要保存文件或目录的 workflow 节点统一使用 `save_location`，并遵循双路径规则：

- 相对路径表示 ObjectStore 目录，例如 `workflow/roi` 会写入默认本地 ObjectStore 根目录下的 `workflow/roi`。
- 当前系统可解析的绝对路径表示本机文件系统目录，例如 Windows 的 `T:\temp\roi`；绝对路径不得伪装成 object key，也不得写入数据库中的 object key 字段。
- `Crop Export` 无论保存到哪一种目录，给后续节点的结果都继续使用 raw memory image-ref；落盘位置单独记录在每个图片结果的 `saved_output` 中，避免保存动作把后续推理链路降级为磁盘读取和重复解码。
- 系统绝对路径依赖 runtime 所在主机的挂载和权限。发布后的 Workflow App 与 Trigger 会在 runtime 主机上解释该路径，不在浏览器所在主机上解释。
- `save_location` 是节点保存接口的唯一公开参数。

OpenCV shared runtime、Barcode/QR runtime、SAM3/YOLOE 图片入口、图片预览与保存、regions/ROI/video overlay 和 ZeroMQ 示例均遵守同一规则：中间结果默认走 raw BGR24 memory image-ref，只在 JSON、预览和落盘边界编码。

### 高分辨率预览和交互取参

20MP、4K、8K 图片的性能优化只允许发生在前端显示边界，不能改变节点算法输入或正式 payload：

- `Image Preview`、节点卡片底部 `debug_preview` 和只读结果图可以生成显示图。显示图只用于前端快速查看，当前在图片超过 1920x1080 像素量或长边超过 1920px 时才缩放，display 图按最长边 1920px 等比例生成，横图、竖图和细长图都不能改变长宽比。
- `ImageViewer` 交互式参数面板必须使用原图坐标空间。ROI、找圆、找线、模板区域、手动点对和 Homography overlay 写回的参数必须对应原图像素，不能对应显示图像素。
- preview payload 需要保留原图元数据，例如 `source_width/source_height`、`source_media_type`、`source_object_key` 或等价 source image 引用；显示图元数据单独放在 `display_width/display_height` 或 `display_image` 中。
- 生产 runtime、WorkflowAppRuntime、TriggerSource、模型 DeploymentInstance 和节点间 image-ref 链路不得因为 preview 优化而产生缩略图中间结果。
- 交互式取参始终写回原图坐标；显示层优化不得改变正式节点输入和参数语义。

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

如果需要返回图片，应通过 workflow 图和 TriggerSource `result_bindings` 明确选择，并在前端和文档中标明这不是高帧率默认方式。不再使用“binding 不存在时返回全部 outputs”的 fallback。

以下结果返回矩阵是已接受但尚未实现的目标。当前可运行 ZeroMQ reply 仍只有单帧 JSON，当前代码也仍使用单个 `result_binding`；在 ADR-0007 和实施基线门禁全部完成前，不能把 `result_bindings`、`Image Encode`、统一 ZeroMQ 图片 attachments 或本机共享内存图片返回写成已交付 capability。

### 节点表示与 Trigger 传输分层

Workflow 节点决定结果语义和图片表示，Trigger adapter 只负责搬运：

| Workflow 公开输出 | 语义 |
| --- | --- |
| 图片直接连接 App Result | `image-ref.v1` 图片 attachment |
| 一组图片直接连接 App Result | `image-refs.v1` 多图片 attachments |
| 图片经过 `Image Base64 Encode` | `image-base64.v1` JSON |
| 图片经过 `Image Encode` | JPEG/PNG/BMP/WebP 等编码 `image-ref.v1` attachment |

直接 raw BGR24 输出保留 raw bytes、shape、dtype、layout 和 pixel format。adapter 不得为了方便传输而暗中编码 JPEG/PNG；需要编码时由图中的 `Image Encode` 明确完成。现有 `Image Body` 显式生成 `response-body.v1`，在 adapter capability 和容量允许时可以被 `result_bindings` 明确选择，但不会被 Trigger adapter 隐式插入或用作 transport 选择器。

`result_bindings` 可以同时选择普通 JSON、单图和多图。绑定类型由已发布 Workflow App Version 的公开输出契约确定，不递归扫描 `value.v1`、`workflow-result.v1`、node records 或调试 payload 中的嵌套临时 image-ref。需要同步返回的短期图片必须作为独立公开图片 binding。已选择的 JSON binding 出现嵌套 memory/buffer/frame ref 时返回 `ephemeral_image_ref_in_json_result`，不能自动提升为 attachment。

内部结果与公开 wire 结果分层：worker 生成协议中立的 `PreparedTriggerResult`，其中有序 logical attachments 通过 `payload_id` 引用按完整物理 representation identity 去重的 physical payloads；adapter 再映射为 `WorkflowTriggerResultV1`。checksum 只用于完整性校验，不能单独作为 lease 所有权或传输去重依据。公开 attachment locator 使用 `kind` discriminator：`local-buffer`、`zeromq-frame` 或 `object-store`。attachment 顺序固定为 `result_bindings` 顺序，再按 `image-refs.v1.items` 顺序；`source_image` 不自动加入。同一完整物理 identity 被多个 binding/item 选择时只 handoff、校验、发送和释放一次。

### 各 Trigger 的结果数据面

| Trigger | JSON | 直接图片 |
| --- | --- | --- |
| `local-shared-memory` sync | Workflow Trigger mailbox inline/page-chain | LocalBuffer BufferRef；结果对象持有 reader guard 到 Dispose 后 ACK |
| ZeroMQ Trigger Result v1 | Frame 0 JSON manifest | Frame 1 到 N 唯一 physical payload；无图片时 N=0 |
| PLC/IO/MQTT/目录/定时 `event-only` | 丢弃 | 丢弃，不 handoff |
| `accepted-then-query` | 状态和 run id | 稳定 ObjectStore locator 查询；临时图片先持久化，或显式丢弃 |

图中显式生成的 `image-base64.v1` 属于结构化 JSON：本机共享内存 Trigger 可以通过 inline/page-chain 返回，但受默认 32 MiB 单响应上限约束。它不是 inference mailbox 图片通道，也不是本机高性能默认路径；超限时明确拒绝，不自动切换 LocalBuffer、文件、队列或其他协议。

ZeroMQ 只使用一个 `amvision.workflow-trigger-result.v1`。Frame 0 manifest 记录状态、结构化结果、统一 error，以及 logical attachment 到唯一 physical payload/frame 的映射；Frame 1 到 N 保存唯一图片 payload bytes。多个逻辑 attachment 可以共享同一 frame index。没有图片时 `attachments=[]` 且消息自然只有 Frame 0，不形成另一种协议。raw 输出传 raw bytes，显式编码输出传对应 JPEG/PNG 等 bytes，Base64 输出只留在 JSON 中。ZeroMQ 仍保留整图协议复制，性能低于本机共享内存 Trigger。

ZeroMQ adapter 为每个唯一 physical payload 创建 tracked `zmq.Frame`。发送 Frame 0 前必须为整个响应预留 adapter 进程内有界 transport-lifetime registry 容量，并取得所有 reader guard/ObjectStore read snapshot；满载时返回 `zeromq_transport_capacity_exhausted`，不发送部分 multipart。发送失败时先停止监听并以 `linger=0` 关闭 socket，再等待已登记 tracker；仍未完成的 Frame、tracker、view/snapshot 和 guard 继续由 adapter registry 持有，lease 进入 ACTIVE → REVOKING → QUARANTINED/FREE 回收链。LocalBufferBroker 不管理 libzmq tracker，只按 adapter 条件释放、OS guard、deadline 和 receipt 管理 lease。发送还受 reply deadline、`SNDTIMEO`、最大 JSON、单物理 payload、逻辑 attachment 数、物理 frame 数和总响应容量约束。

TriggerSource 和 SDK 配置包不增加 reply protocol 或 JSON/multipart mode。SDK 始终读取完整 multipart message，并拒绝 manifest 未声明的额外帧、缺少物理帧、越界索引、长度或 checksum 错误；多个 logical attachment 合法共享同一 frame index。成功与失败共用同一 result schema，不保留独立 ZeroMQ error envelope。

不支持同步结果的 Trigger 通过固定 `result_mode=event-only` 丢弃输出，不在每次调用中临时猜测。同步 adapter 不支持已选择的图片 binding 时拒绝配置；不需要的 binding 直接不选择，不增加 discard 开关。顶层 `result_mode`、`reply_timeout_seconds` 和 `ack_policy` 是唯一事实源，`result_mapping` 只保存有序 `result_bindings`。响应计划在创建、enable、Runtime 切版和实际调用前按 route/contract/capability fingerprint 固定，使 worker 能在 cleanup 前完成所需 handoff。

已经接受但尚未实现的 `local-shared-memory` Trigger 会正式支持把公开输出中的 LocalBuffer 图片引用返回给同机 SDK。公开 BufferRef 只负责定位；服务端私有 `LeaseOwnershipReceipt` 保存 pool、expected owner、epoch、generation、deadline 和 guard identity。WorkflowRun 建立并取得真实 Runtime/执行器 permit 后、worker submit 前，输入必须显式从 `workflow-trigger-write` transfer 到 `workflow-runtime`，每个失败点按当时 receipt 补偿回收。

该能力不能在 Workflow Run 结束时直接释放图片 lease；worker 必须在自身 cleanup 前完成来源规范化。当前 Run receipt 对应的 BufferRef 可零复制 handoff，foreign/incomplete BufferRef、memory handle 和 FrameRef 按固定规则复制。storage/local-path 根据目标交付处理：本机 LocalBuffer 返回时物化 output lease；只有具备不可变 version、checksum、准确长度和 media type 的 ObjectStore 结果可以直接返回 locator；临时对象或绝对路径必须复制到受控 LocalBuffer、adapter 自有不可变 bytes 或新的不可变受管理对象。ZeroMQ 从 ObjectStore 发送时持有 `open_read_snapshot()` 到 tracker 完成。整批输出在 RESPONSE 前 transfer 到 `delivery_kind + response_id` owner。local-shared-memory 的 reader guard 由 SDK 结果对象保持到 `Dispose`/`DisposeAsync`，先使 view 失效并释放全部 guard，再发布 ACK；JSON-only 或 SDK-owned copy 可以提前 ACK。详细边界见 [ADR-0007](../../decisions/ADR-0007-local-shared-memory-workflow-trigger.md) 和[实施基线](../../development/local-shared-memory-trigger-implementation.md)。

同一 TriggerSource 的单在途 permit 覆盖完整交付：local-shared-memory 到 Dispose/ACK、取消或 deadline 后的安全回收，ZeroMQ 到所有已提交 physical frame tracker 完成，或未完成资源已由发送前预留的 adapter transport registry 持续承担责任。Runtime token 可以在图执行和 handoff 后释放。包含临时 attachment 的幂等结果不重放旧引用；重复请求返回 `idempotent_attachment_result_not_replayable` 和原 run id。只有 JSON-only 或已经 ObjectStore 持久化的稳定结果可重放/查询。

## 运行记录和诊断开关

高帧率 Trigger 不应每帧都走完整 WorkflowRun 持久化和完整 diagnostics 返回。当前执行元数据使用以下字段控制：

- `workflow_run_record_mode=full`：完整记录，保留 dispatch/final 事件，并按 retention 开关保留 input、outputs 和 node_records。
- `workflow_run_record_mode=minimal`：高速触发默认值；同步调用完成后只写一条轻量 WorkflowRun 状态记录。普通 minimal 会保留公开 outputs；ZeroMQ 高速图片入口同时设置 `retain_input_payload_enabled=false` 和 `retain_outputs_enabled=false`，因此不持久化输入、输出、template_outputs 和 node_records，结果直接通过当前同步 reply 返回。
- `workflow_run_record_mode=none`：同步调用不写 WorkflowRun 数据库记录，仅返回当前调用结果；不适用于 async run。
- `return_timing_metadata_enabled=false`：生产默认值；关闭外层 `metadata.timings`，同时清理模型节点业务输出里的 `metadata.timings`。
- `return_node_timings_enabled=false`：生产默认值；关闭 `metadata.node_timings`。

前端设置位置：

- Workflow App 详情页的 Runtime 栏：设置新建 WorkflowAppRuntime 的默认记录模式和诊断返回策略。
- 集成页 TriggerSource 的高级设置：按触发入口覆盖记录模式和诊断返回策略；ZeroMQ 图片触发默认 `minimal + 不返回诊断数据`。

调试性能时再临时打开 `return_timing_metadata_enabled` 和 `return_node_timings_enabled`。需要历史事件、节点输入输出或完整追踪时，再把 `workflow_run_record_mode` 调整为 `full`，并打开 `retain_trace_enabled`、`retain_node_records_enabled` 和非 `none` 的 `trace_level`。

## 并发边界

当前 ZeroMQ SDK 和后端 adapter 的基本形态是 REQ/REP：

- 一个 `AmvisionTriggerClient` 复用一个 socket，适合单调用链顺序请求。
- 一个 TriggerSource adapter 使用 REP socket 时天然串行处理请求。
- 当前 WorkflowAppRuntime worker 内部仍有运行锁，单 runtime 默认一次处理一个 run。
- 模型 DeploymentInstance 可以配置多实例，但 workflow app trigger 不会自动把一个 runtime 的请求并行分发到多个 workflow worker。

因此，高并发高帧率不能通过给同一个 runtime 增加 Trigger 自动获得。需要扩展并发时，必须明确选择并实现以下一种拓扑：

- 多个 TriggerSource endpoint + 多个 WorkflowAppRuntime worker，按产线、相机或工位分片。
- ZeroMQ ROUTER/DEALER + worker pool。
- WorkflowAppRuntime 多 worker 实例和内部队列。
- 连续帧场景使用 LocalBufferBroker ring channel，并明确 latest、strict、drop-oldest、drop-newest 或 block-with-timeout 策略。

## 性能观测字段

高性能链路应补齐以下观测：

- SDK：获得输入图片后到发送前的 copy/convert 时间、send 等待时间、reply 等待时间。
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
- TriggerSource 默认 `result_bindings` 只选择小 JSON，不默认返回 inline-base64 或图片 attachment。
- 1080p、4K、20MP 图片都有端到端 fixture 或 smoke 测试，至少覆盖 SDK envelope、adapter 写入、workflow 节点读取和模型节点推理。
- 文档、Postman 示例和 Console 默认调用明确区分“高性能默认 BGR24 image-ref 路径”和“正式支持但需要首次解码的 encoded 路径”。

## 相关文档

- [docs/architecture/platform/local-buffer-broker.md](local-buffer-broker.md)
- [docs/architecture/workflows/runtime.md](../workflows/runtime.md)
- [docs/architecture/workflows/node-system.md](../workflows/node-system.md)
- [docs/api/workflow-trigger-sources.md](../../api/workflow-trigger-sources.md)
- [docs/api/workflow-sdks.md](../../api/workflow-sdks.md)
- [docs/api/examples/workflows/README.md](../../api/examples/workflows/README.md)
- [sdks/dotnet/README.md](../../../sdks/dotnet/README.md)
