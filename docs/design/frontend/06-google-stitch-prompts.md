# Google Stitch 前端设计提示词

## 1. 使用目标

Google Stitch 用于把已确定的视觉方向转为结构明确、组件可复用、便于继续实现的页面设计。与图片生成不同，Stitch 提示应强调页面层级、组件名称、字段、交互和响应式行为。

推荐先用“项目级提示”建立统一外壳和 design system，再按业务域逐批生成页面。不要一次要求生成全部页面，否则容易出现导航、组件和资源名称不一致。

## 2. 项目级主提示

```text
Design a desktop-first industrial computer vision platform named AMVision. The product is local-first and used by vision engineers, field deployment engineers, workflow engineers, and operators. It manages projects, datasets, background tasks, model training and evaluation, model conversion, long-running deployment instances, sync/async inference, workflow applications, trigger sources, custom nodes, and system diagnostics.

Visual direction: “human-crafted, clean, futuristic.” Human-crafted means deliberate hierarchy, direct labels, traceable sources, clear manual controls, and a professional engineering-tool character. Clean means a stable grid, compact spacing, thin separators, limited color, and dense but readable information. Futuristic means precise live status, computer-vision overlays, node graphs, and subtle realtime feedback. Do not use cyberpunk neon, glassmorphism, marketing dashboard cards, huge rounded containers, 3D illustrations, or decorative HUD elements.

Use a desktop 16:10 canvas. Create a reusable app shell with a 232px collapsible left sidebar, a 54px top context bar, a flexible main content area, and an optional 360px right inspector. Sidebar groups: 工作空间 (项目, 任务), 数据与模型 (数据集, 模型, 部署, 推理), 自动化 (流程图, 流程应用, 触发源, 自定义节点), 系统 (设置与诊断). Top bar: current project switcher, breadcrumb, global resource search, backend connection status, active task count, and user menu.

Default light theme: page #F6F7F9, surface #FFFFFF, strong text #171A1F, body #344054, muted #667085, border #E4E7EC, deep emerald primary #087A56, soft selected background #EAF6F1. Dark immersive canvas: #101010 and #171918 with bright emerald #00D992 only for selection, healthy runtime, progress, and primary action. Use 4–8px corner radius, subtle shadows only for overlays, compact 36–40px controls, 44–56px table rows, and Inter/system sans fonts with monospace for IDs, paths, logs, and JSON.

Build reusable components: AppShell, ProjectSwitcher, PageHeader, Breadcrumb, ConnectionStatus, ActiveTaskMenu, StatusBadge, FilterBar, DataTable, MetricStrip, ResourceRelation, StepWizard, RightInspector, ImageCanvas, VisionOverlayLegend, TrainingMetricChart, RuntimeHealthPanel, LogViewer, JsonViewer, EmptyState, ErrorSummary, ConfirmDialog, NodeLibrary, WorkflowCanvas, NodeInspector, RunPanel.

Every resource page must show project context, name/ID, resource type, status, source relationship, timestamps, primary action, empty state, loading state, error state, and narrow desktop behavior. Distinguish finite TaskRecord states (queued, running, succeeded, failed, cancelled) from long-running runtime states (stopped, starting, healthy, degraded, failed). Do not mix DatasetVersion with DatasetExport. Do not mix WorkflowGraphTemplate, FlowApplication, WorkflowAppRuntime, and WorkflowRun.

Use Simplified Chinese UI copy. Keep technical names such as YOLO11, RF-DETR, ONNX, OpenVINO, TensorRT, runtime, task ID, format_id, FP16, CUDA, NPU in English. Keep all layouts feasible in Vue 3 with standard CSS, SVG, Canvas, and a LiteGraph/Vue Flow style graph editor.
```

## 3. 数据与任务页面批次

将项目级主提示作为项目上下文，然后依次提交以下页面提示。

### S01–S03 系统入口与全局状态

