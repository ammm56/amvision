# 浏览器前端业务流程和节点通信

## 文档目的

本文档用于说明浏览器前端 Web UI 如何消费后端服务、节点目录和 workflow runtime，明确前端图节点与后端 core nodes、custom nodes 的对应关系，以及数据集、模型、部署、推理和 workflow app 在界面中的主要使用流程。

[frontend-web-ui.md](frontend-web-ui.md) 定义前端职责边界，[frontend-web-ui-structure.md](frontend-web-ui-structure.md) 定义工程目录结构，[frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md) 定义开发准备检查，本文档继续细化实现流程、通信方式和页面布局。

## 适用范围

- 后端节点目录到前端图节点的映射规则
- custom node 新增后，前端如何展示和使用
- workflow template、FlowApplication、PreviewRun、AppRuntime、WorkflowRun 的前端流程
- 数据集导入、导出、训练、验证、转换、发布和推理服务的页面流程
- REST API、WebSocket、文件上传和结果查看的前端协作方式
- 第一阶段真实编码前仍需补齐的规划项

## 总体关系

浏览器前端不直接加载 Python 节点实现，也不直接读取 `custom_nodes` 目录。前端只读取 backend-service 暴露的公开资源视图。

```text
core nodes / custom_nodes
        ↓
NodeCatalogRegistry
        ↓
GET /api/v1/workflows/node-catalog
        ↓
frontend node-catalog.store.ts
        ↓
NodePalette / LiteGraph adapter / NodeInspector
        ↓
WorkflowGraphTemplate / FlowApplication
        ↓
PreviewRun / WorkflowAppRuntime / WorkflowRun
        ↓
REST snapshot + WebSocket events + result viewer
```

关键边界：

- 节点能力来源是后端 `NodeDefinition`，前端不重新定义节点类型。
- 前端图草稿只保存节点实例、连线、参数和 `ui_state`，不把完整 `NodeDefinition` 写进模板。
- 后端保存格式是 `WorkflowGraphTemplate` 和 `FlowApplication`，不是 LiteGraph 内部 JSON。
- 前端只通过 REST API 和 WebSocket 观察任务、运行和部署状态。
- ZeroMQ、LocalBufferBroker、deployment worker 和 workflow worker 都不直接暴露给浏览器。

## 节点目录到图节点的映射

### 节点目录来源

后端通过 `GET /api/v1/workflows/node-catalog` 返回当前节点目录快照，主要字段包括：

- `node_pack_manifests`：已发现的 node pack manifest。
- `payload_contracts`：端口 payload 类型规则。
- `node_definitions`：core nodes 和 custom nodes 合并后的节点定义。
- `palette_groups`：按 `category` 整理后的节点面板分组。

后端已经在 node-catalog 响应中把 `parameter_schema` 与显式 `parameter_ui_schema` 合并，前端应优先消费返回后的 `parameter_ui_schema`，不在浏览器里重新猜测参数 UI 规则。

### 字段映射

| 后端字段 | 前端用途 |
| --- | --- |
| `node_type_id` | LiteGraph node type、模板节点实例引用、搜索主键 |
| `display_name` | 节点标题、节点面板显示名、搜索结果显示名 |
| `category` | 节点面板分组、颜色和图标默认规则 |
| `description` | 节点提示、详情面板说明 |
| `implementation_kind` | 显示 core/custom 来源 |
| `runtime_kind` | 显示运行方式，例如 service-call、python-callable、worker-task |
| `input_ports` | 生成输入插槽和连接校验规则 |
| `output_ports` | 生成输出插槽和连接校验规则 |
| `payload_type_id` | 端口颜色、端口提示、连接兼容性判断 |
| `parameter_schema` | 参数默认值、校验和兜底渲染依据 |
| `parameter_ui_schema` | 参数面板分组、字段组件、显示顺序、只读和隐藏规则 |
| `capability_tags` | 节点筛选、能力标签和后续推荐规则 |
| `runtime_requirements` | 依赖提示、禁用原因和运维排障信息 |
| `node_pack_id` / `node_pack_version` | custom node 来源和版本提示 |
| `metadata` | 图标、示例、结果展示建议等非核心扩展信息 |

