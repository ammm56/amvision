# Vue 3 前端实现交接

## 1. 目的

本文把 30 个前端页面设计编号映射到 Vue 3 路由、页面组件、权限、后端资源、实时状态和设计图。实现时以当前代码和公开 API 为事实来源，设计图只决定信息层级、视觉密度和交互表达。

当前前端基线：Vue 3、TypeScript、Vite、Pinia、Vue Router。默认服务地址来自 `runtime-config.ts`，REST 是资源最终依据，WebSocket 只补充实时状态和事件。

实现状态：

- `现有`：已有独立路由和页面组件，应按设计图增强。
- `嵌入`：能力已在聚合页内，应提取为可路由向导或保留嵌入入口并增加深链接。
- `规划`：设计和后端资源已存在，但没有独立前端页面。
- `系统`：启动、登录、离线、无权限和未找到页面。

## 2. 实现事实入口

- 路由总表：[app/router/routes.ts](../../../frontend/web-ui/src/app/router/routes.ts)
- 路由守卫：[app/router/guards.ts](../../../frontend/web-ui/src/app/router/guards.ts)
- 导航：[config/navigation.config.ts](../../../frontend/web-ui/src/config/navigation.config.ts)
- REST 客户端：[shared/api/http-client.ts](../../../frontend/web-ui/src/shared/api/http-client.ts)
- WebSocket 客户端：[shared/ws/resource-stream-client.ts](../../../frontend/web-ui/src/shared/ws/resource-stream-client.ts)
- 运行时地址：[platform/runtime/runtime-config.ts](../../../frontend/web-ui/src/platform/runtime/runtime-config.ts)
- 当前用户与 scope：[app/stores/session.store.ts](../../../frontend/web-ui/src/app/stores/session.store.ts)
- 当前项目：[app/stores/project.store.ts](../../../frontend/web-ui/src/app/stores/project.store.ts)
- 视觉与组件规则：[03-visual-component-system.md](03-visual-component-system.md)
- 逐页规格：[04-page-specifications.md](04-page-specifications.md)
- 设计图索引：[generated/README.md](generated/README.md)

## 3. 路由和页面矩阵

### 3.1 系统入口

| 编号 | 页面 | 当前/目标路由 | 页面组件 | 状态 | 权限 | 后端事实来源 | 设计参考 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | 启动检查 | `/` | `views/StartupView.vue` | 系统 | 无登录要求 | `/system/bootstrap`、`/system/health`、会话恢复 | [检查中](generated/00-foundation/S01_startup-check_light_checking_v01.png) |
| S02 | 本地登录 | `/login` | `modules/auth/pages/LoginPage.vue` | 系统 | 无登录要求 | `/auth/login`、`/auth/refresh`、`/auth/logout`、provider 与 bootstrap admin 状态 | [手动登录](generated/00-foundation/S02_login_light_manual_v01.png) |
| S03 | 离线/403/404 | `/offline`、`/forbidden`、catch-all | `views/ErrorView.vue`、`views/NotFoundView.vue` | 系统 | 无登录要求 | 路由守卫、REST 错误对象、最后连接状态 | [离线](generated/00-foundation/S03_system-state_light_offline_v01.png)、[403](generated/00-foundation/S03_system-state_light_forbidden_v01.png)、[404](generated/00-foundation/S03_system-state_light_not-found_v01.png) |

实现约束：启动失败不能自动进入业务壳层；离线页保留最后一次只读状态但禁用写操作；403 不提供在线申请权限流程；404 必须显示资源类型、ID 和正确返回路径。

### 3.2 项目与任务

