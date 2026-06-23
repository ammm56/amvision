# 代码结构收口计划

## 文档目的

本文档记录当前模型 core / runtime 之外的代码结构审计结果，明确哪些目录已经合理，哪些目录还存在文件过大、职责混在一起或旧边界未清的问题。

本文档只规划代码结构和迁移顺序，不记录临时任务进度，不替代 [project-structure.md](project-structure.md)。

## 保存原则

- 只记录长期结构目标和明确收口顺序。
- 不把每次小改动写成流水账。
- 不在一个文档里重复描述模型 core 的详细实现，模型实现以 [model-core-implementation-plan.md](model-core-implementation-plan.md) 为准。
- 目录调整完成后，应删除旧的平铺入口，不长期保留双路径。

## 本轮审计范围

本轮重点检查模型 core / runtime 之外的目录：

- `backend/service/application/datasets`
- `backend/service/application/workflows`
- `backend/service/api/rest/v1/routes`
- `backend/nodes/core_nodes`
- `custom_nodes/*`
- `frontend/web-ui/src`
- `tests/integration`

`backend/service/application/models` 和 `backend/service/application/runtime` 已按模型 full core 与 deployment runtime 做过大幅收口，本轮只记录它们之外的结构问题。

## 总体判断

当前主要功能链路已经能工作，但部分非模型目录仍有明显平铺问题：

- 数据集导入/导出把格式识别、格式解析、文件写入、任务状态和持久化混在大文件里。
- workflow runtime 把 DTO、服务、worker、消息序列化、事件和响应组装混在少数大文件里。
- API route 文件承担了请求模型、权限、服务装配、响应组装和业务路由多类职责。
- 自定义节点包里有少数 `_runtime.py`、`_common.py`、`_project_native_runtime.py` 文件过大。
- 前端少数页面组件承担了数据加载、表单状态、弹窗、提交、列表和样式，后续应拆成 page + components + composables。

这些问题不一定是功能缺陷，但会降低后续扩展模型、数据集格式、workflow runtime 和现场节点时的可维护性。

## 第一批：datasets 目录

### 当前问题

- 旧 `dataset_import.py` / `dataset_export.py` 平铺入口已经删除。
- 当前导入侧已经拆成 `imports/service.py`、`imports/contracts.py`、`imports/support.py`、`imports/version_writer.py` 和 `imports/formats/*`。
- 当前导出侧已经拆成 `exports/service.py`、`exports/task_service.py`、`exports/contracts.py`、`exports/delivery.py` 和 `exports/formats/*`。
- `imports/service.py` 已不再直接保存格式 parser、路径归一化、图片读取、日志构建和版本文件写入。
- `exports/service.py` 已不再直接保存 annotation payload 构建、格式文件写入、类别名解析和版本图片路径拼装。
- 剩余问题主要是导入任务编排仍在 `imports/service.py`，后续如果继续拆，应只按任务提交、任务执行、状态事件和持久化 helper 小步收口。

### 目标结构

```text
backend/service/application/datasets/
├─ imports/
│  ├─ service.py
│  ├─ contracts.py
│  ├─ support.py
│  ├─ version_writer.py
│  └─ formats/
│     ├─ coco.py
│     ├─ voc.py
│     ├─ imagenet.py
│     ├─ dota.py
│     └─ yolo/
│        ├─ parser.py
│        ├─ manifest.py
│        ├─ scanner.py
│        ├─ annotations.py
│        ├─ detection.py
│        ├─ segmentation.py
│        ├─ pose.py
│        └─ obb.py
├─ exports/
│  ├─ service.py
│  ├─ task_service.py
│  ├─ contracts.py
│  ├─ delivery.py
│  └─ formats/
│     ├─ common.py
│     ├─ payloads.py
│     ├─ files.py
│     ├─ coco.py
│     ├─ voc.py
│     ├─ yolo.py
│     ├─ imagenet.py
│     └─ dota.py
├─ formats/
│  └─ export_support.py
├─ tasks/
│  ├─ imports.py
│  └─ exports.py
└─ README.md
```

### 迁移规则

