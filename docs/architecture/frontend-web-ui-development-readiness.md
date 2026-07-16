# 浏览器前端开发准备检查

## 文档目的

本文档用于检查浏览器前端 Web UI 当前规划是否足够支撑 `frontend/web-ui` 的真实代码实现，并把开工前仍需固定的配置、类型、权限、测试、发布和 UI 状态规则整理成执行清单。

[frontend-web-ui.md](frontend-web-ui.md) 定义前端职责边界，[frontend-web-ui-structure.md](frontend-web-ui-structure.md) 定义工程目录，[frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md) 定义启动会话，[frontend-web-ui-workflows.md](frontend-web-ui-workflows.md) 定义业务流程和节点通信。本文档只回答“是否足够开工、还缺什么、下一步怎么收口”。

## 当前判断

当前规划已经足够开始创建 `frontend/web-ui` 工程骨架，并实现下面这些基础能力：

- Vue 3、TypeScript、Vite、Pinia、Vue Router 和 Reka UI 基础装配。
- `app`、`config`、`shells`、`modules`、`workflows`、`shared`、`platform`、`plugins`、`lib`、`views` 目录分层。
- 本地默认用户 `amvar`、默认长期 user token 自动进入、退出后手动登录标记和 AuthShell。
- WorkbenchShell、Project 上下文、REST client、WebSocket client 和后端连接状态。
- Tasks 列表与详情，作为 REST 快照加 WebSocket 增量模式的第一条落地链路。

当前规划还不足以直接完成整个 workflow editor、结果查看器、权限控制和发布装配。下面这些规则需要在对应模块开工前固定，避免后续反复改目录、改状态模型或改 API client。

## 必须先固定的事项

### runtime config

前端启动必须先读取 runtime config，再调用 `GET /api/v1/system/bootstrap`。

建议固定为：

- 开发模板：`frontend/web-ui/public/runtime-config.template.json`
- 本地开发副本：`frontend/web-ui/public/runtime-config.local.json`
- 发布结果：`release/full/frontend/runtime-config.json`
- 前端加载路径：`/runtime-config.json`，读取失败时回退到 Vite 环境变量和默认 localhost 配置

建议字段：

```json
{
  "apiBaseUrl": "http://127.0.0.1:5600/api/v1",
  "wsBaseUrl": "ws://127.0.0.1:5600/ws/v1",
  "defaultProjectId": "project-1",
  "auth": {
    "autoLoginEnabled": true,
    "defaultUsername": "amvar",
    "defaultUserToken": null,
    "manualLoginRequiredKey": "amvision.web-ui.manual-login-required"
  },
  "storage": {
    "sessionTokenStorage": "sessionStorage",
    "manualLoginStorage": "localStorage"
  },
  "features": {
    "workflowEditor": true,
    "customNodeManagement": false
  }
}
```

规则：

- 默认 user token 不写入业务源码和 Git 管理的模板文件。
- 本地发布包可以由 launcher 或 backend-service 在发布目录生成 `runtime-config.json`。
- `defaultUserToken` 为空时，前端按人工登录流程处理。
- runtime config 不替代 `system/bootstrap`，后端返回的 `auth_mode`、`providers`、`visible_projects` 和 `capabilities` 仍是正式首屏依据。

### 类型来源

第一阶段建议采用“OpenAPI 生成类型 + 少量手写前端类型”的组合。

建议目录：

```text
src/shared/contracts/
├─ generated/
│  └─ api.ts
├─ websocket.ts
├─ workflow-ui.ts
├─ runtime-config.ts
└─ index.ts
```

规则：

- REST 请求和响应类型优先从 `/openapi.json` 生成。
- 生成文件可以提交到仓库，保证没有运行后端时也能执行前端类型检查和构建。
- WebSocket 消息、runtime config、LiteGraph adapter 内部类型和 UI draft 类型由前端手写。
- 模块 `types.ts` 只能扩展页面草稿、筛选条件和展示模型，不重复定义后端返回结构。
- OpenAPI 生成命令和后端版本要写入 `frontend/web-ui/README.md`。

### API client

`shared/api` 必须先收口统一行为，再让模块 service 使用。

必须覆盖：

- Bearer token 注入。
- 401 refresh 和并发锁。
- 403 权限不足状态，不自动跳回登录页。
- 统一分页响应头解析：`x-offset`、`x-limit`、`x-total-count`、`x-has-more`、`x-next-offset`。
- multipart 上传。
- blob 下载。
- JSON 错误响应归一化。
- request id 和后端错误详情透传到诊断面板。