| 编号 | 页面 | 当前/目标路由 | 页面组件 | 状态 | 读取/写入 scope | 资源与接口 | 设计参考 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P01 | 项目列表 | `/projects` | `modules/projects/pages/ProjectListPage.vue` | 现有 | `workflows:read` + `models:read`；创建需要 `datasets:write` 或 `workflows:write`；删除需要 `projects:delete` | `/projects`、`/projects/bootstrap`、deletion-preview、SDK config package | [标准](generated/01-projects-tasks/P01_project-list_light_drawer_v01.png)、[空](generated/01-projects-tasks/P01_project-list_light_empty_v01.png) |
| P02 | 项目概览 | 目标 `/projects/:projectId` | `modules/projects/pages/ProjectOverviewPage.vue` | 规划 | 继承项目可见性；操作按目标资源 scope | `/projects/{id}/summary`，DatasetVersion、ModelVersion、DeploymentInstance、WorkflowAppRuntime 摘要 | [概览](generated/01-projects-tasks/P02_project-overview_light_active_v01.png) |
| T01 | 任务中心 | `/tasks` | `modules/tasks/pages/TaskListPage.vue` | 现有 | `tasks:read`；取消需要 `tasks:write` | `/tasks`，WS `/tasks/events` | [运行](generated/01-projects-tasks/T01_task-center_light_running_v01.png)、[失败](generated/01-projects-tasks/T01_task-center_light_failed_v01.png)、[空](generated/01-projects-tasks/T01_task-center_light_empty_v01.png) |
| T02 | 通用任务详情 | `/tasks/:taskId` | `modules/tasks/pages/TaskDetailPage.vue` | 现有 | `tasks:read`；取消需要 `tasks:write` | `/tasks/{id}`、`/tasks/{id}/events`、`/tasks/{id}/cancel` | [转换失败](generated/01-projects-tasks/T02_task-detail_light_conversion-failed_v01.png) |

P02 不应重新聚合一套独立业务模型。项目概览只读取各领域摘要并链接到权威页面。T01/T02 只展示有开始和结束的 `TaskRecord`，不把长期 `DeploymentInstance` 或 `WorkflowAppRuntime` 当作任务。

### 3.3 数据集

| 编号 | 页面 | 当前/目标路由 | 页面组件 | 状态 | 读取/写入 scope | 资源与接口 | 设计参考 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | 数据集工作台 | `/datasets` | `modules/datasets/pages/DatasetOperationsPage.vue` | 现有 | `datasets:read` / `datasets:write` | `/datasets/imports`、`/datasets/versions`、`/datasets/exports`、`/datasets/export-formats` | [标准](generated/02-datasets/D01_dataset-workbench_light_populated_v01.png)、[空](generated/02-datasets/D01_dataset-workbench_light_empty_v01.png) |
| D02 | 导入向导 | 当前嵌入 D01；目标 `/datasets/imports/new` | 现有 `DatasetImportForm.vue`，目标 `DatasetImportWizardPage.vue` | 嵌入 | `datasets:read` / `datasets:write` | `POST /datasets/imports`，格式能力与 preflight 响应 | [预检查](generated/02-datasets/D02_import-wizard_light_preflight_v01.png) |
| D03 | 导入详情 | `/datasets/imports/:datasetImportId` | `DatasetImportDetailPage.vue` | 现有 | `datasets:read` / `datasets:write` | `/datasets/imports/{id}`、关联 TaskRecord、生成的 DatasetVersion | [成功](generated/02-datasets/D03_import-detail_light_success_v01.png) |
| D04 | 数据版本详情 | 目标 `/datasets/versions/:datasetVersionId` | `DatasetVersionDetailPage.vue` | 规划 | `datasets:read` | `/datasets/versions`、`/datasets/{datasetId}/versions/{versionId}`、对象存储样本内容 | [样本](generated/02-datasets/D04_dataset-version_light_samples_v01.png) |
| D05 | 导出向导 | 当前嵌入 D01；目标 `/datasets/exports/new` | 现有 `DatasetExportForm.vue`，目标 `DatasetExportWizardPage.vue` | 嵌入 | `datasets:read` / `datasets:write` | `POST /datasets/exports`、`/datasets/export-formats`、DatasetVersion picker | [兼容检查](generated/02-datasets/D05_export-wizard_light_compatibility-check_v01.png) |
| D06 | 导出详情 | `/datasets/exports/:datasetExportId` | `DatasetExportDetailPage.vue` | 现有 | `datasets:read` / `datasets:write` | `/datasets/exports/{id}`、package、manifest、download、delete | [成功](generated/02-datasets/D06_export-detail_light_success_v01.png) |