### 前端内部对象

前端应把节点目录和图草稿分开保存：

```text
NodeDefinitionIndex
├─ byNodeTypeId
├─ byCategory
├─ byPayloadTypeId
└─ nodePackSummary

GraphDraft
├─ nodes: GraphNodeDraft[]
├─ edges: GraphEdgeDraft[]
├─ templateInputs: TemplateInputDraft[]
├─ templateOutputs: TemplateOutputDraft[]
└─ dirtyState
```

`GraphNodeDraft` 只保留下面这类信息：

- `node_id`
- `node_type_id`
- `parameters`
- `ui_state`
- `metadata`

渲染节点标题、端口、参数面板和来源说明时，再通过 `node_type_id` 到 `NodeDefinitionIndex` 读取定义。

### 连接校验

前端连线校验应先做轻量检查，再交给后端 validate 做最终判断。

前端轻量检查：

- 源端口必须来自 `output_ports`。
- 目标端口必须来自 `input_ports`。
- 源端口和目标端口的 `payload_type_id` 必须一致。
- 非 `multiple=true` 的输入端口只允许一条上游边。
- 禁止自环。
- 画布上可以提前提示 DAG 风险，但最终是否成环以后端 validate 结果为准。

后端最终检查：

- `POST /api/v1/workflows/templates/validate`
- 保存 template 时再次校验
- 创建 PreviewRun、AppRuntime 或 WorkflowRun 时固定 snapshot 并校验运行输入

### 参数面板

`NodeInspector` 的渲染顺序：

1. 读取当前节点实例的 `node_type_id`。
2. 从 `node-catalog.store.ts` 找到 `NodeDefinition`。
3. 按 `parameter_ui_schema.groups` 绘制分组。
4. 按 `parameter_ui_schema.fields` 选择字段组件。
5. 字段值读写到 `GraphNodeDraft.parameters`。
6. 保存或试跑前把草稿转换为 `WorkflowGraphNode.parameters`。

字段组件由 `shared/ui/form` 和 workflow editor 的 `inspector/fields` 共同承担：

- 基础类型使用 `shared/ui/form`，例如文本、数字、布尔、枚举、数组和对象。
- 业务字段使用 workflow editor 内部字段组件，例如模型选择、deployment 选择、dataset export 选择、颜色阈值和 ROI 配置。
- 如果 `parameter_ui_schema` 为空，参数面板显示“无参数”状态。
- 如果字段组件暂不支持，参数面板使用 JSON 编辑器兜底，并在保存前调用后端 validate。

### custom node 新增后的前端表现

后端新增 custom node 的正常链路：

1. node pack 增加或修改 Python 节点实现。
2. node pack 更新 `workflow/catalog_sources` 或 `workflow/catalog.json`。
3. backend-service 通过 LocalNodePackLoader 和 NodeCatalogRegistry 合并节点目录。
4. 前端刷新 `GET /api/v1/workflows/node-catalog`。
5. 新节点自动进入 `NodePalette` 和 `NodeSearch`。
6. 参数面板按 `parameter_ui_schema` 渲染。
7. 图保存和运行仍由后端校验节点定义与执行能力。

前端不需要为每个 custom node 新增硬编码组件。只有下面两类能力可以进入前端代码：

- 通用参数编辑器和通用结果查看器。
- 受控 `plugins/builtin` 中登记的内置字段或结果展示组件。

第一阶段不允许 node pack 携带任意前端 JS 注入工作台。

### 节点目录变化和模板兼容

已保存模板只引用 `node_type_id`、参数和 `ui_state`。当后端节点目录变化时，前端按下面规则处理：

- 当前 catalog 中找不到 `node_type_id`：画布节点显示为缺失状态，禁止保存覆盖，允许另存为修复版本。
- 端口减少或 payload 类型变化：相关边显示错误，模板 validate 返回最终错误。
- 参数 schema 变化：参数面板显示现有参数和新字段，未知字段保留在 JSON 视图中，保存前提示需要确认。
- custom node 的 `node_pack_version` 仅用于显示和排障；当前模板版本固定仍以后端保存规则为准。后续如需严格 pin 版本，应扩展 template JSON，而不是由前端自行记录。