- `imports/service.py` 只负责编排导入流程。
- 各格式 parser 只负责把外部数据集转成平台内部 `DatasetVersion` 样本。
- `exports/formats/*` 只负责把内部 `DatasetVersion` 写成指定格式。
- task service 只处理队列、状态、事件和任务 payload。
- 迁移完成后删除旧 `dataset_import.py` / `dataset_export.py` 平铺实现，不长期保留兼容入口。

## 第二批：workflows 目录

### 当前问题

- `runtime_service.py` 约 100KB，混合了 execution policy、preview run、app runtime、sync invoke、workflow run 查询和事件读取。
- 旧 `runtime_worker.py` 已删除，worker manager、子进程入口、消息、heartbeat 和 health 已拆到 `worker/*`。
- `graph_executor.py` 约 54KB，混合了节点执行、registry、for-each、变量读写和执行记录构造。
- `workflow_service.py` 原约 49KB，混合了 workflow 文档 contracts、模板管理、应用管理、summary sidecar 和 object key 规则。
- 旧 `service_node_runtime.py` 已删除，平台 service runtime 已拆到 `service_runtime/context.py`、`service_runtime/builders.py` 和 `service_runtime/payloads.py`。
- 当前已把 workflow 文档 contracts 拆到 `documents/contracts.py`，把模板/应用校验摘要拆到 `documents/validation.py`，把 object key 规则、sidecar summary、路径归一化拆到 `documents/storage.py`。
- 当前已把模板文档管理拆到 `documents/templates.py`，把流程应用文档管理拆到 `documents/applications.py`，`workflow_service.py` 只保留对外门面和 store 装配。
- 当前已把 graph executor 的执行数据结构拆到 `execution/contracts.py`，节点运行时注册表拆到 `execution/registry.py`，for-each 纯解析/校验拆到 `execution/foreach.py`，变量存储辅助函数拆到 `execution/variables.py`。
- 当前已把拓扑排序拆到 `execution/topology.py`，模板输入和节点输入解析拆到 `execution/inputs.py`，节点事件与失败详情构造拆到 `execution/events.py`。
- 当前已把 runtime execution policy 的默认值、创建请求、metadata 摘要、超时和持久化保留策略拆到 `runtime/policies.py`。
- 当前已把 preview run 的创建请求、请求规范化、列表过滤、默认保留时间和删除前状态判断拆到 `runtime/preview_runs.py`。
- 当前已把 app runtime 的创建请求、请求规范化、资源更新主体 metadata 和 worker state 回写拆到 `runtime/app_runtimes.py`。
- 当前已把 sync/async invoke 请求与同步调用结果拆到 `runtime/invokes.py`，把 WorkflowRun 结果回写、node_records 序列化、BufferRef cleanup 和 WorkflowRun events 文件读写拆到 `runtime/persistence.py`。
- 后续继续收 API route 响应组装边界，以及 service runtime 内部更细的按任务分类 builder。

### 目标结构

```text
backend/service/application/workflows/
├─ documents/
│  ├─ contracts.py
│  ├─ templates.py
│  ├─ applications.py
│  ├─ validation.py
│  └─ storage.py
├─ execution/
│  ├─ graph_executor.py
│  ├─ registry.py
│  ├─ foreach.py
│  ├─ contracts.py
│  ├─ inputs.py
│  ├─ topology.py
│  ├─ events.py
│  └─ variables.py
├─ runtime/
│  ├─ service.py
│  ├─ preview_runs.py
│  ├─ app_runtimes.py
│  ├─ policies.py
│  ├─ invokes.py
│  └─ persistence.py
├─ worker/
│  ├─ manager.py
│  ├─ process.py
│  ├─ messages.py
│  ├─ heartbeat.py
│  └─ health.py
├─ service_runtime/
│  ├─ context.py
│  ├─ builders.py
│  └─ payloads.py
├─ events.py
└─ README.md
```

### 迁移规则

- 不做旧路径兼容壳；移动代码后同步更新引用。
- API route 不直接理解 worker message 细节。
- worker process 不直接写 workflow 文档存储规则。
- preview run 和 app runtime 可以复用底层执行器，但 service 边界要分开。
- `graph_executor` 只保留图执行和节点调用，不承担 API response 组装。

### 建议顺序

