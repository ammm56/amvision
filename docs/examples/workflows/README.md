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

## USB / UVC 相机样例

- `camera_usb_uvc_enumerate_capture_preview.template.json`
- `camera_usb_uvc_enumerate_capture_preview.application.json`
- `camera_usb_uvc_session_single_frame_review.template.json`
- `camera_usb_uvc_session_single_frame_review.application.json`
- `camera_usb_uvc_stream_window_preview.template.json`
- `camera_usb_uvc_stream_window_preview.application.json`

这三组样例面向 `custom.camera.usb.*` 这批节点的第一轮现场调试，不直接耦合检测模型或工业规则链，而是先把“能枚举、能抓图、能调参、能读窗口、能预览”这条相机主线单独收稳。

### camera_usb_uvc_enumerate_capture_preview

链路固定为：

- `template-input.value(request_camera_config)`
- `custom.camera.usb.enumerate-devices`
- `custom.camera.usb.capture-frame`
- `image-body`

输入约定：

- `request_camera_config`：`value.v1`
  - 示例：`{"value":{"device_index":0,"device_count":4,"backend_preference":"msmf","width":1280,"height":720,"output_format":"png"}}`

输出约定：

- `enumeration_result`：`value.v1`
- `captured_image`：`image-ref.v1`
- `preview_body`：`response-body.v1`
- `capture_summary`：`value.v1`

适用场景：

- 首次确认当前机器是否能看到 USB / UVC 相机
- 需要一条 checked-in 的“枚举 -> 单帧直采 -> 预览”最短链路
- 现场先排查 backend、分辨率和抓图是否正常，还不准备进入会话调参

注意事项：

- 该样例把同一份 `request_camera_config` 同时喂给 `enumerate-devices` 和 `capture-frame`；两边只会读取自己需要的字段，额外字段会被忽略
- 如果现场只想快速看一眼是否能出图，保留默认参数即可；如果需要固定 backend，优先改 `backend_preference`

### camera_usb_uvc_session_single_frame_review

链路固定为：

- `template-input.value(request_session_config)`
- `custom.camera.usb.open-device`
- `custom.camera.usb.set-parameter`
- `custom.camera.usb.get-parameter`
- `custom.camera.usb.read-latest-frame`
- `image-body`
- `custom.camera.usb.close-device`

输入约定：

- `request_session_config`：`value.v1`
  - 示例：`{"value":{"device_index":0,"backend_preference":"msmf","width":1280,"height":720,"fps":30.0,"output_format":"png"}}`
- `request_set_parameters`：`value.v1`
  - 可选；示例：`{"value":{"parameter_values":{"width":1920,"height":1080,"fps":10.0},"verify_after_set":true}}`
- `request_parameter_query`：`value.v1`
  - 可选；示例：`{"value":{"parameter_names":["width","height","fps","backend_name","requested_width","requested_height","requested_fps"]}}`

输出约定：

- `open_session_summary`：`value.v1`
- `set_result`：`value.v1`
- `parameter_result`：`value.v1`
- `captured_image`：`image-ref.v1`
- `preview_body`：`response-body.v1`
- `capture_summary`：`value.v1`
- `close_result`：`value.v1`

适用场景：

- 现场需要先固定分辨率、帧率，再验证会话型单帧重复采图
- 想看“请求参数”和“当前观测参数”是否一致
- 需要一条 checked-in 的“open -> set/get -> read -> close”正式模板

注意事项：

- `request_set_parameters` 和 `request_parameter_query` 当前都是可选；不传时会回退到模板内默认参数
- `read-latest-frame` 会沿用 `request_session_config` 里的读帧相关字段，因此同一个请求体里可以同时写 `device_index`、`fps` 和 `output_format`
- 这条样例更适合排查会话边界、参数写入和单帧稳定性，不适合长时间连续采流

### camera_usb_uvc_stream_window_preview

链路固定为：

- `custom.camera.usb.open-device`
- `template-input.value(request_stream_config)`
- `custom.camera.usb.start-stream`
- `custom.camera.usb.get-parameter`
- `custom.camera.usb.read-window`
- `frame-window-preview`
- `custom.camera.usb.close-device`

输入约定：

- `request_session_config`：`value.v1`
  - 示例：`{"value":{"device_index":0,"backend_preference":"msmf","width":1280,"height":720,"fps":15.0}}`
- `request_stream_config`：`value.v1`
  - 示例：`{"value":{"buffer_capacity":12,"target_fps":10.0,"max_frames":6,"wait_for_min_frames":3,"wait_timeout_seconds":1.0,"sample_mode":"uniform"}}`

输出约定：

- `open_session_summary`：`value.v1`
- `stream_start_summary`：`value.v1`
- `stream_state`：`value.v1`
- `frames`：`frame-window.v1`
- `preview_body`：`response-body.v1`
- `window_summary`：`value.v1`
- `close_result`：`value.v1`

适用场景：

- 需要先验证后台采流线程、缓冲和 `frame-window.v1` 是否正常
- 想把 USB / UVC 相机直接接到现有多帧预览、SAM3 视频分割或后续视频链
- 需要一条 checked-in 的“open -> start-stream -> read-window -> preview -> close”正式模板

注意事项：

- `get-parameter` 当前会显式读出 `stream_active / stream_buffer_count / stream_last_frame_index` 这些流状态字段，便于现场判断流线程是否真的在跑
- 该样例输出的是 `frame-window.v1` 和 gallery-preview body，不会自动保存视频文件；如果现场后续要进视频归档，可继续接 `video-save`
- `request_stream_config` 当前是必填，是为了把 `start-stream` 和 `read-window` 这两层运行时参数显式暴露出来；如果只想沿用模板默认值，可传 `{"value":{}}`

## PLC / Modbus 等待样例

- `plc_modbus_wait_status_word_ready_mask.template.json`
- `plc_modbus_wait_status_word_ready_mask.application.json`
- `plc_modbus_wait_status_word_alarm_mask.template.json`
- `plc_modbus_wait_status_word_alarm_mask.application.json`
- `plc_modbus_wait_ready_ack_callback.template.json`
- `plc_modbus_wait_ready_ack_callback.application.json`

这三组样例聚焦 `custom.plc.modbus.wait-condition` 的现场用法，前两组默认都走状态字地址语义：

- `ready_mask`：用 `bitmask_all_set` 等待全部 ready 位都置位
- `alarm_mask`：用 `bitmask_any_set` 等待任一报警位命中
- `ready_ack_callback`：先等待 ready，再写入 ack，最后把统一 `result-record` 回传到 HTTP 接口

输入约定：

