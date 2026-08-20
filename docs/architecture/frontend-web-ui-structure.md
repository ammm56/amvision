# 浏览器前端工程结构

## 当前目录

```text
frontend/web-ui/
├─ public/                 运行配置模板和公开静态资源
├─ src/
│  ├─ app/                应用 bootstrap、router、Pinia 与根组件
│  ├─ config/             导航和静态配置
│  ├─ lib/                图引擎等底层库及薄适配
│  ├─ modules/            资源型业务模块
│  ├─ platform/           i18n、runtime config、浏览器存储和平台适配
│  ├─ shared/             API、contracts、UI、样式、格式化和 WebSocket
│  ├─ shells/             Workbench 与空白页面外壳
│  ├─ views/              Startup、Error、NotFound 等跨模块页面
│  └─ workflows/          Workflow App 与图编辑器业务流
├─ tests/                 前端测试资源
├─ playwright.config.ts   浏览器 E2E 配置
├─ vite.config.ts
└─ package.json
```

## 依赖方向

```text
views / shells / modules / workflows
                  ↓
          shared / platform / config
                  ↓
              lib / Vue ecosystem
```

约束：

- `shared` 不依赖具体业务页面。
- `modules` 不直接读取数据库、文件系统、ZeroMQ 或 Worker。
- `workflows/workflow-editor` 可以组合共享组件与业务资源选择器，但正式数据契约来自 `shared/contracts`。
- `platform` 只封装浏览器与发行环境差异，不承载模型或 Workflow 业务。
- API URL、WebSocket URL、默认项目和鉴权启动参数通过 runtime config 注入，不在页面中散落常量。

## 路由组织

`src/app/router/routes.ts` 汇总各模块路由；每个业务模块在自己的 `routes.ts` 内注册页面。Workflow 当前公开路由包括：

- `/workflows/apps`
- `/workflows/apps/:applicationId`
- `/workflows/graph/new`
- `/workflows/graph/apps/:applicationId`

旧 Template/Application 编辑路由只保留重定向，不再形成第二套 Workflow 编辑体验。

路由 `meta.requiredScopes` 是前端可见性门禁；后端仍执行最终权限校验。`meta.graphWorkbench` 用于切换图编辑器工作台外壳。

## 状态分层

- session store：当前主体、凭据、登录状态与 bootstrap。
- preferences store：主题、语言和本地偏好。
- 业务 store/composable：列表、详情、事件游标和操作状态。
- Workflow graph draft：节点、边、分组、参数、输入输出和未保存状态。
- 组件局部状态：展开、选择、弹窗、过滤和临时输入。

服务端状态不能只在前端乐观修改后长期保存；控制动作完成后应刷新对应资源快照。

## API 与类型

- `shared/api` 负责统一 base URL、token、刷新、错误解析和请求序列化。
- `shared/contracts` 保存与公开 API 对齐的 TypeScript 契约。
- `shared/ws` 负责 WebSocket 连接与事件消费。
- 业务模块 service 负责把公开 API 组合为页面动作，不在组件中散落请求字符串。

公开字段变化必须同步后端 schema、OpenAPI、前端 contract、页面 service 和测试。

## 测试边界

- Vitest：store、service、composable、组件和页面交互。
- `vue-tsc --noEmit`：模板与 TypeScript 契约。
- Vite build：生产静态资源。
- Playwright：鉴权、核心页面、Workflow 版本选择与浏览器错误门禁。

完整命令见 [开发指南](../development/README.md)。
