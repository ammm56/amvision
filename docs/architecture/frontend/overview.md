# 浏览器前端 Web UI

## 定位

`frontend/web-ui` 是 AMVision 的 Vue 3 工作台，面向本地工作站、工控机和浏览器运维场景。它负责资源管理、流程编排、状态观察与结果展示，不在浏览器中执行训练、转换、推理或 Workflow 节点。

前端只通过版本化 REST API 和 WebSocket 使用后端能力；ZeroMQ、LocalBuffer、Worker、Inference Daemon、数据库和 ObjectStore 均由后端边界封装。

## 技术基线

- Vue 3、TypeScript、Vite
- Vue Router、Pinia、VueUse
- Reka UI 与项目自己的 `shared/ui`
- ECharts
- 项目内 Workflow 图引擎适配层
- Vitest、Vue Test Utils、Playwright

版本约束和脚本以 [frontend/web-ui/package.json](../../../frontend/web-ui/package.json) 为准。当前 Node.js 要求为 24.15+。

## 页面模块

| 模块 | 主要职责 |
| --- | --- |
| `projects` | 项目选择、项目资源入口 |
| `datasets` | 数据集、导入、导出和版本 |
| `tasks` | 跨业务任务索引、事件和错误 |
| `models` | 基础模型、训练、评估、转换和模型产物 |
| `deployments` | DeploymentInstance 创建、启停、预热、健康和重置 |
| `inference` | 同步推理、异步推理任务和结果 |
| `integrations` | Trigger、协议集成和外部系统配置 |
| `workflows/workflow-editor` | Workflow App 列表、详情、图编辑、Preview、版本、Runtime 和 Trigger |
| `custom-nodes` | Node Pack 和节点目录视图 |
| `settings` | 系统、服务、用户和运行参数 |

`/tasks/:taskId` 是通用任务状态页。业务结果、文件、登记和删除入口保留在数据集或模型业务详情页，避免通用任务页重复实现业务控制面。

## 交互边界

- 服务端资源是最终事实来源；Pinia 保存会话、页面查询结果和编辑草稿。
- REST 提供资源快照与控制动作，WebSocket 提供事件增量；断线恢复先重新读取快照，再续订事件。
- 前端消费后端返回的 NodeDefinition、端口契约和参数 UI schema，不重新定义 Python 节点。
- Workflow 图保存为平台的 Template/Application 契约，不暴露图引擎内部对象。
- 自定义节点不能向工作台任意注入前端 JavaScript；通用参数和结果组件由项目统一维护。
- 页面不得把模型内部状态、Worker 句柄或运行时进程对象写入业务草稿。

## 工业现场要求

- 所有静态资源随发行包本地分发，不依赖外网 CDN。
- 页面兼顾大图、长列表、高信息密度、离线和局域网环境。
- 破坏性动作必须显示明确对象、状态和后果。
- 异步任务必须保留快照读取、错误详情和重新进入后的恢复能力。
- Workflow Preview 展示节点耗时只用于调试；正式 Runtime 使用生产高性能链路。

## 相关文档

- [前端工程结构](structure.md)
- [启动与会话](session.md)
- [Workflow 页面与通信](../workflows/editor.md)
- [前端设计规范](../../design/frontend/README.md)
- [开发指南](../../development/README.md)
