# 浏览器前端工程结构

## 文档目的

本文档用于定义 `frontend/web-ui` 的工程骨架、目录分层、命名规则、组件归属和图编辑器接入方式，为后续 Vue 3 前端代码实现提供直接依据。

[frontend-web-ui.md](frontend-web-ui.md) 说明前端职责和交互边界，本文档继续细化代码目录和模块关系。[frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md) 说明本地部署启动、默认用户、自动进入和退出规则。[frontend-web-ui-workflows.md](frontend-web-ui-workflows.md) 说明节点目录、业务流程、workflow app 调用和事件通信规则。[frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md) 说明真实编码前的准备检查和剩余缺口。

## 适用范围

- Vue 3 前端工程目录结构
- LiteGraph 在前端中的放置位置和使用边界
- Reka UI、本地 UI 组件和业务组件的分层关系
- `config`、`components`、`plugins`、`views` 等目录职责
- 本地启动、默认用户、AuthShell、session store 和 route guard 的文件归属
- workflow 图编辑器、普通业务模块和共享层的依赖方向
- 具体页面流程、节点映射和运行通信规则见 [frontend-web-ui-workflows.md](frontend-web-ui-workflows.md)
- 真实编码前的 runtime config、类型、权限、测试和发布规则见 [frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)

## 技术选择

- 前端主栈使用 Vue 3、TypeScript、Vite。
- 路由使用 Vue Router。
- 状态管理使用 Pinia。
- 通用组合式能力优先使用 VueUse。
- UI primitives 采用 Reka UI，项目内沉淀自己的 `shared/ui` 组件体系。
- 图编辑器底层走 LiteGraph 方向，通过本项目自己的 adapter 接入 workflow 编辑器。
- 图编辑器保存到后端时，正式格式仍以 `WorkflowGraphTemplate` 和 `FlowApplication` 为准，不以 LiteGraph 内部对象为公开格式。

## 参考项目边界

ComfyUI frontend 可作为图编辑器交互和工作台布局参考，但不直接复制其 GPL 实现代码。LiteGraph 相关源码如需放入仓库，应来自可接受的上游来源或项目自行维护版本，并在 `src/lib/litegraph/README.md` 记录来源、版本、license 和本地修改。

Dify 可作为后续 LLM、VLM、agent、工具节点、人机输入和模型 provider 管理的产品参考，但本项目第一阶段不按 Dify 的 React/Next 工程形态实现，也不把前端定位成通用 AI 应用平台。

## 顶层工程目录

前端工程固定放在仓库内的 `frontend/web-ui`：

```text
frontend/
└─ web-ui/
   ├─ public/
   ├─ src/
   ├─ index.html
   ├─ package.json
   ├─ vite.config.ts
   ├─ tsconfig.json
   ├─ .env.example
   └─ README.md
```

`frontend/web-ui` 是独立前端工程。后端服务、worker、custom_nodes 不直接 import 前端源码；发布时由 release 组装复制前端构建结果。

## src 目录总览

```text
src/
├─ main.ts
├─ app/
├─ config/
├─ shells/
├─ modules/
├─ workflows/
├─ shared/
├─ platform/
├─ plugins/
├─ lib/
└─ views/
```

各目录职责如下：

| 目录 | 职责 |
| --- | --- |
| `app` | Vue 应用装配、Router、Pinia、启动流程和全局守卫 |
| `config` | 前端运行配置、导航配置、feature flags 和常量配置 |
| `shells` | 页面骨架、工作台布局、导航、顶部栏、侧栏和底部面板 |
| `modules` | 数据集、任务、模型、部署、集成、自定义节点和设置等资源模块 |
| `workflows` | 跨模块操作流，尤其是 workflow 图编辑、运行和发布链路 |
| `shared` | 通用 UI、API client、WebSocket client、类型、工具和组合式函数 |
| `platform` | 鉴权、运行环境、浏览器存储、诊断和发布形态适配 |
| `plugins` | 受控前端插件注册层，用于结果查看器、参数编辑器等内置扩展点 |
| `lib` | 第三方或底层库源码与薄封装，例如 LiteGraph |
| `views` | 顶层通用视图，例如启动页、错误页和 404 页 |