- `request_wait_config`：`value.v1`
  - 示例：
    `{"value":{"host":"192.168.10.20","unit_id":1,"register_address":"400101","data_type":"uint16","expected_value":5}}`

输出约定：

- `wait_result`：`value.v1`
- `archive`：`value.v1`
- `json_summary`：`value.v1`

推荐使用方式：

- 现场已有 PLC 地址表时，直接改 `register_address`
- 状态字位定义已知时，直接改 `expected_value`
- 需要更稳放行时，提高 `stable_match_count`
- `wait_timeout_seconds = null` 表示无限等待；当前 checked-in 样例默认就用这套语义
- 如果只是调试链路或想避免长时间阻塞，把 `wait_timeout_seconds` 改回显式秒数

现场选择建议：

| 使用方式 | 参数设置 | 适用场景 | 注意事项 |
| --- | --- | --- | --- |
| 有限等待 | `wait_timeout_seconds = 5 ~ 300` 这类显式秒数 | 调试联机、设备应答本来就应在有限时间内完成、需要快速失败并报警的工位 | 最适合首轮联调和排障；超时后 workflow 会直接报错，便于外层收集异常 |
| 无限等待 | `wait_timeout_seconds = null` | 产线节拍不固定、需要等上游设备放行、人工上料或换型确认这类“等到条件满足再继续”的场景 | 当前节点会一直阻塞到条件满足，更适合单次调用里的现场等待；不适合作为长期后台守护 |
| 未来 TriggerSource | 不再由普通 workflow 节点参数控制 | 需要常驻监听 PLC 位、状态字、上升沿事件，再自动触发后续 workflow 的场景 | 这类需求后续应放到 `trigger-source` 类实现，和当前 `wait-condition` 区分开，避免把普通流程节点变成常驻轮询器 |

### plc_modbus_wait_ready_ack_callback

链路固定为：

- `template-input.value(request_wait_config)`
- `template-input.value(request_ack_write_config)`
- `custom.plc.modbus.wait-condition`
- `custom.plc.modbus.write-value`
- `core.rule.ok-ng-decision`
- `core.output.result-record`
- `core.output.http-post`

输入约定：

- `request_wait_config`：`value.v1`
  - 示例：`{"value":{"host":"192.168.10.20","unit_id":1,"register_address":"400101","data_type":"uint16","expected_value":5}}`
- `request_ack_write_config`：`value.v1`
  - 示例：`{"value":{"host":"192.168.10.20","unit_id":1,"register_address":"00021","data_type":"bool","value":true}}`

输出约定：

- `wait_result`：`value.v1`
- `ack_write_result`：`value.v1`
- `inspection_result`：`result-record.v1`
- `decision_summary`：`value.v1`
- `callback_response`：`value.v1`

适用场景：

- 上游 PLC 或工站先给 ready 状态字，当前流程等到满足后再写一个 ack 位
- 需要把一次握手闭环收成统一 `result-record`，再回传给 MES、上位机或现场服务
- 希望保留有限等待语义，ready 长时间不到就让 workflow 直接失败并交给外层报警

注意事项：

- 该样例默认使用 `wait_timeout_seconds = 60.0`，用于演示“有限等待 + 成功回传”这类更贴现场的闭环；如果现场更适合一直等放行，可改成 `null`
- `write-value` 默认写的是 `00021` 的 `bool = true` 确认位；如果现场要求写 holding register 或不同数据类型，直接改 `request_ack_write_config`
- `build_ack_write_request` 会把 `wait_result` 注入写入请求对象里的 `wait_context` 字段，主要作用是显式建立“先等后写”的执行依赖，同时便于后续排障追踪
- `http-post.url` 当前是示例回调地址，导入后应先改成现场真实接口，再执行

## PLC TriggerSource 回传样例

- `plc_register_modbus_tcp_async_result_record.template.json`
- `plc_register_modbus_tcp_async_result_record.application.json`

这组样例聚焦 `plc-register` TriggerSource 的正式使用面，不再让 workflow 内节点自己轮询 PLC：

- TriggerSource 负责 `modbus-tcp + polling + match_rule + async submit`
- workflow app 只接收标准化后的寄存器事件
- 图内把事件收成 `result-record`，再通过 `http-post` 回传到现场系统

### plc_register_modbus_tcp_async_result_record

链路固定为：

- `payload-to-value(request_trigger_payload)`
- `payload-to-value(request_trigger_event)`
- `value-field-extract`
- `compare`
- `ok-ng-decision`
- `alarm-condition`
- `result-record`
- `http-post`

输入约定：

- `request_trigger_payload`：`response-body.v1`
  - 来自 `plc-register` 的 `payload`
  - 示例：`{"matched":true,"observed_value":5,"register_address":"400101","sequence_id":12}`
- `request_trigger_event`：`response-body.v1`
  - 来自标准化后的 `event`
  - 示例：`{"trigger_source_id":"plc-trigger-source-08","event_id":"plc-line-a-event-000012","occurred_at":"2026-06-09T09:00:00Z"}`

输出约定：

- `inspection_result`：`result-record.v1`
- `inspection_alarm`：`alarm-record.v1`
- `decision_summary`：`value.v1`
- `callback_response`：`value.v1`

适用场景：

- PLC 位或状态字命中后，直接触发一条正式 workflow，再把结果回传给 MES、上位机或现场服务
- 希望把 TriggerSource 的轮询职责和 workflow 图内的业务处理职责明确拆开
- 需要一条 checked-in 的 `plc-register -> workflow app runtime -> result-record -> http-post` 正式样例

注意事项：

- 这条样例当前故意把两个输入都定义成 `response-body.v1`，再在图内用 `payload-to-value` 显式桥接；原因是 TriggerSource 的 `input_binding_mapping` 当前只负责读取原始 `payload / event` 对象，不会自动包成 `value.v1`
- 如果后续 TriggerSource 层补了“按目标 payload_type_id 自动包装”的能力，这条样例可以再收敛回直接使用 `value.v1` 输入
- `http-post.url` 当前是示例回调地址，导入后应先改成现场真实接口，再执行

## 工业单帧规则样例

