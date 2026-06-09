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

## 工业单帧规则样例

- `industrial_single_frame_sealant_quality_gate.template.json`
- `industrial_single_frame_sealant_quality_gate.application.json`
- `industrial_single_frame_segments_continuity_gate.template.json`
- `industrial_single_frame_segments_continuity_gate.application.json`
- `industrial_single_frame_glue_roi_callback.template.json`
- `industrial_single_frame_glue_roi_callback.application.json`
- `industrial_single_frame_glue_polygon_roi_changeover.template.json`
- `industrial_single_frame_glue_polygon_roi_changeover.application.json`
- `industrial_single_frame_yolox_position_gate.template.json`
- `industrial_single_frame_yolox_position_gate.application.json`
- `industrial_local_directory_batch_input.template.json`
- `industrial_local_directory_batch_input.application.json`
- `industrial_local_directory_batch_segments_continuity_gate.template.json`
- `industrial_local_directory_batch_segments_continuity_gate.application.json`
- `industrial_local_directory_batch_regions_continuity_gate.template.json`
- `industrial_local_directory_batch_regions_continuity_gate.application.json`
- `industrial_local_directory_batch_yolox_position_gate.template.json`
- `industrial_local_directory_batch_yolox_position_gate.application.json`
- `industrial_local_directory_polling_cursor_guard.template.json`
- `industrial_local_directory_polling_cursor_guard.application.json`

前两组样例聚焦“单图输入 -> 规则判定 -> `process-decision` -> 结果回传”，不把相机、PLC 或特定模型耦合进模板本体。`industrial_single_frame_segments_continuity_gate` 则把“分割输出 -> `segments.v1` -> `regions.v1` -> 工业规则链”这层也一起接通；`industrial_single_frame_yolox_position_gate` 对应把“检测输出 -> `detections.v1` -> `regions.v1` -> 工业规则链”这层接通；`industrial_single_frame_glue_polygon_roi_changeover` 进一步演示多边形 ROI 的换型和现场回调；`industrial_local_directory_batch_input` 把本地文件夹小批量输入这层单独收成可复用模板；`industrial_local_directory_batch_segments_continuity_gate` 与 `industrial_local_directory_batch_regions_continuity_gate` 则把“目录批次 -> 分割/区域结果 -> 连续性规则链 -> CSV / JSON 归档”两类上游入口接到同一套批次骨架；`industrial_local_directory_batch_yolox_position_gate` 继续把这条目录批次输入主线真正接到“逐图检测 -> 规则判定 -> CSV 持续归档 -> 批次 JSON 汇总”的现场闭环；`industrial_local_directory_polling_cursor_guard` 则把“目录轮询守护 / cursor 落盘恢复 / 批次归档 JSON”这层独立收成可复用状态模板。

上游 `regions.v1` 的典型来源：

- `custom.yoloe.*` 的 `prompt-free-detect / text-prompt-detect / visual-prompt-detect` 输出端口
- `custom.sam3.*` 的 `interactive-segment / semantic-segment` 输出端口
- `core.vision.segments-to-regions`，把外部或中间节点输出的 `segments.v1(mask / polygon / bbox)` 规整回 `regions.v1`
- 视频链里的 `core.vision.tracks-to-regions`，把 `tracks.v1` 拆回单帧 `regions.v1`
- 外部系统直接按标准 `regions.v1` 合同提交

当前已发布 deployment detection 主链默认输出的是 `detections.v1`；如果现场规则链消费的是 `regions.v1`，当前推荐先接 `core.vision.detections-to-regions` 再进入工业规则节点。

如果上游拿到的是分割结果而不是 bbox 检测，当前推荐直接使用 `regions.v1`；只有在上游结果仍是独立 `mask / polygon / bbox` 组合、还没有收成 `regions.v1` 时，才需要先接 `core.vision.segments-to-regions`。

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

## 工业本地批量输入样例

- `industrial_local_directory_batch_input.template.json`
- `industrial_local_directory_batch_input.application.json`
- `industrial_local_directory_batch_segments_continuity_gate.template.json`
- `industrial_local_directory_batch_segments_continuity_gate.application.json`
- `industrial_local_directory_batch_regions_continuity_gate.template.json`
- `industrial_local_directory_batch_regions_continuity_gate.application.json`
- `industrial_local_directory_batch_yolox_position_gate.template.json`
- `industrial_local_directory_batch_yolox_position_gate.application.json`
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
