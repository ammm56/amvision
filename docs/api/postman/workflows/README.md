# Workflow Postman 调试目录

本目录按 workflow 场景编号分组保存 Postman collection，和 `docs/api/examples/workflows` 的目录编号保持一致。

## 目录顺序

1. `00-short-dev-examples/`：短链路、开发中、单节点或边界不明确的 workflow 示例。
2. `01-detection-end-to-end-qr-crop-remap/`：第一类完整导入、导出、训练、评估、转换、部署和 QR remap 链路；目录名暂沿用历史。
3. `02-detection-deployment-sync-infer-health/`：第二类 start、warmup、sync infer 和 health 链路。
4. `03-detection-deployment-qr-crop-remap/`：第三类检测、AOI crop、二维码识别和原图回绘链路。
5. `04-detection-deployment-infer-opencv-health/`：第四类 sync infer、health 和 OpenCV 处理链路。
6. `05-opencv-process-save-image/`：第五类纯 OpenCV 处理、图片保存和默认 HTTP 返回链路。
7. `06-detection-deployment-infer-opencv-health-zeromq-image-ref/`：第六类同 app HTTP base64 + ZeroMQ image-ref 检测推理链路。
8. `07-opencv-process-save-image-zeromq-image-ref/`：第七类同 app HTTP base64 + ZeroMQ image-ref OpenCV 处理链路。
9. `08-plc-register-modbus-tcp-async-result-record/`：第八类 `plc-register` Modbus TCP polling + async submit + result-record / http-post 回传链路。
10. `09-industrial-local-directory-watch-detection-position-gate/`：第九类 `directory-watch` 目录事件监听 + 静态 deployment_request 注入 + 工业检测位置门控链路。
11. `10-industrial-single-frame-glue-roi-delivery-bundle/`：第十类工业单帧 `regions.v1 + ROI + delivery context` 结果交付链，覆盖 PLC 信号写入、JSON/CSV 归档、MES 请求准备和 local-db upsert。
12. `11-industrial-local-directory-poll-detection-position-gate/`：第十一类 `directory-poll` 固定周期目录轮询 + 静态 deployment_request 注入 + 工业检测位置门控链路。

后续完整 workflow app 示例按 `12-*`、`13-*` 继续添加。

## 每个 collection 的调用面

每个场景都保留完整调用路径：

- Save Template：保存界面图编排产出的 workflow template。
- Save Application：保存 app 绑定关系。
- Create Preview Run / Get Preview Run：覆盖界面图编排阶段的快速执行和结果回查。
- Create App Runtime / Start / Health：覆盖保存 app 后的正式 runtime 生命周期。
- Invoke App Runtime：覆盖正式生产入口的同步调用。
- Create Workflow Run / Get Workflow Run：覆盖正式生产入口的异步 run 创建和结果回查。
- Stop App Runtime：结束本次 runtime 调试。

`06-*`、`07-*`、`08-*`、`09-*`、`11-*` collection 在上述完整本地调试链路之外，再额外覆盖 TriggerSource 控制面和协议入口验证：

- Invoke App Runtime (HTTP Base64)：验证同一个 runtime 的 HTTP base64 输入通道。
- Invoke App Runtime (Synthetic Event)：验证同一个 runtime 的 synthetic trigger event 输入通道。
- Create TriggerSource / Enable / Health / Disable：准备 TriggerSource 管理控制面和协议监听器。
- Stop App Runtime：结束本次 TriggerSource 调试。

## 使用说明