## 依赖方向

前端目录依赖方向固定为：

```text
app
 ↓
shells
 ↓
modules / workflows
 ↓
shared
 ↓
platform / config / lib
```

细化规则如下：

- `app` 可以引用 `shells`、`modules`、`workflows`、`platform` 和 `config`。
- `shells` 可以引用 `shared`、`platform` 和模块暴露的路由信息。
- `modules` 可以引用 `shared`、`platform` 和 `config`。
- `workflows` 可以引用 `shared`、`platform`、`config` 和 `lib/litegraph`。
- `shared` 不引用 `modules` 和 `workflows`。
- `lib` 不引用业务目录。
- `plugins` 可以引用 `shared`，但不反向控制 `app` 启动流程。
- 普通模块之间不互相 import 内部组件；确实需要共享时，下沉到 `shared`。

## app 目录

`app` 负责应用启动和全局装配，不放业务页面。

```text
src/app/
├─ App.vue
├─ bootstrap.ts
├─ router/
│  ├─ index.ts
│  ├─ routes.ts
│  └─ guards.ts
└─ stores/
   ├─ app.store.ts
   ├─ session.store.ts
   └─ project.store.ts
```

职责说明：

- `App.vue`：应用根组件，只挂载当前 shell 和全局基础组件。
- `bootstrap.ts`：装配 Pinia、Router、UI 插件、全局错误处理和启动检查。
- `router`：聚合模块路由、设置鉴权守卫和默认跳转。
- `stores`：只放应用级状态，例如当前 Project、后端连接状态和用户 session 摘要。

## config 目录

`config` 只放前端运行配置，不放业务逻辑。

```text
src/config/
├─ app.config.ts
├─ api.config.ts
├─ auth.config.ts
├─ navigation.config.ts
└─ feature-flags.ts
```

职责说明：

- `app.config.ts`：应用名称、默认语言、版本显示和默认工作台行为。
- `api.config.ts`：REST API base URL、WebSocket base URL、请求超时和文件访问前缀。
- `auth.config.ts`：自动进入、默认用户名显示、token 存储策略和登录页行为配置。
- `navigation.config.ts`：侧栏导航、模块入口、图标和可见性规则。
- `feature-flags.ts`：前端功能开关，服务于阶段性启用和现场部署裁剪。

构建配置继续放在 `frontend/web-ui` 根目录，例如 `vite.config.ts`、`tsconfig.json` 和 `.env.example`。

## shells 目录

`shells` 负责页面骨架，不直接实现数据集、任务、模型等业务细节。

```text
src/shells/
├─ workbench/
│  ├─ WorkbenchShell.vue
│  └─ components/
│     ├─ AppTopbar.vue
│     ├─ AppSidebar.vue
│     ├─ AppBottomPanel.vue
│     ├─ ProjectSwitcher.vue
│     └─ ConnectionStatus.vue
├─ auth/
│  └─ AuthShell.vue
└─ blank/
   └─ BlankShell.vue
```

职责说明：

- `workbench`：主工作台骨架，承载侧栏、顶部栏、底部面板和路由内容区。
- `auth`：登录、初始化和无会话状态页面骨架。
- `blank`：错误页、启动页和少量不需要完整工作台的页面骨架。

## modules 目录

`modules` 放资源型业务模块。每个模块保持同一套内部结构。

```text
src/modules/
├─ auth/
├─ projects/
├─ datasets/
├─ tasks/
├─ models/
├─ deployments/
├─ integrations/
├─ custom-nodes/
└─ settings/
```

`modules/auth` 只放人工登录、退出后重新进入、用户管理和 token 管理页面。默认本地部署的自动进入流程由 `app/bootstrap.ts`、`app/stores/session.store.ts` 和 `platform/auth` 负责，不把登录页作为常规首屏。

普通模块标准结构如下：

```text
modules/tasks/
├─ pages/
│  ├─ TaskListPage.vue
│  └─ TaskDetailPage.vue
├─ components/
│  ├─ TaskStatusBadge.vue
│  ├─ TaskEventTimeline.vue
│  └─ TaskLogPanel.vue
├─ services/
│  └─ task.service.ts
├─ stores/
│  └─ task.store.ts
├─ composables/
│  └─ useTaskEvents.ts
├─ routes.ts
└─ types.ts
```