数据集页面必须维持 `Dataset`、`DatasetImport`、`DatasetVersion`、`DatasetExport` 四层边界。删除 Import/Export 只删除任务和运行数据，不删除 `DatasetVersion`。D02、D05 的向导状态应写入路由 query 或页面局部 store，刷新后不能误提交半成品。

### 3.4 模型、训练、验证和转换

| 编号 | 页面 | 当前/目标路由 | 页面组件 | 状态 | 读取/写入 scope | 资源与接口 | 设计参考 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M01 | 模型工作台 | `/models` | `modules/models/pages/ModelOperationsPage.vue` | 现有 | `models:read` + `tasks:read`；创建任务需 `tasks:write` | platform base、deployment sources、training/conversion task families | [工作台](generated/03-models/M01_model-workbench_light_detection_v01.png)、[空](generated/03-models/M01_model-workbench_light_empty_v01.png) |
| M02 | 训练向导 | 当前嵌入 M01；目标 `/models/training/new` | 现有 `ModelTrainingForm.vue`，目标 `TrainingTaskWizardPage.vue` | 嵌入 | `models:read` + `datasets:read`；提交需 `tasks:write` | `/{taskType}/training-tasks`、training parameter schemas、DatasetExport picker | [参数](generated/03-models/M02_training-wizard_light_parameters_v01.png) |
| M03 | 训练详情 | `/models/:taskType/training-tasks/:taskId` | `TrainingTaskDetailPage.vue` | 现有 | `tasks:read`；控制/删除/登记需 `tasks:write`，登记还需 `models:write` | training task、control、output files，WS training telemetry | [运行](generated/03-models/M03_training-detail_light_running_v01.png)、[失败](generated/03-models/M03_training-detail_light_failed_v01.png) |
| M04 | 验证与评估中心 | 目标 `/models/evaluations` | `EvaluationCenterPage.vue` | 规划 | `models:read` + `tasks:read`；创建需 `tasks:write` | `/{taskType}/validation-sessions`、`/{taskType}/evaluation-tasks` | [标准](generated/03-models/M04_evaluation-center_light_tasks-compare_v01.png)、[空](generated/03-models/M04_evaluation-center_light_empty_v01.png) |
| M05 | 评估详情 | 目标 `/models/:taskType/evaluation-tasks/:taskId` | `EvaluationDetailPage.vue` | 规划 | `models:read` + `tasks:read` | evaluation task、report、output files、错误样本内容 | [类别与错误](generated/03-models/M05_evaluation-detail_light_per-class-errors_v01.png) |
| M06 | 模型版本详情 | 目标 `/models/versions/:modelVersionId` | `ModelVersionDetailPage.vue` | 规划 | `models:read`；创建转换/部署需 `tasks:write` 或 `models:write` | deployment source detail、ModelVersion files、ModelBuild、evaluations、deployment/workflow references | [构建矩阵](generated/03-models/M06_model-version-detail_light_build-matrix_v01.png) |
| M07 | 转换向导 | 当前嵌入 M01；目标 `/models/conversions/new` | 现有 `ModelConversionForm.vue`，目标 `ConversionTaskWizardPage.vue` | 嵌入 | `models:read`；提交需 `tasks:write` | `/{taskType}/conversion-tasks`、runtime capabilities、source ModelVersion | [TensorRT 参数](generated/03-models/M07_conversion-wizard_light_tensorrt-parameters_v01.png) |
| M08 | 转换详情 | `/models/:taskType/conversion-tasks/:taskId` | `ConversionTaskDetailPage.vue` | 现有 | `tasks:read`；删除需 `models:write` + `tasks:write` | conversion task、ModelBuild/ModelFile、delete dependency check | [成功](generated/03-models/M08_conversion-detail_light_tensorrt-success_v01.png)、[失败](generated/03-models/M08_conversion-detail_light_tensorrt-failed_v01.png) |

模型页面使用后端 capability catalog 过滤 `model_type × task_type`，不能在前端硬编码不存在的组合。训练的 warm start 与 resume 是不同操作。`best` 和 `latest` checkpoint 分开。评估比较必须同时匹配 task、DatasetExport 和 split。

