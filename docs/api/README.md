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

App Runtime 的 JSON、文本、图片、文件和多文件统一输入规划见 [Workflow App Entry 多类型输入实施基线](../development/workflow-app-entry-input-implementation.md)。该专题明确标记当前实现与待实现能力，API 字段仍以当前 OpenAPI 为准。

revision、generation、worker epoch 和稳定 id 的内部设计见 [Workflow App 版本管理](../architecture/workflows/app-versioning.md)。

## 待实现的应用与运行界面

amvar app 组成、命名来源、运行入口、在线结果、Workflow JSON 导入导出和应用打包恢复的接口边界统一见[实施基线](../development/workflow-views-and-app-packages-implementation.md)。页面仅辅助公开输入与非硬实时显示，不规划结果队列、缓存或补发接口。新增 WS 结果流允许 Base64 图片，整条 UTF-8 JSON 消息上限为 64MB（67,108,864 字节），与文本/JSON/资源引用共同按公开 payload 解析；内置与第三方独立前端使用同一 HTTP/WS 标准，不影响核心执行或扩大现有协议限制。其中新增字段与路径是待实现草案，不代表当前 OpenAPI 已提供接口；前端改称“工作流”不重命名既有 Workflow API、资源 ID 或 SDK。

结果流路径与消息语义在实施基线第 6.5 节固定：发送 Runtime 完整公开输出，覆盖同步、持久化异步及 none + event-only 终态；内置页面手动调用选择已有 `response_mode=run`，不改变记录模式或 SDK 默认响应。认证沿用现有默认全权限用户的永久 token，与 SDK 相同；登录用户拥有全部操作权限，不新增角色或分级 scope。HTTP 使用 Bearer，浏览器 WS 使用已有 access_token 参数；登录 session 与永久 user-token 的期限仍按[本地认证](local-auth.md)区分。以上新结果流待实现，既有认证接口不由规划修改。

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
