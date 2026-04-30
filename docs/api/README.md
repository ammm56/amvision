# API 文档目录

## 文档目的

本目录用于存放对外公开接口文档，包括 REST API、WebSocket 消息和版本化接口说明。ZeroMQ 边界尚未形成当前公开协议面时，不在本目录展开。

## 当前文档

- [docs/api/current-api.md](current-api.md)：当前已经公开的 REST API、WebSocket 入口、鉴权头和任务事件订阅规则
- [docs/api/communication-contracts.md](communication-contracts.md)：REST API、WebSocket、ZeroMQ 的职责拆分与事件规则边界
- [docs/api/datasets-imports.md](datasets-imports.md)：DatasetImport 导入、详情查询、列表查询、task_id 关联和错误语义
- [docs/api/datasets-exports.md](datasets-exports.md)：DatasetExport 创建、详情查询、列表查询、package/download/manifest 和 training 输入边界
- [docs/api/yolox-training.md](yolox-training.md)：YOLOX training 创建接口、DatasetExport 输入解析规则和当前能力边界
- [docs/api/postman/datasets-imports.postman_collection.json](postman/datasets-imports.postman_collection.json)：当前公开的 system、DatasetImport、tasks 接口 Postman collection
- [docs/api/postman/datasets-exports.postman_collection.json](postman/datasets-exports.postman_collection.json)：当前公开的 DatasetExport 接口 Postman collection
- [docs/api/postman/yolox-training.postman_collection.json](postman/yolox-training.postman_collection.json)：当前公开的 YOLOX training 创建接口 Postman collection
- [docs/architecture/backend-service.md](../architecture/backend-service.md)：FastAPI 应用分层、路由拆分、数据库会话、权限和中间件骨架

## 建议内容

- REST 资源与版本说明
- WebSocket 事件类型与订阅主题清单
- ZeroMQ 本地 IPC 主题与消息约束
- 错误码、分页、鉴权和兼容性说明
- Postman collection 与最小调试示例

## 存放规则

- 只记录公开接口与规则，不展开内部实现细节
- 一旦接口公开，文档更新与行为变更同步进行
- 版本差异单独标注，不在同一段落混写多版本行为