模块 service 只表达业务资源语义，例如 `task.service.ts`、`dataset.service.ts`、`workflow-runtime.service.ts`，不重复写 token、分页和错误处理。

### WebSocket client

`shared/ws` 必须先实现资源流通用模型。

建议最小状态：

- `resourceId`
- `stream`
- `connected`
- `stale`
- `lastBusinessCursor`
- `lastBusinessOccurredAt`
- `lastDisconnectReason`
- `reconnectAttempt`
- `lastError`

规则：

- 连接前先读 REST 详情或 summary。
- `*.connected`、`*.heartbeat`、`*.lagging` 不写业务状态。
- preview-runs、runs、app-runtimes、deployments 使用业务 cursor 恢复。
- projects.events 不使用 `after_cursor`，断线后重新读取 Project summary。
- token refresh 成功后重建连接。
- WebSocket 401 或 4401 进入会话恢复流程，403 或 4403 进入权限不足状态。

### 公开文件和结果查看

图片和结果文件必须通过 Project 公开文件接口读取，不直接拼 ObjectStore 内部路径。

建议封装：

```text
src/shared/api/file-url.ts
src/shared/composables/useObjectFile.ts
src/workflows/workflow-editor/result-viewer/
```

规则：

- 已知 `object_key` 时，先调用 `GET /api/v1/projects/{project_id}/files/metadata` 取 `content_url` 和 `download_url`。
- 已知 `file_id` 时，可以从文件列表或 metadata 结果复用。
- 如果文件内容接口需要 Bearer token，图片预览使用 `fetch` 加 Authorization，再生成 browser object URL。
- object URL 要在组件卸载或资源切换时 revoke。
- 下载同样走 `fetch` 加 Authorization，再触发本地下载。
- sync preview run 的 `node_records.outputs`、`outputs` 和 `template_outputs` 属于即时响应数据；如果里面直接带 inline base64，editor 可以直接渲染，不需要走持久化回放逻辑。
- `memory image-ref` 只显示摘要和短期有效提示，不当作可长期打开的图片。
- 脱敏 base64 只显示脱敏状态，不尝试还原。

### 权限和可见性

前端不新增角色系统，只消费 `current_user.scopes` 和 `project_ids`。

建议第一阶段 scope 映射：

| 前端区域 | 读取 scope | 写入 scope |
| --- | --- | --- |
| Projects 和工作台 summary | `workflows:read` + `models:read` | `datasets:write` 或 `workflows:write` |
| Datasets | `datasets:read` | `datasets:write` |
| Tasks | `tasks:read` | `tasks:write` |
| Models、Validation、Conversion | `models:read` 或 `tasks:read` | `models:write` 或 `tasks:write` |
| Deployments | `models:read` | `models:write` |
| Workflows | `workflows:read` | `workflows:write` |
| Settings 用户和 token 管理 | `auth:read` | `auth:write` |
| System diagnostics | `system:read` | 无 |

规则：

- 导航可见性按读取 scope 控制。
- 创建、保存、删除、启停、取消、重试按钮按写入 scope 控制。
- 训练任务按钮还必须读取后端 `available_actions` 和 `control_status`。
- 资源详情页收到 403 时显示权限不足，不清理登录态。
- Project 可见性由后端 `project_ids` 裁剪，前端只显示当前主体可见 Project。

### UI 状态

每个页面都需要固定一套通用状态，不把异常状态临时散落在组件里。

页面状态：

- `loading`
- `ready`
- `empty`
- `error`
- `forbidden`
- `offline`
- `stale`

