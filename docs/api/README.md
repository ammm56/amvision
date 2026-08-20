# API 与集成

本目录说明已公开的 REST、WebSocket、ZeroMQ、Trigger Source 和 SDK 契约。字段的最终事实来源是当前 OpenAPI 与版本化 contract；文档负责调用顺序、语义和示例。

## 开始调用

1. 启动完整服务或开发态 backend-service。
2. 打开 `/docs` 查看当前 OpenAPI。
3. 完成本地登录或创建长期调用 token。
4. 初始化/选择 Project。
5. 按业务资源文档调用。

通用鉴权、错误和分页见 [当前 API 总览](current-api.md)。

## 平台与鉴权

- [本地鉴权](local-auth.md)：用户、session、refresh token、长期 token 和 scope。
- [Project](projects.md)：Project bootstrap、目录、summary 和文件读取。
- [通信契约](communication-contracts.md)：REST、WebSocket、ZeroMQ 和 LocalBuffer 的职责。
- [WebSocket 使用](websocket-usage.md)：订阅、游标、重连和错误处理。
- [SDK 配置包](sdk-config-packages.md)：项目工作台导出 Workflow、Trigger 和 Deployment 配置。

## 数据集与模型

- [DatasetImport](datasets-imports.md)
- [DatasetExport](datasets-exports.md)
- [平台基础模型](platform-base-models.md)
- [Detection 任务接口](detection-training.md)
- [模型 Deployment SDK](model-deployment-sdks.md)

模型、任务和 runtime 的完整 endpoint 清单以 [当前 API 总览](current-api.md) 为准；模型支持组合以 [模型支持矩阵](../architecture/model-support-matrix.md) 为准。

## Workflow

| 资源 | 文档 |
|---|---|
| Template、Application、Catalog | [Workflow](workflows.md) |
| 编辑态执行 | [Preview Run](workflow-preview-runs.md) |
| 不可变发布物 | [App Version](workflow-app-versions.md) |
| 稳定生产实例 | [App Runtime](workflow-app-runtimes.md) |
| 同步/异步执行 | [Workflow Run](workflow-runs.md) |
| 执行默认值 | [Execution Policy](workflow-execution-policies.md) |
| 外部触发 | [Trigger Source](workflow-trigger-sources.md) |
| .NET 调用 | [Workflow SDK](workflow-sdks.md) |

版本发布、revision/generation、归档、恢复和稳定 id 的设计见 [Workflow App 版本管理](../architecture/workflow-app-versioning.md)。

## 示例与调试

- `docs/api/examples/workflows/`：可直接保存和调用的请求体。
- `docs/api/postman/README.md`：Postman 环境、变量和使用顺序。
- `docs/api/postman/*-full-chain.postman_collection.json`：classification、detection、segmentation、pose、OBB 全链路。
- `docs/api/postman/workflows/README.md`：Workflow、Trigger、PLC、目录监听和工业节点场景。
- `docs/examples/workflows/`：可复用 Workflow 文档和输入示例。

Postman 调试资产放在 `data/files/postman-assets/`，不纳入 git。集合中的固定 id 和本地路径只用于示例，运行前必须替换为当前环境资源。

## 版本和错误规则

- 公开 contract id、字段或协议发生破坏性变化时必须显式版本化。
- mutation 使用稳定错误码与结构化 details；客户端不依赖中文 message 做分支判断。
- 列表接口显式传递 `offset`/`limit`，不能假设默认页包含全部资源。
- Project 资源调用必须携带匹配的 `project_id`，详情、输出和控制接口同样校验归属。
- 大图片主链路使用 `image-ref.v1`/LocalBuffer；Base64 是小型兼容输入。
- 未出现在 OpenAPI、Node Catalog 或 adapter capability 中的字段不属于公开能力。

## 文档维护

- 不在本目录保存 API 草案、阶段计划或内部 Repository 细节。
- OpenAPI 变化必须同步更新对应专题、SDK contract test 和调用示例。
- 真实路径、端口和 token 不写入仓库。
