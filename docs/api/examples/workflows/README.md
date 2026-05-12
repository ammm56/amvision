# Workflow API 示例目录

本目录按 workflow 场景编号分组保存 API 请求体示例，避免所有 workflow JSON 平铺在一个目录中。

## 目录规则

- `00-short-dev-examples/`：短链路、开发中、单节点或边界不明确的 workflow 示例，用于快速调试 template/application、preview run 和 runtime 调用。
- `01-*` 到 `05-*`：已经明确为第一到第五类完整 workflow app 的验证示例。
- 后续完整示例按 `06-*`、`07-*`、`08-*` 继续新增。

## 每个示例目录的文件

- `save-template.request.json`：保存 workflow template 的请求体。
- `save-application.request.json`：保存 FlowApplication 的请求体。
- `preview-run.request.json`：编辑态 preview run 的请求体。
- `app-runtime.create.request.json`：创建正式 app runtime 的请求体。
- `app-runtime.invoke.request.json`：正式 runtime 同步 invoke 的请求体。
- `app-runtime.run.create.request.json`：正式 runtime async run create 的请求体。

`dataset-package.v1` 的 preview 示例使用 JSON 内联 base64 `package_bytes` 表达小型 zip 包；正式 runtime invoke/run 示例会保留 `content_type: multipart/form-data`、`input_bindings_json` 和 `files` 字段，实际 Postman 调用使用对应 collection 中的 form-data。

## 与 LocalBufferBroker 的关系

本目录中的请求体示例面向已公开 HTTP 控制面，仍保留可复制的 `image-base64.v1`、storage `image-ref.v1` 和 multipart 输入形状。`BufferRef` 和 `FrameRef` 属于本机 LocalBufferBroker 短期引用，包含当前机器上的 mmap path、offset、broker_epoch 和 generation，不适合作为固定 checked-in 请求体。

最新运行链路已经在服务内部使用 LocalBufferBroker。HTTP base64 图片进入 workflow 后会先变成 execution memory image-ref；YOLOX detection 节点会在存在 broker writer 时写入 LocalBufferBroker，并通过 PublishedInferenceGateway 调用 backend-service 持有的长期 deployment worker。OpenCV 与 Barcode/QR 自定义节点通过公共 image helper 读取图片，因此同一示例图可以在后续本地 adapter 场景中接收 buffer/frame image-ref。

后续本地 adapter 或 WorkflowTriggerSource 公开后，应按 `06-*` 新增高速输入示例目录，单独展示 FrameRef/BufferRef 输入映射和回执策略。

第二到第五类 workflow 当前没有像第一类训练链路那样的 template 内动态默认请求拼装。`02-*`、`03-*`、`04-*` 的示例请求体只显式展示真实输入 `deployment_instance_id`，`05-*` 只显式展示 `request_image`；检测阈值、OpenCV 处理参数、health 摘要字段等固定值保留在 `save-template.request.json` 的节点参数中。

对于 `02-*`、`03-*`、`04-*` 这类依赖已有 `deployment_instance_id` 的 workflow，`preview-run.request.json` 主要用于校验 template/application 绑定和输入形状。preview run 仍保持独立 snapshot 子进程，不直接复用 backend-service 父进程中的 deployment supervisor 状态；当前主干已接入 LocalBufferBroker direct mmap 数据面和 PublishedInferenceGateway 事件 dispatcher，推理节点会通过 BufferRef / FrameRef 调用 backend-service 持有的长期运行 deployment worker。目标 deployment 仍需提前通过 sync/start 或 sync/warmup 启动，或者在节点参数中显式允许 `auto_start_process`。