1. 先收 `workflow_service.py`：已拆 `documents/contracts.py`、`documents/validation.py`、`documents/storage.py`、`documents/templates.py` 和 `documents/applications.py`。
2. 再收 `graph_executor.py`：已拆 `execution/contracts.py`、`execution/registry.py`、`execution/foreach.py`、`execution/variables.py`、`execution/inputs.py`、`execution/topology.py` 和 `execution/events.py`；后续只在确认收益明确时继续拆 for-each 执行循环本体。
3. 再收 `runtime_service.py`：已拆 `runtime/policies.py`、`runtime/preview_runs.py`、`runtime/app_runtimes.py`、`runtime/invokes.py` 和 `runtime/persistence.py`。
4. 再收旧 `runtime_worker.py`：已删除旧平铺文件，拆到 `worker/manager.py`、`worker/process.py`、`worker/messages.py`、`worker/heartbeat.py` 和 `worker/health.py`。
5. 最后收旧 `service_node_runtime.py`：已删除旧平铺文件，按 `service_runtime/context.py`、`service_runtime/builders.py` 和 `service_runtime/payloads.py` 细分平台服务装配。

## 第三批：API routes

### 当前问题

- 旧 `datasets.py` 与 `dataset_exports.py` 已删除，数据集导入/导出路由已拆到 `routes/datasets/`。
- 旧 `detection_training_tasks.py` 和 `detection_training_route_models.py` 已删除，detection 训练任务路由已拆到 `routes/detection_training_tasks/`，训练响应模型和响应构建函数已并入 `detection_training_tasks/responses.py`。
- 旧 `classification_training_tasks.py`、`segmentation_training_tasks.py`、`pose_training_tasks.py`、`obb_training_tasks.py` 和 `non_detection_training_management.py` 已删除，non-detection training 入口已按任务类型拆成 `router.py`、`schemas.py`、`responses.py`、`services.py`、`controls.py`，共同任务查询、详情、控制、resume/delete 和响应构建由 `task_training/` 装配。
- 旧 `detection_validation_sessions.py`、`classification_validation_sessions.py`、`segmentation_validation_sessions.py`、`pose_validation_sessions.py` 和 `obb_validation_sessions.py` 已删除，validation session 入口已按任务类型拆成 `router.py`、`schemas.py`、`responses.py`、`services.py`，共同项目权限校验和 tensor spec payload 由 `task_validation/` 装配。
- 旧 `detection_evaluation_tasks.py`、`detection_evaluation_route_models.py`、`detection_output_files.py`、`classification_evaluation_tasks.py`、`segmentation_evaluation_tasks.py`、`pose_evaluation_tasks.py` 和 `obb_evaluation_tasks.py` 已删除，evaluation task 入口已按任务类型拆成 `router.py`、`schemas.py`、`responses.py`、`services.py`，detection evaluation 报告和输出文件读取放在 `detection_evaluation_tasks/outputs.py`，detection training 输出文件读取放在 `detection_training_tasks/output_files.py`。
- 旧 `task_conversion_routes_common.py` 已删除，task-native conversion 公共 schema、response、service 装配、结果文件读取和可见性校验已拆到 `routes/task_conversion/`。
- 旧 `detection_conversion_tasks.py` 和 `detection_conversion_route_models.py` 已删除，detection conversion 的创建、查询、结果读取、schema、response、service 装配和可见性校验已拆到 `routes/detection_conversion_tasks/`。
- 旧 `classification_conversion_tasks.py`、`segmentation_conversion_tasks.py`、`pose_conversion_tasks.py` 和 `obb_conversion_tasks.py` 已删除，non-detection conversion 入口已按任务类型拆成 `router.py` 与 `services.py`。
- 旧 `detection_deployments.py` 和 `detection_deployment_helpers.py` 已删除，detection deployment 已按实例管理、事件、sync/async 控制、schema、response、service 和 runtime action 拆到 `routes/detection_deployments/`。
- 旧 `classification_deployments.py`、`segmentation_deployments.py`、`pose_deployments.py`、`obb_deployments.py` 以及对应 helper 已删除，non-detection deployment 入口已按任务类型拆成 `router.py`、`schemas.py`、`responses.py`、`services.py`，共同 CRUD 与 sync/async 控制由 `task_deployments/factory.py` 装配。
- 旧 `detection_inference_tasks.py` 和 `detection_inference_helpers.py` 已删除，detection inference 已按 router、schema、response、service、outputs、runtime control 拆到 `routes/detection_inference_tasks/`。
- 旧 `classification_inference_tasks.py`、`segmentation_inference_tasks.py`、`pose_inference_tasks.py`、`obb_inference_tasks.py`、`classification_inference_helpers.py` 和 `inference_route_helpers.py` 已删除，non-detection inference 入口已按任务类型拆成 `router.py`、`schemas.py`、`responses.py`、`services.py`，共同请求读取、响应构建、可见性和结果读取由 `task_inference/` 装配。
- 旧 `tasks.py` 已删除，通用任务创建、列表、详情、事件和取消 API 已拆到 `routes/tasks/`，schema、response builder、可见性校验和控制动作分文件放置。
- 旧 `models.py` 已删除，平台基础模型列表和详情 API 已拆到 `routes/models/`，schema、response builder 和 service 查询 helper 分文件放置。
- 旧 `workflow_trigger_sources.py` 已删除，WorkflowTriggerSource 管理 API 已拆到 `routes/workflow_trigger_sources/`，router、schema、response builder、service 装配、health 响应和 runtime/application 引用摘要分文件放置。
- 旧 `projects.py` 已删除，Project 目录、summary、bootstrap 和 Project 公开文件 API 已拆到 `routes/projects/`，router、schema、response builder、service 装配和公开文件路径规则分文件放置。
- 旧 `system.py` 已删除，System health、bootstrap、diagnostics、me 和 database API 已拆到 `routes/system/`，router、schema、response builder、service 装配和 diagnostics 探测工具分文件放置。
- 旧 `auth.py` 已删除，Auth bootstrap-admin、provider 发现、login / refresh / logout、用户管理和长期 user token API 已拆到 `routes/auth/`，router、schema、response builder、service 装配和 endpoint 分组分文件放置。
- route 文件里混有请求模型、权限检查、服务装配和 response builder。
- 当前已删除旧 `workflows.py` 单文件入口，按 node catalog、node pack admin、template 文档和 application 文档拆到 `workflows/`，并由 `workflows/router.py` 统一装配。
- 当前已删除旧 `workflow_runtime.py` 单文件入口，按 endpoint 组拆到 `workflow_runtime/`，并由 `workflow_runtime/router.py` 统一装配。跨 endpoint 共用的请求体、响应构建、服务装配和 multipart 调用构建暂放 `workflow_runtime_support/`。