## workflow 编辑和运行流程

### 新建或打开模板

1. 进入 `/workflows/templates`。
2. 列表页读取 `GET /api/v1/workflows/projects/{project_id}/templates`。
3. 打开编辑页时读取 template 详情，或创建空白草稿。
4. 编辑器启动时读取 node catalog，建立本地索引。
5. `template-to-graph.ts` 把 `WorkflowGraphTemplate` 转换为 `GraphDraft`。
6. LiteGraph adapter 根据 `GraphDraft` 创建画布节点和连线。
7. 用户修改节点、连线、参数、模板输入和模板输出。
8. `graph-to-template.ts` 把草稿转换回 `WorkflowGraphTemplate`。
9. 调用 `POST /api/v1/workflows/templates/validate`。
10. 校验通过后调用 template save 接口。

模板编辑页必须支持三类错误定位：

- 节点错误：定位到节点卡片和右侧参数面板。
- 端口或连线错误：定位到连线和对应端口。
- 模板输入输出错误：定位到右侧 GraphInspector。

### 创建流程应用

FlowApplication 负责把模板输入输出绑定到现场入口和返回方式。

1. 从模板详情或应用列表进入 application 创建页面。
2. 选择 template id 和 version。
3. 读取 template summary，展示 `template_inputs` 和 `template_outputs`。
4. 为输入选择 binding kind，例如 API request、upload、ZeroMQ trigger 或后续协议入口。
5. 为输出选择 binding kind，例如 HTTP response、result file、callback 或协议回写。
6. 调用 `POST /api/v1/workflows/applications/validate`。
7. 调用 application save 接口。

当前阶段不自动生成专用 FastAPI 路由。前端在应用详情页应明确显示通用调用入口：

- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke`
- `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs`

### 编辑态试跑

PreviewRun 用于工作流调试，不等同于正式运行。

1. 编辑器把当前草稿转换为 inline template 和 inline application。
2. 用户在 PreviewRunPanel 中填写输入绑定。
3. 调用 `POST /api/v1/workflows/preview-runs`。
4. `wait_mode=sync` 时直接展示返回结果。
5. `wait_mode=async` 时先展示 running 状态，再订阅 `/ws/v1/workflows/preview-runs/events`。
6. 断线或切页回来时，先调用详情接口和 events 历史接口恢复状态，再继续订阅实时事件。
7. 结果进入 `result-viewer`，节点执行摘要叠加到画布节点状态。

界面不能假设 `node_records` 一定存在。执行策略可能关闭 trace 和节点记录，此时应只展示最终 outputs、template_outputs 和错误摘要。

### 发布应用运行

已发布应用运行由 WorkflowAppRuntime 承接。

1. 应用详情页点击创建 runtime。
2. 调用 `POST /api/v1/workflows/app-runtimes`，后端固定 application/template snapshot。
3. RuntimeDetailPage 展示 desired_state、observed_state、health、instances 和最近事件。
4. 用户执行 start、stop、restart。
5. 运行状态通过 REST 快照和 `/ws/v1/workflows/app-runtimes/events` 同步。
6. runtime running 后，InvokePanel 才允许调用。

### 正式调用

正式调用分同步和异步两条路径，但都落到 WorkflowRun。

同步调用：

1. 调用 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke`。
2. 请求等待返回完整 WorkflowRun。
3. 页面展示 state、outputs、template_outputs、错误摘要和耗时。

异步调用：