### 3.5 部署与推理

| 编号 | 页面 | 当前/目标路由 | 页面组件 | 状态 | 读取/写入 scope | 资源与接口 | 设计参考 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R01 | 部署工作台 | `/deployments` | `modules/deployments/pages/DeploymentOperationsPage.vue` | 现有 | `models:read` / `models:write` | `/{taskType}/deployment-instances`、runtime capabilities、status/health/events | [标准](generated/04-deployments-inference/R01_deployment-workbench_light_service-control_v01.png)、[空](generated/04-deployments-inference/R01_deployment-workbench_light_empty_v01.png) |
| R02 | 部署实例详情 | 当前为 R01 内部选择状态；目标 `/deployments/:deploymentInstanceId` | 目标 `DeploymentInstanceDetailPage.vue`，复用 R01 runtime panels | 规划 | `models:read` / `models:write` | instance detail、sync/async start/stop/warmup/reset、health、events、workflow references | [监控](generated/04-deployments-inference/R02_deployment-instance_light_interface-monitoring_v01.png)、[失败](generated/04-deployments-inference/R02_deployment-instance_light_failed_v01.png) |
| I01 | 推理实验室 | `/inference` | `modules/inference/pages/InferenceDebugPage.vue` | 现有 | `models:read`；异步历史需 `tasks:read`；提交需 `tasks:write` | `/{taskType}/deployment-instances/{id}/infer`、`/{taskType}/inference-tasks` | [同步结果](generated/04-deployments-inference/I01_inference-lab_light_sync-result_v01.png) |

R01/R02 的状态是长期 runtime 状态，不使用 `succeeded`。停止或删除前必须显示 WorkflowAppRuntime/TriggerSource 影响。I01 只选择已登记且可用的 `DeploymentInstance`，按 classification、detection、segmentation、pose、obb 切换参数与结果组件。

### 3.6 流程、集成和节点

| 编号 | 页面 | 当前/目标路由 | 页面组件 | 状态 | 读取/写入 scope | 资源与接口 | 设计参考 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| W01 | 流程应用列表 | `/workflows/apps` | `workflows/workflow-editor/pages/WorkflowAppListPage.vue` | 现有 | `workflows:read` / `workflows:write` | applications、templates、app-runtimes、runs 摘要 | [列表](generated/05-workflows-integrations/W01_flow-application-list_light_runtime-health_v01.png)、[空](generated/05-workflows-integrations/W01_flow-application-list_light_empty_v01.png) |
| W02 | 流程应用详情 | `/workflows/apps/:applicationId` | `WorkflowAppDetailPage.vue` | 现有 | `workflows:read` / `workflows:write` | application、App Contract、app-runtimes、invoke、runs、TriggerSource | [详情](generated/05-workflows-integrations/W02_flow-application-detail_light_contract-runtimes_v01.png)、[失败](generated/05-workflows-integrations/W02_flow-application-detail_light_failed_v01.png) |
| W03 | 流程编辑器 | `/workflows/graph/new`、`/workflows/graph/apps/:applicationId` | `WorkflowEditorPage.vue` | 现有多路由 | 新建需 `workflows:write`；已发布只读可用 `workflows:read` | node catalog、template/application validate/save、preview runs、DeploymentInstance picker | [预览成功](generated/05-workflows-integrations/W03_workflow-editor_dark_preview-success_v01.png) |
| X01 | 触发源 | `/integrations/trigger-sources` | `modules/integrations/pages/TriggerSourcePage.vue` | 现有 | `workflows:read` / `workflows:write` | `/workflows/trigger-sources`、enable/disable/delete/health、app-runtimes | [ZeroMQ 映射](generated/05-workflows-integrations/X01_trigger-source_light_zeromq-mapping_v01.png)、[无 Runtime](generated/05-workflows-integrations/X01_trigger-source_light_empty-no-runtime_v01.png) |
| N01 | 自定义节点目录 | `/custom-nodes` | `modules/custom-nodes/pages/CustomNodeCatalogPage.vue` | 现有 | `workflows:read` / `workflows:write` | node catalog、node-pack-status、reload/validate/enable/disable、versions、rollback、logs、audit | [OpenCV 包](generated/05-workflows-integrations/N01_custom-node-catalog_light_opencv-pack_v01.png)、[空](generated/05-workflows-integrations/N01_custom-node-catalog_light_empty_v01.png) |