### 目标结构

```text
backend/service/api/rest/v1/routes/
├─ datasets/
│  ├─ router.py
│  ├─ imports.py
│  ├─ exports.py
│  ├─ schemas.py
│  └─ responses.py
├─ workflows/
│  ├─ router.py
│  ├─ templates.py
│  ├─ applications.py
│  ├─ node_catalog.py
│  ├─ node_pack_admin.py
│  ├─ documents.py
│  ├─ node_catalog_helpers.py
│  ├─ node_pack_helpers.py
│  ├─ schemas.py
│  └─ ...
├─ workflow_runtime/
│  ├─ router.py
│  ├─ preview_runs.py
│  ├─ app_runtimes.py
│  ├─ runs.py
│  ├─ policies.py
│  ├─ schemas.py
│  └─ responses.py
├─ workflow_runtime_support/
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  └─ uploads.py
├─ detection_training_tasks/
│  ├─ router.py
│  ├─ create.py
│  ├─ queries.py
│  ├─ controls.py
│  ├─ outputs.py
│  ├─ output_files.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ task_training/
│  ├─ catalog.py
│  ├─ controls.py
│  ├─ responses.py
│  ├─ schemas.py
│  └─ services.py
├─ task_validation/
│  └─ services.py
├─ detection_validation_sessions/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ classification_validation_sessions/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ segmentation_validation_sessions/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ pose_validation_sessions/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ obb_validation_sessions/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ task_evaluation/
│  └─ services.py
├─ detection_evaluation_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ outputs.py
│  └─ services.py
├─ classification_evaluation_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ segmentation_evaluation_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ pose_evaluation_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ obb_evaluation_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ classification_training_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  └─ controls.py
├─ segmentation_training_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  └─ controls.py
├─ pose_training_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  └─ controls.py
├─ obb_training_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  └─ controls.py
├─ task_conversion/
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  ├─ outputs.py
│  ├─ visibility.py
│  └─ files.py
├─ detection_conversion_tasks/
│  ├─ router.py
│  ├─ create.py
│  ├─ queries.py
│  ├─ outputs.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  └─ visibility.py
├─ classification_conversion_tasks/
│  ├─ router.py
│  └─ services.py
├─ segmentation_conversion_tasks/
│  ├─ router.py
│  └─ services.py
├─ pose_conversion_tasks/
│  ├─ router.py
│  └─ services.py
├─ obb_conversion_tasks/
│  ├─ router.py
│  └─ services.py
├─ detection_deployments/
│  ├─ router.py
│  ├─ instances.py
│  ├─ events.py
│  ├─ sync.py
│  ├─ async_runtime.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  └─ runtime_actions.py
├─ task_deployments/
│  ├─ factory.py
│  └─ runtime_controls.py
├─ classification_deployments/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ segmentation_deployments/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ pose_deployments/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ obb_deployments/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ task_inference/
│  ├─ requests.py
│  ├─ responses.py
│  └─ visibility.py
├─ detection_inference_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  ├─ outputs.py
│  └─ runtime_controls.py
├─ classification_inference_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ segmentation_inference_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ pose_inference_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ obb_inference_tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ tasks/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ visibility.py
│  └─ controls.py
├─ models/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  └─ services.py
├─ workflow_trigger_sources/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  ├─ health.py
│  └─ references.py
├─ projects/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  └─ files.py
├─ system/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  ├─ health.py
│  ├─ bootstrap.py
│  ├─ diagnostics.py
│  ├─ me.py
│  └─ database.py
├─ auth/
│  ├─ router.py
│  ├─ schemas.py
│  ├─ responses.py
│  ├─ services.py
│  ├─ bootstrap_admin.py
│  ├─ providers.py
│  ├─ sessions.py
│  ├─ users.py
│  └─ tokens.py
└─ ...
```

