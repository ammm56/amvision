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

- 旧 `datasets.py` 与 `dataset_exports.py` 已删除，数据集导入/导出路由已拆到 `routes/datasets/`；后续继续收多个 deployment / inference route 文件。
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
- 问题主要在 support 文件和节点数量继续增长后目录会过大。

### 目标结构

```text
backend/nodes/core_nodes/
├─ io/
├─ model/
├─ vision/
├─ rule/
├─ output/
├─ video/
├─ workflow/
├─ support/
└─ catalog.py
```

### 迁移规则

- 节点可以继续一节点一文件，但按能力族分目录。
- 公共 helper 放 `support/`，不要散在节点目录根部。
- catalog loader 应支持递归发现，不再依赖平铺文件。
- 迁移时先改 loader，再移动节点文件。

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
4. 再拆 custom node 大 runtime 文件。
5. 再拆 core_nodes 平铺目录。
6. 最后拆前端大页面。

每一批都要先移动纯 helper 和 DTO，再移动执行逻辑，最后删除旧入口。不要长期保留“新旧双实现”。