`WorkflowGraphTemplate`、`FlowApplication`、`WorkflowAppRuntime`、`WorkflowRun` 必须分层。TriggerSource 绑定指定 runtime。Camera、PLC、数据库和其他现场能力是 permissioned Custom Node 或外部代理，不进入核心平台硬件控制链路。

### 3.7 设置与诊断

| 编号 | 页面 | 当前/目标路由 | 页面组件 | 状态 | 读取/写入 scope | 资源与接口 | 设计参考 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | 设置与诊断 | `/settings` | `modules/settings/pages/SettingsDiagnosticsPage.vue` | 现有 | `auth:read`；账号和 token 写操作需 `auth:write` | `/system/diagnostics`、bootstrap/health/config/database/me、`/auth/users`、tokens/providers | [设备与服务](generated/06-settings-system/C01_settings-diagnostics_light_devices_v02.png) |

C01 只展示可用性、版本、原因和最后检查时间。开发态显示 conda，发布态显示 bundled Python。SQLite、本地 ObjectStore、本地持久化队列是默认实现；不能展示 PostgreSQL、RabbitMQ 或在线 CDN 为本地运行前提。

## 4. 共享组件落点

| 设计组件 | 当前代码 | 实现动作 |
| --- | --- | --- |
| AppShell / PageHeader | `shells/workbench`、`PageHeader.vue` | 所有浅色页面共用；W03 使用 graphWorkbench 壳层，不复制导航状态 |
| Button / Select / MultiSelect / Tabs | `shared/ui/components`、`shared/ui/navigation` | 新页面不得直接创建第二套表单控件 |
| StatusBadge | `shared/ui/data-display/StatusBadge.vue` | 收敛颜色、图标和文字，不只靠颜色表达 |
| Empty / Loading / Error | `EmptyState.vue`、`LoadingPanel.vue`、`InlineError.vue` | 新增 `ListStateBoundary.vue` 统一加载、首次空、筛选空和重连状态 |
| Task lifecycle | `TaskStateBadge.vue`、`TaskStatusBadge.vue`、`TaskProgress.vue`、`TaskEventTimeline.vue` | 收敛重复 badge；按 G04 固定有限任务状态与允许操作 |
| Runtime lifecycle | 当前散落在 Deployment 和 Workflow 页面 | 新增 `RuntimeStateBadge.vue`、`RuntimeHealthPanel.vue`、`RuntimeActions.vue`、`RuntimeEventTimeline.vue`，按 G05 共用 |
| 危险确认 | `ConfirmDialog.vue` | 扩展对象身份、影响摘要、blockers、typed confirmation 和默认取消焦点；按 G06 实现 |
| 分页 | `PaginationControls.vue` | 所有资源列表使用后端分页头，不在前端截断完整集合 |
| ImageCanvas | `ImageViewer.vue` 与 `shared/ui/image-viewer` | I01、D04、M05、W03 预览复用；保持缩放、叠加和 geometry 编辑边界 |
| Workflow canvas | `workflows/workflow-editor/components` | 保留单一节点、连线、group、minimap、inspector、preview 组件体系 |

## 5. 状态与数据所有权

### 5.1 全局状态

- `session.store.ts`：当前用户、登录态、scope；不得复制到领域 store。
- `project.store.ts`：当前 Project 和可见项目；路由切换时校验可见性。
- `preferences.store.ts`：主题、密度、语言等本地偏好。
- `feedback.store.ts`：toast 和全局反馈，不保存业务记录。

### 5.2 页面和领域状态

