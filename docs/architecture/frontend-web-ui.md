# 浏览器前端 Web UI 架构

## 文档目的

本文档用于定义项目浏览器前端界面的职责、模块边界、路由结构、状态组织和与后端服务的交互方式。

这里的前端是现代浏览器中的 Vue 3 Web 应用，服务于工作站、现场操作和运维管理场景。

具体工程骨架、目录分层、LiteGraph 接入位置、组件层和插件层边界见 [frontend-web-ui-structure.md](frontend-web-ui-structure.md)。

前端节点与后端节点目录的对应关系、数据集到模型发布的页面流程、workflow app 调用流程和事件通信规则见 [frontend-web-ui-workflows.md](frontend-web-ui-workflows.md)。

本地部署默认用户、长期 user token、自动进入工作台、登录页出现条件和退出语义见 [frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md)。

前端真实代码实现前的准备检查、剩余缺口和开工顺序见 [frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)。

## 适用范围

- 浏览器前端界面的职责边界
- Vue 3 应用的模块划分、路由结构和状态组织
- 与 backend-service 的 REST API、WebSocket 交互模型
- 本地部署默认启动、自动登录、退出和会话恢复规则
- 前端开发准备检查、横切能力和发布接入要求
- 前端节点、后端 core nodes 和 custom nodes 的对应关系
- 页面类型、工作流页面和大图像结果浏览界面
- 与自定义节点目录、节点编辑器、集成端点和任务状态流的关系

## 前端定位

前端是面向浏览器的 Web 应用，不是终端控制台，不直接处理业务执行，也不直接访问数据库、对象存储或执行器内部能力。

前端的职责是把数据集、任务、模型、部署、流程、自定义节点和外部系统集成等复杂能力组织成清晰、稳定、可操作的浏览器界面。

## 命名约定

- 架构文档统一使用 frontend-web-ui 或“浏览器前端 Web UI”描述这个子系统
- 建议的目录命名同步使用 frontend/web-ui

## 前端职责

- 展示项目、数据集、任务、模型、部署、流程和自定义节点相关信息
- 提供创建任务、查看状态、管理配置和执行管理动作的操作界面
- 提供节点编辑器、结果查看器、图像叠加和图表可视化界面
- 通过 WebSocket 订阅状态流、日志流和告警事件
- 通过 REST API 执行资源读写、查询和管理动作

## 前端非职责边界

- 不直接执行训练、推理、转换或流程任务
- 不直接连接 executors、数据库或对象存储
- 不持有任务最终状态，只消费 backend-service 暴露的状态视图
- 不在前端重新发明自定义节点加载规则或任务状态模型

## 本地启动和会话边界

- standalone、workstation 和 edge 本地部署默认直接进入工作台，不把登录页作为默认首屏。
- 默认本地用户为 `amvar`，前端应通过本地部署注入的长期 user token 完成自动进入。
- 用户明确退出后，前端记录本机退出标记，再次打开时显示登录页。
- 默认 user token 失效、被撤销、后端不可用或权限不足时，前端进入登录页或错误页。
- 登录页默认用户名为 `amvar`，但不默认填入密码。
- 长期 user token 不能调用 logout；退出时只清理前端本地凭据和连接。

## 模块划分

### shells

- 负责整体布局、导航、页面骨架和全局会话状态

### modules

- datasets：数据集与数据版本界面
- tasks：任务列表、任务详情、日志和状态追踪界面
- models：模型、模型输出文件、转换结果和 benchmark 界面
- deployments：部署实例、运行状态和回滚界面
- integrations：外部系统集成端点、回调和联动界面
- workflows：流程模板、节点编排和执行结果界面
- custom-nodes：自定义节点包、节点定义和 schema 界面
- settings：系统配置、运行时配置和管理设置界面

### workflows

- 面向跨模块操作流，例如训练发布、部署切换、流程执行和集成触发

### shared

- shared：放组件、状态封装、API client、WebSocket client、组合式能力和前端接口封装

## 路由结构建议

- /projects
- /datasets
- /tasks
- /models
- /deployments
- /integrations
- /workflows
- /custom-nodes
- /settings

## 当前已实现页面状态