- `industrial_single_frame_sealant_quality_gate.template.json`
- `industrial_single_frame_sealant_quality_gate.application.json`
- `industrial_single_frame_segments_continuity_gate.template.json`
- `industrial_single_frame_segments_continuity_gate.application.json`
- `industrial_single_frame_glue_roi_callback.template.json`
- `industrial_single_frame_glue_roi_callback.application.json`
- `industrial_single_frame_glue_polygon_roi_changeover.template.json`
- `industrial_single_frame_glue_polygon_roi_changeover.application.json`
- `industrial_single_frame_regions_overlay_review.template.json`
- `industrial_single_frame_regions_overlay_review.application.json`
- `industrial_single_frame_yoloe_text_overlay_review.template.json`
- `industrial_single_frame_yoloe_text_overlay_review.application.json`
- `industrial_single_frame_yoloe_visual_overlay_review.template.json`
- `industrial_single_frame_yoloe_visual_overlay_review.application.json`
- `industrial_single_frame_yolox_position_gate.template.json`
- `industrial_single_frame_yolox_position_gate.application.json`
- `industrial_single_frame_line_pair_measure_gate.template.json`
- `industrial_single_frame_line_pair_measure_gate.application.json`
- `industrial_single_frame_circle_concentricity_gate.template.json`
- `industrial_single_frame_circle_concentricity_gate.application.json`
- `industrial_single_frame_segments_overlay_review.template.json`
- `industrial_single_frame_segments_overlay_review.application.json`
- `industrial_single_frame_sam3_semantic_overlay_review.template.json`
- `industrial_single_frame_sam3_semantic_overlay_review.application.json`
- `industrial_single_frame_sam3_interactive_overlay_review.template.json`
- `industrial_single_frame_sam3_interactive_overlay_review.application.json`
- `industrial_local_directory_batch_input.template.json`
- `industrial_local_directory_batch_input.application.json`
- `industrial_local_directory_batch_segments_continuity_gate.template.json`
- `industrial_local_directory_batch_segments_continuity_gate.application.json`
- `industrial_local_directory_batch_regions_continuity_gate.template.json`
- `industrial_local_directory_batch_regions_continuity_gate.application.json`
- `industrial_local_directory_batch_yolox_position_gate.template.json`
- `industrial_local_directory_batch_yolox_position_gate.application.json`
- `industrial_local_directory_watch_yolox_position_gate.template.json`
- `industrial_local_directory_watch_yolox_position_gate.application.json`
- `industrial_local_directory_polling_cursor_guard.template.json`
- `industrial_local_directory_polling_cursor_guard.application.json`

前两组样例聚焦“单图输入 -> 规则判定 -> `process-decision` -> 结果回传”，不把相机、PLC 或特定模型耦合进模板本体。`industrial_single_frame_segments_continuity_gate` 则把“分割输出 -> `segments.v1` -> `regions.v1` -> 工业规则链”这层也一起接通；`industrial_single_frame_regions_overlay_review` 与 `industrial_single_frame_segments_overlay_review` 进一步把 `draw-roi / mask-overlay` 这层 checked-in，分别覆盖“上游已是标准 `regions.v1`”和“上游仍是 `segments.v1` 需要先桥接”的两种现场复核入口；`industrial_single_frame_yoloe_text_overlay_review`、`industrial_single_frame_yoloe_visual_overlay_review`、`industrial_single_frame_sam3_semantic_overlay_review` 与 `industrial_single_frame_sam3_interactive_overlay_review` 则继续把这条 overlay 复核链直接前移到 YOLOE / SAM3 节点本身，分别覆盖“文本开放词汇检测”“视觉提示检测”“文本语义分割”和“交互分割”四类本项目自带上游；`industrial_single_frame_yolox_position_gate` 对应把“检测输出 -> `detections.v1` -> `regions.v1` -> 工业规则链”这层接通；`industrial_single_frame_glue_polygon_roi_changeover` 进一步演示多边形 ROI 的换型和现场回调；`industrial_single_frame_line_pair_measure_gate` 与 `industrial_single_frame_circle_concentricity_gate` 则把传统 OpenCV 几何量测这层收成 checked-in 现场模板，分别覆盖双边线槽宽/平行度和双圆孔径/同心度/圆度；`industrial_local_directory_batch_input` 把本地文件夹小批量输入这层单独收成可复用模板；`industrial_local_directory_batch_segments_continuity_gate` 与 `industrial_local_directory_batch_regions_continuity_gate` 则把“目录批次 -> 分割/区域结果 -> 连续性规则链 -> CSV / JSON 归档”两类上游入口接到同一套批次骨架；`industrial_local_directory_batch_yolox_position_gate` 继续把这条目录批次输入主线真正接到“逐图检测 -> 规则判定 -> CSV 持续归档 -> 批次 JSON 汇总”的现场闭环；`industrial_local_directory_watch_yolox_position_gate` 再把 `directory-watch` TriggerSource 标准化后的 `payload / event` 直接接进同一条检测与规则批次骨架，覆盖“目录变化触发 -> 批次检测 -> 结构化归档 / 回传”这类更贴现场守护式接入；`industrial_local_directory_polling_cursor_guard` 则把“目录轮询守护 / cursor 落盘恢复 / 批次归档 JSON”这层独立收成可复用状态模板。

上游 `regions.v1` 的典型来源：

- `custom.yoloe.*` 的 `prompt-free-detect / text-prompt-detect / visual-prompt-detect` 输出端口
- `custom.sam3.*` 的 `interactive-segment / semantic-segment` 输出端口
- `core.vision.segments-to-regions`，把外部或中间节点输出的 `segments.v1(mask / polygon / bbox)` 规整回 `regions.v1`
- 视频链里的 `core.vision.tracks-to-regions`，把 `tracks.v1` 拆回单帧 `regions.v1`
- 外部系统直接按标准 `regions.v1` 合同提交

当前已发布 deployment detection 主链默认输出的是 `detections.v1`；如果现场规则链消费的是 `regions.v1`，当前推荐先接 `core.vision.detections-to-regions` 再进入工业规则节点。

如果上游拿到的是分割结果而不是 bbox 检测，当前推荐直接使用 `regions.v1`；只有在上游结果仍是独立 `mask / polygon / bbox` 组合、还没有收成 `regions.v1` 时，才需要先接 `core.vision.segments-to-regions`。

如果现场当前主要需求不是“直接出规则门限”，而是“先把区域和 ROI 依据画出来给工艺或设备人员复核”，当前推荐优先使用 `industrial_single_frame_regions_overlay_review` 或 `industrial_single_frame_segments_overlay_review` 这两条 overlay 样例，再按现场需要继续接 JSON/CSV/HTTP 回传。

如果现场已经明确要直接走本项目自带的开放词汇模型或分割模型，而不是先由外部系统喂 `regions.v1 / segments.v1`，当前推荐优先使用 `industrial_single_frame_yoloe_text_overlay_review`、`industrial_single_frame_yoloe_visual_overlay_review`、`industrial_single_frame_sam3_semantic_overlay_review` 或 `industrial_single_frame_sam3_interactive_overlay_review`，按实际提示类型选择即可。

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

