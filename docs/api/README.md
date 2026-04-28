# API 文档目录

## 文档目的

本目录用于存放对外公开接口文档，包括 REST API、WebSocket 消息、ZeroMQ 边界和版本化接口说明。

## 当前文档

- [docs/api/communication-contracts.md](communication-contracts.md)：REST API、WebSocket、ZeroMQ 的职责拆分与事件规则边界
- [docs/architecture/backend-service.md](../architecture/backend-service.md)：FastAPI 应用分层、路由拆分、数据库会话、权限和中间件骨架

## 建议内容

- REST 资源与版本说明
- WebSocket 事件类型与订阅主题清单
- ZeroMQ 本地 IPC 主题与消息约束
- 错误码、分页、鉴权和兼容性说明

## 存放规则

- 只记录公开接口与规则，不展开内部实现细节
- 一旦接口公开，文档更新与行为变更同步进行
- 版本差异单独标注，不在同一段落混写多版本行为