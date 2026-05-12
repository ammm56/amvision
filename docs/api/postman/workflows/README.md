# Workflow Postman 调试目录

本目录按 workflow 场景编号分组保存 Postman collection，和 `docs/api/examples/workflows` 的目录编号保持一致。

## 目录顺序

1. `00-short-dev-examples/`：短链路、开发中、单节点或边界不明确的 workflow 示例。
2. `01-yolox-end-to-end-qr-crop-remap/`：第一类完整导入、导出、训练、评估、转换、部署和 QR remap 链路。
3. `02-yolox-deployment-sync-infer-health/`：第二类 start、warmup、sync infer 和 health 链路。
4. `03-yolox-deployment-qr-crop-remap/`：第三类检测、AOI crop、二维码识别和原图回绘链路。
5. `04-yolox-deployment-infer-opencv-health/`：第四类 sync infer、health 和 OpenCV 处理链路。
6. `05-opencv-process-save-image/`：第五类纯 OpenCV 处理、图片保存和默认 HTTP 返回链路。

后续完整 workflow app 示例按 `06-*`、`07-*`、`08-*` 继续添加。

## 每个 collection 的调用面

每个场景都保留完整调用路径：

- Save Template：保存界面图编排产出的 workflow template。
- Save Application：保存 app 绑定关系。
- Create Preview Run / Get Preview Run：覆盖界面图编排阶段的快速执行和结果回查。
- Create App Runtime / Start / Health：覆盖保存 app 后的正式 runtime 生命周期。
- Invoke App Runtime：覆盖正式生产入口的同步调用。
- Create Workflow Run / Get Workflow Run：覆盖正式生产入口的异步 run 创建和结果回查。
- Stop App Runtime：结束本次 runtime 调试。

## 使用说明

- 当前 FastAPI 默认触发入口是通用接口 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke`。
- application JSON 中 `bindings.config.route` 当前作为绑定声明，用于表达目标接入形态；现阶段不会自动生成同名专用 HTTP 路由。
- `image-ref.v1` 输入绑定通过 JSON invoke 传入，常见形状是 `{"object_key": "inputs/source.jpg", "media_type": "image/png"}`。
- `image-base64.v1` 输入绑定通过 JSON invoke 传入，常见形状是 `{"image_base64": "<base64>", "media_type": "image/png"}`；也支持 `data:image/png;base64,...` 形式的单行字符串。
- `dataset-package.v1` 在 preview run 中使用 JSON 内联 base64 `package_bytes` 表达小型 zip 包；正式 runtime invoke/run 通过 `/invoke/upload` 或 `/runs/upload` 传入，文件字段名必须等于 binding_id。当前 multipart 上传入口只支持这类 zip 包文件输入，不支持把图片文件直接作为 `request_image` 上传。
- 对于 template 内可以根据上下文自动补齐的默认参数，collection 里的请求体仍优先显式展示关键值，便于排查问题；例如第一类 workflow 的 `training_request_payload.value.warm_start_model_version_id` 会直接写出预训练 model_version_id，而不是只保留 `model_scale`。
- 对于 `02-*`、`03-*`、`04-*` 这类依赖已有 deployment 的 collection，`Create Preview Run` 只适合校验编排绑定和输入形状。preview run 会在独立 snapshot 子进程中执行，不复用已经由 `Start` 或 `Warmup` 拉起的 deployment supervisor 状态；要验证真实已启动 deployment，请改用 `Invoke App Runtime` 或 `Create Workflow Run`。
- `workflow-execute-output` 类型的输出会直接出现在 `outputs[binding_id]`；`http-response` 类型的输出会出现在 `outputs[binding_id] = {"status_code": 200, "body": {...}}`。
- 第一类 collection 的 request_package 默认指向 `projectsrc/datasets/barcodeqrcode.zip`，导入 Postman 后如路径不匹配，需要把文件字段指到该 zip 包的本地路径。