### industrial_single_frame_segments_continuity_gate

链路固定为：

- `template-input.value`
- `image-load-local`
- `segments-to-regions`
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
  - 示例：`{"value":"D:/cases/line-seg/frame-015.png"}`
- `request_segments`：`segments.v1`
  - 由上游分割模型、外部系统或中间 mask 处理节点提供
  - 每个 segment 当前至少应包含 `mask_image`、`polygon_xy` 或 `bbox_xyxy` 之一

输出约定：

- `normalized_regions`：`regions.v1`
- `inspection_result`：`result-record.v1`
- `inspection_alarm`：`alarm-record.v1`
- `decision_summary`：`value.v1`
- `json_summary`：`value.v1`
- `csv_summary`：`value.v1`

适用场景：

- 胶线、涂层、焊缝等分割结果需要进一步做面积占比和连续性判定
- 上游拿到的是 `mask / polygon / bbox` 分割结果，还没有先规整成 `regions.v1`
- 需要一条 checked-in 的“分割输出 -> 工业规则链”正式样例

注意事项：

- 该样例会先把 `segments.v1` 统一桥接为 `regions.v1`，再进入现有连续性规则链；这是当前分割结果接工业规则的推荐接法
- 模板里显式把 `load_image.image` 接到 `segments-to-regions.image`，这样即使上游 `segments.v1` 本身未附带 `source_image`，桥接后的 `regions.v1` 也会带上来源图像
- 如果上游已经直接给出标准 `regions.v1`，则更适合直接复用 `industrial_single_frame_sealant_quality_gate`

### industrial_single_frame_regions_overlay_review

链路固定为：

- `template-input.value`
- `image-load-local`
- `regions-filter`
- `roi-create`
- `draw-roi`
- `mask-overlay`
- `presence-check`
- `regions-inside-check`
- `process-decision`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/review/frame-031.png"}`
- `request_regions`：`regions.v1`
  - 适合直接接 YOLOE、SAM3 或外部系统已经标准化好的区域结果
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内默认多边形 ROI

输出约定：

- `filtered_regions`：`regions.v1`
- `effective_roi`：`roi.v1`
- `review_overlay_image`：`image-ref.v1`
- `inspection_result`：`result-record.v1`
- `decision_summary`：`value.v1`

适用场景：

- 上游已经直接输出标准 `regions.v1`
- 现场需要先把 ROI 和区域叠加回原图，再做最小 OK/NG 复核
- 需要把 overlay 图直接挂进 `result-record`，给人工复核或外部系统继续使用

注意事项：

- 这条样例会把 `mask-overlay.image` 直接接到 `process-decision.image`，所以输出的 `inspection_result` 会携带最终复核图引用
- 该样例默认使用多边形 ROI，更适合不规则工位或换型边界复核

### industrial_single_frame_segments_overlay_review

链路固定为：

- `template-input.value`
- `image-load-local`
- `segments-to-regions`
- `regions-filter`
- `roi-create`
- `draw-roi`
- `mask-overlay`
- `presence-check`
- `regions-coverage-check`
- `process-decision`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/review/frame-seg-012.png"}`
- `request_segments`：`segments.v1`
  - 适合上游仍输出 `mask / polygon / bbox` 分割结果、还未先规整成 `regions.v1` 的场景
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内默认矩形 ROI

输出约定：

- `normalized_regions`：`regions.v1`
- `effective_roi`：`roi.v1`
- `review_overlay_image`：`image-ref.v1`
- `inspection_result`：`result-record.v1`
- `decision_summary`：`value.v1`

适用场景：

- SAM3、YOLOE 分割链或外部分割模块先给出 `segments.v1`
- 需要先桥接成标准 `regions.v1`，再统一复核和挂接工业规则链
- 需要一条 checked-in 的“segments -> overlay -> result-record” 现场模板

注意事项：

- 模板里显式把 `load_image.image` 接到 `segments-to-regions.image`，这样标准化后的 `regions.v1` 会带上来源图像
- 这条样例默认用矩形 ROI + coverage 作为最小复核语义，现场也可以继续替换成 inside/offset 或更完整的规则链

### industrial_single_frame_yoloe_text_overlay_review

链路固定为：

- `template-input.value`
- `image-load-local`
- `custom.yoloe.text-prompt-detect`
- `regions-filter`
- `roi-create`
- `draw-roi`
- `mask-overlay`
- `presence-check`
- `regions-inside-check`
- `process-decision`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/yoloe/frame-021.png"}`
- `request_prompts`：`text-prompts.v1`
  - 示例：`{"items":[{"prompt_id":"target","display_name":"Target","text":"glue bead"}]}`
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内默认多边形 ROI

输出约定：

- `model_detections`：`detections.v1`
- `model_regions`：`regions.v1`
- `filtered_regions`：`regions.v1`
- `effective_roi`：`roi.v1`
- `review_overlay_image`：`image-ref.v1`
- `inspection_result`：`result-record.v1`
- `decision_summary`：`value.v1`

适用场景：

- 已经明确要直接使用 YOLOE 文本提示检测
- 希望把文本提示检测结果直接叠加回原图做现场复核
- 需要同时保留 `detections.v1` 和标准 `regions.v1` 两种输出面

注意事项：

- `request_prompts` 应使用标准 `text-prompts.v1`；同一 `prompt_id` 可以带多条 positive/negative 文本
- 这条样例当前默认走文本提示，不演示 visual-prompt 或 prompt-free 变体；如果现场需要这两类入口，可复用同一 overlay 骨架替换上游节点

### industrial_single_frame_yoloe_visual_overlay_review

链路固定为：

- `template-input.value`
- `image-load-local`
- `image-load-local(prompt_image)`
- `custom.yoloe.visual-prompt-detect`
- `regions-filter`
- `roi-create`
- `draw-roi`
- `mask-overlay`
- `presence-check`
- `regions-inside-check`
- `process-decision`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/yoloe/frame-021.png"}`
- `request_prompt_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/yoloe/prompt-template-01.png"}`
- `request_prompts`：`prompt-regions.v1`
  - 示例：`{"items":[{"prompt_id":"target","display_name":"Target","prompt_kind":"box","bbox_xyxy":[120,80,280,240]}]}`
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内默认多边形 ROI

输出约定：

- `model_detections`：`detections.v1`
- `model_regions`：`regions.v1`
- `filtered_regions`：`regions.v1`
- `effective_roi`：`roi.v1`
- `review_overlay_image`：`image-ref.v1`
- `inspection_result`：`result-record.v1`
- `decision_summary`：`value.v1`

适用场景：