目录职责：

- `pages`：路由页面，直接挂到 Router。
- `components`：只服务当前模块的业务组件。
- `services`：封装当前模块的后端 API 调用，底层使用 `shared/api`。
- `stores`：当前模块的 Pinia 状态，主要保存列表、详情、筛选和页面草稿。
- `composables`：当前模块的复用逻辑，例如事件订阅、筛选同步和详情刷新。
- `routes.ts`：当前模块的路由声明。
- `types.ts`：当前模块自己的前端类型，优先复用 `shared/contracts` 中的公开类型。

## workflows 目录

`workflows` 放跨模块操作流和 workflow 图编辑器。它不同于普通资源模块，允许同时组合 node catalog、任务、部署、运行记录和结果查看能力。

```text
src/workflows/
├─ workflow-editor/
├─ training-release/
├─ deployment-debug/
└─ trigger-source-setup/
```

第一阶段优先实现 `workflow-editor`，其他目录可按页面实际推进再创建。

### workflow-editor 结构

```text
workflows/workflow-editor/
├─ pages/
│  ├─ WorkflowEditorPage.vue
│  ├─ WorkflowTemplateListPage.vue
│  ├─ WorkflowApplicationListPage.vue
│  └─ WorkflowRunDetailPage.vue
├─ canvas/
│  ├─ WorkflowCanvas.vue
│  ├─ graph-engine/
│  │  ├─ litegraph-adapter.ts
│  │  ├─ graph-model.ts
│  │  ├─ graph-commands.ts
│  │  ├─ graph-selection.ts
│  │  └─ graph-events.ts
│  ├─ overlays/
│  ├─ context-menu/
│  └─ styles/
├─ palette/
│  ├─ NodePalette.vue
│  ├─ NodeSearch.vue
│  └─ NodeCategoryTree.vue
├─ inspector/
│  ├─ NodeInspector.vue
│  ├─ GraphInspector.vue
│  └─ fields/
├─ run-panel/
│  ├─ PreviewRunPanel.vue
│  ├─ WorkflowRunEvents.vue
│  └─ RuntimeStatusPanel.vue
├─ result-viewer/
│  ├─ ResultViewer.vue
│  ├─ ImageResultView.vue
│  ├─ DetectionResultView.vue
│  └─ JsonResultView.vue
├─ adapters/
│  ├─ graph-to-template.ts
│  ├─ template-to-graph.ts
│  ├─ application-adapter.ts
│  └─ node-catalog-adapter.ts
├─ services/
│  ├─ node-catalog.service.ts
│  ├─ workflow-template.service.ts
│  ├─ workflow-application.service.ts
│  └─ workflow-runtime.service.ts
├─ stores/
│  ├─ node-catalog.store.ts
│  ├─ graph-draft.store.ts
│  ├─ workflow-editor.store.ts
│  └─ workflow-run.store.ts
├─ composables/
│  ├─ useNodeCatalog.ts
│  ├─ useWorkflowPreviewRun.ts
│  └─ useWorkflowRunEvents.ts
├─ routes.ts
└─ types.ts
```

边界说明：

- `canvas/graph-engine` 只处理 LiteGraph 和画布行为。
- `adapters` 负责前端图状态与后端 `WorkflowGraphTemplate`、`FlowApplication` 的互相转换。
- `palette` 消费 `/api/v1/workflows/node-catalog`，不重新定义节点加载规则。
- `inspector` 根据 `NodeDefinition.parameter_schema` 和 `parameter_ui_schema` 渲染参数表单。
- `run-panel` 通过 REST 创建 PreviewRun、WorkflowRun，并通过 WebSocket 消费事件。
- `result-viewer` 展示图片、检测框、表格、JSON 和后续更多结果类型。

## shared 目录

`shared` 放跨模块复用能力。它不能引用任何 `modules` 或 `workflows` 目录。

```text
src/shared/
├─ ui/
├─ api/
├─ ws/
├─ contracts/
├─ composables/
├─ utils/
├─ styles/
└─ icons/
```