```text
Create five system-entry and global-state screens using one reusable SystemStateShell instead of the full business navigation.

1. S01 StartupCheckPage at /: show AMVision v0.1.4, local API, local session, SQLite schema, static assets/node catalog, and workspace startup as five explicit checks. Use completed, checking, and waiting icons plus text. Show diagnostics and automatic-entry branches without implying a blocked spinner.
2. S02 LoginPage at /login: use a dark-ink brand panel and a light local-login form. Show local service connection, username/password, manual login after session restore did not complete, backend address, and v0.1.4. Do not add registration, social login, or cloud collaboration.
3. S03 OfflinePage at /offline: show the unavailable local service address, last connection time, read-only cache mode, reconnect, and connection settings. Disable writes without clearing cached data.
4. S03 ForbiddenPage at /forbidden: show 403, resource type/name, required local scope, current user, safe return, and copy diagnostics. Do not add an online permission-request workflow.
5. S03 NotFoundPage at /not-found: show 404, resource type and ID, source path or query time, the correct resource-list return action, and copy resource ID.

Keep all five screens local-first, compact, accessible without color alone, and free of marketing illustrations.
```

### P01 项目列表

```text
Create a ProjectListPage at /projects using the shared AppShell. Header actions: 新建项目 (primary), 生成 SDK 配置包 (secondary). Main content is a compact table with project name, short ID, description, dataset count, model count, workflow app count, and updated time. Clicking a row switches project context. Use a right drawer for creating a project with name and description. Include an SDK package panel and a dependency-aware delete confirmation. Create populated, empty, and delete-blocked states.
```

### P02 项目概览

```text
Create ProjectOverviewPage at /projects/:projectId as the project-level entry to the end-to-end vision workflow. Header shows project name, short ID, description, edit, and SDK package generation. Use four compact resource counts for DatasetVersion, available ModelVersion, healthy DeploymentInstance, and running WorkflowAppRuntime; do not turn them into sales KPIs. Add a recent-resource timeline and a current-operations panel that explicitly separates finite TaskRecord entries from long-running DeploymentInstance and WorkflowAppRuntime entries. Finish with four continue-work cards for importing data, creating training, creating deployment, and editing workflow, each with one recent resource and one action. Include active, new-project-empty, and failed-task variants.
```

### T01 任务中心与 T02 详情

```text
Create TaskListPage at /tasks and TaskDetailPage at /tasks/:taskId. The list has a compact metric strip for running, queued, failed, and completed today; a filter bar for project, task type, status, queue, date, and task ID search; and a live table with type, related resource, stage, progress, status, start time, duration, and actions. Use websocket status as a small connection indicator, but treat REST data as final authority.

The detail page has task identity and actions, a summary grid, a chronological event timeline, a stage/progress panel, a structured ErrorSummary, a collapsible stack trace, request/result JSON, and links to related resources. Explicitly support queued, running, succeeded, failed, and cancelled variants. Do not show deployment runtimes or workflow runtimes as tasks.
```

### D01 数据集工作台

```text
Create DatasetOperationsPage at /datasets. Header actions: 导入数据集 and 创建导出. Add local tabs: 数据集, 导入记录, 数据版本, 导出记录. Each tab uses a task-aware FilterBar and DataTable. Dataset rows show task type, source format, current version, sample and annotation counts, splits, classes, and update time. Import rows show detected format, validation state, progress, and timestamps. Version rows show immutable version identity and split summary. Export rows show format_id, model compatibility, status, package size, and source version. Keep DatasetVersion and DatasetExport visually distinct.
```

### D02 数据集导入向导

```text
Create a five-step DatasetImportWizard: 上传, 数据定义, split 与类别, 预检查, 提交. Accept zip only. Task type controls available formats: classification=ImageNet; detection=COCO/VOC/YOLO; segmentation=COCO/YOLO; pose=COCO/YOLO; obb=DOTA/YOLO. Provide split_strategy auto/train/val/test and optional class map JSON. The preflight step shows a directory summary, image/annotation counts, split counts, category map, warnings, and blocking errors. Submitting creates an async DatasetImport and navigates to its detail page. Include unsafe-path, invalid-label, missing-image, and incompatible-format errors.
```

### D03–D06 数据集详情与导出