- 已经明确要直接使用 YOLOE visual-prompt 检测
- 现场已有参考样张、模板图或 exemplar 图，需要从提示图中圈定目标外观
- 希望把视觉提示检测结果直接叠加回原图做复核，同时保留 `detections.v1` 与标准 `regions.v1`

注意事项：

- `request_prompts` 使用标准 `prompt-regions.v1`；其中坐标语义对应 `request_prompt_image_path` 指向的提示参考图，而不是目标检测图
- `prompt-regions.v1` 当前支持 `box / point / polygon / mask`，同一 `prompt_id` 也可以混合多类提示
- 这条样例默认使用 `presence + inside` 做最小复核语义，更适合“找到了没有、是否落在工位内”这类检测型场景

### industrial_single_frame_sam3_semantic_overlay_review

链路固定为：

- `template-input.value`
- `image-load-local`
- `custom.sam3.semantic-segment`
- `regions-filter`
- `roi-create`
- `draw-roi`
- `mask-overlay`
- `presence-check`
- `regions-coverage-check`
- `process-decision`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/sam3/frame-014.png"}`
- `request_prompts`：`text-prompts.v1`
  - 示例：`{"items":[{"prompt_id":"defect","display_name":"Defect","text":"surface defect"},{"prompt_id":"defect","display_name":"Defect","text":"background","negative":true}]}`
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内默认矩形 ROI

输出约定：

- `model_regions`：`regions.v1`
- `filtered_regions`：`regions.v1`
- `effective_roi`：`roi.v1`
- `review_overlay_image`：`image-ref.v1`
- `inspection_result`：`result-record.v1`
- `decision_summary`：`value.v1`

适用场景：

- 已经明确要直接使用 SAM3 文本语义分割
- 需要把分割 mask 直接叠加回原图做缺陷、涂层或覆盖面复核
- 希望输出仍统一收成 `regions.v1`，继续接既有工业规则链

注意事项：

- 这条样例默认使用 `presence + coverage` 作为最小复核语义，更适合分割覆盖类场景
- `request_prompts` 同样使用标准 `text-prompts.v1`，支持同一 `prompt_id` 下的正负文本组合

### industrial_single_frame_sam3_interactive_overlay_review

链路固定为：

- `template-input.value`
- `image-load-local`
- `custom.sam3.interactive-segment`
- `regions-filter`
- `roi-create`
- `draw-roi`
- `mask-overlay`
- `presence-check`
- `regions-coverage-check`
- `process-decision`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/sam3/frame-014.png"}`
- `request_prompts`：`prompt-regions.v1`
  - 示例：`{"items":[{"prompt_id":"target","display_name":"Target","prompt_kind":"box","bbox_xyxy":[260,180,860,620]}]}`
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内默认矩形 ROI

输出约定：

- `model_regions`：`regions.v1`
- `filtered_regions`：`regions.v1`
- `effective_roi`：`roi.v1`
- `review_overlay_image`：`image-ref.v1`
- `inspection_result`：`result-record.v1`
- `decision_summary`：`value.v1`

适用场景：

- 已经明确要直接使用 SAM3 interactive segmentation
- 现场需要人工或上游流程给一个 box / point / polygon / mask 提示，再把分割结果叠加回原图复核
- 希望交互分割输出继续统一收成 `regions.v1`，直接接既有工业规则链

注意事项：

- `request_prompts` 使用标准 `prompt-regions.v1`；这里的提示坐标语义对应当前待分割图像本身，而不是额外参考图
- 这条样例默认使用 `presence + coverage` 作为最小复核语义，更适合区域覆盖、缺陷圈定或工艺面复核
- 如果现场更关心“是否越界/是否落位”，可以直接把 `coverage-check` 替换成 `inside-check` 或 `offset-check`

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
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内 `create_roi` 的默认 ROI 参数
  - 示例：`{"value":{"roi_id":"line-b-roi","bbox_xyxy":[240,160,1120,640]}}`

输出约定：

- `inspection_result`：`result-record.v1`
- `inspection_alarm`：`alarm-record.v1`
- `decision_summary`：`value.v1`
- `json_summary`：`value.v1`
- `csv_summary`：`value.v1`
- `callback_response`：`value.v1`

注意事项：

- 模板里的 `roi-create` 既支持固定参数，也支持 `request_roi` 运行时覆盖；现场工位 ROI 经常需要按相机分辨率、换型工装或班次配置动态下发
- `request_roi.value` 当前直接使用 ROI 对象，建议传 `roi_kind / roi_id / bbox_xyxy` 或 `roi_kind / roi_id / polygon_xy`
- `http-post.url` 当前是示例回调地址，导入后应先改成现场真实接口，再执行
- `http-post` 的输出是 `value.v1` 摘要，不是 `http-response.v1`；摘要里会带 `ok / status_code / headers / body_json 或 body_text`

### industrial_single_frame_glue_polygon_roi_changeover

链路固定为：

- `template-input.value`
- `image-load-local`
- `regions-filter`
- `roi-create`
- `regions-coverage-check`
- `regions-inside-check`
- `regions-intersection-metrics`
- `process-decision`
- `alarm-condition`
- `json-save-local`
- `csv-append-local`
- `http-post`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-b/frame-088.png"}`
- `request_regions`：`regions.v1`
  - 由上游检测/分割节点或外部系统提供
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内默认多边形 ROI
  - 示例：`{"value":{"roi_id":"line-b-shift-2","roi_kind":"polygon","polygon_xy":[[210,230],[380,160],[920,165],[1090,255],[1000,640],[250,620]]}}`

输出约定：

- `inspection_result`：`result-record.v1`
- `inspection_alarm`：`alarm-record.v1`
- `decision_summary`：`value.v1`
- `json_summary`：`value.v1`
- `csv_summary`：`value.v1`
- `callback_response`：`value.v1`

适用场景：

- 工位形状不规则、矩形 ROI 不够表达的点胶或涂覆区域
- 不同产品型号或工装切换时，需要运行时下发多边形 ROI
- 需要边做本地归档，边把结果回传给现场系统

注意事项：

- 该样例把 `roi-create` 的默认 ROI 固定成多边形，但运行时 `request_roi` 仍可用 `bbox` 或 `polygon` 覆盖
- 相比矩形 ROI 版，这条样例更强调“换型”和“不规则工位区域”，因此使用 `inside-check` 代替偏移检查更直观
- `http-post.url` 当前是示例回调地址，导入后应先改成现场真实接口，再执行

### industrial_single_frame_yolox_position_gate

链路固定为：

