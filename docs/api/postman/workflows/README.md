# Workflow Postman 调试目录

本目录按 docs/examples/workflows 示例文档和第一到第五类正式 workflow 场景拆分 Postman collection，避免把模板保存、端到端链路、deployment 复用链路和纯 OpenCV 链路混在同一个 collection 里。

## 文件顺序

1. 00-workflow-example-documents.postman_collection.json：按 docs/examples/workflows 目录现有 template/application 示例拆分的保存与读取调试 collection。
2. 01-yolox-end-to-end-qr-crop-remap.postman_collection.json：第一类完整导入、导出、训练、评估、转换、部署和 QR remap 链路。
3. 02-yolox-deployment-sync-infer-health.postman_collection.json：第二类 start、warmup、sync infer 和 health 链路。
4. 03-yolox-deployment-qr-crop-remap.postman_collection.json：第三类检测、AOI crop、二维码识别和原图回绘链路。
5. 04-yolox-deployment-infer-opencv-health.postman_collection.json：第四类 sync infer、health 和 OpenCV 处理链路。
6. 05-opencv-process-save-image.postman_collection.json：第五类纯 OpenCV 处理、图片保存和默认 HTTP 返回链路。

## 建议联调顺序

1. 00-workflow-example-documents：先把 docs/examples/workflows 中需要的 template 和 application 保存到当前环境，适合作为后续 runtime 联调的准备步骤。
2. 05-opencv-process-save-image：不依赖 deployment，也不依赖 worker 长链路，适合作为本地环境和图片处理的第一条 smoke。
3. 01-yolox-end-to-end-qr-crop-remap：用于验证完整 submit family、task.wait、deployment create 和 QR remap 正式链路，也可以产出后续第二到第四类需要复用的 deployment。
4. 02-yolox-deployment-sync-infer-health：验证已有 deployment 的 start、warmup、sync infer 和 health 控制面。
5. 03-yolox-deployment-qr-crop-remap：在已有 deployment 上验证 AOI crop、二维码识别和原图回绘。
6. 04-yolox-deployment-infer-opencv-health：在已有 deployment 上验证 sync infer、health 和通用 OpenCV 节点链路。

## 依赖关系

- 第二到第四类 collection 默认要求对应的 workflow template 和 application 已经保存，并且其中的 deployment_instance_id 已替换为真实值。
- 第一类 collection 可以用于准备完整链路产物；第二到第四类也可以直接复用手工创建的 deployment_instance_id。
- docs/examples/workflows 下现有示例的模板与应用保存、读取调试使用 00-workflow-example-documents.postman_collection.json。
- workflow template、FlowApplication、preview-run、execution-policy 和 runtime 控制面的通用调试仍使用上级目录中的 workflow-runtime.postman_collection.json。

## 使用说明

- 每个 collection 只保留当前场景最小需要的 create runtime、health 和 invoke 请求。
- 00-workflow-example-documents 会为每组示例生成 Save Template、Get Template、Save Application 和 Get Application 四条请求。
- create runtime 返回 workflow_runtime_id 后，会写回 collection variable，供 health 和 invoke 继续使用。
- 第一类 collection 的 request_package 默认文件名写成 barcodeqrcode.zip，导入 Postman 后需要把本地文件路径指到真实 zip 包。