```text
Create four related pages using shared ResourceHeader and ResourceRelation components.

1. D03 DatasetImportDetailPage: import stage timeline, package/staging/queue summary, validation report, detected format, category map, metadata, and generated DatasetVersion link.
2. D04 DatasetVersionDetailPage: immutable version header; metrics; tabs for overview, samples, classes, annotation quality, exports, metadata; task-specific image overlays; Create Export action.
3. D05 DatasetExportWizard: source version, target model or format_id, compatibility rules, split/category check, expected files and disk size; make clear that trainers consume DatasetExport.
4. D06 DatasetExportDetailPage: format, source version, package file/checksum, runtime data, split list, category list, metadata, download, and Create Training action.

Use VOC2012 Detection as realistic example data, with 11,540 images, train 5,717, val 5,823, and 20 classes.
```

## 4. 模型页面批次

### M01 模型工作台

```text
Create ModelOperationsPage at /models. First-level task tabs: classification, detection, segmentation, pose, obb. Second-level resource tabs: 模型版本, 训练任务, 转换任务, 构建产物. Add header actions 创建训练 and 转换模型. Use the backend capability catalog to restrict model/task combinations: YOLOX only detection; YOLOv8, YOLO11, YOLO26 support all five tasks; RF-DETR only detection and segmentation. Never show unsupported combinations. Model versions should show source, metric, runtime build matrix, deployment count, and update time. Include platform base-model picker and project-trained-model picker as separate sections.
```

### M02 创建训练

```text
Create a five-step TrainingTaskWizard: 任务与模型, 数据, 初始化, 参数, 确认. The task selection filters compatible models. DatasetExport selection shows format_id, train/val/test, classes, samples, and model compatibility; missing val is a blocking error. Initialization has three distinct choices: platform pretrained warm start, ModelVersion warm start, or resume from compatible training checkpoint. Parameters are schema-driven and include epochs, batch/AutoBatch, input size, device, AMP, optimizer, learning rate, workers, and checkpoint interval only when supported. The final summary shows model, data, initialization semantics, splits, parameters, device check, and outputs.
```

### M03 训练详情

```text
Create TrainingTaskDetailPage. Header shows display name, model/task, finite task status, refresh/cancel/register/delete actions depending on state. Add summary, epoch/batch/ETA progress, separate train loss, val loss, and main metric charts, a best epoch marker, completed-epoch metrics, current-batch metrics, validation metrics, and output files. Distinguish best checkpoint from latest checkpoint. After success, link to ModelVersion, Conversion, and Evaluation. If no test split exists, show final test unavailable instead of reusing val. Failure state keeps last epoch, latest checkpoint, error summary, logs, and valid resume options.
```

### M04–M06 评估与模型版本

```text
Create M04 EvaluationCenterPage, M05 EvaluationDetailPage, and M06 ModelVersionDetailPage.

Evaluation Center has ValidationSession, EvaluationTask, and Compare tabs with filters and result tables. Compare only evaluations with the same task and dataset contract.

Evaluation Detail uses task-specific metrics: classification top-1/top-5; detection box AP/precision/recall; segmentation mask AP/IoU; pose OKS AP; OBB rotated IoU/AP. Add class table, PR curve or confusion matrix where relevant, TP/FP/FN sample gallery with task-specific overlays, runtime settings, and report export.

Model Version Detail shows provenance from TrainingTask and DatasetExport, task/model type, input and label schema, best metric, files, checksum, evaluations, deployments, workflow references, and a build matrix for PyTorch, ONNX, ONNX optimized, OpenVINO IR, and TensorRT engine.
```

### M07–M08 转换

```text
Create ConversionTaskWizard and ConversionTaskDetailPage. Wizard source is ModelVersion. Current targets are ONNX, ONNX optimized, OpenVINO IR, and TensorRT engine. Do not expose CoreML or ARM NPU as currently available. Target-specific parameters include opset, dynamic/static shapes, precision, workspace, and device profile. The final compatibility check must show model/task schema, target runtime, hardware, and version constraints.

Detail page shows source, target, precision, device profile, conversion stage timeline, one or more ModelBuild rows, file size/checksum/device compatibility, output validation summary, raw spec in a collapsed JsonViewer, errors by stage, and Create Deployment action for successful builds.
```

## 5. 部署与推理页面批次

### R01 部署工作台

