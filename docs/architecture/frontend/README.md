# 前端架构

- [Web UI 定位与模块](overview.md)
- [工程结构](structure.md)
- [启动、鉴权与会话](session.md)
- [Workflow 编辑器](../workflows/editor.md)
- [产品与界面规范](../../design/frontend/README.md)

本目录只描述 Vue 3 前端的工程边界和与后端的协作关系。组件视觉规则和页面规格进入 `docs/design/`，源码启动命令进入 `docs/deployment/`。

## 已接受、待实现的扩展

amvar app 与独立运行界面的多来源公开输入输出绑定、Vue 文档渲染、独立版本和模型生成边界见 [ADR-0012](../../decisions/ADR-0012-workflow-views-and-app-packages.md)。页面仅辅助在线显示、不要求硬实时，不承担业务计算或结果队列/缓存/补发。新增 WS 支持公开 Base64 图片，整条消息上限 64MB；HTTP 继续负责调用、上传与引用资源读取，通信不阻塞 Workflow/Runtime/Trigger。第三方可按同一公开标准独立实现前端，不依赖内置设计器；本仓库主栈仍为 Vue 3。前端“应用/工作流”术语、容量口径、详细设计与阶段门禁统一维护在[amvar app 实施基线](../../development/workflow-views-and-app-packages-implementation.md)，不作为当前页面能力说明。

页面从完整公开输出中按 binding 选字段，手动调用显式使用现有 response_mode=run；不增加服务端字段投影、结果缓存或历史记录。登录用户具有全部操作权限，独立客户端使用默认用户永久 token，与 SDK 相同；不新增角色、应用 ACL 或权限管理界面。设计器与生产页按操作职责分离，不按用户权限拆成不同执行链。
