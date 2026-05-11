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