长任务状态：

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`
- `unknown`

连接状态：

- `connecting`
- `connected`
- `reconnecting`
- `stale`
- `disconnected`
- `permission-denied`

规则：

- 弱网或 WebSocket 断线时，页面保持 REST 快照并标记 stale，不清空主体内容。
- 业务动作提交后显示 pending 状态，直到 REST 快照或事件确认。
- 错误提示必须保留后端 message、error code、request id 和可见的诊断入口。
- 表格、详情页、图编辑器、结果查看器都要有空状态和失败状态。

### 表单和参数 UI schema

`parameter_ui_schema` 进入真实编码前需要固定字段组件清单。

第一阶段建议支持：

- text
- textarea
- number
- integer
- boolean
- select
- multi-select
- slider
- file-ref
- image-ref
- dataset-export-select
- model-version-select
- deployment-select
- roi-editor
- color-threshold
- json-editor

规则：

- 基础字段放 `shared/ui/form`。
- 业务字段放 workflow editor 的 `inspector/fields` 或受控 `plugins/builtin`。
- 不支持的字段组件使用 JSON editor 兜底。
- 保存、validate 和 preview run 前都交给后端做最终校验。

### 测试策略

前端工程创建时应同步建立最小测试工具链。

建议工具：

- Vitest：纯函数、Pinia store、adapter、API client。
- Vue Test Utils：组件状态和交互。
- Playwright：启动、自动进入、退出后登录、任务详情、WebSocket 恢复、workflow editor 基础交互。
- MSW 或本地 mock adapter：前端单元和组件测试隔离后端。

第一批测试：

- runtime config 加载和默认值回退。
- 默认 user token 自动进入。
- user-token 退出不调用 logout，并写入手动登录标记。
- session token 401 refresh 只触发一次并发刷新。
- 403 显示权限不足。
- 分页响应头解析。
- Project 文件 metadata 到 image object URL 的转换和 revoke。
- WebSocket heartbeat 不推进业务 cursor。
- graph-to-template 和 template-to-graph 往返。
- 缺失节点、端口错误和参数错误的显示。

### 构建和发布

`release/full/frontend` 当前只是占位目录。前端工程创建后，需要把 Vite build 结果接入 `assemble-release`。

建议规则：

- 前端构建输出目录固定为 `frontend/web-ui/dist`。
- release 组装复制 `frontend/web-ui/dist/**` 到 `release/full/frontend/`。
- 发布目录必须包含 `runtime-config.json`。
- 后端服务需要能托管前端静态资源，或 launcher 明确启动静态资源服务。
- `validate-layout` 应检查 `frontend/index.html`、主要静态资源和 runtime config 是否存在。
- 发布验证要覆盖前端静态资源、REST health、`system/bootstrap` 和至少一条 WebSocket 订阅。

## 可以边做边补的事项

下面事项不阻塞创建工程骨架，但会影响对应模块质量，应在模块开工前补齐：

- LiteGraph 上游来源、版本、license、本地补丁和升级记录。
- result-viewer 第一批真实示例数据。
- workflow validate 错误定位字段。如果后端暂时只返回全局错误，前端先显示全局错误和相关节点 id。
- Custom Nodes enable、disable、rollback 管理 API。第一阶段仍只做只读目录。
- 训练、验证、评估、转换、部署和 workflow runtime 的操作向导细节。
- 工控机触屏尺寸、深色模式、高对比状态色和大图浏览性能测试。
- 在线账号 provider 接入点。第一阶段只保留结构，不实现完整在线登录。

## 第一阶段开工顺序修订

建议把第一阶段拆成三个小阶段。

### 1. 基础壳层

1. 创建 `frontend/web-ui` 工程。
2. 固定 package manager、Node 版本、lint、format、typecheck、test 和 build 命令。
3. 实现 runtime config 加载。
4. 实现 API client、session store、AuthShell、route guard。
5. 实现 WorkbenchShell、Project 选择、后端连接状态和全局错误入口。

### 2. 第一条业务闭环

1. 实现 Projects 列表和 Project summary。
2. 实现 Tasks 列表、详情、事件历史和 WebSocket 订阅。
3. 实现 Project files metadata、图片预览和下载封装。
4. 验证自动进入、退出后登录、403、离线和 WebSocket 重连。

### 3. 视觉平台主链路

1. Datasets 导入、导出和 DatasetVersion 详情。
2. detection training 任务创建、详情、控制按钮和输出文件。
3. Validation、Evaluation、Conversion 和 Deployment 详情。
4. Custom Nodes 只读目录和 node catalog。
5. Workflow editor、PreviewRun、AppRuntime 和 WorkflowRun。
6. release 组装前端构建产物。

## 开工结论

当前规划可以支持前端项目开始开发，但建议先以“基础壳层 + 第一条业务闭环”为目标，不直接冲完整 workflow editor。

开工前最小必备项是：runtime config、默认 user token 自动进入、API client、WebSocket client、权限映射、Project 文件读取封装、测试命令和 release 前端目录规则。完成这些后，再进入数据集、模型、部署和 workflow editor 会更稳。