- `frontend/web-ui/src/modules/models/` 当前已经提供平台基础模型列表、训练任务提交、转换任务提交、训练历史和转换历史调试面。
- `models` 页面当前不再只写死 detection 路径；训练与转换表单会显式选择 `task_type`，并要求填写 `model_type`，再调用 `/models/{task_type}/training-tasks` 和 `/models/{task_type}/conversion-tasks`。
- 训练任务详情页当前使用 `/models/{task_type}/training-tasks/{task_id}` 前端路由，并按路由里的 `task_type` 调用对应后端接口；`output-files` 和 `register-model-version` 仍只在 detection 任务详情中显示，因为这两个调试端点当前只在 detection 训练控制面公开。
- `frontend/web-ui/src/modules/deployments/` 当前已经提供 DeploymentInstance 创建、列表、sync/async start/status/stop/warmup/health/reset 和事件读取调试面。
- `deployments` 页面当前不再只写死 detection 路径；页面顶部会显式选择 `task_type`，创建表单会显式填写 `model_type`，后续运行时动作统一调用 `/models/{task_type}/deployment-instances/...`。
- `frontend/web-ui/src/modules/inference/` 当前已经提供 DeploymentInstance 选择、同步 `/infer`、异步 inference task 提交、任务列表和结果读取调试面。
- `inference` 页面当前不再只写死 detection 路径；页面顶部会显式选择 `task_type`，并用同一选择调用 `/models/{task_type}/deployment-instances/{id}/infer`、`/models/{task_type}/inference-tasks` 和结果读取接口。

## 图编辑器和 UI 组件方向

- workflow 图编辑器底层采用 LiteGraph 方向，通过本项目自己的 adapter 接入，正式保存格式仍以 `WorkflowGraphTemplate` 和 `FlowApplication` 为准。
- LiteGraph 相关源码和薄封装放在 `frontend/web-ui/src/lib/litegraph`，业务侧只通过 workflow editor 的 graph-engine adapter 使用。
- UI primitives 采用 Reka UI，项目内在 `shared/ui` 沉淀自己的组件体系，不把 shadcn-vue 整套作为项目组件来源。
- 自定义节点的前端展示优先通过后端 `NodeDefinition.parameter_ui_schema`、payload 规则和 metadata 渲染，不在第一阶段允许 node pack 任意注入前端 JS。

## 状态组织原则

- 服务端最终状态优先，前端状态以查询结果、订阅视图和交互草稿为主
- 长任务状态通过 REST 快照与 WebSocket 事件结合维护
- 页面局部状态、全局会话状态和可缓存查询状态分层管理
- 节点编辑器状态与资源型页面状态分开组织，避免全局 store 过度膨胀

## 与后端服务的交互模型

### REST API

- 负责资源查询、配置提交、任务创建、取消、重试、启停和回滚动作

### WebSocket

- 负责任务状态、日志、进度、部署变化和告警事件订阅
- 路由组织、连接规则、重连方式和资源流分层统一遵循 [websocket-architecture.md](websocket-architecture.md)

### ZeroMQ

- 不直接暴露给浏览器前端
- 如现场需要同机本地 IPC，应由 backend-service 或本地服务封装后再对前端提供可消费视图

## 页面类型

### 资源管理页面

- 数据集、模型、部署、自定义节点和集成端点等资源型页面

### 任务与状态页面

- 任务列表、任务详情、日志、进度、失败原因和回写结果页面

### 流程与节点页面

- 节点编辑器、流程模板管理、节点参数面板和执行结果查看页面

### 结果与可视化页面

- 图像浏览、检测框叠加、指标图表、对比视图和过程结果可视化页面

## 自定义节点与前端的关系

- 前端应读取 backend-service 暴露的自定义节点目录、节点定义和 UI schema
- 自定义节点扩展的节点、参数面板和结果展示元数据应通过受控 schema 接入
- 前端不直接加载未登记的任意脚本来扩展核心界面

## 工业场景下的前端要求

- 面向浏览器界面，但需兼顾工控机、工作站和大屏使用场景
- 优先保证大图像浏览、稳定布局和低误操作成本
- 避免过度依赖云端资源、在线字体或外网 CDN
- 对弱网、局域网和离线部署有良好适配

## 推荐后续文档

- [docs/architecture/system-overview.md](system-overview.md)
- [docs/architecture/project-structure.md](project-structure.md)
- [docs/architecture/frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md)
- [docs/api/communication-contracts.md](../api/communication-contracts.md)