### 迁移规则

- route 文件只保留 HTTP 入口、依赖注入和调用应用服务。
- request / response schema 放到同目录 `schemas.py` 或 `responses.py`。
- 复杂 response builder 从 route 文件移出。
- 完成迁移后删除旧单文件 route，不保留双路由。
- `<route>_support/` 只放跨多个 endpoint 组共用的 helper；如果 helper 只服务单个 endpoint 组，应继续并入对应正式目录。

## 第四批：core_nodes

### 当前问题

- 当前节点基本保持一节点一文件，这是合理的。
- 旧平铺根目录已经开始收口，`core.rule.*` 已拆到 `core_nodes/rule/`，`core.output.*` 已拆到 `core_nodes/output/`。
- `core.vision` 第一批已开始收口，区域结果处理已拆到 `core_nodes/vision/regions/`，ROI 与覆盖规则已拆到 `core_nodes/vision/roi/`。
- `core.vision` 连续性与完整性指标已拆到 `core_nodes/vision/continuity/`。
- `core.vision` 缺陷与异常语义节点已拆到 `core_nodes/vision/defects/`。
- `core.vision` 几何量测与位置关系节点已拆到 `core_nodes/vision/geometry/`，图案、装配关系与结构缺陷节点已拆到 `core_nodes/vision/pattern/`。
- `core.io` 第一批已开始收口，本地文件输入已拆到 `core_nodes/io/local/`，目录扫描、批次窗口和游标节点已拆到 `core_nodes/io/directory/`，批次文件处理已拆到 `core_nodes/io/batch/`。
- `core.model` 的 deployment 直连推理节点已拆到 `core_nodes/model/deployment/`。
- `core.model.sahi-inference` 已拆到 `core_nodes/model/inference/`。
- `core.service` 的模型任务提交节点已拆到 `core_nodes/service/model_tasks/`，模型 deployment 控制节点已拆到 `core_nodes/service/deployment/`。
- `core.service` 的数据集导入、导出、打包节点已拆到 `core_nodes/service/datasets/`，通用任务查询和等待节点已拆到 `core_nodes/service/tasks/`。
- `core.logic` 已按 boolean、control、collections、objects、state、value 拆到 `core_nodes/logic/`。
- `core.io` 的图片编码、图片预览、图片保存、模板输入、表格预览和值预览节点已分别拆到 `core_nodes/io/image/`、`core_nodes/io/templates/` 和 `core_nodes/io/preview/`。
- `core.video` 已按本地输入输出、帧窗口和跟踪叠加拆到 `core_nodes/video/io/`、`core_nodes/video/windows/` 和 `core_nodes/video/tracks/`。
- `core.vision.edge-break-check` 已并入 `core_nodes/vision/defects/`，`core.vision.reference-mark-align-check` 已并入 `core_nodes/vision/geometry/`。
- 旧 `_xxx_support.py` 支撑文件已改成 `core_nodes/support/<短名>.py`，不再使用根目录下划线 support 文件。
- `workflow service node` 的平台 task/model 参数 helper 已从单个 `platform_service.py` 拆到 `core_nodes/support/platform/constants.py`、`parameters.py`、`schemas.py`；训练请求类型分发已收成 `training_requests.py` 注册表。
- `regions.v1`、`roi.v1` 和视频跟踪支撑代码已从 `region.py`、`roi.py`、`video_track.py` 三个大文件拆成 `support/region/`、`support/roi/`、`support/video_track/` 包，按 payload、mask、geometry、intersection、validator、filter 等能力分文件放置。
- `logic.py` 已拆成 `support/logic/`，按 payload、JSON 安全值、点分路径和比较语义分文件放置。
- `local_io.py` 已拆成 `support/local_io/`，按路径解析、文件记录、图片读取、CSV 展开和 result/alarm 输入解析分文件放置。
- `service.py` 已拆成 `support/service/`，按 runtime context、参数读取、response body、service builder 和 deployment 子进程动作分文件放置。
- `directory_window.py` 已拆成 `support/directory_window/`，按窗口参数、cursor 起点和窗口输出 payload 分文件放置。
- `directory_cursor.py` 已拆成 `support/directory_cursor/`，按 cursor 输入读取、字段校验和规范化分文件放置。
- `assembly.py` 已拆成 `support/assembly/`，按 region selector、装配几何和参数读取分文件放置。
- `condition_expression.py` 已拆成 `support/condition_expression/`，按条件表达式校验和执行分文件放置。
- `get_core_node_specs()` 已改成递归扫描，后续 `vision/`、`io/`、`model/` 等能力族继续迁移时不再依赖根目录平铺文件。
- `core_nodes/` 根目录目前只保留扫描入口 `__init__.py`，不再放具体节点文件。
- 剩余问题主要是 `batch_result_summary.py`、`collection.py`、`object.py`、`state.py`、`task.py` 等较小 helper 还可以按实际增长继续拆细；如果后续新增 workflow 专属节点，再单独建立 `core_nodes/workflow/`，不为了空目录提前保留。