- `template-input.value`
- `template-input.object`
- `image-load-local`
- `core.model.yolox-detection`
- `core.vision.detections-to-regions`
- `regions-filter`
- `regions-select-best`
- `roi-create`
- `regions-inside-check`
- `regions-offset-check`
- `presence-check`
- `process-decision`
- `alarm-condition`
- `json-save-local`
- `csv-append-local`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-c/frame-105.png"}`
- `deployment_request`：`value.v1`
  - 示例：`{"value":{"deployment_instance_id":"deployment-instance-1"}}`
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内 `create_roi` 的默认 ROI 参数

输出约定：

- `model_detections`：`detections.v1`
- `model_regions`：`regions.v1`
- `inspection_result`：`result-record.v1`
- `inspection_alarm`：`alarm-record.v1`
- `decision_summary`：`value.v1`
- `json_summary`：`value.v1`
- `csv_summary`：`value.v1`

适用场景：

- 已有 published detection deployment，需要直接接工业落位/偏移/存在性规则
- 需要一条 checked-in 的“模型输出 -> 规则判定”正式样例
- 规则更偏 bbox 语义，不适合直接上连续性/空洞/断裂这类分割型指标

注意事项：

- 该样例使用的是 `core.model.yolox-detection`，因此要求 `deployment_request.value` 至少包含 `deployment_instance_id`
- 该样例先把 `detections.v1` 转成 `regions.v1`，再进入 `presence / inside / offset` 规则链；这是当前 deployment detection 接工业规则的推荐接法
- 如果现场使用的不是 YOLOX，而是其他能输出 `detections.v1` 的模型节点，同样可以复用 `core.vision.detections-to-regions` 和后面的规则链

### industrial_single_frame_line_pair_measure_gate

链路固定为：

- `template-input.value`
- `image-load-local`
- `otsu-threshold`
- `contour`
- `fit-line`
- `payload-to-value`
- `value-field-extract`
- `point-distance`
- `parallelism-metrics`
- `slot-width`
- `range-check`
- `process-decision`
- `alarm-condition`
- `json-save-local`
- `csv-append-local`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-geometry/frame-001.png"}`

输出约定：

- `inspection_result`：`result-record.v1`
- `inspection_alarm`：`alarm-record.v1`
- `decision_summary`：`value.v1`
- `json_summary`：`value.v1`
- `csv_summary`：`value.v1`

适用场景：

- 双边线槽宽量测
- 导轨、边线、夹爪口宽的平行度检查
- 希望把传统几何量测直接收成统一 OK/NG 结果对象

注意事项：

- 该样例默认假设图里能稳定提取两条主边线，因此 `fit-line` 采用 `length_pixels` 降序，后续 `parallelism-metrics / slot-width` 默认拿最长与最短两条线
- `measure_midpoint_distance` 主要用于把两条边线的中点间距一并放进结果指标，便于现场排障和人工复核
- 如果现场更适合检测斜边或竖边，可直接改 `parallelism_check` 阈值，而不用改节点协议

### industrial_single_frame_circle_concentricity_gate

链路固定为：

- `template-input.value`
- `image-load-local`
- `otsu-threshold`
- `contour`
- `contour-filter`
- `min-enclosing-circle`
- `circle-diameter`
- `concentricity-metrics`
- `contours-to-regions`
- `circularity-check`
- `range-check`
- `process-decision`
- `alarm-condition`
- `json-save-local`
- `csv-append-local`

输入约定：

- `request_image_path`：`value.v1`
  - 示例：`{"value":"D:/cases/circle-geometry/frame-015.png"}`

输出约定：

- `inspection_result`：`result-record.v1`
- `inspection_alarm`：`alarm-record.v1`
- `decision_summary`：`value.v1`
- `json_summary`：`value.v1`
- `csv_summary`：`value.v1`

适用场景：

- 双圆孔、轴套、垫片、圆环的孔径和同心度检查
- 需要把传统圆度判断直接纳入统一工业规则链
- 需要一条 checked-in 的“图像输入 -> 双圆量测 -> OK/NG”正式模板

注意事项：

- 该样例通过 `contour-filter(limit=2)` 把轮廓数先收成两条主轮廓，再分别接 `min-enclosing-circle` 和 `contours-to-regions`
- `measure_diameter` 默认读取较小圆的直径，适合更常见的内孔量测；如果现场要看外圆，直接把 `circle_strategy` 改成 `largest`
- `circularity-check` 当前同时看 `min_circularity` 和 `min_fill_ratio`，比只看单个圆度值更稳，适合现场抑制边缘缺口或明显非圆形轮廓

## 工业本地批量输入样例

- `industrial_local_directory_batch_input.template.json`
- `industrial_local_directory_batch_input.application.json`
- `industrial_local_directory_batch_segments_continuity_gate.template.json`
- `industrial_local_directory_batch_segments_continuity_gate.application.json`
- `industrial_local_directory_batch_regions_continuity_gate.template.json`
- `industrial_local_directory_batch_regions_continuity_gate.application.json`
- `industrial_local_directory_batch_yolox_position_gate.template.json`
- `industrial_local_directory_batch_yolox_position_gate.application.json`
- `industrial_local_directory_watch_yolox_position_gate.template.json`
- `industrial_local_directory_watch_yolox_position_gate.application.json`
- `industrial_local_directory_polling_cursor_guard.template.json`
- `industrial_local_directory_polling_cursor_guard.application.json`

该样例面向“本地文件夹里持续放图，小批量按窗口推进”的现场输入准备场景，链路固定为：

- `template-input.value(directory_path)`
- `directory-scan`
- `directory-batch-window`
- `image-list-local`
- `object-create(summary)`

输入约定：

- `request_directory_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-d/incoming"}`
- `request_batch_start_index`：`value.v1`
  - 可选；示例：`{"value":0}`
- `request_batch_size`：`value.v1`
  - 可选；示例：`{"value":8}`
- `request_batch_cursor`：`value.v1`
  - 可选；示例：`{"value":{"last_path":"D:/cases/line-d/incoming/frame-008.png","next_start_index":8}}`

输出约定：

- `batch_files`：`value.v1`
- `batch_images`：`image-refs.v1`
- `scan_summary`：`value.v1`
- `batch_cursor`：`value.v1`
- `batch_summary`：`value.v1`

适用场景：

- 现场先按目录做单帧小批量输入，不急着直接接相机或 RTSP
- 需要先把一批图片载入 workflow，再接后续检测或分割规则链
- 需要显式知道当前窗口、是否还有下一批，以及可直接回传的下一步 cursor

注意事项：

