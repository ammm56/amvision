# Postman 使用说明

本文档只说明数据集导入这一步怎么调。

## 和前端一致的用法

- `task_type` 明确传
- `format_type` 默认留空，等同前端 `auto`
- `package` 就传当前要调试的 zip 包

也就是说，真实联调时通常只需要改：

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

## 根入口 collection

### `datasets-imports.postman_collection.json`

先改：

- `projectId`
- `datasetId`
- `datasetZipPath`
- `taskType`

默认不要动：

- `formatType`

只有在需要显式指定格式时，才启用请求体里的 `format_type` 字段，并把 `formatType` 改成目标格式。

## 全链路 collection

各个 full-chain collection 现在也按同一规则处理：

- `detection-full-chain.postman_collection.json`
- `segmentation-full-chain.postman_collection.json`
- `classification-full-chain.postman_collection.json`
- `pose-full-chain.postman_collection.json`
- `obb-full-chain.postman_collection.json`

通常只需要改：

- `projectId`
- `datasetId`
- `datasetZipPath`

说明：

- 这些 collection 本身已经固定了各自的 `task_type`
- `format_type` 默认关闭，等同前端 `auto`
- 如果要强制指定格式，再启用 `format_type` 并填写对应值

## 最短调试顺序

1. 选对应的 collection
2. 改 `projectId`、`datasetId`、`datasetZipPath`
3. 先点 `Bootstrap Project`
4. 再点 `Create * Dataset Import`
5. 最后点 `Get * Dataset Import Detail`

## 本地 zip 放哪里

见 [local-debug-assets.md](local-debug-assets.md)。