- 筛选、分页、标签、选中 ID 写入 route query，支持刷新和复制链接。
- 向导草稿默认在页面 composable 中；只有明确需要跨路由恢复时才进入 Pinia，并带 schema version。
- 服务文件只负责 HTTP/序列化，不保存 UI 状态。
- 列表 REST snapshot 是权威集合；WebSocket 只按资源 ID 合并状态和事件。
- WebSocket 断开时保留只读缓存、显示最后同步和重试状态、禁用写操作；重新连接后先拉 REST snapshot 再继续事件流。

### 5.3 有限任务和长期实例

```text
TaskRecord: queued → running → succeeded | failed | cancelled
DeploymentInstance / WorkflowAppRuntime: stopped ↔ starting ↔ healthy ↔ degraded | failed
```

失败任务重试必须创建新 `TaskRecord`。长期实例允许 start、stop、restart 和受控恢复，不能用任务完成态表示。

## 6. 权限实现规则

1. `route.meta.requiredScopes` 只决定能否进入页面。
2. 页面内按钮继续使用 `sessionStore.hasScopes()` 做操作级控制。
3. 隐藏与禁用按风险选择：无读取权限隐藏入口；有读取但无写权限时保留信息并禁用写操作，显示所需 scope。
4. 后端 403 仍是最终权限判断；前端不能把按钮禁用当作安全边界。
5. 主要 scope：`datasets:read/write`、`models:read/write`、`tasks:read/write`、`workflows:read/write`、`auth:read/write`、`projects:delete`。

## 7. 建议实现顺序

### 阶段一：共享状态和交互基线

1. 新增 `ListStateBoundary`，接入 P01、T01、D01、M01、M04、R01、W01、X01、N01。
2. 收敛有限任务状态组件，完成 G04 规则。
3. 提取长期 runtime 组件，供 R01/R02/W02 使用。
4. 扩展 `ConfirmDialog`，实现 G06 的预检、blocker 和 typed confirmation。

### 阶段二：补独立路由

1. P02 项目概览。
2. D04 DatasetVersion 详情；把 D02/D05 提取为可深链接向导。
3. M04/M05/M06；把 M02/M07 提取为可深链接向导。
4. R02 DeploymentInstance 详情。

### 阶段三：按设计增强现有页面

1. T01/T02、D01/D03/D06、M01/M03/M08。
2. R01/I01。
3. W01/W02/W03、X01、N01。
4. C01 和系统状态页。

### 阶段四：窄桌面与离线验收

- 在 `1586×992` 和 `1366×768` 检查每个一级页面。
- 列表窄屏隐藏次要列，检查器改覆盖式 drawer。
- W03 在窄屏只同时展示 NodeLibrary 或 Inspector 中一个。
- 无外网、后端重连、403、404、首次空、筛选空和失败状态均需要组件测试。

## 8. 页面验收门槛

每个页面合并前至少证明：

- 路由可直接打开，刷新后参数和选择状态不丢失。
- route scope 和操作 scope 分开验证。
- loading、first-empty、filtered-empty、error、reconnecting、populated 状态完整。
- REST snapshot 与 WebSocket 合并不会产生重复、回退或过期状态。
- 危险操作先做依赖预检，blocker 存在时按钮不可用。
- 资源命名和关系符合领域边界，不把 Import、Version、Export、Task、Build、Deployment、Runtime 混为一体。
- 所有图片叠加、图表、表格和画布都能由 Vue 3 组件实现，不依赖生成图中的装饰性文字。
- 关键操作有可访问名称、键盘焦点和非颜色状态表达。
- 前端构建不依赖外部 CDN；发行包可与本地服务和 bundled Python 一起分发。

## 9. 测试建议

- 路由：守卫、redirect、query 恢复、403/404/offline。
- 组件：StatusBadge、ListStateBoundary、ConfirmDialog、RuntimeActions、分页。
- 页面：每个领域至少覆盖 populated、first-empty、failed/reconnecting。
- 数据：Mock Service Worker 或同等 API mock 验证分页头、结构化错误和删除 blocker。
- WebSocket：断线保留缓存、指数退避、重连后 REST 校准、unknown 状态。
- 视觉：在标准和窄桌面尺寸截图比对设计图；只校验结构、层级和状态，不追求生成图的像素噪声。
