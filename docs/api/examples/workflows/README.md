# Workflow API 示例目录

本目录按 workflow 场景编号分组保存 API 请求体示例，避免所有 workflow JSON 平铺在一个目录中。

## 目录规则

- `00-short-dev-examples/`：短链路、开发中、单节点或边界不明确的 workflow 示例，用于快速调试 template/application、preview run 和 runtime 调用。
- `01-*` 到 `05-*`：已经明确为第一到第五类完整 HTTP workflow app 的验证示例。
- `06-*`、`07-*`：独立的 TriggerSource / ZeroMQ 调试示例，同一个 workflow app 同时发布 HTTP `image-base64.v1` 和 ZeroMQ `image-ref.v1` 输入，在与 `04-*`、`05-*` 一致的本地调试链路上额外验证双入口和图级显式转换。
- `08-*`：独立的 TriggerSource / PLC 调试示例，聚焦 `plc-register -> workflow app runtime -> result-record -> http-post` 这条现场回传链。
- `09-*`：独立的 TriggerSource / directory-watch 调试示例，聚焦“目录事件 -> 工业目录批次检测 workflow app”的现场接法。
- `10-*`：正式的工业单帧交付示例，聚焦 `regions.v1 + ROI + delivery context -> process-decision -> PLC/JSON/CSV/MES/local-db` 这条现场结果交付链。
- `11-*`：独立的 TriggerSource / directory-poll 调试示例，聚焦“固定周期目录轮询 -> 工业目录批次检测 workflow app”的现场接法，并把 `checkpoint + batch + callback` 这条正式链路收成 checked-in 调试入口。
- `12-*`：正式的 segmentation direct model 调试示例，聚焦 `image-base64 -> core.model.segmentation -> segments-to-regions -> process-decision` 这条最小现场链。
- `13-*`：正式的 classification direct model 调试示例，聚焦 `top class + top score -> process-decision` 这条最小现场链。
- `14-*`：正式的 pose direct model 调试示例，聚焦 `count + top pose score -> process-decision` 这条最小现场链。
- `15-*`：正式的 OBB direct model 调试示例，聚焦 `count + angle range -> process-decision` 这条最小现场链。
- 后续完整示例按 `16-*`、`17-*` 继续新增。

`12-*` 到 `15-*` 继续只保留 workflow/runtime 使用面的 checked-in 示例，不承接 dataset import、dataset export、training、validation、evaluation、conversion 和 deployment 全生命周期调试。对应的完整 API 联调入口统一放在 `docs/api/postman/*-full-chain.postman_collection.json`。

## 每个示例目录的文件

- `00-*` 到 `05-*` 目录包含：`save-template.request.json`、`save-application.request.json`、`preview-run.request.json`、`app-runtime.create.request.json`、`app-runtime.invoke.request.json`、`app-runtime.run.create.request.json`。
- `06-*`、`07-*`、`08-*` 目录包含：`save-template.request.json`、`save-application.request.json`、`preview-run.request.json`、`app-runtime.create.request.json`、`app-runtime.invoke.request.json`、`app-runtime.run.create.request.json`、`trigger-source.create.request.json`。
- `09-*` 目录包含：`save-template.request.json`、`save-application.request.json`、`preview-run.request.json`、`app-runtime.create.request.json`、`app-runtime.invoke.request.json`、`app-runtime.run.create.request.json`、`trigger-source.create.request.json`。
- `10-*` 目录包含：`save-template.request.json`、`save-application.request.json`、`preview-run.request.json`、`app-runtime.create.request.json`、`app-runtime.invoke.request.json`、`app-runtime.run.create.request.json`。
- `11-*` 目录包含：`save-template.request.json`、`save-application.request.json`、`preview-run.request.json`、`app-runtime.create.request.json`、`app-runtime.invoke.request.json`、`app-runtime.run.create.request.json`、`trigger-source.create.request.json`。
- `12-*` 到 `15-*` 目录包含：`save-template.request.json`、`save-application.request.json`、`preview-run.request.json`、`app-runtime.create.request.json`、`app-runtime.invoke.request.json`、`app-runtime.run.create.request.json`。

`06-*`、`07-*`、`08-*`、`09-*` 不是只保留 TriggerSource 特例接口；Save Template、Save Application、Preview Run、Create App Runtime、Invoke App Runtime 和 Create Workflow Run 仍然完整保留，TriggerSource 请求只是额外增加的协议入口调试步骤。

`09-*` 当前仍然复用已经 checked-in 的 `docs/examples/workflows/industrial_local_directory_watch_detection_position_gate.template.json` 与 `industrial_local_directory_watch_detection_position_gate.application.json` 作为上游源，但为了和其他正式场景保持一致，也继续补齐 `save-template.request.json` 与 `save-application.request.json`。这样 Postman collection、API 请求体示例和 checked-in workflow 源 JSON 可以沿同一套完整调试链路收口。

`09-*` 的实际导入变量、改值位置和推荐联调顺序见 [docs/api/postman/workflows/09-industrial-local-directory-watch-detection-position-gate/README.md](../../postman/workflows/09-industrial-local-directory-watch-detection-position-gate/README.md)。