### 目标结构

```text
backend/nodes/core_nodes/
├─ io/
├─ model/
├─ service/
├─ vision/
├─ rule/
├─ output/
├─ logic/
├─ video/
├─ support/
│  ├─ platform/
│  ├─ region/
│  ├─ roi/
│  ├─ video_track/
│  ├─ logic/
│  ├─ local_io/
│  ├─ service/
│  ├─ directory_window/
│  ├─ directory_cursor/
│  ├─ assembly/
│  ├─ condition_expression/
│  └─ ...
└─ catalog.py
```

### 迁移规则

- 节点可以继续一节点一文件，但按能力族分目录。
- 公共 helper 放 `support/`，不要散在节点目录根部。
- 节点目录只放带 `CORE_NODE_SPEC` 的节点模块；注册表、DTO 解析、参数校验和跨节点 helper 放到 `support/` 对应领域目录。
- catalog loader 应支持递归发现，不再依赖平铺文件。
- 迁移时先改 loader，再移动节点文件。
- 公开 `node_type_id` 不因目录移动而变化，workflow 示例、Postman 和已有应用不需要改节点 ID。
- 完成每批迁移后，同步更新 import smoke 和节点专项测试，不保留旧平铺模块兼容壳。
- 节点模块导入阶段只允许声明节点定义和轻量 helper；不得为了类型注解、常量或可选执行分支顶层导入训练、转换、deployment、worker、HTTP client 等重依赖。
- service node 需要调用平台服务时，DTO、worker 队列、部署 gateway 和模型运行时依赖应在 handler 或 service builder 执行阶段导入。
- workflow preview / runtime worker / application process 子进程不得在启动阶段无条件启动 deployment supervisor；只在 workflow 实际执行 deployment 或模型推理服务节点时按需创建。