1. 调用 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs`。
2. 立即展示 workflow_run_id 和 queued/running 状态。
3. 订阅 `/ws/v1/workflows/runs/events`。
4. 需要恢复时调用 `GET /api/v1/workflows/runs/{workflow_run_id}` 和 events 历史接口。
5. 终态后展示结果，必要时允许 cancel。

multipart 调用只在后端当前支持的绑定类型范围内开放。界面应根据 application input binding 的 payload 类型决定是否展示文件上传控件。

## 数据集到模型发布流程

数据集、训练、验证、转换、部署和推理不是单个页面完成，而是一条跨模块操作流。前端应把它实现为模块页面加操作向导的组合。

```text
DatasetImport
  → DatasetVersion
  → DatasetExport
  → TrainingTask
  → ModelVersion
  → ValidationSession / EvaluationTask
  → ConversionTask
  → ModelBuild
  → DeploymentInstance
  → InferenceTask / workflow detection node
```

### 数据集导入

页面入口：`/datasets`、`/datasets/imports` 或数据集详情页。

前端流程：

1. 选择 Project 和导入目标。
2. 上传 zip 包，调用 `POST /api/v1/datasets/imports`。
3. 返回 `dataset_import_id` 和关联 task 信息后进入导入详情页。
4. 轮询导入详情，或通过任务事件流更新状态。
5. 展示 detected profile、split、class summary、validation_report 和 error_message。
6. 成功后展示生成的 DatasetVersion，并提供“创建导出”动作。

布局建议：

- 左侧为导入步骤和状态。
- 中间为包信息、格式识别和校验摘要。
- 右侧为错误列表、样本统计和后续动作。

### 数据集导出

页面入口：DatasetVersionDetailPage。

前端流程：

1. 读取 `GET /api/v1/datasets/export-formats` 展示可用格式。
2. 创建 DatasetExport。
3. 在导出详情中展示 status、manifest_object_key、export_path、class_count、sample_count。
4. 完成后允许 package、download 和查看 manifest。
5. 训练创建页只消费 DatasetExport，而不直接读取 DatasetVersion 内部目录。

### 训练

页面入口：`/models/training`、DatasetExport 详情页或训练发布向导。

前端流程：

1. 选择 DatasetExport。
2. 选择基础模型、训练配置、设备和输出选项。
3. 调用 YOLOX training task 创建接口。
4. 跳转 TrainingTaskDetailPage。
5. 详情页展示 stage、percent、epoch、best metric、train metrics、validation metrics 和输出文件状态。
6. 操作按钮只依据 `available_actions` 和 `control_status` 显示 save、pause、resume、terminate。
7. 当 `latest_checkpoint_model_version_id` 可用时，显示“进入验证”动作。
8. 任务完成后，展示 best/latest checkpoint、labels、summary 和自动登记的 ModelVersion。

布局建议：

- 顶部状态条显示任务状态、进度、当前 epoch 和主要指标。
- 主区域左侧显示指标曲线，右侧显示配置和输出文件。
- 底部事件面板显示训练事件和最近日志。

### 验证和评估

单图人工验证：

1. 选择 ModelVersion 或 latest checkpoint。
2. 创建 validation session。
3. 上传或选择测试图片。
4. 调用 predict。
5. 在结果查看器中显示图片、检测框、类别、score 和原始 JSON。

数据集级评估：

1. 选择 ModelVersion 和 DatasetExport 或评估输入。
2. 创建 evaluation task。
3. 详情页展示进度、mAP、错误样本摘要和评估输出文件。
4. 评估结果可作为 conversion 或 deployment 前的质量参考。

### 转换

页面入口：ModelVersionDetailPage 或训练发布向导。

前端流程：

1. 选择 source ModelVersion。
2. 选择目标格式：ONNX、optimized ONNX、OpenVINO IR、TensorRT engine 等。
3. 调用对应 conversion task 创建接口。
4. ConversionTaskDetailPage 展示状态、目标格式、precision、输出文件和验证摘要。
5. 成功后展示 ModelBuild，并提供“创建部署”动作。

### 发布推理服务

页面入口：ModelBuildDetailPage 或 `/deployments`。

前端流程：

1. 选择 ModelBuild。
2. 创建 DeploymentInstance。
3. 进入 DeploymentDetailPage。
4. 控制 start、warmup、health、stop、reset。
5. 订阅 deployment events，展示子进程、runtime backend、warmup、健康状态和错误摘要。
6. running 后允许同步 infer 或创建异步 inference task。

推理入口分两类：

- REST 推理任务：面向外部调试、批量或异步请求，使用 inference task 接口。
- workflow detection 节点：在 PreviewRun、WorkflowAppRuntime 和 WorkflowRun 中通过 PublishedInferenceGateway 调用已发布 deployment，不走公开 inference task 接口。

前端页面要把这两类路径分开显示，避免把 workflow 内部推理误认为普通 inference task。

## 页面布局规划

### WorkbenchShell

WorkbenchShell 面向工作站和现场操作，布局以稳定、密集、可扫描为主。

```text
┌────────────────────────────────────────────────────────────┐
│ Topbar: Project / backend status / user / runtime warnings │
├───────────────┬────────────────────────────────────────────┤
│ Sidebar       │ Page content                                │
│ - Projects    │                                            │
│ - Datasets    │                                            │
│ - Tasks       │                                            │
│ - Models      │                                            │
│ - Deployments │                                            │
│ - Workflows   │                                            │
│ - Integrations│                                            │
│ - CustomNodes │                                            │
│ - Settings    │                                            │
├───────────────┴────────────────────────────────────────────┤
│ BottomPanel: event stream / task log / diagnostics         │
└────────────────────────────────────────────────────────────┘
```

布局规则：

- 左侧导航固定，支持折叠。
- 顶部栏只放当前 Project、后端连接、用户和关键运行状态。
- 底部面板用于任务事件、运行日志和诊断，不作为普通页面内容区。
- 页面主体优先使用表格、分栏详情和状态条，避免营销式大卡片布局。

### WorkflowEditorPage

```text
┌────────────────────────────────────────────────────────────┐
│ EditorToolbar: save / validate / preview / publish / zoom  │
├───────────────┬───────────────────────────┬────────────────┤
│ NodePalette   │ WorkflowCanvas            │ Inspector      │
│ search/filter │ LiteGraph canvas          │ node/graph/app │
├───────────────┴───────────────────────────┴────────────────┤
│ RunPanel: inputs / events / outputs / node records         │
└────────────────────────────────────────────────────────────┘
```

布局规则：

- NodePalette 默认宽度 280-340px，支持搜索、分类、node pack 过滤和 payload 类型过滤。
- Canvas 占主区域，负责拖拽、连线、框选、快捷键和视图缩放。
- Inspector 默认宽度 360-440px，显示节点参数、端口信息、GraphInspector 和 ApplicationBindingInspector。
- RunPanel 默认高度 260-360px，展示输入绑定、试跑状态、事件、结果和错误。
- 1080p 屏幕下允许折叠 Palette、Inspector 或 RunPanel，但不能隐藏保存、校验和试跑入口。

### 资源详情页

数据集、训练、转换、部署、runtime 和 run 详情页采用同一类布局：

```text
Header: title / state / primary actions
Summary: key metrics / timestamps / references
Main: table, chart, result viewer or config
Side: metadata / related resources / next actions
Bottom: events / logs / diagnostics
```

状态、动作和错误来源以后端响应为准。前端按钮启用状态只读 `available_actions`、状态字段或明确的 health 响应，不自己推断后台是否可执行。

## 状态和通信实现规则

### REST 快照 + WebSocket 增量

所有长任务和 runtime 页面使用同一模式：

1. 进入页面先调用 REST 详情接口取得快照。
2. 读取 events 历史接口恢复最近事件。
3. 建立 WebSocket 订阅实时事件。
4. WebSocket 事件更新本地 store。
5. 断线重连后再次读取 REST 快照和 events 历史。
6. 最终状态以 REST 详情为准。

### store 分层

- `shared/api`：HTTP client、错误、分页、上传和文件 URL。
- `shared/ws`：连接、订阅、cursor、重连和 lagging 处理。
- `modules/*/services`：资源语义 API，例如 dataset、training、deployment。
- `modules/*/stores`：列表、详情、筛选和页面草稿。
- `workflows/workflow-editor/stores`：node catalog、graph draft、editor state、preview run 和 workflow run。

### 结果查看

`result-viewer` 根据 payload 类型和结果结构选择展示组件：

| payload 类型或结果形状 | 默认展示 |
| --- | --- |
| `image-ref.v1` | 图片查看器，优先通过公开文件读取接口取图 |
| `detections.v1` | 检测框叠加、类别表格、score 过滤 |
| `measurements.v1` | 表格和关键值摘要 |
| `response-body.v1` | JSON / 表格 / 图片预览组合 |
| `http-response.v1` | status、headers、body 分区展示 |
| 普通 JSON | JSON tree 和复制按钮 |
| 脱敏 base64 | 显示脱敏状态，不尝试还原图片 |
| memory image-ref | 显示摘要，提示该引用只在本机短期有效 |

需要长期查看的图片和结果必须通过后端保存为 ObjectStore 文件引用，再由前端通过公开文件接口读取。

## 第一阶段实现范围

第一阶段前端实现建议按下面顺序推进：

1. 工程骨架、路由、WorkbenchShell、API client、WebSocket client 和基础 UI。
2. Project 上下文、后端连接状态、错误处理和全局事件面板。
3. Tasks 列表和详情，用它验证 REST 快照 + WebSocket 增量模式。
4. Datasets 导入、导出和 DatasetVersion 详情。
5. YOLOX training 任务创建、详情、控制按钮、指标和输出文件。
6. Validation session、evaluation task、conversion task 和 ModelBuild 详情。
7. DeploymentInstance 列表、详情、控制、事件和 inference task 调试。
8. Custom Nodes 只读目录、node pack 来源、节点定义详情和 schema 预览。
9. Workflow editor 的 node catalog、palette、canvas、inspector 和 template validate/save/load。
10. PreviewRun 调试、result-viewer、节点状态叠加和事件恢复。
11. FlowApplication binding、AppRuntime 控制和 WorkflowRun sync/async 调用。
12. release 组装接入前端构建结果。

## 当前规划缺口

在开始真实编码前，还需要把下面几项进一步固定：

- 启动会话和默认本地用户细节见 [frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md)。runtime config、默认 user token 来源、退出后手动登录标记、类型生成、文件读取、权限、测试和发布接入见 [frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)。
- LiteGraph 来源、版本、license、本地补丁目录和升级方式。
- WebSocket 事件类型到 store 更新的最小映射表。
- Workflow validate 错误如何携带节点、端口和字段定位信息；如果后端暂未提供精确定位，前端先显示全局错误和相关节点 id。
- `parameter_ui_schema` 的字段组件清单和内置业务字段组件清单。
- result-viewer 的第一批 payload 类型示例和测试数据。
- Custom Nodes 管理 API 尚未覆盖 enable、disable、rollback 时，前端第一阶段只做只读目录，不做管理动作。

这些缺口不阻塞搭建工程骨架，但会影响 workflow editor、结果查看和全链路页面的开发质量，应在对应模块开工前逐项固定。

## 不做事项

- 不在浏览器前端执行 Python node。
- 不让前端直接读取 `custom_nodes` 文件夹。
- 不把 LiteGraph JSON 作为后端保存格式。
- 不通过前端硬编码 custom node 类型。
- 不把 PreviewRun 当成正式生产调用记录。
- 不把 WorkflowRun 当成训练、转换和推理任务系统的替代物。
- 不让浏览器直接访问 ZeroMQ、LocalBufferBroker、数据库、deployment worker 或 workflow worker。

## 推荐同步文档

- [frontend-web-ui.md](frontend-web-ui.md)
- [frontend-web-ui-structure.md](frontend-web-ui-structure.md)
- [frontend-web-ui-startup-session.md](frontend-web-ui-startup-session.md)
- [frontend-web-ui-development-readiness.md](frontend-web-ui-development-readiness.md)
- [workflow-json-contracts.md](workflow-json-contracts.md)
- [workflow-runtime.md](workflow-runtime.md)
- [node-system.md](node-system.md)
- [../api/workflows.md](../api/workflows.md)
- [../api/datasets-imports.md](../api/datasets-imports.md)
- [../api/datasets-exports.md](../api/datasets-exports.md)
- [../api/yolox-training.md](../api/yolox-training.md)