- 该样例当前只负责“目录扫描 -> 批次窗口 -> 图片载入”，后续具体接检测链还是分割链由现场 workflow 再继续拼接
- `directory-scan` 当前已支持 `min_stable_age_seconds` 和 `dedupe_by`；示例模板默认打开 `min_stable_age_seconds = 1.0`，用于避开仍在写入中的新文件
- `directory-batch-window` 当前已支持运行时 `start_index / batch_size / cursor` 输入，因此可以直接做批次推进或游标推进，而不必只靠模板内写死参数
- 当前这版仍沿用 `directory-batch-window` 的现有报错语义：目录为空或 cursor 推到末尾时会报错，而不是返回空批次

### industrial_local_directory_polling_cursor_guard

链路固定为：

- `template-input.value(directory_path)`
- `json-load-local`
- `directory-scan`
- `directory-poll-window`
- `object-create(batch_archive)`
- `json-save-local(cursor)`
- `json-save-local(batch_archive)`

输入约定：

- `request_directory_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-d/incoming"}`
- `request_batch_size`：`value.v1`
  - 可选；示例：`{"value":8}`

输出约定：

- `has_work`：`boolean.v1`
- `batch_files`：`value.v1`
- `scan_summary`：`value.v1`
- `poll_summary`：`value.v1`
- `batch_cursor`：`value.v1`
- `cursor_state`：`value.v1`
- `cursor_load_summary`：`value.v1`
- `cursor_save_summary`：`value.v1`
- `batch_archive`：`value.v1`
- `archive_summary`：`value.v1`

适用场景：

- 现场需要按固定周期轮询本地目录，但当前还不准备引入常驻 daemon 或设备接入 custom node
- 需要把“有没有新文件”单独判断出来，避免空目录或无新增时把整个 workflow 当异常
- 需要把 cursor 和每次轮询批次摘要都落到本地 JSON，便于断点恢复、巡检和排障

注意事项：

- 该样例故意不直接接检测或分割节点，只负责“目录状态守护 + 轮询窗口 + 本地归档”；推荐由外部调度周期性调用它，再在 `has_work = true` 时触发后续检测或分割 workflow
- `directory-poll-window` 与 `directory-batch-window` 不同：当前没有新文件时返回 `has_work = false` 和空 `files`，而不是直接报错
- 该样例默认使用 `sort_by = modified_time` 且 `descending = false`，目的是让 `cursor.last_path -> 后续新文件` 的推进语义保持单向稳定；如果现场目录更依赖文件名顺序，可改成 `sort_by = name`
- 当前 cursor 落盘位置固定在 `{workflow_app_result_dir}/industrial-local-directory-polling-cursor-guard/cursor.json`；批次归档 JSON 固定写到同目录下的 `archive/`
- `directory-scan` 当前示例默认打开 `min_stable_age_seconds = 1.0` 和 `dedupe_by = path`，用于避开仍在写入中的文件以及重复路径记录

### industrial_local_directory_batch_segments_continuity_gate

链路固定为：

- `template-input.value(directory_path)`
- `directory-scan`
- `directory-batch-window`
- `for-each`
- `image-load-local`
- `list-item-get`
- `value-to-segments`
- `segments-to-regions`
- `regions-filter`
- `regions-area-ratio`
- `region-continuity-score`
- `region-gap-check`
- `presence-check`
- `range-check`
- `process-decision`
- `csv-append-local`
- `object-create(batch_summary)`
- `json-save-local`

输入约定：

- `request_directory_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-seg/incoming"}`
- `request_batch_start_index`：`value.v1`
  - 可选；示例：`{"value":0}`
- `request_batch_size`：`value.v1`
  - 可选；示例：`{"value":8}`
- `request_batch_cursor`：`value.v1`
  - 可选；示例：`{"value":{"last_path":"D:/cases/line-seg/incoming/frame-008.png","next_start_index":8}}`
- `request_segments_items`：`value.v1`
  - `value` 内必须是数组，且 `value[i]` 必须是与 `batch_files.value[i]` 对齐的一份标准 `segments.v1`

输出约定：

- `batch_files`：`value.v1`
- `inspection_results`：`value.v1`
- `inspection_result_count`：`value.v1`
- `terminated_early`：`boolean.v1`
- `termination_reason`：`value.v1`
- `scan_summary`：`value.v1`
- `window_summary`：`value.v1`
- `batch_cursor`：`value.v1`
- `batch_summary`：`value.v1`
- `json_summary`：`value.v1`

适用场景：

- 上游给的是逐图 `segments.v1(mask / polygon / bbox)`，现场又希望统一走现有连续性规则链
- 目录批次里的每张图都要做面积占比、断裂和连续性判断
- 需要一条 checked-in 的“目录批次 -> 分割桥接 -> 工业规则链”正式样例

注意事项：

- `request_segments_items.value` 的顺序必须和当前批次 `batch_files.value` 完全一致；该样例不会自动按文件名回配
- 该样例会先通过 `value-to-segments` 恢复正式 `segments.v1`，再接 `segments-to-regions`，适合把目录批次里的逐项 `value` 输入重新桥回标准分割链
- 当前目录为空时，workflow 会沿用 `directory-batch-window` 现有规则直接报错

### industrial_local_directory_batch_regions_continuity_gate

链路固定为：

- `template-input.value(directory_path)`
- `directory-scan`
- `directory-batch-window`
- `for-each`
- `image-load-local`
- `list-item-get`
- `value-to-regions`
- `regions-filter`
- `regions-area-ratio`
- `region-continuity-score`
- `region-gap-check`
- `presence-check`
- `range-check`
- `process-decision`
- `csv-append-local`
- `object-create(batch_summary)`
- `json-save-local`

输入约定：

- `request_directory_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-seg/incoming"}`
- `request_batch_start_index`：`value.v1`
  - 可选；示例：`{"value":0}`
- `request_batch_size`：`value.v1`
  - 可选；示例：`{"value":8}`
- `request_batch_cursor`：`value.v1`
  - 可选；示例：`{"value":{"last_path":"D:/cases/line-seg/incoming/frame-008.png","next_start_index":8}}`
- `request_regions_items`：`value.v1`
  - `value` 内必须是数组，且 `value[i]` 必须是与 `batch_files.value[i]` 对齐的一份标准 `regions.v1`

输出约定：

- `batch_files`：`value.v1`
- `inspection_results`：`value.v1`
- `inspection_result_count`：`value.v1`
- `terminated_early`：`boolean.v1`
- `termination_reason`：`value.v1`
- `scan_summary`：`value.v1`
- `window_summary`：`value.v1`
- `batch_cursor`：`value.v1`
- `batch_summary`：`value.v1`
- `json_summary`：`value.v1`

适用场景：