### shared/ui

`shared/ui` 是项目自己的 UI 组件层，底层可使用 Reka UI primitives。

```text
shared/ui/
├─ primitives/
├─ components/
├─ data-display/
├─ feedback/
├─ layout/
├─ form/
└─ tokens/
```

职责说明：

- `primitives`：对 Reka UI 的薄封装。
- `components`：Button、IconButton、Input、Select、Tabs、Tooltip、Popover、Menu。
- `data-display`：DataTable、StatusBadge、MetricStrip、KeyValueGrid。
- `feedback`：Toast、InlineError、EmptyState、ConfirmDialog。
- `layout`：Panel、Splitter、Toolbar、SidebarSection、PageHeader。
- `form`：SchemaForm、FieldRow、NumberField、SwitchField。
- `tokens`：颜色、尺寸、状态色、z-index、间距和阴影。

不把 shadcn-vue 整套作为项目组件体系。需要的组件样式可以参考 shadcn-vue 的组织方式，但代码以项目本地组件为准。

### shared/api

```text
shared/api/
├─ http-client.ts
├─ error.ts
├─ pagination.ts
├─ auth-header.ts
├─ file-url.ts
└─ generated/
```

`shared/api` 只处理 HTTP 细节，不放业务资源语义。业务语义放在模块自己的 `services` 中。

### shared/ws

```text
shared/ws/
├─ resource-stream-client.ts
├─ cursor.ts
├─ reconnect.ts
├─ message.ts
└─ errors.ts
```

WebSocket 使用“REST 快照 + WebSocket 增量”的模式。`shared/ws` 负责连接、重连、cursor、心跳和 lagging 处理；具体事件如何更新页面状态，由模块 composable 决定。

推荐流向：

```text
WebSocket event
-> shared/ws/resource-stream-client
-> modules/tasks/composables/useTaskEvents
-> modules/tasks/stores/task.store.ts
-> page/component
```

## platform 目录

`platform` 放运行环境适配，不放业务页面。

```text
src/platform/
├─ auth/
├─ runtime/
├─ storage/
└─ diagnostics/
```

职责说明：

- `auth`：登录 token、refresh、长期调用 token 和权限 scope 的前端适配。
- `auth`：同时负责默认 user token 自动进入、`manualLoginRequired` 标记、logout 语义和 refresh 恢复。
- `runtime`：standalone、workstation、edge、online 等前端运行形态判断。
- `storage`：localStorage、sessionStorage、IndexedDB 等浏览器存储封装。
- `diagnostics`：前端错误收集、连接诊断和调试信息导出。

## plugins 目录

`plugins` 是受控前端插件注册层，不等同于 ComfyUI 式任意前端扩展。

```text
src/plugins/
├─ registry.ts
├─ types.ts
└─ builtin/
   ├─ image-result.plugin.ts
   ├─ detection-result.plugin.ts
   ├─ table-result.plugin.ts
   └─ json-result.plugin.ts
```

第一阶段用途：

- 注册内置结果查看器，例如图片、检测框、表格、JSON。
- 注册特殊参数编辑器，例如模型选择、颜色阈值、ROI 配置。
- 注册工作台面板扩展，例如任务事件、运行日志和运行结果。

第一阶段不允许 node pack 自带 JS 任意注入前端。自定义节点的前端展示先通过后端 `NodeDefinition.parameter_ui_schema`、payload 规则和 metadata 渲染。后续如需开放第三方前端插件，应补充签名、版本、权限、禁用和发布装配规则。

## lib 目录

`lib` 放第三方或底层库源码与薄封装，不放业务逻辑。

```text
src/lib/
└─ litegraph/
   ├─ README.md
   ├─ litegraph.ts
   ├─ litegraph.css
   ├─ types.ts
   └─ patches/
```

LiteGraph 使用规则：

- `src/lib/litegraph` 只保存 LiteGraph 源码、样式、类型补充和小补丁。
- `workflows/workflow-editor/canvas/graph-engine/litegraph-adapter.ts` 是业务侧访问 LiteGraph 的唯一入口。
- 普通模块、共享组件和业务 service 不直接 import LiteGraph。
- 后端保存格式不使用 LiteGraph 内部 JSON，必须通过 `adapters` 转成后端 workflow JSON。
- `README.md` 必须记录 LiteGraph 来源、版本、license 和本地修改说明。