`10-*` 的实际导入变量、改值位置和推荐联调顺序见 [docs/api/postman/workflows/10-industrial-single-frame-glue-roi-delivery-bundle/README.md](../../postman/workflows/10-industrial-single-frame-glue-roi-delivery-bundle/README.md)。

`11-*` 当前复用已经 checked-in 的 `docs/examples/workflows/industrial_local_directory_poll_detection_position_gate.template.json` 与 `industrial_local_directory_poll_detection_position_gate.application.json` 作为上游源，并把 `trigger-source.create.request.json`、synthetic preview/invoke/run 和正式 Postman 调试链一起补齐。这样 `directory-poll` 的正式配置样例、workflow 源 JSON 和调试请求体也能像 `09-*` 一样沿同一套链路收口。

`11-*` 的实际导入变量、改值位置和推荐联调顺序见 [docs/api/postman/workflows/11-industrial-local-directory-poll-detection-position-gate/README.md](../../postman/workflows/11-industrial-local-directory-poll-detection-position-gate/README.md)。

`dataset-package.v1` 的 preview 示例使用 JSON 内联 base64 `package_bytes` 表达小型 zip 包；正式 runtime invoke/run 示例会保留 `content_type: multipart/form-data`、`input_bindings_json` 和 `files` 字段，实际 Postman 调用使用对应 collection 中的 form-data。

## 与 LocalBufferBroker 的关系

本目录中的请求体示例面向已公开 HTTP 控制面和 TriggerSource 管理控制面，继续保留可复制的 `image-base64.v1`、storage `image-ref.v1` 和 multipart 输入形状。`BufferRef` 和 `FrameRef` 属于本机 LocalBufferBroker 短期引用，包含当前机器上的 mmap path、offset、broker_epoch 和 generation，不适合作为固定 checked-in 请求体。

最新运行链路已经在服务内部使用 LocalBufferBroker。HTTP base64 图片进入 workflow 后会先变成 execution memory image-ref；图里的 detection deployment 节点会在存在 broker writer 时写入 LocalBufferBroker，并通过 PublishedInferenceGateway 调用 backend-service 持有的长期 deployment worker。OpenCV 与 Barcode/QR 自定义节点通过公共 image helper 读取图片，因此同一张图可以同时接收 HTTP base64 输入和 TriggerSource 传入的 buffer/frame image-ref。

TriggerSource 示例目录在完整本地调试链路之外额外描述协议入口和运行时准备，不把图内转换塞进触发层。当前 `06-*`、`07-*` 已显式发布 `request_image_base64` 和 `request_image_ref` 两个 input binding，并在图里加入 `image-ref -> image-base64` 转换节点后再汇入后续链路。

`08-*` 当前则显式保留另一条边界：`plc-register` 的 `input_binding_mapping` 目前只读取标准化后的 `payload / event` 原始对象，不会自动包装成 `value.v1`。因此该示例把 `request_trigger_payload` 与 `request_trigger_event` 定义为 `response-body.v1`，再在图内使用 `payload-to-value` 桥接为后续规则节点需要的 `value.v1`。

`09-*` 当前沿用同一条边界：`directory-watch` 的 `input_binding_mapping` 仍然只负责把标准化后的 `payload / event` 原始对象映射到 workflow app 输入，不会自动补 `value.v1` 包装。因此目录监听示例继续把 `request_trigger_payload` 与 `request_trigger_event` 定义为 `response-body.v1`，并把固定 `deployment_instance_id` 通过 `input_binding_mapping.deployment_request.value` 静态注入到 workflow app。

`11-*` 当前也沿用同一条边界：`directory-poll` 的 `input_binding_mapping` 仍然只负责把标准化后的 `payload / event` 原始对象映射到 workflow app 输入，不会自动补 `value.v1` 包装。因此目录轮询示例同样把 `request_trigger_payload` 与 `request_trigger_event` 定义为 `response-body.v1`，并把固定 `deployment_instance_id` 通过 `input_binding_mapping.deployment_request.value` 静态注入到 workflow app。

第二到第五类 workflow 当前没有像第一类训练链路那样的 template 内动态默认请求拼装。`02-*`、`03-*`、`04-*` 的示例请求体只显式展示真实输入 `deployment_instance_id`，`05-*` 只显式展示 `request_image`；检测阈值、OpenCV 处理参数、health 摘要字段等固定值保留在 `save-template.request.json` 的节点参数中。

对于 `02-*`、`03-*`、`04-*` 这类依赖已有 `deployment_instance_id` 的 workflow，`preview-run.request.json` 主要用于校验 template/application 绑定和输入形状。preview run 仍保持独立 snapshot 子进程，不直接复用 backend-service 父进程中的 deployment supervisor 状态；当前主干已接入 LocalBufferBroker direct mmap 数据面和 PublishedInferenceGateway 事件 dispatcher，推理节点会通过 BufferRef / FrameRef 调用 backend-service 持有的长期运行 deployment worker。目标 deployment 仍需提前通过 sync/start 或 sync/warmup 启动，或者在节点参数中显式允许 `auto_start_process`。