```text
Create DeploymentOperationsPage at /deployments. Treat each DeploymentInstance as a long-running supervised service, not a finite background task. Header actions: 新建部署, 刷新, 设备能力. Create flow selects ModelBuild, sync or async mode, runtime, device, precision, display name, concurrency and queue settings. Runtime options are capability-driven: PyTorch, ONNX Runtime, OpenVINO, TensorRT with valid CPU/CUDA/AUTO/GPU/NPU and FP32/FP16 combinations. The table shows model/task, runtime, device, mode, health, uptime, P95, and updated time. Row actions: start, stop, restart, warmup, reset, open inference, delete. Selecting a row opens a RuntimeHealthPanel with process, endpoint, input schema, and events.
```

### R02 部署详情

```text
Create DeploymentInstanceDetailPage. Header has instance identity, health, sync/async mode, start/stop/restart, and Open Inference. Show model build, runtime, device, precision, uptime, heartbeat, and endpoint. Tabs: 概览, 接口, 输入输出, 事件, 日志, 配置, 引用. Monitoring supports request rate, average/P95 latency, error rate, and queue depth only when data exists. Show workflow runtime references and dependency impact before stop/delete. Failure state shows process exit code, last heartbeat, runtime error, and recovery action.
```

### I01 推理实验室

```text
Create InferenceDebugPage at /inference with a desktop three-column workspace. Top target selector displays healthy DeploymentInstances with model/task/runtime/device/mode. Left column: input source and schema-driven parameters. Center: large ImageCanvas with zoom, pan, fit/original, overlay toggles, confidence threshold, class filter, and legend. Right inspector: latency breakdown, task-specific result list, selected prediction fields, and JSON. Bottom: async task history and result retrieval. Provide sync and async actions with distinct labels. Render classification labels, detection boxes, segmentation masks, pose skeletons, and OBB rotated boxes according to task type.
```

## 6. 流程与扩展页面批次

### W01–W02 流程应用

```text
Create WorkflowAppListPage and WorkflowAppDetailPage. The list distinguishes published FlowApplication from its WorkflowAppRuntime instances. Show template version, runtime count, trigger count, latest run, status, and updated time. Actions: create workflow, view app, edit graph, create runtime, delete when allowed.

App Detail contains application summary, App Contract input/output ports, runtime table, selected-runtime HTTP endpoint and request example, last receipt, recent WorkflowRun records, and TriggerSource list. Runtime actions: set current, start, stop, restart, health refresh, add trigger, delete. Keep long-running runtime health separate from individual run success/failure.
```

### W03 流程编辑器

```text
Create a full-bleed dark WorkflowEditorPage. Structure: compact top command bar, searchable/categorized NodeLibrary on the left, large WorkflowCanvas in the center, NodeInspector on the right, collapsible RunPanel at the bottom. Top commands: back, editable graph name/version, save state, undo/redo, validate, preview run, publish, more. Node categories: Input, IO, Vision, Model, Logic, Service, Support, Video, Custom. Nodes have typed input ports on the left and output ports on the right. Support node groups, minimap, zoom, selection, disabled nodes, validation errors, and read-only published view.

The inspector is schema-driven and can select a DeploymentInstance for model nodes. Preview run shows input bindings, per-node state and duration, image/result preview, logs, and direct navigation to the failed node. Publish flow shows version note, App Contract changes, and compatibility check. Use a subtle dot grid and low-saturation category colors; selected node uses emerald, error uses a small red indicator.
```

### X01 触发源

```text
Create TriggerSourcePage at /integrations/trigger-sources. Creation starts from a selected healthy WorkflowAppRuntime, then protocol template, endpoint/topic, idempotency key path, LocalBuffer pool when relevant, and visual mapping from external payload fields to App Contract inputs. Table columns: name, type, runtime, endpoint/topic, enabled, health, latest trigger. Actions: enable/disable, test, copy config, view receipt, delete. Do not create a core camera or PLC driver control center; direct hardware connections belong to permissioned custom nodes or external agents.
```

### N01 自定义节点目录

```text
Create CustomNodeCatalogPage at /custom-nodes with a three-column catalog layout. Left: node packs and categories. Center: searchable node definitions or selected pack rows. Right inspector: node display name and node_type_id, description, inputs, outputs, parameters, phase, enabled state; for packs show manifest version, capabilities, dependencies, entrypoint, permissions, compatibility, timeout, isolation, enabledByDefault, logs, and audit. Actions: rescan, enable, disable. Include barcode, camera, database, hello_world, http, opencv, plc, sam3, and yoloe as realistic packs, clearly labeled as extensions.
```

