# Postman 使用说明

本文档说明仓库内 Postman collection 的当前用途。接口语义以真实 backend-service 代码和 [current-api.md](../current-api.md) 为准。

## 根入口 collection

- `local-auth.postman_collection.json`：本地账号、session、长期调用 user token、`system/me`、`system/bootstrap` 和 `system/config`。
- `workflow-runtime.postman_collection.json`：workflow runtime、WorkflowRun、TriggerSource、Project 文件和统一配置读取。
- `datasets-imports.postman_collection.json`：DatasetImport zip 上传和导入记录调试。
- `datasets-exports.postman_collection.json`：DatasetExport 和导出包调试。
- `platform-base-models.postman_collection.json`：平台基础模型目录调试。
- `*-full-chain.postman_collection.json`：检测、分类、分割、姿态和 OBB 模型链路调试。

## Workflow 和 TriggerSource

`workflow-runtime.postman_collection.json` 的 `System / Get System Config` 会调用：

```text
GET {{baseUrl}}/api/v1/system/config
```

该请求用于读取当前 backend-service 已解析的统一配置。创建 ZeroMQ TriggerSource 前，应从响应的 `config.local_buffer_broker.default_pool_name` 和 `config.local_buffer_broker.pools` 确认可选 pool，再把选中的名称写入 TriggerSource 的 `transport_config.pool_name`。

正式 workflow 场景已经拆到 `docs/api/postman/workflows/`：

- 04/05：HTTP base64 调试路径。
- 06/07：同一个 app 的 HTTP base64 + ZeroMQ image-ref 双入口调试路径。
- 08：PLC register 触发记录。
- 09/11：本地目录 watch/poll 触发。
- 12-15：分割、分类、姿态、OBB 的部署同步调用场景。

## 数据集导入

数据集导入 collection 与前端一致：

- `task_type` 明确传。
- `format_type` 默认留空，等同前端 `auto`。
- `package` 传当前要调试的 zip 包。

真实联调时通常只需要改：

- `projectId`
- `datasetId`
- `datasetZipPath`
- `taskType`

如果导入包命中了多个候选格式，或者需要强制指定格式，再额外启用 `format_type` 并填写：

- `coco`
- `voc`
- `yolo`
- `imagenet`
- `dota`

## 最短调试顺序

1. 选对应的 collection。
2. 改 `baseUrl`、`accessToken`、`projectId` 和场景变量。
3. 先运行 bootstrap 或 list 请求确认当前服务和资源状态。
4. 再运行 create / invoke / enable 等写操作。
5. 最后用 detail / health / events 请求回查结果。

## 本地 zip 放哪里

见 [local-debug-assets.md](local-debug-assets.md)。