## views 目录

`views` 只放顶层通用视图，不承载业务资源页面。

```text
src/views/
├─ StartupView.vue
├─ ErrorView.vue
└─ NotFoundView.vue
```

业务页面放在模块自己的 `pages` 目录。例如：

```text
src/modules/tasks/pages/TaskListPage.vue
src/modules/deployments/pages/DeploymentDetailPage.vue
src/workflows/workflow-editor/pages/WorkflowEditorPage.vue
```

## 路由组织

路由由 `app/router/routes.ts` 聚合，各模块只暴露自己的 `routes.ts`。

建议第一阶段路由：

```text
/
/projects
/tasks
/tasks/:taskId
/datasets
/models
/deployments
/deployments/:deploymentInstanceId
/workflows/templates
/workflows/templates/:templateId/versions/:templateVersion/edit
/workflows/applications
/workflows/runs/:workflowRunId
/integrations/trigger-sources
/custom-nodes
/settings
/login
```

路由页面都应经过 `WorkbenchShell`，登录、启动和错误页除外。`/login` 只在手动退出、默认 token 失效或后端要求人工登录时使用。

## 状态组织

Pinia store 分三类：

- 应用级 store：登录态、默认自动进入状态、当前 Project、后端连接状态、全局配置。
- 查询级 store：资源列表、分页、筛选、详情缓存。
- 草稿级 store：表单草稿、workflow 图草稿、当前选中节点和未保存状态。

长期任务状态以后端 REST 快照为准，WebSocket 只作为增量更新来源。前端不自行判定任务最终状态，也不把本地状态当成最终事实。

## 第一阶段实现顺序

1. 创建 `frontend/web-ui` 工程骨架。
2. 建立 `app`、`config`、`shells`、`shared/api`、`shared/ws`、`shared/ui` 基础目录。
3. 固定 runtime config、OpenAPI 类型生成、API client、WebSocket client、权限映射和测试命令。
4. 实现启动流程、默认 user token 自动进入、`manualLoginRequired`、AuthShell 和 route guard。
5. 实现 `WorkbenchShell`、Project 上下文和后端连接状态。
6. 实现 Tasks 列表、详情和 WebSocket 事件流。
7. 实现 Project files metadata、图片预览和下载封装。
8. 实现 Datasets 导入、导出和 DatasetVersion 详情。
9. 实现 Deployments 列表、详情、health、start、stop、warmup。
10. 实现 Custom Nodes 和 node catalog 只读页面。
11. 接入 LiteGraph 基础库和 `workflow-editor/canvas/graph-engine` adapter。
12. 实现最小 workflow 编辑器：节点 palette、画布、连线、参数面板。
13. 实现 template validate/save/load。
14. 实现 PreviewRun 调试面板、事件流和结果查看。
15. 实现 AppRuntime、WorkflowRun 和 TriggerSource 生产调用页面。
16. 将前端构建结果接入 release 组装。

## 不做事项

- 不直接复制 ComfyUI frontend 的实现代码。
- 不把 LiteGraph 内部 JSON 当成后端公开保存格式。
- 不把所有页面放进顶层 `views`。
- 不把所有组件放进一个顶层 `components` 目录。
- 不开放 node pack 任意前端 JS 注入。
- 不让浏览器前端直接访问 ZeroMQ、LocalBufferBroker、数据库或对象存储内部路径。
- 不让 `shared` 反向依赖业务模块。
- 不把登录页作为本地生产环境默认首屏。
- 不在用户明确退出后继续自动使用默认 user token。

## 推荐同步文档

- [frontend-web-ui.md](frontend-web-ui.md)
- [frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md)
- [frontend-web-ui-workflows.md](frontend-web-ui-workflows.md)
- [frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)
- [project-structure.md](project-structure.md)
- [workflow-runtime.md](workflow-runtime.md)
- [node-system.md](node-system.md)
- [websocket-architecture.md](websocket-architecture.md)
- [docs/api/websocket-usage.md](../api/websocket-usage.md)
