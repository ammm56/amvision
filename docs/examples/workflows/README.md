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

## 视频与跟踪样例

- `sam3_video_memory_attention_review.template.json`
- `sam3_video_memory_attention_review.application.json`

该样例面向现场本地视频，链路固定为：

- `video-load-local`
- `video-decode-frames`
- `custom.sam3.video-interactive-segment`
- `tracks-filter`
- `video-overlay-render`
- `video-save`
- `video-body`

输入约定：

- `request_video_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-a/review.mp4"}`
- `request_prompts`：`prompt-regions.v1`
  - 直接传 `box / point / polygon / mask`

输出约定：

- `preview_body`：`response-body.v1`
- `tracks`：`tracks.v1`
- `summary`：`value.v1`

样例默认参数：

- `tracking_mode = memory-attention-tracker`
- `history_limit = 6`
- `prototype_momentum = 0.72`
- `attention_temperature = 0.12`
- `prototype_blend_weight = 0.35`
- `max_memory_tokens_per_entry = 256`

推荐使用方式：

- 复杂遮挡、长窗口、大位移、多目标复盘，直接用这套样例
- 简单任务先把 `tracking_mode` 改成 `memory-prototype-state`
- 更轻场景再继续降到 `stateful-mask-propagation` 或 `shared-prompts-across-window`

## 工业单帧规则样例

- `industrial_single_frame_sealant_quality_gate.template.json`
- `industrial_single_frame_sealant_quality_gate.application.json`
- `industrial_single_frame_glue_roi_callback.template.json`
- `industrial_single_frame_glue_roi_callback.application.json`

这两组样例都聚焦“单图输入 -> 规则判定 -> `process-decision` -> 结果回传”，不把相机、PLC 或特定模型耦合进模板本体。默认假设上游模型或外部系统已经产出 `regions.v1`，当前模板专注于工业规则和现场结果链。

### industrial_single_frame_sealant_quality_gate

链路固定为：

- `template-input.value`
- `image-load-local`
- `regions-filter`
- `regions-area-ratio`
- `region-continuity-score`
- `region-gap-check`
- `presence-check`
- `range-check`
- `process-decision`
- `alarm-condition`
- `json-save-local`
- `csv-append-local`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-a/frame-001.png"}`
- `request_regions`：`regions.v1`
  - 由上游检测/分割节点或外部系统提供

输出约定：

- `inspection_result`：`result-record.v1`
- `inspection_alarm`：`alarm-record.v1`
- `decision_summary`：`value.v1`
- `json_summary`：`value.v1`
- `csv_summary`：`value.v1`

适用场景：

- 密封胶/胶线单帧质量门
- 需要同时看数量、面积占比和连续性
- 现场先做本地 JSON/CSV 归档，不急着接外部回调

### industrial_single_frame_glue_roi_callback

链路固定为：

- `template-input.value`
- `image-load-local`
- `regions-filter`
- `roi-create`
- `regions-coverage-check`
- `regions-offset-check`
- `regions-intersection-metrics`
- `process-decision`
- `alarm-condition`
- `json-save-local`
- `csv-append-local`
- `http-post`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-b/frame-021.png"}`
- `request_regions`：`regions.v1`
  - 由上游检测/分割节点或外部系统提供

输出约定：

- `inspection_result`：`result-record.v1`
- `inspection_alarm`：`alarm-record.v1`
- `decision_summary`：`value.v1`
- `json_summary`：`value.v1`
- `csv_summary`：`value.v1`
- `callback_response`：`value.v1`

注意事项：

- 模板里的 `roi-create` 默认写的是固定工位 ROI，现场落地时通常需要先按设备画面尺寸调整 `bbox_xyxy`
- `http-post.url` 当前是示例回调地址，导入后应先改成现场真实接口，再执行