## 7. 设置页面批次

### C01 设置与诊断

```text
Create SettingsDiagnosticsPage at /settings using a full-width three-level settings layout. Primary categories: 常规, 系统, 访问与安全. Secondary sections include preferences, services, about, host, Python, devices, session, projects, providers. Show API, WebSocket, database, object store, queue, and six worker profiles; app/OS/CPU/memory/disk; development or bundled Python runtime; CPU/CUDA/OpenVINO GPU/NPU/TensorRT capabilities; current session scopes and project access. Actions: refresh, copy diagnostic summary, download diagnostic package. Use clear availability, version, reason, and last checked fields. Do not expose unsafe system path editing as a normal preference.
```

## 8. 组件复用补充提示

如果 Stitch 为不同页面生成了不一致的组件，追加以下提示：

```text
Refactor these screens to reuse the established AMVision components and tokens. Keep exactly one AppShell, PageHeader, StatusBadge system, FilterBar, DataTable density, form control style, empty state style, error summary style, right inspector, and confirmation dialog. Preserve the deep emerald primary color, 4–8px radius, thin borders, desktop density, Simplified Chinese labels, and monospace technical values. Do not redesign individual pages as separate visual themes.
```

## 9. 响应式补充提示

```text
Create a 1366×768 narrow-desktop variant without converting the product into a mobile app. Collapse the sidebar to 64px icons, keep the current project accessible, hide low-priority table columns, make the inspector an overlay drawer, stack charts vertically when needed, and preserve primary actions and health status. For the workflow editor, show either NodeLibrary or NodeInspector at one time while keeping the canvas usable.
```

## 10. 状态补充提示

### 空状态

```text
Add realistic empty states using a small line icon, direct title, prerequisite explanation, and one primary action. Do not use people illustrations. Keep filters and page context visible.
```

### 领域首次空状态

```text
Create four domain-specific first-empty variants while preserving the populated page shell, filters, table headers, and component tokens:

1. T01 TaskListPage: all counters are zero; no generic create-task action. Explain that finite tasks originate from dataset, model, evaluation, inference, or workflow business pages, and that DeploymentInstance and WorkflowAppRuntime are not tasks. Primary action opens Project Overview.
2. M04 EvaluationCenterPage: tabs and comparison basket are empty. Show ModelVersion + compatible DatasetExport val/test split as prerequisites. Disable Create Evaluation and Compare until prerequisites exist. Do not substitute val for missing test.
3. X01 TriggerSourcePage: no WorkflowAppRuntime exists. Keep the three-step flow on Select Runtime and disable template, mapping, test, and save. Show FlowApplication → healthy WorkflowAppRuntime → TriggerSource. Primary action opens Workflow Apps.
4. N01 CustomNodeCatalogPage: the local custom_nodes/ scan returns zero extension NodePacks. Keep the three-column catalog, show the NodePack contract requirements, and make Rescan the primary action. Do not add a cloud marketplace, upload dropzone, or automatic enablement.
```

### 加载与重连

```text
Add skeleton loading for initial resource lists and a small persistent reconnect indicator for websocket interruption. Do not clear existing data during reconnect. Show last updated time and use the next REST snapshot as the authoritative state.
```

### 失败与危险操作

```text
Add failure states with a concise error summary, failed stage, error code, last successful state, copy diagnostics, and a valid recovery action. Use restrained red semantics. Destructive dialogs must name the resource, list dependent runtimes/workflows, explain recoverability, and keep the destructive button unfocused by default.
```

## 11. Stitch 输出检查

- 是否复用了同一套 AppShell 和 design tokens。
- 是否正确区分资源、任务和长期 runtime。
- 是否只显示真实支持的模型、任务、格式、转换目标和设备组合。
- 是否为主要列表生成了筛选、空状态、加载、错误和分页结构。
- 是否为关键资源保留来源链和下一步操作。
- 是否把图像画布和流程画布作为核心工作区，而非卡片附件。
- 是否能在 Vue 3 和常规前端技术栈中实现。