## 第五批：custom_nodes

### 当前问题

- `plc_modbus_tcp_nodes/backend/nodes/_runtime.py` 同时包含连接参数、地址解析、编码解码、读写、等待条件、结果信号映射和错误处理。
- `yoloe_open_vocab_nodes/backend/nodes/_project_native_runtime.py` 同时包含模型模块、checkpoint 读取、prompt-free/text/visual session、后处理和 mask 编码。
- `sam3_segment_nodes/backend/nodes/_common.py` 同时包含 prompt 读取、payload 构造、summary、session cache 和部分 mask 处理。

### 目标结构

```text
custom_nodes/plc_modbus_tcp_nodes/backend/
├─ runtime/
│  ├─ config.py
│  ├─ addresses.py
│  ├─ codec.py
│  ├─ client.py
│  ├─ read_write.py
│  ├─ wait_condition.py
│  └─ result_signals.py
└─ nodes/
```

```text
custom_nodes/yoloe_open_vocab_nodes/backend/
├─ runtime/
│  ├─ nn/
│  ├─ weights.py
│  ├─ sessions.py
│  ├─ prompts.py
│  ├─ postprocess.py
│  └─ payloads.py
└─ nodes/
```

```text
custom_nodes/sam3_segment_nodes/backend/
├─ runtime/
│  ├─ prompts.py
│  ├─ payloads.py
│  ├─ sessions.py
│  ├─ masks.py
│  └─ summaries.py
└─ nodes/
```

### 迁移规则

- 自定义节点入口文件只读参数、调用 runtime、返回 payload。
- 设备协议、模型 session、codec 和后处理不放在节点入口文件。
- 不再新增 `_runtime.py` 这种无边界大文件。

## 第六批：frontend

### 当前问题

- `ModelOperationsPage.vue`、`DatasetOperationsPage.vue`、`WorkflowEditorPage.vue` 较大。
- `litegraph` 目录是图编辑器内核，体量大但不属于普通业务页面，不和业务页面一起拆。

### 目标结构

```text
frontend/web-ui/src/modules/models/
├─ pages/
├─ components/
├─ composables/
├─ services/
└─ types.ts
```

```text
frontend/web-ui/src/modules/datasets/
├─ pages/
├─ components/
├─ composables/
├─ services/
└─ types.ts
```

### 迁移规则

- page 组件只负责页面布局和主流程组合。
- 弹窗、选择器、列表、任务表格拆成 components。
- 表单状态、提交、轮询和 API 组合逻辑拆成 composables。
- i18n 文案可以继续集中管理，但页面内不要保留大量硬编码分支。

## 不优先处理

- `frontend/web-ui/src/lib/litegraph`：这是图编辑器内核，当前不按业务页面标准拆分。
- `tests/` 下的大测试文件：除非测试行为需要调整，否则不为“行数少”单独拆测试。
- 模型 core / runtime：已有独立 full core 收口计划，本文件不重复展开。

## 推荐执行顺序

1. 先拆 `datasets`，因为它是训练全链路入口。
2. 再拆 `workflow runtime`，因为它影响流程编排和现场长期运行。
3. 再拆 API routes，使 HTTP 层保持薄入口。
4. 再拆 core_nodes 平铺目录。
5. 再拆 custom node 大 runtime 文件。
6. 最后拆前端大页面。

每一批都要先移动纯 helper 和 DTO，再移动执行逻辑，最后删除旧入口。不要长期保留“新旧双实现”。