- 上游已经直接输出标准 `regions.v1`，不需要再经过 `segments-to-regions`
- 目录批次里的每张图都要走同一套面积占比和连续性规则
- 需要把检测链、分割链和外部系统结果统一收进同一套工业规则批处理骨架

注意事项：

- `request_regions_items.value` 的顺序必须和当前批次 `batch_files.value` 完全一致；该样例不会自动按文件名回配
- `value-to-regions` 适合把目录批次里的逐项 `value` 输入重新恢复成正式 `regions.v1`
- 当前目录为空时，workflow 会沿用 `directory-batch-window` 现有规则直接报错

### industrial_local_directory_batch_yolox_position_gate

链路固定为：

- `template-input.value(directory_path)`
- `template-input.object(deployment_request)`
- `directory-scan`
- `directory-batch-window`
- `roi-create`
- `for-each`
- `image-load-local`
- `core.model.yolox-detection`
- `core.vision.detections-to-regions`
- `regions-filter`
- `regions-select-best`
- `regions-inside-check`
- `regions-offset-check`
- `presence-check`
- `process-decision`
- `csv-append-local`
- `object-create(batch_summary)`
- `json-save-local`

输入约定：

- `request_directory_path`：`value.v1`
  - 示例：`{"value":"D:/cases/line-d/incoming"}`
- `request_batch_start_index`：`value.v1`
  - 可选；示例：`{"value":0}`
- `request_batch_size`：`value.v1`
  - 可选；示例：`{"value":8}`
- `request_batch_cursor`：`value.v1`
  - 可选；示例：`{"value":{"last_path":"D:/cases/line-d/incoming/frame-008.png","next_start_index":8}}`
- `deployment_request`：`value.v1`
  - 示例：`{"value":{"deployment_instance_id":"deployment-instance-1"}}`
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内默认 ROI 参数

输出约定：

- `batch_files`：`value.v1`
- `inspection_results`：`value.v1`
  - `value` 内是当前批次逐图收集的 `result-record.v1` 列表
- `inspection_result_count`：`value.v1`
- `terminated_early`：`boolean.v1`
- `termination_reason`：`value.v1`
- `scan_summary`：`value.v1`
- `window_summary`：`value.v1`
- `batch_cursor`：`value.v1`
- `batch_summary`：`value.v1`
- `json_summary`：`value.v1`

适用场景：

- 本地目录持续来图，但现场先按小批次推进，不急着做目录轮询守护进程
- 已有 published detection deployment，希望把目录批处理直接接到存在性、落位和偏移规则
- 需要一条 checked-in 的“目录批次 -> 检测 -> 规则判定 -> CSV / JSON 归档”正式样例

注意事项：

- 该样例把单图结果逐条追加到固定 CSV，再把整个批次结果对象保存为一份 JSON；因此更适合“每批次一份总表 + 一条持续历史 CSV”的现场归档方式
- `inspection_results.value` 当前直接收集 `result-record.v1` 列表，便于后续再接本地回传、人工复核或批次摘要节点
- `directory-scan` 当前示例默认打开 `min_stable_age_seconds = 1.0`；如果现场目录是复制后原子改名落地，可按情况调小或关闭
- 当前这版仍沿用 `directory-batch-window` 的现有报错语义：目录为空或 cursor 推到末尾时会报错，而不是返回空批次
- 如果现场上游使用的是分割链而不是检测链，当前推荐保留目录批次与 `for-each` 骨架，把 `detect + detections-to-regions` 替换成分割输出到 `segments-to-regions` 或直接输出 `regions.v1`

### industrial_local_directory_watch_yolox_position_gate

链路固定为：

- `trigger-source-input(payload)`
- `trigger-source-input(event)`
- `payload-to-value`
- `value-field-extract(files / batch_id / scan_summary / directory_path)`
- `template-input.object(deployment_request)`
- `roi-create`
- `for-each`
- `image-load-local`
- `core.model.yolox-detection`
- `core.vision.detections-to-regions`
- `regions-filter`
- `regions-select-best`
- `regions-inside-check`
- `regions-offset-check`
- `presence-check`
- `process-decision`
- `csv-append-local`
- `batch-record`
- `batch-result-summary`
- `json-save-local`
- `http-post`

输入约定：

- `request_trigger_payload`：`response-body.v1`
  - 来自 `directory-watch` 的原始 `payload`
  - 示例：`{"batch_id":"watch-batch-001","directory_path":"D:/cases/line-d/incoming","files":[{"path":"D:/cases/line-d/incoming/frame-001.png"}],"scan_summary":{"file_count":1}}`
- `request_trigger_event`：`response-body.v1`
  - 来自 `directory-watch` 的标准化 `event`
  - 示例：`{"trigger_source_id":"dir-watch-01","event_id":"directory-watch-event-000001","occurred_at":"2026-06-09T09:00:00Z"}`
- `deployment_request`：`value.v1`
  - 示例：`{"value":{"deployment_instance_id":"deployment-instance-1"}}`
- `request_roi`：`value.v1`
  - 可选；未提供时回退到模板内默认 ROI 参数

输出约定：

- `batch_files`：`value.v1`
- `inspection_results`：`value.v1`
  - `value` 内是当前触发批次逐图收集的 `result-record.v1` 列表
- `inspection_result_count`：`value.v1`
- `terminated_early`：`boolean.v1`
- `termination_reason`：`value.v1`
- `batch_record`：`value.v1`
- `batch_result_summary`：`value.v1`
- `json_summary`：`value.v1`
- `callback_response`：`value.v1`

适用场景：

- 现场已经准备把“目录新增/变更文件”作为正式触发源，而不是人工或外部调度去调用目录批处理 workflow
- 已有 published detection deployment，希望目录触发后直接走存在性、落位和偏移判定
- 需要一条 checked-in 的“directory-watch -> 检测 -> 规则判定 -> batch-record / JSON / HTTP 回传”正式样例

注意事项：

- 当前 `directory-watch` 的 `input_binding_mapping` 应分别把 `payload` 映射到 `request_trigger_payload`，把 `event` 映射到 `request_trigger_event`；该样例故意在图内保留 `payload-to-value`，避免把 TriggerSource 输入包装逻辑隐式塞进运行时
- `deployment_request` 当前仍由 workflow execute 输入单独提供，适合把“触发源”和“具体 deployment 实例”分开管理；如果现场 deployment 固定，也可以由上层应用层在调用时填入固定对象
- 该样例会把每张图的单图结果持续追加到固定 CSV，再把整批触发结果收成 `batch-record` 和一份 JSON；因此更适合“持续历史表 + 每批次归档对象”的现场归档方式
- `http-post.url` 当前是示例回调地址，导入后应先改成现场真实接口，再执行