- 当前 FastAPI 默认触发入口是通用接口 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke`。
- application JSON 中 `bindings.config.route` 当前作为绑定声明，用于表达目标接入形态；现阶段不会自动生成同名专用 HTTP 路由。
- `image-ref.v1` 输入绑定通过 JSON invoke 传入，常见公开形状是 `{"object_key": "projects/{project_id}/inputs/source.jpg", "media_type": "image/png"}`。长期输入资产应进入 `projects/{project_id}/inputs/...`，请求期临时输入应进入 `runtime/inputs/{consumer}/{request_id}/...`。受控本地 adapter 或后续 TriggerSource 场景也可以携带 `buffer_ref` 或 `frame_ref`，但这类引用依赖本机 LocalBufferBroker 的短期 mmap 状态，不写入当前通用 Postman 请求体。
- `image-base64.v1` 输入绑定通过 JSON invoke 传入，常见形状是 `{"image_base64": "<base64>", "media_type": "image/png"}`；也支持 `data:image/png;base64,...` 形式的单行字符串。
- `dataset-package.v1` 在 preview run 中使用 JSON 内联 base64 `package_bytes` 表达小型 zip 包；正式 runtime invoke/run 通过 `/invoke/upload` 或 `/runs/upload` 传入，文件字段名必须等于 binding_id。当前 multipart 上传入口只支持这类 zip 包文件输入，不支持把图片文件直接作为 `request_image` 上传。
- 对于 template 内可以根据上下文自动补齐的默认参数，collection 里的请求体仍优先显式展示关键值，便于排查问题；例如第一类 workflow 的 `training_request_payload.value.warm_start_model_version_id` 会直接写出预训练 model_version_id，而不是只保留 `model_scale`。
- 对于 `02-*`、`03-*`、`04-*` 这类依赖已有 deployment 的 collection，`Create Preview Run` 主要用于校验编排绑定和输入形状。preview run 仍保持独立 snapshot 子进程，不直接复用 backend-service 父进程中的 deployment supervisor 状态；当前主干已接入 LocalBufferBroker direct mmap 数据面和 PublishedInferenceGateway 事件 dispatcher，推理节点会通过 BufferRef / FrameRef 调用 backend-service 持有的长期运行 deployment worker。目标 deployment 仍需提前通过 sync/start 或 sync/warmup 启动，或者在节点参数中显式允许 `auto_start_process`。
- `06-*`、`07-*` collection 和 `04-*`、`05-*` HTTP collection 分开维护，避免把已验证 HTTP 调试路径和 ZeroMQ TriggerSource 调试路径混在同一目录中；06/07 仍保留完整本地 Save Template / Preview Run / Runtime / Workflow Run 调试链路，其中 HTTP invoke 只是用于验证同一 app 的双入口，不替代 04/05 的独立 HTTP 调试目录。
- `08-*` collection 不再验证 HTTP 图片双入口，而是验证 `plc-register` 的事件输入边界；direct invoke 使用 synthetic event payload，只用于本地复现同一条业务处理链，不替代真实 PLC TriggerSource 常驻监听。
- `09-*` collection 继续沿用 synthetic event 调试方式，但重点变成 `directory-watch` 的目录批次 payload/event 输入边界，以及静态 `deployment_request` 如何从 TriggerSource 直接注入到 workflow app；真实目录监听仍以 enable 后的 TriggerSource 常驻线程为准。
- `09-*` 的具体导入变量、改值位置和推荐联调顺序见 [docs/api/postman/workflows/09-industrial-local-directory-watch-detection-position-gate/README.md](09-industrial-local-directory-watch-detection-position-gate/README.md)。
- `10-*` collection 回到标准 HTTP workflow app 调试面，但把现场最常见的结果交付出口收进同一条链：同一个 runtime 中既能做 ROI/规则判定，也能同步准备 PLC/JSON/CSV/MES/local-db 结果对象。
- `10-*` 的具体导入变量、改值位置和推荐联调顺序见 [docs/api/postman/workflows/10-industrial-single-frame-glue-roi-delivery-bundle/README.md](10-industrial-single-frame-glue-roi-delivery-bundle/README.md)。
- `11-*` collection 与 `09-*` 一样保留完整 TriggerSource 调试链，但把入口语义换成固定周期轮询：重点变成 `directory-poll` 的扫描周期、稳定期、checkpoint 恢复，以及静态 `deployment_request` 如何接进同一条 detection 规则链。
- `11-*` 的具体导入变量、改值位置和推荐联调顺序见 [docs/api/postman/workflows/11-industrial-local-directory-poll-detection-position-gate/README.md](11-industrial-local-directory-poll-detection-position-gate/README.md)。
- FrameRef/BufferRef 的固定请求体需要由本地 adapter 在运行时生成，因此 `06-*`、`07-*` collection 仍不直接发送图片 bytes；图片数据面继续使用 C# SDK 或其他后续 SDK。
- TriggerSource 只负责提交协议原生输入，不替 workflow 图做 `image-ref -> image-base64`、本地磁盘读图或相机取帧。需要这些能力时，应通过图中的显式节点或 custom node 实现。
- 当前 `plc-register` 和 `directory-watch` 的 `input_binding_mapping` 还不会自动把 `payload / event` 原始对象包装成 `value.v1`；因此 `08-*`、`09-*` collection 对应的 workflow app 都显式使用 `response-body.v1 -> payload-to-value` 做图内桥接。
- 当前 `directory-poll` 也沿用同一条边界；因此 `11-*` collection 对应的 workflow app 也显式使用 `response-body.v1 -> payload-to-value` 做图内桥接，而不是把包装逻辑隐式塞进 TriggerSource。
- `workflow-execute-output` 类型的输出会直接出现在 `outputs[binding_id]`；`http-response` 类型的输出会出现在 `outputs[binding_id] = {"status_code": 200, "body": {...}}`。
- 项目目录读取、Project 文件 metadata/content，以及模板/应用/runtime 主列表的 offset/limit 分页示例统一收口到 [docs/api/postman/workflow-runtime.postman_collection.json](../workflow-runtime.postman_collection.json)。分场景 collection 继续只保留最短业务链路，不重复铺通用控制面请求。
- `05-*`、`07-*` 这类保存图片场景的默认模板已经切到 `projects/{project_id}/results/workflow-applications/{application_id}/runs/{workflow_run_id}/...` 结果域，因此后续可以直接接入 Project 结果读取面。旧模板如果仍写 `workflow-apps/...`，当前运行时继续兼容，但不再作为默认示例。
- 第一类 collection 的 request_package 默认指向 `projectsrc/datasets/barcodeqrcode.zip`，导入 Postman 后如路径不匹配，需要把文件字段指到该 zip 包的本地路径。
