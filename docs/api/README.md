# API 与集成

本目录解释已公开 REST、WebSocket、ZeroMQ、Trigger Source 和 SDK 的调用语义。字段和 endpoint 的最终事实来源是 backend-service 当前生成的 `/openapi.json`；文档不手工复制一份容易失真的完整路由表。

## 开始调用

1. 按 [开发环境](../deployment/development-environment.md) 或 [生产环境](../deployment/production-environment.md) 启动完整服务。
2. 打开 `/docs` 或 `/openapi.json` 核对当前契约。
3. 完成本地登录或创建长期调用 token。
4. 初始化或选择 Project。
5. 按资源专题和示例发起调用。

鉴权、分页、错误和幂等规则见 [通用约定](conventions.md)。

## 平台

- [本地鉴权](local-auth.md)
- [Project](projects.md)
- [通信契约](communication-contracts.md)
- [WebSocket](websocket-usage.md)
- [SDK 配置包](sdk-config-packages.md)

## 数据集与模型

- [DatasetImport](datasets-imports.md)
- [DatasetExport](datasets-exports.md)
- [平台基础模型](platform-base-models.md)
- [Detection 训练、评估、转换、部署与推理](detection-training.md)
- [模型 Deployment SDK](model-deployment-sdks.md)

模型/任务组合以 [模型支持矩阵](../reference/models/support-matrix.md) 为准。

## Workflow

| 资源 | 文档 |
| --- | --- |
| Template、Application、Node Catalog | [Workflow](workflows.md) |
| 编辑态执行 | [Preview Run](workflow-preview-runs.md) |
| 不可变发布物 | [App Version](workflow-app-versions.md) |
| 稳定生产实例 | [App Runtime](workflow-app-runtimes.md) |
| 同步和异步执行 | [Workflow Run](workflow-runs.md) |
| 执行默认值 | [Execution Policy](workflow-execution-policies.md) |
| 外部触发 | [Trigger Source](workflow-trigger-sources.md) |
| .NET 调用 | [Workflow SDK](workflow-sdks.md) |

revision、generation、worker epoch 和稳定 id 的内部设计见 [Workflow App 版本管理](../architecture/workflows/app-versioning.md)。

## 示例与调试

- `docs/api/examples/workflows/`：可直接提交的请求体。
- `docs/examples/workflows/`：可复用 Template/Application 源文档。
- [Postman 使用](postman/README.md)
- [full-chain collection 本地调试数据包说明](postman/local-debug-assets.md)：本地调试资产约定，仓库路径为 `docs/api/postman/local-debug-assets.md`。
- `docs/api/postman/detection-full-chain.postman_collection.json`
- `docs/api/postman/classification-full-chain.postman_collection.json`
- `docs/api/postman/segmentation-full-chain.postman_collection.json`
- `docs/api/postman/pose-full-chain.postman_collection.json`
- `docs/api/postman/obb-full-chain.postman_collection.json`

`01-*` 到 `15-*` 这些目录只覆盖 workflow/runtime 场景面；`12-*` 到 `15-*` 继续只表示 segmentation / classification / pose / OBB 的 workflow/runtime 使用面。完整模型业务链以根级 full-chain collection 为准。

Postman 调试资产位于 `data/files/postman-assets/`，不纳入 git；固定 id、token 和本地路径必须替换为当前环境值。

## 维护边界

- 不保存完整 endpoint 镜像、内部 Repository 细节、实施计划或会话记录。
- OpenAPI 变化同步更新对应专题、SDK contract test 和请求示例。
- 客户端按稳定错误码和结构化 `details` 分支，不解析中文 message。
- 列表调用显式处理 `offset`/`limit`，不能假设默认页包含全部资源。
