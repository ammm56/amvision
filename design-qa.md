# 项目工作区 Design QA

## 部署页面重构与验证记录（2026-11-26）

围绕 P6 部署分类（[deployment-pages-design.md](docs/design/frontend/deployment-pages-design.md)、[deployment-design-review.md](docs/design/frontend/deployment-design-review.md)、[deployment-interaction-completion-design.md](docs/design/frontend/deployment-interaction-completion-design.md)）完成阶段 B1 接口补齐、四语种 i18n 统一收敛与组件模块化重构，自动化验证情况如下：

- **后端接口补齐与测试**：
  - [model_deployment_transfers.py](backend/service/api/rest/v1/routes/model_deployment_transfers.py) 在导出记录响应补充 `file_name`、`upload_bytes`、`uploaded_at`、`file_cleaned_at` 与 `zip_state`，并新增只读 `GET /projects/{project_id}/model-deployment-transfers/deployment/{deployment_id}/references` 引用查询接口。
  - [test_model_deployment_transfer_api.py](tests/test_model_deployment_transfer_api.py) 新增 `zip_state` 与跨项目权限/引用隔离测试；`pytest tests/test_model_deployment_transfer_api.py tests/test_detection_deployment_instances_api.py` 18 项全部通过（3 + 15 passed）。
- **前端模块化重构与统一 i18n**：
  - 重构 [DeploymentOperationsPage.vue](frontend/web-ui/src/modules/deployments/pages/DeploymentOperationsPage.vue)，拆分 `DeploymentInstanceTable.vue`、`DeploymentCreateWizard.vue`（3 步创建向导与启动失败独立提示）、`DeploymentStatusDrawer.vue`（5 个下划线页签：概览 / 运行配置 / 接口与契约 / 诊断与日志 / 引用关系）、`DeploymentCapabilitiesDrawer.vue` 与 `DeploymentTransferRecordsTab.vue`，并在 `deployment-presentation.ts` 集中处理运行时格式化与配置对比映射。
  - 在 `frontend/web-ui/src/platform/i18n/` 下统一新增四语种字典 [deployment-workspace.ts](frontend/web-ui/src/platform/i18n/deployment-workspace.ts)、合并至 [messages.ts](frontend/web-ui/src/platform/i18n/messages.ts) 并补齐 [deployment-transfers.ts](frontend/web-ui/src/platform/i18n/deployment-transfers.ts) 的 `ja-JP`/`ko-KR` 翻译；同步修复 `ImportedModelAssets.vue` 在无插件注入单测挂载场景的 `useI18n()` 异常。
- **前端构建与单元测试**：
  - 最新一轮布局优化后复验：`vue-tsc --noEmit` 零错误通过，`vite build` 生产构建通过（4598 modules transformed），部署模块专项 Vitest（8 个测试文件 / 63 项测试，含新增 [test_deployment_workspace_p6.ts](tests/frontend/deployments/test_deployment_workspace_p6.ts)）全部通过；此前部署+模型 16 个文件 / 154 项回归全部通过，全量 Vitest（271 个测试文件）中 270 个文件 / 1445 项通过、2 项仓库既有跳过（`tests/frontend/models/test_task_detail_lifecycle.ts` 在并发重负载下 1 例 5000ms 超时并在单独重跑中 39/39 通过）。
- **实时浏览器验收（passed for Stage B1 P6 deployments scope）**：
  - 在 `http://127.0.0.1:5601/deployments` 完成只读联调验收（10 条真实部署实例，含 `yolo11-s-pcbpetslot4570-20261107184647` 与 `3913 barcode OpenVINO CPU`）：验证 3 个顶栏动作与 3 个下划线页签（`部署实例` / `导入记录` / `导出记录`）、`设备能力` 抽屉与实时查询（`ONNX Runtime · cpu`）、`创建部署` 3 步向导及行内校验（退出未提交）、`详情` 5 页签抽屉（`概览`、`运行配置` 请求值 vs 生效值对比表、`接口与契约`、`诊断与日志`、`引用关系`）及 `重置` 实底确认弹框（取消未提交）。
  - 针对实机截图发现的表头/按钮竖向折行与 1024×768 `en-US` 容器外扩问题，已在 [index.css](frontend/web-ui/src/shared/styles/index.css)（`.workbench-shell` `max-width: 100vw`、`.workbench-shell__main` `grid-template-columns: minmax(0, 1fr)`）与 [DeploymentInstanceTable.vue](frontend/web-ui/src/modules/deployments/components/DeploymentInstanceTable.vue) 完成修复并实机复验：`1366×768`（亮/暗主题、中/英文 8 列单行显示）及 `1024×768`（`zh-CN` 903.85px / `en-US` 888px，隐藏第 5 列调用模式、无横向溢出与裁切），控制台错误 0，HTTP `>=400` 响应 0。
- **设计稿对齐重设计与交互收敛（`docs/design/frontend/generated/部署/`）**：
  - 对照 `docs/design/frontend/generated/部署/` 设计图及后端真实接口契约重构 P6 部署模块组件：[DeploymentOperationsPage.vue](frontend/web-ui/src/modules/deployments/pages/DeploymentOperationsPage.vue)（顶栏收敛为 `<TabList>`，停用/重置/删除确认与运行中/引用依赖阻止弹框接入真实引用查询与 `查看引用` 跳转）、[DeploymentInstanceTable.vue](frontend/web-ui/src/modules/deployments/components/DeploymentInstanceTable.vue)（`.deployment-card` 卡片框体、`项目：{name}` 顶栏与 4 动作、空状态卡、搜索 + 状态/任务/调用模式筛选、7 列实例表与 4 通道微指示条、`详情` + `...` `ResourceMenu`、分页脚标）、[DeploymentCapabilitiesDrawer.vue](frontend/web-ui/src/modules/deployments/components/DeploymentCapabilitiesDrawer.vue)（`当前主机` + 4 列 `后端设备能力` 表格 + 提示条 + 折叠详细能力探测）、[DeploymentStatusDrawer.vue](frontend/web-ui/src/modules/deployments/components/DeploymentStatusDrawer.vue)（状态点与模式标签、5 栏短标签页 `概览`/`运行配置`/`接口`/`诊断`/`引用`、可折叠 `身份信息`、`服务检查`、`运行统计`、`实际生效配置` 对比表、接口调用方式与可复制示例、事件与 `最近错误` 及可搜索引用表）、[DeploymentCreateWizard.vue](frontend/web-ui/src/modules/deployments/components/DeploymentCreateWizard.vue)（面包屑 + 3 步进度条、`按任务浏览` 与行内模型/版本/产物单选及 `已选产物摘要`、校验计数 `请修正 N 项参数`、步骤 3 检查项与配置摘要）与 [DeploymentTransferRecordsTab.vue](frontend/web-ui/src/modules/deployments/components/DeploymentTransferRecordsTab.vue) / [DeploymentTransferPanel.vue](frontend/web-ui/src/modules/deployments/components/DeploymentTransferPanel.vue)（6 列记录表、空项目兜底 `—`、导入 4 步进度条、导入/导出详情抽屉 `基本信息` / `文件内容`）；不添加无后端支持的运行期改配或切版本假按钮。
  - 在 [deployment-presentation.ts](frontend/web-ui/src/modules/deployments/deployment-presentation.ts) 补齐 `formatDeploymentDeviceName`、`formatDeploymentCapacityLabel` 与 `buildHostCapabilityRows`，并在 [deployment-workspace.ts](frontend/web-ui/src/platform/i18n/deployment-workspace.ts) 保持四语种（`zh-CN` / `en-US` / `ja-JP` / `ko-KR`）完整键名对齐，同时修复向导与详情抽屉中的 `deploymentOps.fields.*`、`deploymentOps.runtimeConfig.*` 键名引用。
- **风格与已有页面（`/models`、`/datasets`）统一优化（`/swarm` + `/browser` 闭环）**：
  - 顶栏与工具栏对齐：移除 [DeploymentInstanceTable.vue](frontend/web-ui/src/modules/deployments/components/DeploymentInstanceTable.vue)、[DeploymentTransferRecordsTab.vue](frontend/web-ui/src/modules/deployments/components/DeploymentTransferRecordsTab.vue) 与 [DeploymentCreateWizard.vue](frontend/web-ui/src/modules/deployments/components/DeploymentCreateWizard.vue) 左上角多余的 `项目：` 标识；[DeploymentOperationsPage.vue](frontend/web-ui/src/modules/deployments/pages/DeploymentOperationsPage.vue) 将动作按钮收拢到 `.deployment-ops-navigation` 右侧（`.ui-button--md`，`36px`），工具栏统一为左搜索框（带清空按钮）+ 右筛选下拉与刷新按钮。
  - 表格排版与单行省略：统一为 `.resource-table` `th`（`12px` / `700`）与 `td`（`14px`，行高 `~54.67px`），通过 `table-layout: fixed`、`<colgroup>` 与 `ellipsis` + `:title` 确保长名称、状态标签与操作按钮均单行不折行。
  - 版本与纯图标运行时标识：`DeploymentOperationsPage.vue` 通过 `listProjectModelCatalog` 解析并下发 `versionLabelsById`，使表格、`详情` 抽屉与传输记录统一展示 `v1` / `v2`（替代 `· s` 与内部 UUID）；新建 [DeploymentRuntimeBadge.vue](frontend/web-ui/src/modules/deployments/components/DeploymentRuntimeBadge.vue) 复用 `/models` 的 SVG 与设备图标（深色模式反色兼容）进行纯图标 + `aria-label`/`title` 展示。
  - 交互缺陷修复：`DeploymentCreateWizard.vue` 修复第 1 步禁用态透明度、第 2 步 `实例数 = 0` 失焦被改回 `1` 的校验缺陷与第 3 步默认设备展示 `自动选择（默认）`；`DeploymentStatusDrawer.vue` 中文本地化 `实际生效配置` 参数名并清洗告警中的原始 ID；行内对运行中实例点击 `删除` 改为弹出 `暂时无法删除部署` 阻止弹框，且切换页签自动清除瞬时错误提示。
- **全栈联调深度细节优化（`/swarm` 全栈并行闭环）**：
  - **后端主机与模型版本链路**：[diagnostics.py](backend/service/api/rest/v1/routes/system/diagnostics.py) 在 `build_device_diagnostics()` 新增 `host`（Windows 版本/Build 号、Linux `PRETTY_NAME`、macOS `mac_ver`、主机名与平台架构，消除裸 `Win32`）与 `cpu` 核数/线程数；[deployment_instance_service.py](backend/service/application/deployments/deployment_instance_service.py) 与各任务部署响应（[detection_deployments/responses.py](backend/service/api/rest/v1/routes/detection_deployments/responses.py) 及 `{classification,obb,pose,segmentation}_deployments/{schemas,responses}.py`）批量读取并透传 `model_display_name` 与 `model_version_number`。
  - **表格列、单色图标与生效配置对比**：[DeploymentInstanceTable.vue](frontend/web-ui/src/modules/deployments/components/DeploymentInstanceTable.vue) 去掉 `模型版本` 列任务前缀，只保留模型名称与 `v1/v2`；[DeploymentRuntimeBadge.vue](frontend/web-ui/src/modules/deployments/components/DeploymentRuntimeBadge.vue) 新增 `backendOnly`/`muted`/`tooltip` 并将 NVIDIA SVG 统一为亮暗单色图标；[deployment-presentation.ts](frontend/web-ui/src/modules/deployments/deployment-presentation.ts) 修复 `buildHostCapabilityRows` 识别后端 `installed`/`supports_*` 字段，以及 `buildDeploymentConfigComparisonRows` 解包 `allocated_runtime_configuration` 与 `cpu_device_resource_manager`。
  - **导入实例、外置工具栏、向导步进与抽屉**：[DeploymentTransferPanel.vue](frontend/web-ui/src/modules/deployments/components/DeploymentTransferPanel.vue)（联合 [DeploymentOperationsPage.vue](frontend/web-ui/src/modules/deployments/pages/DeploymentOperationsPage.vue)）点击 `导入部署实例` 先打开第 1 步选包/摘要弹窗并优化第 2 步映射与配置分组；[DeploymentTransferRecordsTab.vue](frontend/web-ui/src/modules/deployments/components/DeploymentTransferRecordsTab.vue) 取消外层卡片框使搜索/筛选位于表格上方外侧，加宽详情标签列；[DeploymentCreateWizard.vue](frontend/web-ui/src/modules/deployments/components/DeploymentCreateWizard.vue) 将 3 步进度条设为自适应页面全宽；[DeploymentCapabilitiesDrawer.vue](frontend/web-ui/src/modules/deployments/components/DeploymentCapabilitiesDrawer.vue) 展示详尽 OS、后端纯图标+悬停提示与结构化表格/胶囊芯片属性；[DeploymentStatusDrawer.vue](frontend/web-ui/src/modules/deployments/components/DeploymentStatusDrawer.vue) 补齐接口 `输出内容`、诊断圆标与中文本地化引用状态，四语种字典在 [deployment-workspace.ts](frontend/web-ui/src/platform/i18n/deployment-workspace.ts) 与 [deployment-transfers.ts](frontend/web-ui/src/platform/i18n/deployment-transfers.ts) 保持同步。
- **后端与前端构建及单元测试（最终实跑通过）**：
  - 后端：`pytest tests/test_detection_deployment_instances_api.py tests/test_system_diagnostics_service_status.py` **27/27 全部通过**（16 + 11），`ruff check` 14 个改动文件全部通过。
  - 前端：`npm --prefix frontend/web-ui run build`（`vue-tsc --noEmit && vite build`，4601 modules transformed）零错误通过；`npm --prefix frontend/web-ui test -- tests/frontend/deployments frontend/web-ui/src/modules/deployments tests/frontend/models` **16/16 个测试文件、162/162 项测试全部通过**（`test_deployment_workspace_p6.ts` 13/13、`test_deployment_transfer.ts` 15/15、`DeploymentOperationsPage.test.ts` 21/21；部署测试 `intlify` 缺键告警 0、未捕获异常 0）。
- **实机 `/browser` 全项只读终验（服务重启后实跑通过）**：
  - 复用浏览器验证子代理（`bf13209e-ab68-490b-83c3-86df4f74ef43`）在 `http://127.0.0.1:5601/deployments`（后端 `http://127.0.0.1:5600`）完成全项只读验收，**控制台错误 0，HTTP `>= 400` 响应 0**：
    - 接口实测：`/api/v1/system/bootstrap?include_devices=true` 返回 `host`（`Windows x64`、`Windows 11 Pro 25H2 (Build 26200.9278)`、`DESKTOP-AM`）与 `cpu`（`8 核 / 16 线程`）；部署实例接口返回 `model_display_name` 与 `model_version_number`。
    - 主列表（1366×768 亮/暗色）：`模型版本` 仅展示 `<model_display_name> · v1`，单行 `54.67px` 省略截断，纯图标运行时；`导入部署实例` 先打开第 1 步选包/摘要弹窗；`导出记录` 搜索与右侧下拉位于 `.resource-table` 外部上方且详情标签单行不折行；`新建部署` 3 步进度条在 1366/1024px 全宽自适配；`设备能力` 抽屉展示完整 Windows 11 信息、后端列纯图标与单色 NVIDIA、OpenVINO CPU/GPU `可用` 与结构化可折叠属性芯片；`详情` 5 页签显示真实 `实际生效配置`（如 `推理线程数: 自动 -> 8`）、接口 `输出内容`、诊断圆标及本地化 `Runtime 运行中` 引用状态，退出后已恢复亮色、`zh-CN`、`1366×768`。

final result: passed for full-stack P6 deployments deep polish and live browser verification (27/27 pytest, build + 16/16 Vitest files / 162/162 tests, 0 console/HTTP errors)

## 模型页面浏览器验收收口（2026-11-26）

在 `http://127.0.0.1:5601` 对 P5 模型区 5 个子域执行 1024×768、1366×768 亮暗主题真实浏览器验收（全程只读操作，向导与编辑/删除对话框均取消关闭未提交），并完成回归修复与复验：

- **验证范围与真实记录**：项目模型列表（31 条，含 `目标检测 RFDETR-n`、`4570托盘 YOLO11-s-import`、`3570塑盒 YOLO11-s`）与基础模型、训练任务（19 条，含 `task-521feff540fe` 与失败任务 `task-a3e7b9e79e18`）、转换任务（`task-ea61996024cd`、`task-61220d0aa679`）、模型包记录（1 条导入、5 条导出）、7 类评估入口与比较/报告（`task-f866f7152e47`、`task-ba41a14002ee`、`task-612a33478026`、`ui-eval-segmentation`）。
- **已修复并复验项**：
  1. 评估顶栏收拢 `+ 创建评估`、零选中时不显示批量操作栏，并统一 `TabList` 下划线页签样式。
  2. 移除 `ConfirmDialog` 内层面板入场透明度与外层遮罩的叠加过渡，复验 `删除模型版本` 与 `无法删除模型版本` 在右侧抽屉之上保持亮暗实底，无底层文字透出；`ModelPickerDialogShell`（`width: min(1120px, calc(100vw - 36px))`）在 1024px 视口完整居中无裁切。
  3. 统一任务类型、`build_format`（`OpenVINO`、`ONNX（优化）`）、AMP 默认值（`自动选择`）及四语种 `conversionRuntimeProfileId`（大写 `ID`）显示；补充并运行 [test_p5_acceptance_polish.ts](tests/frontend/models/test_p5_acceptance_polish.ts)。
  4. 优化 `ModelBuildDetail` 表头 `数据类型` 单行显示、1024×768 训练列表 `200 / 200 轮` 单行不折行、失败训练 `task-a3e7b9e79e18` 显示 `0 / 1 轮` 失败态样式，以及 `task-521feff540fe` `GPU 与显存` 暗色图例分页与右轴 `GiB` 间距。
- **验证结果与已知边界**：前端 `typecheck` 零错误，P5 相关 Vitest 13 个文件 116 项测试全部通过；浏览器复验期间控制台错误 0，HTTP >=400 请求 0。已知边界保持不变：语义分割（`semantic`）与异常检测（`anomaly`）评估基于预测结果包输入；OpenVINO INT8 量化限 YOLO11 目标检测与固定静态输入及独立校准/校验划分。

final result: passed for reviewed P5 models scope

## 模型页面阶段性核对（2026-11-17）

2026-11-18 阶段验收更新。场景 54 的转换任务确认按图划分删除与保留范围。真实记录在 1024×768、1366×768 查看亮暗确认，隔离测试验证删除后登记文件下载与部署引用仍可用。列表标签、搜索和详情返回通过浏览器核对。

场景 3、17、57 的训练参数及检查页使用实际 YOLO11-s 与 COCO 导出检查两种短屏和亮暗主题。真实项目的草稿未提交，隔离副本由 Worker 跑 1 轮 CPU，生成模型版本、最佳和最新检查点及验证指标。恢复检查和缺失清单的阻止分支通过隔离 API 测试。参数仍保留真实 AMP 三态和独立宽高输入。

转换参数按场景 6 区分固定输入、实际张量、高级参数和执行环境。场景 25、26 的真实转换预检中，YOLO11 原始 ONNX 验证动态批次，隔离产物声明 Opset 19，批次 1、2 与 PyTorch 数值核对通过。当前尚未交付动态宽高、INT8 校准和独立模型包、评估页面，模型全量验收继续为 blocked。

2026-11-18 训练数据步骤：从导出记录快照读取各划分数量，不使用源版本当前数量替代；缺少历史统计时显示未知。真实导出 `dataset-export-5515e019b157` 显示 train 5、val 1、test 未包含，已核对亮暗 1024×768；来源名称和版本“数据集界面验收-已核对 v9”在浏览器中单独核对。来源名称异步读取失败时可重试，旧请求不得覆盖新选择。导出与任务、模型格式不匹配时停留数据步骤；训练参数无效时停留参数步骤，避免直到提交前才提示。未创建训练任务。

模型训练产物登记现在拒绝将同名同规格但不同系列的版本附加到已有模型。隔离数据库测试验证既有版本保留、冲突版本和文件不登记。该保护目前发生在产物登记时，训练提交前的冲突预检仍需补齐。

转换检查页使用服务端预检复用提交时的来源和转换方案校验，配置改变或返回时取消旧请求，失败可重试，结果未通过时禁止提交；环境检查仍在执行时进行。真实 YOLOX 模型的 OpenVINO 检查和亮暗 1024×768 已核对，未创建转换任务。YOLOX 与其他任务类型的 API 测试覆盖预检和提交，前端覆盖预检失败、重试和过期响应。修复转换接口对来源模型类型或任务类型不匹配时仍可能创建任务的问题，预检及提交均在入队前拒绝。转换高级参数、模型包和评估等尚未完成，不能认定模型页面全部实现。

final result: blocked for model pages

已对照模型版本目录与详情的参考图，使用实际项目模型核对搜索、分页、版本切换及产物归属，并检查 1024×768 亮暗列表。短屏表格曾出现列标题和操作换行，现已调整。

本次补充版本的直接部署引用分页、搜索及跳转；实际包含两个部署的版本已核对，运行状态分别展示记录中的同步和异步状态。原始文件及转换产物已支持存在性检查与单文件下载：实际 ONNX 和类别文本下载与源文件的 SHA-256 一致；原始文件、产物和引用抽屉已检查亮暗及 1024×768。基础模型选择后的关闭和详情读取失败重试已修复。

基础模型选择器现改为右侧抽屉，使用真实目录及 checkpoint 存在性，检查了搜索、选择和亮暗 1024×768；选择权重后表单显示真实来源版本。为保留现有训练表单的从头训练能力，当前抽屉额外提供“仅选择模型结构”，待训练向导独立实现任务与模型选择后再对照设计收敛。缺失和读取失败状态使用隔离测试覆盖，尚未在真实开发目录制造缺失文件。

模型展示名称及说明采用独立 metadata 和 revision，保留原登记名称；隔离数据库验证了保存、搜索、并发冲突和跨项目访问。模型版本删除在受理时重新检查范围与依赖；真实含两条部署引用的版本验证了阻止界面、引用跳转及 1024×768 亮暗视图。删除执行使用隔离数据库和文件：目标登记被移除，其他版本以及训练、转换任务文件保留；未删除实际项目数据。编辑抽屉用实际模型检查了未保存草稿和亮暗短屏，实际项目未提交修改。

训练创建入口现分为任务与模型、数据、初始化、参数和检查五步；使用实际 YOLO11 基础模型和数据集导出检查了选择、步骤切换、从头训练、取消权重选择，以及 1024×768 亮暗检查页。参数的高级选项默认收起。训练任务未在真实项目提交；检查页展示配置和已有客户端校验结果，文件和设备仍由后端在提交时校验。结果未知时禁止重复提交并在当前浏览器会话中保留状态，核对列表后可显式解除；该路径目前由隔离测试验证。训练列表使用实际记录核对搜索、失败和空筛选，检查 1024×768 亮暗显示并修正操作列；现有接口最多读取 100 条，页面明确说明该限制。

训练详情的标题显示和返回训练列表已用已有完成任务验证。输出列表现使用文件名与可读大小，文本预览默认收起；实际 `labels.txt` 的内容预览及下载已核对，下载文件与源文件的 SHA-256 一致，checkpoint 不提供文本预览。下载接口的五种任务类型、跨项目、错误类型和路径归属由隔离测试覆盖；页面目前通过 Blob 下载，大文件需要占用浏览器内存。训练详情其他布局、状态和图表仍需逐图实现并验收。

训练曲线使用真实已完成任务验证了 1024×768 亮暗主题；暗色坐标和图例此前对比度不足，现跟随主题更新文字、网格与曲线颜色，主题切换和清理也有组件测试。该检查不代表训练详情图表已与设计图逐项一致。

转换入口现在先显示任务列表，创建时分来源、目标、参数、检查四步；实际选择已有 YOLOX 版本和 OpenVINO FP16，到检查页后未提交任务。检查了 1024×768 的亮色目标页和暗色检查页，验证了详情返回转换列表。检查页区分文件存在性、来源与方案检查和执行环境检查；当前仍使用既有的目标格式及配置接口，转换参数、环境预检和来源产物选择尚未达到设计图。转换提交成功或结果未知时阻止重复提交，结果未知的会话恢复通过隔离测试覆盖。转换选择器显示可编辑的模型展示名称，内部仍使用原登记名称和版本 ID。

转换详情的原始结果及规格默认折叠，输出表显示真实文件名；阶段列表仅按任务记录的 planned steps 与 executed steps 展示，真实 OpenVINO 转换记录的四个阶段已核对亮暗短屏。来源列表现检查已登记 checkpoint 是否存在；缺少或无法检查的版本保留在选择列表中并显示原因、禁止选择。实际预训练引用的类别缺失提示已核对，文件缺失与恢复通过隔离 API 测试覆盖；存在不代表内容有效或环境兼容。报告和 OpenVINO 的 XML、BIN 下载已用真实转换任务核对文件 SHA-256，并以隔离 API 测试覆盖五种任务类型的权限及归属；浏览器通过 Blob 下载，大文件需要占用浏览器内存。校验明细、失败状态和其余设计仍待实现核对。

转换详情新增报告中实际存在的数值校验摘要。已核对现有 OpenVINO 记录的阶段、最大绝对差、绝对和相对容差与通过状态；相对容差会参与比较，不能仅以最大差值与绝对容差判断结果。缺失的字段显示为“—”，不生成设计图中的示例指标。

转换列表支持搜索、任务类型与状态筛选，显示任务实际目标格式和已登记产物精度；使用真实转换记录验证搜索、详情返回及 1024×768 亮暗布局。列表最多读取 100 条，筛选和分页只作用于已读取记录。导入区域仍为部署实例导入资产，不等同设计中的独立模型包导入记录。

历史模型缺少可靠的注册顺序及版本编号，目录当前展示版本数；详情仍缺完整来源和产物管理；训练和转换向导、模型包、评估及其他状态的逐图实现与验收尚未完成。本记录不表示模型页面已通过验收。

日期：2026-11-04。范围：公共主题、抽屉/确认框及项目分类。实现为现有 Vue 3 产品，不是静态原型。

## 最新补齐核对

再次复核记录的创建/编辑结果未知、SDK 等待关闭、错误返回、列表定位等缺口已完成。最新证据见[项目分类补齐验证](docs/development/project-workspace-followup-validation.md)，下方首批/收尾记录属于历史范围。

- 同一工具输入并列查看了 1672×941 的已确认列表亮色、编辑亮暗源图与本轮实况。布局、统一遮罩、纯色主题、品牌选中、固定动作区符合规范；生成图示意字形/示例数量不作为产品数据和 CSS 定值。
- 新发现的抽屉焦点丢失已修复并通过真实冲突选择、Esc/内层确认检查；清空说明的恢复、完整 ID 定位优先也补齐测试。
- 69 项前端、2 项后端回归通过，类型检查和构建通过。真实创建、并发编辑、SDK 下载与版本冲突、删除回执、失效链接返回完成。
- 1366×768、1093×614、911×512 CSS 空间已核对；原生浏览器缩放快捷键在当前 IAB 未生效，不把等效空间检查称为原生缩放验收。
- 本批没有未处理的已确认视觉缺陷；已有导航/文字密度保持不变，不重新生成设计图。

final result: passed for reviewed follow-up scope

## 收尾核对结果

后续完整性复核确认的 7 项缺口已修复，本轮范围通过。详细结果见[收尾验收记录](docs/development/project-workspace-completion-validation.md)。本文件下方首批截图、测试数量和限制保留为历史过程，当前状态以本节为准。

| 原问题 | 当前处理与验证 |
| --- | --- |
| 删除未知结果丢失恢复入口 | 按账号/项目保存多项；失败不清除、不重复 DELETE；连续故障测试与真实生命周期通过 |
| 离页草稿与未知创建恢复 | 路由/beforeunload 保护、跨组件请求身份；真实返回/Esc 取消保留输入 |
| 概览展开、资源来源及刷新不全 | 全宽筛选分页、真实版本更新、观察时间；137 条记录跨页核对 |
| 失败混用空态 | 旧数据与时间保留、首次失败独立；失权清除；重复错误提示修正 |
| 资源权限与 SDK 容量 | 服务端裁剪、入口/表单一致；分页查询、明确超限、预览 revision；受控测试和真实下载通过 |
| 资源详情和短屏 | 真实版本数据、正确标签与共享字段样式；520 px 抽屉/760 px SDK，固定动作区可达 |

最终 56 项前端测试、TypeScript 与构建通过；后端 35 个不同用例完成检查及失败项修正后的复测。真实同数据[亮色概览](docs/design/frontend/verification/projects-completion-20261104/overview-light.jpg)/[暗色概览](docs/design/frontend/verification/projects-completion-20261104/overview-dark.jpg)、[信息抽屉](docs/design/frontend/verification/projects-completion-20261104/information-light.jpg)、[短屏 SDK](docs/design/frontend/verification/projects-completion-20261104/sdk-compact-dark.jpg)已核对。没有重新生成设计图。

原生刷新确认框与原生浏览器缩放未单独完成视觉验收；短 CSS 视口与 beforeunload 自动化已覆盖对应布局/逻辑。其他分类专用组件与长期生产稳定性单独验收。本次服务已停止，保留原有前端开发服务。

## 首批对照依据（历史）

- 视觉源：`docs/design/frontend/generated/项目/`，当前 15 组、30 张有效图；行为与 CSS 定值按 `docs/design/frontend/project-complete-design.md`。
- 真实截图：`docs/design/frontend/verification/projects-20261104/`。
- 逐项检查范围：项目列表、概览、信息/编辑、SDK 预览/范围/长列表、删除及短屏。
- 概览源图与 `overview-reference-light.jpg` 同为 1672×941；实际 CSS 视口 1672×941，deviceScaleFactor=1。信息与 SDK 全景截图为 1920×1080、density=1；比较容器和文字时以规格中的 520/760 CSS px 为准，不把不同画布大小直接作为像素偏差。
- 源图有示例数据、偏蓝文字及局部暗纹理。按已确认规范使用实际数据、中性文本、纯色背景；保留现有 220 px 导航和字体密度，不放大整个工作站去模拟生成图片中的文字比例。

源图与实现截图在同一次工具输入中并列查看：概览亮色、信息暗色、SDK 长列表暗色；之前已核对列表与信息亮色。长列表及 911×512 短屏额外检查正文滚动和动作区。信息抽屉标签/数值、概览表头/行以及 SDK 选择控件均可在截图中直接辨识，无需猜测小字。

## 首批发现与修复记录（历史）

| 级别 | 问题 | 修复与复核证据 |
| --- | --- | --- |
| P1 | 忙碌按钮禁用后失焦，SDK 下载后 Esc 不能关闭 | 公共容器恢复焦点；真实下载完成后 Esc 通过，新增组件回归 |
| P2 | 信息切编辑、SDK 范围子视图切换后焦点遗失 | 聚焦新输入；关闭归还原入口，真实页面和组件验证 |
| P2 | 信息标签/值间距散乱，缺少直接编辑入口 | 108 px 标签列、28 px 行距、底部编辑；`information-light.jpg` / `information-dark.jpg` |
| P2 | 长服务列表无限拉长，继续工作被挤出主要区域 | 概览列表有界滚动；`overview-light.jpg` / `overview-dark.jpg` |
| P2 | 最近更新缺少独立状态/时间列及类型图标 | 采用表头与四列表格、复用图标库；`overview-reference-light.jpg` 与源图再次对照 |
| P2 | SDK 范围视图重复显示生成摘要、短屏正文空间不足 | 范围页只保留项目、搜索、计数、分组列表和动作；`sdk-resources-dark.jpg`、`sdk-150-light.jpg` |

以上问题均有修改后重新截图/交互检查。此处记录首批已修复问题，不代表没有剩余问题。2026-11-04 完整性复核发现删除清理结果身份/颜色层级、概览展开和异常交互仍未达到设计要求，详见[完整性复核](docs/development/project-workspace-ui-completeness-review.md)。

## 五项核对

| 表面 | 结论 |
| --- | --- |
| 字体 | 沿用本地字体栈，正文 14 px、次要值 12–13 px，标题加权；普通参数不全加粗。与生成图的示意字形大小存在明确的产品密度差异 |
| 间距布局 | 无新增全局顶栏；四资源指标、双面板、继续工作；信息右侧覆盖、底层无位移；短屏正文滚动、底部动作可达 |
| 颜色 | 统一 #00D992 品牌绿、白色主按钮标记、中性 hover/focus、实色危险按钮；遮罩同时覆盖导航和正文；暗色无纹理 |
| 资产 | 复用现有 AMVAR 品牌组件与图标库。该分类无照片/插画，不引入假截图、装饰图片或自绘图标替代实际控件 |
| 文本数据 | 真实项目名称、资源数、状态和时间；缺失说明为“—”；SDK 依赖/删除错误有短原因，正常状态无长解释；中英日韩项目新增标签完整 |

## 首批交互与限制（历史）

- 27 项前端回归、类型检查和构建通过；真实 Chromium 0 个 pageerror。
- 亮暗同 DOM，项目抽屉 520 CSS px；标题/正文/动作在短视口内可达。
- 真实 SDK 下载、范围草稿取消、隐藏选择保留、信息编辑焦点、默认项目保护、独立测试项目删除回执通过。
- 1366×768 亮暗及 125%/150% 等效 CSS 可用空间检查通过；不是原生浏览器缩放的全面验收。
- 真实数据与源图不同，当前没有运行中的训练任务，因此不使用示例 37% 进度补位。最近更新来自当前任务与运行控制面；不伪造尚未存在的统一资源审计事件。
- 内置浏览器连接失效；上述截图与操作来自本机独立 Chromium。其他模块只做首屏冒烟，不等于全面业务或长期稳定性验收。

## 交付检查

- [x] 修复本批发现的焦点和布局问题并重新截图。
- [x] 亮暗、抽屉遮罩、SDK 长列表和短视口核对。
- [x] 同步 API、实施进度及真实验证记录。
- [x] 保留有效截图与结构化检查事实，移除失败过程截图。

概览全宽分页、筛选、真实资源更新和局部刷新属于已约定的项目分类目标，不能以不建设新审计系统为由从本阶段移除。复用现有资源元数据和控制面查询补齐即可。

首次完整性复核曾因删除响应未知恢复、草稿保护、权限、大清单与视觉差距阻止交付；后续已逐项修复，当前完成情况见上方收尾核对和关联验收记录。

final result: passed for reviewed project scope

### 追加验收状态（2026-11-04）

编辑保存和 SDK 下载的短反馈已补齐，复用现有全局轻提示组件；78 项相关回归和类型检查通过。随后在真实开发环境、内置浏览器完成编辑亮暗反馈和实际 SDK 下载核对，见[追加验证记录](docs/development/project-workspace-followup-validation.md)。用户明确取消浏览器原生缩放验收，不再作为项目分类完成门槛。项目分类本次约定缺口已完成；不将局部截图核对扩大为全平台或长期生产验收。

### 悬停与分隔线复核（2026-11-04）

顶部分类和“继续工作”已统一为内缩圆角、中性灰悬停，禁用时不高亮；查看入口补齐相同的圆角与键盘反馈。最近更新、全部记录和当前运行移除逐行横线。真实亮暗页面、数据跳转、分页、空筛选及抽屉操作已核对；75 项相关回归与生产构建通过。[修复与证据](docs/development/project-workspace-followup-validation.md#追加分类入口悬停与列表细节2026-11-04)。本次检查再次表明，自动化通过不能替代实际悬停等视觉状态核对。

### 整格入口修订（2026-11-05）

按最新要求取代上轮内缩悬停方案：顶部分类和“继续工作”整格响应中性灰悬停、整格可点击，移除分类竖线、箭头及快捷入口标题下的多余横线。容器保留外侧圆角，键盘焦点在内侧显示；少量入口均分宽度，窄窗口双列。真实亮暗截图、边缘点击、Enter/Tab 和窄窗口检查通过，39 项相关回归和类型检查通过。详见[最新验证](docs/development/project-workspace-followup-validation.md#追加整格分类入口2026-11-05)。

### 列表与操作边界修订（2026-11-05）

保留概览设计布局，项目活动列表与触发入口复用 ResourceTable、StatusBadge；概览记录整行点击，不新增查看操作列。主项目列表原有操作列使用公共 Button，编辑和删除仍在原有菜单。移除重复刷新提示；长名称单行省略，状态完整显示，概览记录统一 72 px 行高，中性悬停两端 6 px 圆角。亮暗真实数据、操作按钮、筛选及跳转已核对，53 项相关测试和类型检查通过。见[验证记录](docs/development/project-workspace-followup-validation.md#追加资源列表复用与操作边界2026-11-05)。

### 密度与重复信息修订（2026-11-05）

主列表恢复原有行距，实测默认项目 74 px；概览记录仍为 72 px。名称／类型占至少六成，状态和更新时间紧凑排列，保持完整显示。删除快捷栏的可见标题、空任务分组及当前运行内重复分类入口。原有布局、整行导航和操作列按钮不变；亮暗真实页面、窄窗口和导航复核通过，46 项相关回归及类型检查通过。见[最新核对记录](docs/development/project-workspace-followup-validation.md#追加列表密度与概览精简2026-11-05)。开发服务按用户要求保持运行。

### 普通反馈移除装饰色条（2026-11-05）

删除“项目已创建”提示的品牌绿左边框，恢复四边一致的中性细边框和 6 px 圆角；提示文字、查看及关闭操作保留。内置浏览器直接核对当前创建成功提示，四边颜色和宽度相同，无伪元素色条，见[真实截图](docs/design/frontend/verification/projects-overview-density-20261105/notice-neutral.png)。规则已写入[视觉与组件系统](docs/design/frontend/design-system.md#22-语义色)，普通反馈不得使用装饰性彩色侧边条。此次仅删除 CSS 装饰声明并补充规范，未重复运行业务回归或修改业务数据。

### 搜索输入框边框修订（2026-11-05）

项目搜索栏聚焦时，内部 input 被全局 `:focus-visible` 添加内侧阴影，与外框形成重复边框。已复用公共 `.input-with-icon`，由外框统一显示中性灰焦点边框，删除页面重复定义；公共输入区补齐宽度收缩约束，长项目 ID 不再挤压搜索图标。此规则同步写入视觉与组件系统。

代码核对覆盖数据集版本选择、训练数据选择、Workflow 节点库及自定义节点搜索；这些同类输入已有内框排除规则。实际浏览器验证项目与自定义节点搜索的亮暗外观、项目默认与鼠标／键盘聚焦、Enter 搜索真实“测试”项目通过，无页面横向溢出，搜索图标保持 18 px，内部边框为 0、阴影为 none。用户原筛选条件和项目数据保留，外观恢复亮色。

项目页面回归 10 项及 Vue TypeScript 检查通过。截图：[项目亮色](docs/design/frontend/verification/projects-search-focus-20261105/project-search-light.png)、[项目暗色](docs/design/frontend/verification/projects-search-focus-20261105/project-search-dark.png)、[节点搜索亮色](docs/design/frontend/verification/projects-search-focus-20261105/catalog-search-light.png)、[节点搜索暗色](docs/design/frontend/verification/projects-search-focus-20261105/catalog-search-dark.png)。开发服务保持运行。

### 项目原表格密度与重复操作修订（2026-11-05）

进一步追溯工作台重做前的 `e49b1050`：项目列表使用公共 `.resource-table`，单元格内边距为 `12px 14px`，并非新工作台的 `18px 16px`。本次据此恢复表头及数据行内边距；窄屏只缩减水平内边距，不再增加垂直留白。真实页面带“当前项目”第二行的记录由约 74 px 降为约 62 px，普通单行记录约 55 px；未设固定高度裁切内容。此项取代前面“74 px 已恢复原行距”的结论。

查看按钮补齐 16 px Eye 图标；更多菜单移除重复的 SDK 配置包及对应组件参数、事件类型，保留项目信息、编辑、删除，顶部 SDK 按钮保持可用。真实菜单核对和项目页面 10 项回归、Vue TypeScript 检查通过，见[实际页面](docs/design/frontend/verification/projects-compact-actions-20261105/list-and-menu.png)。

### 项目列表直接操作与满高布局（2026-11-05）

按最新要求替代更多菜单：查看、项目信息、编辑、删除全部使用直接图标按钮，保留 title 和 aria-label；默认／受保护项目隐藏删除按钮，无写入或删除权限时不显示对应操作。删除不再使用的 ProjectMenu 组件。选中行仅以已有品牌色背景和 aria-pressed 表达，不再追加“当前项目”第二行。

搜索栏宽度缩至 240 px，清除占位文字，保留搜索图标和可访问名称。列表单独使用满高布局：表格面板填满工作区余高，正文内部滚动、表头吸顶、分页位于面板底部；空态也保留满高容器，查看后返回恢复正文滚动位置。概览页布局不变。

真实数据验证两行均约 55 px，默认项目只有三个图标，普通项目四个图标；详情和编辑均能直接打开原抽屉。1236×1036 与 1236×640 视口均无外层溢出，分页保持可见，测试结束恢复原视口。新增受保护项目及只读权限、直接抽屉操作回归，共 12 项页面测试和 Vue TypeScript 检查通过；未删除或修改项目业务数据。见[列表截图](docs/design/frontend/verification/projects-direct-actions-20261105/list-light.png)、[短屏截图](docs/design/frontend/verification/projects-direct-actions-20261105/list-short.png)。

### 项目列表恢复内容高度与条件分页（2026-11-05，当前有效）

用户确认项目数量通常较少，满高白色区域削弱卡片层次、产生空白占位。本次撤回上节的满高布局、正文独立滚动及底部分页固定，恢复表格随实际行数增高，返回列表时恢复外层滚动。紧凑行距、直接图标操作、受保护项目隐藏删除及短搜索栏继续保留。

分页栏仅在 `offset > 0`、`hasMore` 或已知总数超过当前页容量时显示，避免末页记录少时丢失返回上一页入口。空态、不足一页及恰好一页均不显示分页栏。真实两条记录的表格面板约 151 px，分页不渲染，见[最新有效截图](docs/design/frontend/verification/projects-direct-actions-20261105/list-content-height.png)。项目页面 17 项回归通过，包括已知／未知总数与末页边界；视觉规范同步更新。前节满高截图仅为已撤回方案的检查记录，不再作为实施依据。

### 创建后的完整列表与中性下载反馈（2026-11-05）

创建成功不再调用项目 ID 搜索定位，清空已有筛选、返回第一页并选中新项目，保留简短创建反馈和查看入口。后端已有按更新时间倒序排序，使用原列表接口即可显示新记录；用户主动定位的行为保留。

公共 Toast 的普通成功／信息样式改为中性色，警告和错误语义色保持；SDK 下载使用信息提示“已开始下载”。创建前有／无筛选、分页恢复、同名项目、SDK 成功／请求失败／浏览器触发失败、轻提示计时和关闭等 40 项回归通过，Vue TypeScript 检查通过。真实开发环境以不包含访问凭据的配置包触发下载，提示背景为白色、边框 `rgb(228,231,236)`、图标灰色，见[实际下载反馈](docs/design/frontend/verification/projects-feedback-20261105/sdk-neutral-light.png)。本次未额外创建或改写项目业务数据，创建后的列表逻辑由组件回归覆盖。

### 项目切换与创建入口（2026-11-05）

行点击不再等待重复的项目详情请求，直接使用列表已有的项目与摘要更新当前上下文；“查看”直接导航，最新数据及权限由概览页原有请求核对。连续选择和重复点击不新增请求，不保留上一项目的摘要。顶部及创建抽屉命名恢复为“创建新项目”。

26 项相关回归、Vue TypeScript 检查通过。内置浏览器使用现有三个项目验证名称／整行选择、查看／返回及创建抽屉打开／取消，控制台无 error，页面无横向溢出；未改变项目业务数据。见[实际页面](docs/design/frontend/verification/projects-switch-20261105/list.png)。

### 项目操作列补回文字（2026-11-05）

按最新要求，操作列改为带图标与文字的“查看／详情／编辑／删除”，替代前面的纯图标方案。沿用公共小型按钮，默认项目仍不显示删除，其他权限条件及点击行为不变。操作列宽度增加到 330 px，按钮文字保持单行，窄屏使用表格容器横向滚动。

20 项页面回归与 Vue TypeScript 检查通过。内置浏览器验证普通项目四个按钮、默认项目三个按钮，以及详情抽屉打开／关闭。1280 px 视口无页面横向溢出，按钮高度 30 px、数据行约 55 px，控制台无 error。见[操作列截图](docs/design/frontend/verification/projects-actions-text-20261105/list.png)。

### 项目抽屉动效和删除层级（2026-11-05）

先核对实际详情、编辑、创建及删除流程，再修复共用动效和信息层级：

| 检查步骤 | 发现与修复 | 核对结果 |
| --- | --- | --- |
| 详情／创建打开 | 条件挂载缺少 appear；补齐右侧 200 ms 滑入与遮罩过渡 | 真实页面亮暗可用，布局保持不变 |
| 编辑、取消、保存 | 直接卸载截断退场；改为退场后关闭并恢复焦点 | 自动化覆盖保存和快速重开；实际草稿继续编辑／放弃正常 |
| 删除预检 | 长 ID、全部内部资源数同时展开；改为名称确认、主要数量和按需明细 | 面板由 640 px 收紧到 520 px，亮暗一致，危险动作仍受预检限制 |
| 阻止与结果未知 | 保留直接可见的原因与恢复动作，技术编号按需展开 | 回归覆盖阻止、响应未知、清理失败，核对不会重复发起删除 |

55 项相关回归和 Vue TypeScript 检查通过；真实页面关闭后无残留模态隔离，控制台 warning/error 为空。本轮没有删除或改写业务记录。截图与详细记录见[追加验证](docs/development/project-workspace-followup-validation.md#追加项目抽屉动效与删除确认2026-11-05)。样式规范已同步；本结论限定为本次项目抽屉与删除流程，不扩大为所有页面已无缺陷。

### 项目操作收回菜单（2026-11-05，当前有效）

按最新要求替代逐项按钮：保留“查看 + …”，详情／编辑／删除收回菜单，操作列从 330 px 缩为 144 px。“查看”改用打开文件夹图标，移除 Eye 图标。默认项目不显示删除，只读账号菜单仅有详情；菜单不重复加入 SDK 操作。复用 Reka UI 菜单，并在其关闭焦点回收后打开业务面板，避免菜单把抽屉焦点抢回背景。

20 项项目页面回归及 Vue TypeScript 检查通过。真实内置浏览器验证普通项目菜单、默认项目删除保护、详情与删除确认入口、关闭后焦点返回、Escape 关闭菜单；未提交删除或修改业务数据，控制台 warning/error 为空。见[实际菜单](docs/design/frontend/verification/projects-menu-20261105/list-menu.png)。服务保持运行，本次未创建 `.tmp` 临时产物。

### 删除确认与完成反馈继续精简（2026-11-05，当前有效）

删除明细、资源数量汇总、技术信息及手动“核对结果”全部移除。确认面板只保留名称、不可撤销说明和名称确认；完成面板只保留“项目已移除”、项目名称、绿底白勾和关闭按钮。完整资源预检、权限和后端 Project ID 校验继续有效。

后端原有后台清理不变。前端自动读取删除回执：处理中串行间隔 1 秒查询，短暂网络故障间隔 5 秒再读；结果明确完成或失败后停止，失权停止；只重读、不重发 DELETE。关闭面板终止未完成 GET 和定时器，原有未完成记录仍保留；相同状态不反复刷新项目列表。只有后端返回 `deleted` 才显示成功，失败原因保持直接可见。

45 项组件与页面回归、Vue TypeScript 检查通过，覆盖清理完成、断线后恢复、失败／失权停止、取消查询及迟到响应。内置浏览器核对真实项目的简化确认、菜单返回和默认禁用状态，控制台 warning/error 为空；未删除现有业务项目。成功状态及自动查询链路由组件回归验证，本轮未另建项目执行真实删除。证据：[简化确认](docs/design/frontend/verification/projects-delete-simple-20261105/confirm-light.png)。开发服务保持运行，本次未产生 `.tmp` 产物。

### 创建成功统一轻提示（2026-11-05，当前有效）

移除列表内“项目已创建 · 名称 · 查看”提示条及其状态、关闭入口、专属样式；创建成功与编辑成功共同使用右上角公共中性 Toast，显示“项目已创建”，按现有规则 4.5 秒后自动消失。仍在服务器确认成功并完成抽屉退出后触发；创建失败不提示成功。创建后显示完整列表首屏并选中新项目，不添加搜索条件。

45 项组件／页面回归及 Vue TypeScript 检查通过；内置浏览器确认当前提示条已消失、真实两条项目记录保留。Toast 事件与默认时长由已有组件回归核对，本次未另外创建业务记录。样式规范已同步，开发服务继续运行。

### 数据集工作区实现核对（2026-11-05）

实现依据：[数据集列表母版](docs/design/frontend/generated/数据集/数据集列表-亮色.png)、[标注样本网格](docs/design/frontend/generated/数据集/标注样本网格-亮色.png)，以及数据集的抽屉、结构、导入/导出、管理与异常状态规格。对照使用源图与真实浏览器截图；桌面视口统一为 1672×941，另检查 1280×640 短屏。没有生成替代实现截图的设计图。

| 核对范围 | 结果与适配 |
| --- | --- |
| 全页布局 | 保留平级主导航、四类管理标签、页面内工具栏、浮动表格；版本页保留统计、五个内容标签、筛选和样本网格。无额外全局顶栏 |
| 导航与密度 | 复用已完成项目分类的实际导航宽度、字体、控件尺寸；不逐像素复刻生成图的放大文字。短屏可由 Logo 展开，未增加另一个展开按钮 |
| 字体与内容 | 名称强调、说明弱化；普通内容不全加粗。真实数据替代示意名称与版本号，任务类型中文化，长名称单行省略并提供完整 title |
| 颜色与图标 | 品牌绿用于主操作和选择；悬停/输入焦点中性。复用 Lucide 与公共按钮。标注颜色按类别区分，不能把所有对象染为品牌绿 |
| 表格 | 使用 ResourceTable 原有圆角、行距和悬停；少量数据不强行铺满剩余高度，无分页时不显示分页栏。早期的划分列与窄容器水平滚动方案已由同日下方修订替代 |
| 抽屉 | 复用 SideDrawer，右侧覆盖不挤压背景，遮罩覆盖导航和内容；200 ms 进出动画、焦点恢复及未保存草稿确认；实际验证取消放弃后输入保留 |
| 图像 | 缩略图、大图使用真实图片和真实框；类别、尺寸及对象坐标可查看，开关标注与前后切换不改写源数据 |
| 细节修正 | 样本深链接改用请求代次而非 Vue 代理对象身份比较；切版先使旧样本请求失效；格式检查状态和比较计数标题可读化 |

已在同一次核对中查看完整页面，并重点检查列表表头/行、样本网格首行、抽屉头部/底部和标注区域。最终证据：

- [列表亮色](docs/design/frontend/verification/datasets-workspace-20261105/catalog-desktop-light.png)、[列表暗色](docs/design/frontend/verification/datasets-workspace-20261105/catalog-desktop-dark.png)、[列表短屏](docs/design/frontend/verification/datasets-workspace-20261105/catalog-short-light.png)。
- [样本网格亮色](docs/design/frontend/verification/datasets-workspace-20261105/samples-desktop-light.png)、[样本网格暗色短屏](docs/design/frontend/verification/datasets-workspace-20261105/samples-short-dark.png)、[样本大图](docs/design/frontend/verification/datasets-workspace-20261105/sample-viewer-light.png)。
- [编辑抽屉](docs/design/frontend/verification/datasets-workspace-20261105/edit-drawer-dark.png)、[样本信息](docs/design/frontend/verification/datasets-workspace-20261105/sample-info-short-dark.png)、[文件关联样本](docs/design/frontend/verification/datasets-workspace-20261105/file-associated-samples-dark.png)。

相关后端 112 项、前端 63 项回归通过，生产构建通过。真实 worker 已完成独立副本的导入、检查、派生、比较及所选样本导出。用户授权后已正常重启 worker，补验版本更新时间、排队/运行中取消、失败后继续处理均通过；服务 ready，部署 6/6、Runtime 10/10、Trigger 8/8 就绪。设计中的未来异常、连接器参考和三维资产专属管理不以本轮二维工作区替代；本轮结果不等于长期生产全面验收。详细范围、迁移、接口和验证见[实施记录](docs/development/dataset-workspace-implementation.md)。

### 数据集列表与版本修订复核（2026-11-05 22:50）

以用户最新修订覆盖旧图的多余字段，保留已确认的整体布局、公共控件、主题和抽屉交互。

| 项目 | 最终结果 |
| --- | --- |
| 列表 | 删除数据划分、重复项目名称；列宽随容器分配，长名称及说明省略，查看/更多保持可操作 |
| 版本 | 自动 v1/v2/v3，实际 worker 创建 v4；详情下拉与来源/版本表使用同一持久化序号，不替换资源 ID |
| 查看页 | 补版本选择与完整列表入口，修正类别颜色点、文件名省略、操作列和来源链接；切版数据匹配 |
| 导入详情 | 类别 ID/名称按实际报告显示，卡片标题与内容顶端对齐；划分表、类别表不横向滚动 |
| 原始报告 | 完整长路径在容器内换行；纵向滚动，未截断 JSON 原值 |
| 1024×768 | 展开导航时根宽 1024，类别表 746px、导入表 365px、报告 683px，测得各自 scrollWidth 与 clientWidth 一致；收起导航也已核对 |
| 亮暗与错误 | 同源布局、主题中性色和品牌绿用途一致；最终独立验收标签页未记录 warning/error；恢复亮色并清除临时视口 |

最新证据（同名文件只保留最终结果）：

- [列表亮色](docs/design/frontend/verification/datasets-refinement-20261105/dataset-list-1024-light.png)、[列表暗色](docs/design/frontend/verification/datasets-refinement-20261105/dataset-list-1024-dark.png)。
- [版本选择与真实标注](docs/design/frontend/verification/datasets-refinement-20261105/dataset-versions-1024-dark.png)。
- [导入详情](docs/design/frontend/verification/datasets-refinement-20261105/import-details-1024-light.png)、[长报告](docs/design/frontend/verification/datasets-refinement-20261105/import-report-1024-light.png)。

版本/迁移/工作区/导入导出相关回归 57 项、前端数据集 10 项通过；最后接口修订复核 4 项通过，TypeScript 和 Vite 正式构建通过。既有 Workflow/CloudViewer 构建体积警告未在本次数据集修订中处理。只读生产数据与独立副本验证的边界见实施记录。

### 目录树与样本更新（2026-11-05 至 2026-11-06，历史阶段，版本语义已修正）

按用户最新要求简化功能，保留已确认的导航、主题、表格和抽屉。关联样本、人工复核、外部标注交接/回传检查入口与闲置组件已移除；早期设计及验收截图中的这些入口仅属历史记录。当前规则和中文提示词已同步。

| 核对项 | 结果 |
| --- | --- |
| 数据结构切换 | 使用真实目录树，独立维护展开与选中状态；离开标签仅隐藏，不卸载重建。返回原目录立即显示已加载文件；异步旧响应不能覆盖新目录或新版本 |
| 目录与预览 | 分层按需读取目录、文件分页，叶目录不保留无效展开箭头；图片/文本使用共享 SideDrawer，关闭后返回原位置；无关联样本入口 |
| 添加与删除 | 添加 ZIP 和删除所选进入同一更新页，来源版本、现有数、移除数及撤回操作明确；确认才创建新版本；没有改变旧版本或其外部引用 |
| 结果与异常 | 版本创建结果只显示来源/移除/剩余数量与查看入口，不显示无关分组说明；空更新、全删不补样本、坏包、错误来源、关键点冲突均有阻止；未知提交不自动重发 |
| 草稿与权限 | 沿用数据集读写权限；离开有文件或删除选择的草稿先确认，取消离开保留输入；无法生成空版本 |
| 1024×768 | 展开导航时主区 763px、文件表 575px、抽屉 679px，scrollWidth 与 clientWidth 一致；暗色更新表单 761px 无水平滚动，路径和文件名省略保留完整 title |
| 亮暗与控制台 | 中性色悬停、品牌绿选择、同一遮罩覆盖导航和内容，抽屉不挤压背景；最终验证时段没有新增 warning/error。日志内 23:24 的开发热更新失败早于最终修复，后续页面与正式构建通过。检查后恢复亮色和默认视口 |

真实开发 worker 完成独立副本 v4（2 张）→ v6（4 张/6 对象）→ v7（3 张/5 对象），首轮临时 v5 已清理且编号不复用。最终 COCO ZIP 含 4 张图片、6 个对象，图片 ID/文件名唯一、标注引用有效，旧版本不变。[真实验证数据](docs/design/frontend/verification/dataset-sample-management-20261105/live-validation.json)。

后端本轮 47 项回归通过，图片 ID 合并修订后复测其中 2 项集成测试；前端 6 文件/14 项通过，TypeScript 与 Vite 正式构建通过。现有 Workflow/CloudViewer 分包体积警告仍存在。服务 ready，部署 6/6、Runtime 10/10、Trigger 8/8；独立 worker generation 52 正常运行，服务按要求保持运行。

最终截图：[更新样本](docs/design/frontend/verification/dataset-sample-management-20261105/sample-update-before-submit.png)、[删除选择确认](docs/design/frontend/verification/dataset-sample-management-20261105/remove-sample-confirm.png)、[目录亮色](docs/design/frontend/verification/dataset-sample-management-20261105/structure-1024-light.png)、[目录暗色](docs/design/frontend/verification/dataset-sample-management-20261105/structure-1024-dark.png)、[图片抽屉](docs/design/frontend/verification/dataset-sample-management-20261105/file-preview-1024-dark.png)、[暗色更新表单](docs/design/frontend/verification/dataset-sample-management-20261105/update-form-1024-dark.png)、[新版本样本](docs/design/frontend/verification/dataset-sample-management-20261105/samples-updated-final.png)。

### 当前版本样本修改与手动创建版本（2026-11-06，当前有效）

用户修正版本语义后，添加 ZIP、删除所选改为保存到当前版本，只有独立的“创建新版本”分配新 vN。页面保留当前版本编号与样本数量，提交按钮为“保存修改”。旧图中的自动新建版本不再作为实现要求。`_verified` 来自验收副本的类别重命名，不是系统标注状态。

- 真实验收副本：v7 样本 3 → 5 → 4，版本 ID 不变；显式创建的 v8 保留创建时 5 个样本，图片均可读取。更新失败、过期提交、并发修改、导出图片关联与原版本快照隔离均已回归。
- 目录树在初次展示时区分分支与叶目录；不再需要先点击叶目录才能消除箭头。
- 筛选控件保持可读宽度，窄屏不互相覆盖；网格/列表和标注显示移至选择操作行右侧。1024px 亮暗、展开/收起导航根宽和内容宽均为 1024px，无水平溢出。检查后恢复亮色、收起导航和默认视口。
- 后端相关 56 项覆盖，最终样本集成 2 项复核通过；前端 6 文件/15 项、TypeScript 通过，正式构建通过（既有大分包提示仍在）。完整语义、接口、部署边界与故障保护见[实施记录](docs/development/dataset-sample-management.md)。

最新证据：[真实数据](docs/design/frontend/verification/dataset-polish-20261106/live-validation.json)、[样本页](docs/design/frontend/verification/dataset-polish-20261106/samples-after-light.png)、[更新当前版本](docs/design/frontend/verification/dataset-polish-20261106/update-current-light.png)、[目录树](docs/design/frontend/verification/dataset-polish-20261106/tree-after-light.png)、[1024 亮色](docs/design/frontend/verification/dataset-polish-20261106/samples-1024-light.png)、[1024 暗色](docs/design/frontend/verification/dataset-polish-20261106/samples-1024-dark.png)、[展开导航](docs/design/frontend/verification/dataset-polish-20261106/samples-1024-expanded-light.png)。开发服务保持运行。

### 数据集设计逐页对照与样本生命周期核对（2026-11-06）

已对照数据集已确认的列表、样本网格、目录树、类别与划分、版本与来源、创建版本两步、抽屉、大图和导出设计。遵循最新要求：添加/删除保存当前 vN，创建版本由独立按钮明确执行；不恢复已删除的复核、交接等入口。

修正创建版本表单/单选样式、检查摘要和版本说明；版本切换原子更新、过期响应隔离、旧选择校验、版本下拉重复载入、历史分页缓存；目录保留内容加载、标注对象高亮、同序切图；历史导入计数和历史任务重开不受后续样本修改影响。1024px 亮暗、四个管理标签、编辑和文件抽屉核对通过，无水平溢出。

真实验收副本 v8（5 样本）手动创建 v9；v9 添加 2 后为 7、删除 1 后为 6，ID/编号不变，v8 仍为 5。全部图片可读，导出 COCO 为 6 图片/10 标注，历史导入保持 7/新增 2。过期写入返回 409。前端 20 项回归、后端相关 14 项及补充 API 3 项、TypeScript、生产构建通过。服务 ready，部署 6/6、Runtime 10/10、Trigger 8/8，开发服务保持运行。

[完整修复、边界和截图](docs/design/frontend/verification/datasets-design-alignment-20261106/README.md)。本轮未将旧完整产品设计中的 RGB-D/点云数据集专用查看器视为已实现；未改 Runtime/Trigger/.NET SDK 数据面。

### 数据集列表七列与操作样式（2026-11-06，当前有效）

对照来源：[亮色设计](docs/design/frontend/generated/数据集/数据集列表-亮色.png)、[暗色设计](docs/design/frontend/generated/数据集/数据集列表-暗色.png)。同尺寸参考截图与页面截图对照，保留业务布局、七列、普通正文版本与数量、品牌绿文字查看、简短菜单。

| 核对项 | 结果 |
| --- | --- |
| 工具栏 | 搜索、任务类型、可用状态、刷新整组右对齐；控件不相互遮挡 |
| 列与文字 | 恢复数据划分；版本与数量均为正文 14px；样本单位为张，类别单位为类；数据集说明放详情 |
| 行与操作 | 行高 44px，查看无文件夹图标/外框；省略菜单为详情、编辑、导入、导出；普通悬停中性灰 |
| 1024×768 | 展开导航：页面 1024/1024、表格 762/762（client/scroll）；亮暗无横向溢出，长名称/划分/时间单行省略，title 保留原值 |
| 交互 | 搜索测试1为唯一结果，清空恢复五项；更多菜单和详情抽屉正常；查看进入真实最新 v9，返回列表正确 |
| 工程检查 | TypeScript 通过，git diff --check 通过；浏览器本轮 warning/error 为空；服务保持运行 |

按已确认的后续约定，保留公共导航尺寸与折叠方式、不重复项目名、没有第二页时隐藏分页，并使用纯色主题；不复制早期生成图的暗角、纹理或放大的控件比例。页面使用五项真实数据，不替换成设计图三项示例。相关布局一致性已验证，本记录不声称截图与示例数据逐像素相同，也不扩大为其他数据集页面的全量验收。

最终证据：[默认列表](docs/design/frontend/verification/dataset-catalog-style-20261106/list-final-light.png)、[桌面亮色](docs/design/frontend/verification/dataset-catalog-style-20261106/desktop-light.png)、[桌面暗色](docs/design/frontend/verification/dataset-catalog-style-20261106/desktop-dark.png)、[1024亮色](docs/design/frontend/verification/dataset-catalog-style-20261106/1024-light.png)、[1024暗色](docs/design/frontend/verification/dataset-catalog-style-20261106/1024-dark.png)、[更多菜单](docs/design/frontend/verification/dataset-catalog-style-20261106/menu-light.png)。

Final result: passed（本轮列表范围）。

### 数值色块与矩形提示（2026-11-06，历史，已由分组表头替代）

用户最终选定原参考图的颜色关系与分行提示，仅调整 EVA 色调并删除底部尖角。此前单行原生提示与珊瑚/石墨颜色分组已被替换。搜索框靠左，筛选靠右。

- 已打开并核对最新生成局部图及真实页面截图：两组数字分别蓝/紫和青绿/橙黄/紫，24px小色块，普通矩形提示没有箭头。实际页面保留既有导航和纯色主题，不照搬生成图的比例或阴影误差。
- 亮暗配色文字对比度均大于4.5:1；1024×768展开导航时页面1024/1024、表格762/762（client/scroll），25个数值未截断，所有行44px。搜索与表格左边缘一致。
- 真实数据1,174样本、3类、train939/test117/val118映射正确，零值保留；两行/三行提示、键盘聚焦及Escape关闭已实测。没有鼠标移动API，本轮不声称实际鼠标悬停已自动化验收；使用已有Tooltip组件的标准hover处理。
- TypeScript通过；本轮没有更改数据、后端、Runtime/Trigger或公共表格。完整色值、截图和边界见[验证记录](docs/design/frontend/verification/dataset-count-badges-20261106/README.md)。

Final result: passed（本轮数值色块、布局与矩形提示范围）。

### 版本、记录与样本工作区（2026-11-06）

按已确认数据集设计及最新数值要求，统一版本列表、导入/导出记录、详情、类别和版本来源的数值组件；补齐列表来源、文件、vN 信息，历史统计保持任务快照。样本页修正统计条、筛选/视图控件、卡片与批量选择层级，文件树操作移至文件区；空态可继续添加样本。

真实条码版本 609 张 / 982 对象 / 2 类，划分 520/89/0；v9→v8 切换与图片/统计同步、选择/取消修改、清除筛选、大图切换均正常。三个列表、工作区、报告和详情在 1024px 无水平溢出；亮暗同源布局，矩形提示无箭头、键盘可达。前端 22 项、API 3 项、TypeScript 和差异检查通过。服务保持运行。[完整核对与亮暗截图](docs/design/frontend/verification/dataset-pages-polish-20261106/README.md)。

Final result: passed（本轮指定页面与交互范围）。

### 数据集分组表头（2026-11-06，历史，已由原图斜线显示替代）

用户确认第 2 张分组表头后，撤销此前数值色块方案。已同步数据集、版本、导入/导出记录和相关详情的同类显示。搜索靠左、筛选靠右；两层表头、普通中性数字、无箭头矩形提示。旧记录保留当时的证据，不作为当前实现目标。

同次对照所选原图及 1356×1160 实际截图，核对布局、字体、间距、颜色、图标和文本。修正 1024px 样本子标题截断、展开导航时导出状态过窄，以及详情统计继承等宽字体的问题。四类列表在亮暗、展开/收起导航时无横向滚动，真实数值及历史快照正确，搜索/菜单/详情/版本切换正常。TypeScript、数据集 22 项回归及差异检查通过；控制台 warning/error 为空。

[所选设计](docs/design/frontend/generated/数据集/列表数值分组表头-亮色.png) · [实际页面](docs/design/frontend/verification/dataset-grouped-counts-20261106/datasets-light-1356.png) · [完整验证和亮暗截图](docs/design/frontend/verification/dataset-grouped-counts-20261106/README.md)。已恢复亮色及默认视口，开发服务保持运行。

Final result: passed（本轮分组数值、指定页面交互及窄屏适配范围）。


### 数据集原图斜线数值显示（2026-11-06，最新有效）

依据最新确认，四类列表恢复单层表头，样本/类别显示“1,174 张 / 3 类”，数据划分显示“train 939 / test 117 / val 118”。移除分组子表头，收窄版本列。修正公共表格样式误将数值设为小号灰字的问题：统一14px、21px行高和正文颜色。重复点击当前标签不再清空列表。历史任务快照及数据语义保持不变。

同次对照原设计与1672×941实际截图；在真实开发环境核对四类列表、亮暗主题、1024px展开与收起导航，均无水平溢出。数据行44px，表头单行，完整数值提示无箭头。浏览器控制台无warning/error，专用数值测试2项通过，TypeScript检查通过。恢复亮色、收起导航和默认视口；服务保持运行。

截图：[实际列表](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/slash-final.png) · [原图尺寸对照](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/slash-light-desktop.png) · [暗色1024px](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/slash-dark-1024.png)。

Final result: passed（本轮四类列表的数值、表头、布局与标签切换范围）。


### 数据集查看页细节与生命周期复测（2026-11-06）

对照标注样本网格设计，恢复统计区数值在上、标签在下的层级，数据划分保持普通斜线文本；列表“最新版本”简化为“版本”。目录读取失败时清除旧目录文件，避免新路径配旧文件，并保留重试入口，不误报空目录。复用现有 Vue 组件与主题，无 API 或持久化变更。

真实开发环境使用验收副本 dataset-5996dd3c8b7e421dbe9ad64bd2ee2585：手动创建 v10（dataset-version-2274c0f135b5，6 样本），上传现有 detection-coco-min.zip 后8样本，删除本轮新增 train-1.jpg/val-1.jpg 后恢复6样本，整个样本修改过程保持 v10。切换 v8 为原有5样本，切回 v10 为6；目录树叶节点、目录切换、网格与标注显示核对正常。1024px暗色网格和目录宽度均为1024，无横向溢出。恢复亮色与默认视口；开发服务保持运行。

TypeScript检查通过；现有数据集前端22项通过，新增目录失败重试回归通过（目录文件4项）。控制台无warning/error。未修改生产数据或Runtime/Trigger调用链路。截图：[查看页](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-view-final.png)。

Final result: passed（本轮查看页、样本增删、手动版本创建和切换范围）。


### 版本创建结果与版本列表（2026-11-06）

对照数据集版本列表和创建新版本检查图，修正结果页通用键值列表造成的层级缺失、过多纵向留白、全宽操作按钮。完成态改为标题与来源、横排样本摘要、数据划分、右侧主操作。其他任务的失败/取消/运行展示保持原逻辑。版本列表调整列宽并统一任务名称。

真实历史任务 task-7a6fdcc2293259deb2f2887f016cb107 展示6来源样本、6结果样本、移除0、train5/test0/val1；点击查看新版本成功进入v10。本轮未创建额外任务或修改数据。结果页和版本列表1024px无水平滚动，亮暗主题核对，控制台无warning/error。类型检查与2项针对性回归通过。服务保持运行。

[完成页截图](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-created-light.png) · [版本列表](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/versions-list-final.png)。

Final result: passed（本轮完成态布局、真实结果跳转与列表适配）。当时尚缺的磁盘可用状态已由下节实现与验证补齐。

### 版本可用状态、筛选与创建流程（2026-11-06）

依据数据集版本列表、创建新版本检查设计图，新增真实基础资源状态及筛选。复用公共 Select、StatusBadge、ResourceTable，状态采用圆点与短文本，异常原因保留普通提示；不增加正常状态长说明。预检查增加来源数据集/vN、检查图标和中性摘要区域；完成态沿用已确认的报告层级。

- API：状态检查使用当前 content_revision；有状态条件时先筛选再分页，只有一页执行样本/标注聚合。字段与检查范围见 `docs/design/frontend/dataset-pages-design.md`。不扫描每张图片，不将基础资源可读等同于全量完整性校验。
- 隔离后端测试5项覆盖资源缺失/恢复、空清单、无样本、权限/磁盘错误、更新锁冲突、真实导入、组合筛选、过滤后分页和非法状态；已有工作区 API/任务5项通过。前端数据集25项通过；TypeScript、ruff、diff空白检查通过。
- 真实开发环境：验收副本 v10 经预检查创建 v11（dataset-version-f26305f71daf），6样本、10对象、4类别，train5/test0/val1。查看新版本与切回v10正常，来源统计不变。
- 仅对本轮v11的 categories.json 临时改名，缺失筛选准确返回这一条。恢复后缺失筛选为空，全列表14条均可用；文件 SHA256 恢复前后相同。未修改生产数据集或 Runtime/Trigger 链路。
- 1024px 亮暗、导航展开/收起无水平溢出；44px行高，状态和操作保留完整显示，长内容省略并提供提示。修正展开导航时的创建时间列过窄。浏览器控制台无 warning/error。
- 前端开发页出现旧模板缓存，核对服务实际输出并刷新Vite后，用新验收标签页确认最新模板。开发前后端保持运行，视口恢复默认、主题恢复亮色。

[版本列表亮色](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-availability-1024-light.png) · [版本列表暗色展开导航](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-availability-1024-expanded-dark.png) · [预检查暗色](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/version-check-1024-dark.png)。

Final result: passed（本轮版本基础资源状态、筛选、创建流程和设计细节范围）。


### 版本表头、导入导出记录与详情对照修订（2026-11-06）

对照 `generated/数据集/数据集版本列表-亮色.png`、`导入记录列表-亮色.png`、`导出记录列表-亮色.png`、`导入详情-已完成-亮色.png`、`导出详情-已完成-亮色.png`，并按本轮标注修正：版本首列“数据集”、只显示样本、来源“创建”。导入只显示样本和可跳转目标版本；导出移除样本列，补文件状态、直接下载及筛选。搜索支持文件名，导入支持近7/30天。

详情恢复来源/检查、映射/划分、结果操作的层级；导出文件结构置于映射前。修复报告缺失误报正常、结构化错误未显示、名称查询失败阻断文件浏览、切换记录复用旧文件分页、目录按钮沿用原生样式等问题。类别ID来自真实映射；未知ID不伪造。保留既有样本修改与手动版本语义，不使用历史报告覆盖当前版本统计。

验证：

- 后端48项通过：导入API、导出API、文件清理、记录筛选、工作区API。覆盖项目权限、过滤后分页、文件状态和搜索组合、非法参数等。
- 数据集前端13个文件、27项通过；TypeScript、作用范围内ruff、diff空白检查通过。开发中发现的 filePreviewOpen 初始化顺序错误已修复并覆盖详情初始化/切换回归。
- 真实开发环境：按 detection-coco-min.zip 搜索返回1条；近7天返回6条，旧记录被过滤。导出可下载返回6条、已清理返回0条，与当前数据一致。
- 从列表下载真实验收副本v9的COCO ZIP（3,474,648字节、9个文件），CRC校验通过；6张图片、10个标注、4类，train5/val1。浏览导出annotations目录、打开instances_train.json抽屉正常，叶文件不显示展开箭头，下载提示“已开始下载”。
- 导入详情历史报告为更新后8张/新增2张，正确保留当时结果；当前v10后续已删除这2张、保持6张。未以当前统计改写历史记录。
- 1024×768亮暗、导航展开/收起核对；导出列表收起918px/展开762px，scrollWidth与clientWidth相等，行高44px。版本列表展开746px无溢出；详情表格及展开报告/JSON抽屉无水平滚动。修复导出操作列被公共100px规则覆盖导致的溢出。
- 最终浏览器操作在修复后的15:55至结束无新增warning/error。保留早先开发异常日志，不将其误报为当前错误。主题恢复亮色，临时视口覆盖已重置，开发服务保持运行。

截图：[导入记录](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/records/imports-light.png) · [版本列表](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/records/versions-light.png) · [导出暗色1024](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/records/exports-dark-1024.png) · [导出详情](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/records/export-detail-light.png)。

Final result: passed（本轮版本列表标注、导入导出列表/详情、筛选、文件浏览下载与1024px适配范围；未用本轮短测宣称所有未来数据任务或长期运行已验收）。

### 导入导出状态和列宽再次修订（2026-11-06）

- 对照已确认导入/导出列表设计，修正前轮遗留的胶囊状态标签，改为圆形图标及普通正文；成功、失败、处理中通过图形和文字共同区分。仅这两个列表启用新外观，公共任务状态组件默认外观不变。
- 短字段固定、长字段分配余宽，减少宽列空白并避免挤压状态、时间和操作。长名称、格式、文件信息单行省略；导出文件提示同时显示文件状态、大小和完整文件名。
- 真实8条导入、6条导出记录核对；1024×768亮暗主题及导航展开/收起检查，表格762px或918px，scrollWidth等于clientWidth，页面宽1024px，无水平溢出，行高44px。当前真实记录均为完成态，未伪造失败记录进行实测。
- 前端数据集27项回归通过，TypeScript及diff空白检查通过。首次沙箱测试因缓存重命名EPERM未进入用例，正常开发环境重跑通过。
- 中途开发进程退出后按开发文档恢复 backend、inference daemon、六类Worker与Vite。HTTP liveness为ready，daemon probe通过，Worker topology ready；服务保持运行。最后恢复亮色、折叠导航，浏览器默认视口1280×720。

最新截图：[导入记录](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/record-columns/import-light-final.png) · [导出记录](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/record-columns/export-light-final.png) · [1024暗色](C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-table-refinement/record-columns/export-dark-1024.png)。前轮记录列表截图不作为本轮状态样式基准。


### 查看页、详情、样本大图与结构（2026-11-06）

参考：`docs/design/frontend/generated/数据集/` 中标注样本网格、数据集详情抽屉、样本大图、样本对象信息抽屉、数据结构及样本结构亮暗设计。将源图与实现截图同轮并列检查。保留已确认布局与信息层级，控件尺寸使用项目公共组件，数据来自真实开发环境；不复刻生成图中的示例图片或恢复后来明确删除的外部标注功能。

本轮修正：统计条和工具栏层级、四列卡片及默认8张分页、详情抽屉真实摘要、专用大图工作区与右侧对象信息、文件/样本树。实测修复标注开关重置缩放：watch 改为分别比较 open 和样本标识；补同名文件不同 Sample ID 切换验证。对象表首列截断、标注文字过小同步修正。

验证：

- 数据集前端及公共视口合计16个文件、32项测试通过，覆盖详情统计/失败占位、目录请求、版本过期响应、样本树缓存/分页、标注切换保留缩放和同名样本重新适配。TypeScript检查通过。
- 真实609张条码样本显示982个对象、2个类别、train520/test89/val0；8→16每页数量切换正确；大图前后切换、缩放、标注开关、对象抽屉与对象选择核对正常。
- 验收副本v11为6样本/10对象，切换v8为5样本/8对象，切回v11恢复对应统计及目录；未修改生产样本，也未新建版本。
- 1024×768亮暗、导航收起/展开检查；网格、文件结构、样本结构、大图及详情抽屉 document.scrollWidth 等于1024，无水平滚动。长名称省略；侧栏展开时筛选行允许换行，保持控件可操作。
- 浏览器控制台未见 warning/error。开发服务保持运行，验证结束恢复亮色、折叠导航与默认视口。

截图目录：`C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/dataset-view-alignment/`，包含 samples-light.png、image-light.png、details-dark-1024.png、structure-light.png、structure-light-1024.png。

Final result: passed（本轮查看页及相关交互范围；真实数据核对与前端回归，不等同于所有未来标注格式或长期生产运行验收）。

### 查看页逐图复核后的再次修正（2026-11-06）

前轮“已对齐”不足以说明视觉细节完成。本次重新读取详情抽屉、标注网格、批量列表、大图、对象信息、文件结构、样本结构及不同任务样本的原图和提示词，按参考分组逐项修正。完整差异、最新截图、接口说明和验证边界记录在[逐图核对表](docs/design/frontend/verification/dataset-view-fidelity-20261106/README.md)。

- 修正抽屉信息分组与日期／ID排列、卡片比例、批量栏左右布局、页码、列表缩略图和文件名字体。
- 样本结构显示实际对象裁切图；文件结构包含文件叶子并正确识别空目录，重复请求合并、缓存与版本隔离保留。
- 大图对象面板改为真正的非模态检查面板，背景图像仍可缩放操作；选中对象平移到可见区，关闭恢复位置，Esc 优先关闭面板。共享资源抽屉默认模态行为不变。
- 45 项前端测试、4 项后端测试、TypeScript、ruff 和 diff 空白检查通过。1024px 亮暗主题实测无水平溢出。首次受限环境 API 测试停在 Python 回环 socket 初始化，正常本机环境重跑 4 项通过。
- 浏览器中途 HMR 的旧 `undimmed` 属性警告来自替换属性期间，最终源码已统一为 `nonmodal`。最终刷新后另行核对，不将历史热更新日志当作当前接口错误。

本轮结论仅覆盖上述查看页面和交互。不同标注类型有组件分支验证，真实浏览器用的是已有条码检测数据；不据此宣称全部未来类型和全部 112 张状态图均已完成验收。

## 2026-11-06 样本页面细节复核

final result: passed（仅本轮范围）

按标注样本网格、样本列表批量选择、样本对象信息抽屉三组原图和最新用户要求，修正搜索、排序图标、任务矩形标签、选择栏、分页摘要、大图分组和坐标信息层级。补齐样本列表标注状态，修正旧公共样式造成的文件名字号与颜色偏差。保持当前版本样本管理语义，不恢复已明确移除的外部标注功能。

真实开发环境使用 609 张条码／二维码样本，检查亮暗外观、1024×768、排序、分页、全选／清除、网格列表切换、大图翻页和对象面板。页面无水平溢出，浏览器未记录 error/warn。49 项相关前端测试及 Vue TypeScript 检查通过。

截图及逐项记录：[样本页面核对](docs/design/frontend/verification/dataset-sample-polish-20261106/README.md)。无本轮范围内未处理的 P0/P1/P2；不将本轮结论扩展到全部设计状态。

### 2026-11-06 标签与内容分隔线追加核对

final result: passed（本次两处样式修改）

查看页标签仅移除白色底，保留绿色文字／下划线；样本对象抽屉仅移除内容区分隔线。真实页面样式计算值与截图已核对，记录见 dataset-sample-polish-20261106/README.md 的追加核对。纯 CSS 修改未改变选择、导航或数据逻辑。

## 数据集导入向导、导入详情、导出向导和导出详情（2026-11-10）

17 组亮暗状态已对照，短屏检查为 1024×768。检查数据来自本地开发服务，上传中断通过浏览器故障注入复现。逐图结果、截图和边界见[核对记录](docs/design/frontend/verification/dataset-transfer-20261110/README.md)。

final result: passed（上述状态与数据范围）

## 数据集导入向导细节复核（2026-11-10）

以原图核对上传区、已上传文件行、数据定义、类别映射、划分统计及提交检查。数据定义同时验证新建和已有数据集，切回新建保留输入。真实 COCO 文件生成 v1，提交前与记录中的样本、对象、类别数量为 2、2、1。删除文件、重新选择同一文件、缺失图像阻止提交均在内置浏览器验证。用独立本地测试端口中断首次上传连接，点击重新上传后得到开发服务回执。亮暗短屏 1024×768 无水平溢出。服务端正式校验与本地清单预查分别显示。

[亮色对照](docs/design/frontend/verification/dataset-import-refinement/compare-light.jpg) · [暗色对照](docs/design/frontend/verification/dataset-import-refinement/compare-dark.jpg)。按设计稿与真实状态比较，使用当前工作站导航及真实样本；上传中断交互实测为亮色。

final result: passed（导入向导上述状态）

## 数据集导入、导出设计对照（2026-11-10）

使用本地工作站和 dataset worker，按原图核对两个四步向导、完成／失败详情、记录列表和确认框。桌面参照为 1672 × 941，短屏实测为 1024 × 768，亮暗主题分别截图；短屏目录树默认收起，仍可展开。核对时修正了导出兼容检查的左右栏比例、表头与类别行错位、文件名前图标换行、不兼容时的格式对照以及确认框中的清理／保留范围。

真实 COCO ZIP 的两张图片、两条标注和映射后的类别通过导出 ZIP 的完整性与 JSON 校验。另测上传连接中断后重传、缺图阻止提交、错误边界框导入失败、格式不兼容阻止导出及清理后的下载禁用。没有为凑齐设计稿的示例值补造时间、预计包大小或目标标注；类别映射按现场要求默认收起。数据集前端回归 18 个文件、44 项通过；生产构建通过。

[亮暗设计图与实测截图逐项对照](docs/design/frontend/verification/dataset-transfer-records/导入导出设计实测对照.html)

## 导入与导出字体、日期和图标复核（2026-11-10）

工作站使用本地分发的 Noto Sans SC 可变字体，普通表格正文 14 px、辅助信息 13 px。实心状态图标仅内部符号使用白色描边。文件树的省略号按目录展开，键盘可以操作。亮暗两套 22 组[原图和实测对照](docs/design/frontend/verification/dataset-transfer-records/导入导出设计实测对照.html)已更新。[现有 1,224 张样本的导入详情，1024 × 768 暗色](docs/design/frontend/verification/dataset-transfer-records/实测-导入详情-1024-dark.png)显示同一次执行的四个时间、对应状态以及无白色外圈的结果图标。


## 创建新版本：配置与检查页面（2026-11-16）

final result: passed（本轮配置、预检查和创建流程范围）

依据“创建新版本-配置／检查”的亮暗四张原图及配套中文约束，重建横向两步标题、版本来源、类别映射、划分比例、随机种子与分组、数据范围、版本说明、检查摘要、样本／对象双组对比表及右侧底部操作。复用工作站按钮、下拉框、表格、图标、离线 Noto Sans SC 和主题变量，未引入新 UI 框架。

### 视觉核对

| 范围 | 核对结果与证据 |
| --- | --- |
| 配置页亮色／暗色 | 来源、映射、横向比例、范围、说明及操作顺序一致；已修正重复内边距、字号和暗色面板背景。[亮色对照](docs/design/frontend/verification/derive-20261116/compare-config-light.jpg)、[暗色对照](docs/design/frontend/verification/derive-20261116/compare-config-dark.jpg) |
| 检查页亮色／暗色 | 独立来源卡、预检查状态、四项摘要、双组划分表及两项检查卡已核对；修正变化值颜色覆盖和底部操作位置。[亮色对照](docs/design/frontend/verification/derive-20261116/compare-review-light.jpg)、[暗色对照](docs/design/frontend/verification/derive-20261116/compare-review-dark.jpg) |
| 1024 × 768 | 两种主题均检查，保留正常字号及滚动；无横向溢出，键盘可到达底部操作。[配置](docs/design/frontend/verification/derive-20261116/config-light-1024.jpg)、[检查操作区](docs/design/frontend/verification/derive-20261116/review-light-1024-actions.jpg) |

原图中的示例数据由真实开发数据替换。导航沿用当前工作站尺寸；空操作列及手工字符计数按中文设计修订省略。类别未变显示实际差值 0；减少值使用带符号的负值和主题危险色。未配置分组时显示中性“未检查”，不冒充设计示例中的成功状态。映射排除只删除对应标注，保留样本。上述为有意的数据／公共组件差异，不宣称逐像素相同。

### 行为与真实数据

- 609 张条码／二维码样本、982 个对象：80/10/10 预检查得到 train 487、val 61、test 61，对象分别 782、84、116。
- 合并类别后为 1 类、982 个对象；排除二维码标注后保留 609 张样本、419 个对象。预检查不改变来源版本。
- 比例合计错误阻止继续；不存在的 capture_group 值返回失败并可返回配置。跨划分重复检查实际读取文件计算 SHA256；无法读取的文件阻止创建。
- 真实创建 v2：dataset-version-1114e51e4788。浏览器进入 v2 后核对 609 张、982 对象、2 类和 487/61/61；再核对 v1 仍为 520/未配置/89，源数据未改变。
- 51 项数据集前端测试、11 项后端计划／任务集成测试、ruff 和最终生产构建通过。浏览器最后仅保留开发编辑中产生的旧 HMR 日志，最终页面及构建正常。Vite 仍有既存的大分块体积提示。

截图保存在已忽略的 verification 目录，本地保留、不纳入 Git。测试结论覆盖上述类型、状态与数据，不扩展为全部任务类型或全部数据集页面验收。本轮无尚未修复的 P0/P1/P2 问题。后端、Worker 和推理守护进程按用户要求保持运行。

### 创建新版本输入与步骤条修正（2026-11-16）

final result: passed（本次输入宽度及步骤状态范围）

按现有导入组件修正重新划分：复用 field--compact，比例输入固定 80 × 28 px，随机种子固定 110 × 28 px，不再随整行拉伸；保留标签、百分号及组间间距。步骤条复用 dataset-steps 的 is-active / is-complete 状态和主题颜色，完成步骤显示 Check 图标及绿色连接线，待开始使用中性背景与文字，去掉灰底白字的独立实现。此处按最新用户要求使用已有组件状态，优先于原图中的灰色完成序号。

浏览器核对亮暗配置、检查状态及 1024 × 768，无横向溢出；实测比例宽度均为 80 px，种子为 110 px。最终 TypeScript 检查通过。本轮无后端行为变化，没有额外创建版本。

[配置实测](docs/design/frontend/verification/derive-20261116/compact-controls/config-light.jpg) · [暗色检查步骤](docs/design/frontend/verification/derive-20261116/compact-controls/review-dark.jpg)。

### 创建新版本分组字段修正（2026-11-16）

final result: passed（分组字段布局与输入交互）

对照配置原图中的字段／控件／辅助文本关系，修正分组区：标签与随机种子同行，统一 28 px 控件高度；自定义输入及说明与下拉框左边界对齐，不再跨到标签下方。1024 px 亮暗实测无横向溢出，种子和下拉框的顶部坐标一致。

自定义字段为空或包含不允许的字符时显示明确提示并阻止继续，不再以不分组提交。切换 capture_group、不分组、自定义字段及保留原划分后返回，保留自定义草稿；历史任务恢复时同步恢复自定义模式。分组结果仍由实际预检查确认，不在配置页声称元数据字段存在。浏览器验证空值、空格、有效字段、选项往返和划分方式往返，TypeScript 与 diff 检查通过。没有提交新的检查或创建任务。

证据：[亮色自定义布局](docs/design/frontend/verification/derive-20261116/group-field/custom-light.jpg)、[暗色自定义布局](docs/design/frontend/verification/derive-20261116/group-field/custom-dark.jpg)、[空值阻止继续](docs/design/frontend/verification/derive-20261116/group-field/empty-custom-light.jpg)。

### 创建新版本移除分组配置（2026-11-16）

final result: passed（本次页面范围）

按最新确认移除创建页分组配置、草稿及空值校验，重新划分提交空 group_key。检查页同步删除分组完整性卡片，保留跨划分重复候选，改为单列，不保留空的半栏。后台分组接口与算法不变。历史分组预检查需要重新检查，避免混用不同划分方式的凭据。

真实 609 样本预检查 task-7008faef2a705bfdab90e66ae385cfaa 成功：样本划分 487/61/61；本轮未创建新版本。6 项前端回归覆盖默认空分组提交、历史凭据阻止复用、检查报告数据。亮暗配置页／检查页、1024×768 均核对，横向无溢出，滚动后底部操作可达。

截图：[配置亮色](docs/design/frontend/verification/derive-20261116/sample-split/config-light.jpg)、[配置暗色短屏](docs/design/frontend/verification/derive-20261116/sample-split/config-dark-1024.jpg)、[检查亮色](docs/design/frontend/verification/derive-20261116/sample-split/review-light.jpg)、[检查暗色短屏](docs/design/frontend/verification/derive-20261116/sample-split/review-dark-1024-actions.jpg)。本次产品范围调整覆盖原设计中的分组项，其他布局沿用已核对方案。

### 类别与划分、质量检查、版本与来源复核（2026-11-16）

final result: passed（本轮三个页签的布局、现有能力与交互范围）

逐张查看六张源图及对应中文规格，先保存当前开发页面，再修复并重新截图。字体沿用本地 Noto Sans SC，表格、按钮、行菜单及抽屉复用现有 Vue 组件。截图中的侧栏保留用户的折叠状态，名称、计数和日期使用真实数据，不写入设计样例数值。

| 页面 | 设计参考 | 最终亮色 | 最终暗色 |
| --- | --- | --- | --- |
| 类别与划分 | generated/数据集/类别与划分-亮色.png、类别与划分-暗色.png | [亮色](docs/design/frontend/verification/dataset-tabs-20261116/categories-light.jpg) | [暗色](docs/design/frontend/verification/dataset-tabs-20261116/categories-dark.jpg) |
| 质量检查 | generated/数据集/质量检查-亮色.png、质量检查-暗色.png | [亮色](docs/design/frontend/verification/dataset-tabs-20261116/quality-light.jpg) | [暗色](docs/design/frontend/verification/dataset-tabs-20261116/quality-dark.jpg) |
| 版本与来源 | generated/数据集/版本与来源-亮色.png、版本与来源-暗色.png | [亮色](docs/design/frontend/verification/dataset-tabs-20261116/lineage-light.jpg) | [暗色](docs/design/frontend/verification/dataset-tabs-20261116/lineage-dark.jpg) |

修复及复核结果：

- 类别表原先受通用资源面板的负边距影响而贴边；现在恢复内部留白、表头底色、分隔线和合计行。未配置划分的对象数量显示“—”，实际 0 保留为 0。条码数据验证 barcode 419 图像/419 对象、qrcode 190 图像/563 对象，合计仅计算 982 对象。查看 qrcode 后样本页筛选正确，总数 190。
- 质量页按显示检查项统计已检查、待复核和未检查，不再只显示样本数及问题数。状态、带图标的操作、表头和中性说明区统一；类别通过时可查看分布，重复项可查看候选，报告过期时抽屉也明确提示。请求失败可重试，明细截断时不将已保留明细数冒充完整受影响样本数。
- 版本表补全当前版本比较入口及各行更多操作，圆形选择按钮支持键盘并保留页签切换。真实 v1/v2 切换后统计及来源同步更新；v1 行创建导出准确预选 v1；当前版本比较进入选择界面且没有默认比较自身。来源摘要改为右侧折叠箭头，ZIP 名称与格式保持间隔，导入信息和版本创建信息分别使用真实时间。源记录缺失时无失效链接，存在时跳转到对应导入详情。

真实后台验证：

- 条码 v2（dataset-version-1114e51e4788）：质量任务 task-a2a6945b5d0954469139f45d9c223592，609 样本、0 问题，显示已检查 4 项、待复核 0 项、未检查 1 项。检查前的未检查状态、完成状态和人工说明抽屉均核对。
- PCB v3（dataset-version-2a8a323504c4）：质量任务 task-596a82df1409536d98bdfcef9d6e604a，2,636 样本、1,318 条完全重复提示。显示已检查 4 项、待复核 1 项、未检查 1 项；报告只保留 200 条明细，抽屉完整问题数仍为 1,318，候选图片可打开。[亮色待复核](docs/design/frontend/verification/dataset-tabs-20261116/quality-warning-light.jpg)、[暗色待复核](docs/design/frontend/verification/dataset-tabs-20261116/quality-warning-dark.jpg)、[候选预览](docs/design/frontend/verification/dataset-tabs-20261116/quality-candidate-light.jpg)。两次检查均未修改样本或创建新版本。
- PCB v1 来源链接指向追加导入记录 dataset-import-d9046b0337c5，提交时间 2026-11-10 20:35，与详情一致；版本初建时间仍为 17:03，二者不混用。[真实导入来源](docs/design/frontend/verification/dataset-tabs-20261116/source-import-dark.jpg)。

1024×768 六张配对截图全部实际检查：
[类别亮](docs/design/frontend/verification/dataset-tabs-20261116/categories-light-1024.jpg) / [类别暗](docs/design/frontend/verification/dataset-tabs-20261116/categories-dark-1024.jpg)，
[质量亮](docs/design/frontend/verification/dataset-tabs-20261116/quality-light-1024.jpg) / [质量暗](docs/design/frontend/verification/dataset-tabs-20261116/quality-dark-1024.jpg)，
[来源亮](docs/design/frontend/verification/dataset-tabs-20261116/lineage-light-1024.jpg) / [来源暗](docs/design/frontend/verification/dataset-tabs-20261116/lineage-dark-1024.jpg)。无页面横向溢出，短屏允许正常纵向滚动，操作未被裁切；暗色图标无白色外圈。最终恢复亮色与默认视口，浏览器当前页无控制台错误。

最终验证：22 个数据集测试文件、56 项测试通过；TypeScript 和生产构建通过。Vite 仅有既存大分块提示。测试覆盖计数语义、未配置划分、正确类别 ID、行版本操作、保留页签、部分检查、过期及截断报告、读取失败重试、查看分布事件。截图保存在已忽略的 verification 目录；本轮未在根目录 .tmp 新增临时产物。后端、Worker 和推理守护进程保持运行。

能力边界：本轮不增加新的质量算法。现有完全重复与类别引用检查不能宣称已实现设计样例中的近似重复检测或人工语义判断；页面保留真实能力名称及未检查说明，不虚构结果。历史数据缺少导入者或原导入记录时不补造这些字段。本轮 UI 范围没有遗留的阻断问题，此结论不表示整个平台或尚未实现的算法已验收。

## 2026-11-16 版本比较与任务进度核对

final result: passed（版本比较前端范围）

参考：`generated/数据集/版本比较-亮色.png`、`版本比较-暗色.png` 及同名规格。按左右版本选择、并列版本统计、差异类型按钮组、四行分页表、类别对比和划分对比逐区核对。保留项目现有导航尺寸、字体和公共组件；真实样本、版本号、时间及数量不替换为设计图的工业零件示例。记录缺少创建者时不伪造。

第一轮发现与修复：
- P1：比较仍使用通用任务报告，185 条差异一次性铺满页面，缺少版本摘要和两个统计对照。新增专用比较视图，使用共用 Select、SegmentedButtonGroup、ResourceTable、PaginationControls、Button。
- P1：原生 progress 产生深色轨道，未知进度无明确表现。复用 TaskProgress，使用既有亮暗进度色板、7px 圆角轨道；未知百分比使用无百分比的等待动画，尊重减少动效设置。创建版本等共用结果页同步修正。
- P1：差异的查看入口需要按所属版本定位。移除样本打开左版本，其余打开右版本；请求只补充当前页四条样本详情，失败显示不可用并可重试。
- P2：第一次渲染的分页区多套一层边框，下方统计表行高偏大，暗色表头偏亮。第二轮移除分页外框、调整统计表行距及主题表头颜色，再次截图核对。
- P2：未配置 val 到已配置 val 的正向变化未使用增加颜色；已修正并补充断言。未配置值仍显示破折号，不伪造为 0。

实际浏览器验证：
- 原任务 `task-3893a568b7405171967b8392784530ae` 已完成：v2 → v1，609 张、982 个对象，185 张修改、0 新增、0 移除。
- 新运行 v1 → v2 比较，最终任务 `task-db397a3f47a254c185feeed6a7083452`：185 张修改；train 520 → 487（-33）、val 未配置 → 61（+61）、test 89 → 61（-28）。类别 barcode 419、qrcode 563 对象保持一致。反向任务 `task-1f3afcefd46054aeb00bf1d245e3f0d0` 的增减方向正确反转。
- 全部/修改筛选、下一页、空的新增筛选均核对。四条每页，共 47 页；筛选切换重置页码。
- 查看第一条 barcode107.jpg，实际进入右侧 v2，显示 val、1600×1200、1 对象，与表格一致。浏览器返回后可恢复比较任务。
- 1672×941 亮暗截图与源图放在同一比较输入中核对；数据不同，未声称样例内容逐像素相等。1024×768 亮暗短屏无页面横向溢出，底部对照表正常纵向滚动。运行状态保留两边版本摘要，不只剩一条进度条。
- 本轮没有操作后端、Worker 或推理守护进程；后端由用户管理。本次不需要重启后端。

截图：`docs/design/frontend/verification/compare-20261116/`（忽略目录）。`result-light.jpg` / `result-dark.jpg`、`result-light-1024.jpg` / `result-dark-1024.jpg`、`running-light.jpg`、`progress-dark-1024.jpg`、`empty-light.jpg`、`sample-target-light.jpg`。最终恢复亮色、收起导航和默认视口。

验证：数据集 23 个文件 60 项测试通过；共用任务反馈组件 5 项测试通过；后续颜色修正的比较组件 4 项复测通过。TypeScript 与生产构建通过；既有大分块提示仍在。浏览器控制台无错误。未新增根目录 `.tmp` 产物。

边界：现有接口最多保留前 200 条差异明细，页面明确说明筛选分页只覆盖保留明细，而上方计数覆盖全部差异；本轮未改变后端 API 或比较算法。读取失败、竞态丢弃、报告截断及未知进度以组件测试验证，没有人为破坏真实版本来构造错误。历史任务明细与当前样本读取并非同一快照，检测到来源 revision 变化时提示重新比较。

### 样本与版本返回路径补充验证（2026-11-16）

- 修复页面内“返回”只关闭跨页预览的问题；来源通过历史状态保存，刷新后仍可返回原任务。比较页“查看版本”应用同一返回约定。版本内预览关闭仍停留当前版本。
- 真实任务 `task-db397a3f47a254c185feeed6a7083452` 选择“修改”、第 2 页，打开右版本的 `barcode196.jpg`（test、1 对象）。页面返回后仍为同一任务、修改筛选和第 2 页；刷新样本页后返回同样通过。查看 v2 → 版本内预览 → 关闭 → 版本页返回，也回到原比较页。
- 独立标签页直接打开同一样本，返回后清除 `sample`；刷新不再重新弹出预览。质量任务共用入口和同版本前进后退通过组件回归测试。
- 1024×768 亮暗主题真实返回通过，截图为 `docs/design/frontend/verification/compare-20261116/return-light-1024.jpg`、`return-dark-1024.jpg`。恢复亮色、默认视口，关闭本轮临时标签页。控制台无错误。
- 数据集全量 23 文件、65 项通过；补充查看版本返回后，相关 2 文件、11 项复测通过。TypeScript、生产构建、diff 检查通过；仍有既有大分块提示。本轮未创建根目录 `.tmp` 产物，未操作后端服务，无需重启后端。

### 样本与清理确认补充核对（2026-11-16，未完成全量验收）

- 分类真实样本 `pcbtrayslot_small_20261109` v3 的抽屉补充类别目录、任务类型、标签数量和当前标签，使用实际类别及标注；缺少标注来源时保留空值。浏览器核对 1024×768 亮暗主题。
- 在 `3570托盘` v1 真实导出记录中核对清理确认：补充格式、文件名、大小和清理后无法下载的说明，未执行清理。未伪造设计图中的外部引用检查结论。
- 列表跨页签加载时隐藏上一页的数据；失败导出中的缺失文件错误显示可读提示，原文保留在原始报告。数据集前端 23 文件、68 项通过。其他各类样本、删除与清理确认及异常状态尚未逐图核对，本轮不能认定全部设计完成。

### 版本删除确认补充核对（2026-11-16，未完成全量验收）

- 根据版本删除设计图补充被删除的数据集名称、版本号、图片和标注对象数量，以及不可恢复和外部引用阻止删除的说明。数量来自版本列表响应；不编造导入、导出记录数，也不预先声称引用检查已通过。
- 在真实 `dataset-barcodeqrcode-20261022160700` v2 上核对 609 张和 982 对象，亮暗 1024×768 显示正常；导入记录删除确认也核对了真实文件名及保留范围。未执行删除。
- 当前项目按实例分割、关键点、旋转框、异常、连接器、RGB-D、点云筛选均为空，无法用现有真实版本完成这些预览的浏览器验证。截图：`docs/design/frontend/verification/dataset-remaining-20261116/`。未完成全部设计图及异常分支验收。

### 补充样本预览验证（2026-11-16，未完成全量验收）

- 使用本地工业图像和项目测试夹具中的示例标注，经导入向导创建独立 `ui-qa-segmentation`、`ui-qa-pose`、`ui-qa-obb` 和 `ui-qa-anomaly` 数据集；说明注明用于 UI 验证，标注不是生产真值。异常区域为合成掩膜。
- 分割多边形为 1 个轮廓、4 点；关键点为 (10,16) 可见和 (40,48) 遮挡；旋转框顶点为 (10,10)、(40,10)、(40,30)、(10,30)，页面与输入一致。异常样本显示区域真值和预测未载入；亮暗 1024×768 截图保存在本地 verification 目录。
- 分割预览不再将外接框叠加在分割轮廓上。设计图的轮廓、填充、透明度独立控制目前仍未实现；连接器、RGB-D、点云及删除清理的全部失败分支尚未逐项复核，因此不能认定数据集 UI 全部完成。

### 分割与多媒体样本补充验证（2026-11-17）

- 分割大图提供轮廓、填充和填充透明度独立控制，多边形和 COCO RLE 均可绘制；加载期间禁止修改，重绘保留缩放。测试数据的多边形经浏览器核对，RLE 绘制及控制组合通过组件测试。
- 经正式导入创建 `ui-qa-connector-reference`、`ui-qa-rgbd`、`ui-qa-point-cloud`，均注明测试来源：连接器针位与 2.54 mm 节距为合成设计值，独立实测参考未提供；RGB-D 深度为 200–1000 mm、配准状态未知；点云为 900 个合成有效点。1024×768 亮暗预览和信息抽屉截图保存在 `docs/design/frontend/verification/dataset-media-20261117/`。抽屉展开时缩窄主要预览，避免点云及 RGB-D 被遮挡。
- 隔离后端测试覆盖导入后删除、文件被占用、下载期间删除及取消下载等场景；前端测试覆盖删除和清理请求失败。未对现有用户数据执行删除。数据集前端 23 文件、75 项通过，后端相关测试 7 项通过，TypeScript 检查通过。
- 导入详情缺少包路径时不再因字符串操作报错；补充回归测试。三次实际导入均可打开详情；此前偶现的路由上下文异常没有稳定复现，不能断定已解决。
- 合成样本不代表生产测量数据；上述结果不等于对所有类型、数据集页面及异常情况完成全量验收。自动策略拒绝删除本轮两个 `.tmp` 测试目录，保留原状。

### 生成样本及异常状态复核（2026-11-17，未完成全量验收）

- 使用内置图像生成工具制作六张工业场景图，分别导入 `generated-ui-segmentation-rle`、`generated-ui-pose`、`generated-ui-obb`、`generated-ui-anomaly`、`generated-ui-connector`、`generated-ui-rgbd`。工具未提供可确认的模型版本。生成提示词、原图、合成标注构造脚本及 ZIP 位于 `docs/design/frontend/verification/dataset-generated-20261117/`。其中深度为示意值，关键点、旋转框、PIN 和异常区域是估计值，不用于训练或测量。
- 实际导入并预览 COCO RLE 圈形密封件、三关键点夹具、旋转框零件、划痕掩膜、四 PIN 连接器以及 RGB/合成深度。RLE 保留孔洞；点位和框与图中对象位置一致。六类均有 1024×768 亮暗截图；样本图与源图不同，截图本身不能证明全部布局与交互一致。
- 对照参考图补充关键点编号与可见/遮挡颜色、旋转框四顶点编号、分割复选框；异常预览独立显示未载入的预测图层；RGB-D 复用按钮组切换视图并提供缩放比例和图像尺寸标识。RGB-D 的单深度、并排和缩放，异常原图/真值切换已在浏览器操作。
- 删除或清理请求被拒绝时保留确认对象及原因；连接中断等结果未知时提示先刷新并阻止对当前确认框重复提交。版本删除被引用时隐藏执行按钮。组件测试覆盖 409 依赖阻止、网络结果未知，以及导入详情读取失败后刷新恢复；实际浏览器核对不存在的导入记录，提示和刷新操作可见。未执行不可恢复的真实数据删除。
- 导出清理的数据库提交会先使文件不可下载，再异步清理磁盘；记录详情、历史文件和列表根据清理任务状态区分“清理待完成”“已清理”和“状态待确认”，不能只凭不可下载就宣称清理完成。相关组件及状态回归连同数据集测试共 25 文件、92 项通过，TypeScript 检查和生产构建通过，构建仍有既有大分块提示。
- 六次真实导入提交均进入导入详情，控制台未见相关错误；此前偶发的路由上下文异常未复现、根因未确认。`review-matrix.md` 按本机 113 张 PNG 列出本轮状态；除已明确查看的样本参考外，大部分图仍待逐张核对，不能认定数据集全部完成或开始模型页面实施。
- 使用故意损坏的图片包 `invalid-image.zip` 通过向导提交，得到真实失败记录 `generated-ui-invalid-image`；详情显示图片无法解码且未生成版本。修复失败结束时间误落在待处理的生成版本步骤，失败步骤和页面摘要改为显示失败时间；亮暗 1024×768 截图已保存。
- 版本删除遇到服务端返回的依赖清单时，确认框显示阻止原因及实际返回的资源类型、身份和状态，不显示删除按钮；未返回的资源名、链接和状态不补造。真实浏览器检查新测试版本的删除确认后取消；依赖阻止由组件测试注入实际契约形状验证。由于服务端没有独立只读预检接口，此处不提供会意外执行删除的“重新检查”按钮。
- 分类大图保留原图，不叠加类别浮层；标题显示标签数，详情入口改为样本信息。使用真实 `3570托盘` v1 样本核对标签目录、当前标签及亮暗短屏。

### 列表和版本失效状态复核（2026-11-17，未完成全量验收）

- 对照列表与资源状态亮暗设计图，补齐首次为空和筛选无结果时的表头、操作入口；真实数据列表中验证搜索无结果和清除筛选恢复，亮暗及 1024×768 截图位于 `docs/design/frontend/verification/dataset-audit-20261117/`。首次空状态使用组件测试验证，未清空用户数据。
- 同一查询刷新失败时保留上次结果，提示数据时间和重试；筛选条件变化后请求失败则清除旧查询结果，避免误认为符合当前条件。失败分支使用组件测试注入，尚未做真实断网截图。
- 版本接口返回 404 或 403 时展示对应状态和返回版本列表入口，切换版本失败不残留其他版本内容。使用不存在的版本地址实际验证 404、返回导航及亮暗短屏；403 使用组件测试验证。
- 数据集及相关资源前端测试 25 文件、97 项通过，TypeScript 检查和构建通过。清单中的其他设计图与异常分支仍需逐项核对；此前偶发的导入详情路由上下文异常仍未确认根因，暂不认定数据集 UI 已全部完成。

### 导入详情与特殊样本复核（2026-11-17）

- 将 2026-11-10 已逐图核对的 33 张导入导出设计图关联至原始验收记录；原有亮暗截图及实际操作不重复执行，后续只对受修改影响的状态补查。
- 导入和导出详情在主记录返回后立即结束刷新状态；名称及来源版本独立加载，不阻塞主记录和任务轮询，切换记录时丢弃过期的附加结果。慢请求及跨记录切换由组件测试验证。浏览器从列表进入成功和失败记录、刷新并返回，核对实际信息；成功记录补充 1024×768 亮暗截图。
- 样本网格中标有“查看”的图片区域支持单击打开预览，键盘和卡片双击入口保留。使用已导入的合成 RGB-D 和点云测试数据验证单击、深度／并排切换、点云俯视与正交及样本信息；深度和点云为合成数据，不作为现场测量真值。
- 点云、RGB-D 等特殊样本版本删除确认使用“样本”计数，不误称为图片；使用点云测试版本验证 1024×768 亮暗确认后取消，没有删除数据。依赖阻止与清理失败依旧由组件及隔离后端测试覆盖；没有人为破坏用户数据构造生产故障。
- 截图位于 `docs/design/frontend/verification/dataset-followup-20261117/`。数据集及相关资源前端测试 25 文件、100 项通过，TypeScript 检查通过；本次没有启动或停止后端。

### 特殊样本和清理确认补充（2026-11-17）

- 使用开发服务中已导入的合成样本复核连接器针位开关、异常原图／真值切换与对象信息、分割 RLE 轮廓及填充透明度、关键点和旋转框顶点。图像与坐标用于界面测试，不作为现场测量真值。
- 异常和连接器信息抽屉补充实际图像尺寸，异常信息补充任务类型；修正旋转框顶点表首列表头在短屏被截断。截图保存在 `docs/design/frontend/verification/dataset-followup-2-20261117/`。
- 在实际导出记录中核对 1024×768 亮暗清理确认的文件名、大小和保留范围，均取消操作；新增清理重试仍失败时保留错误和待清理状态的测试，没有对用户文件执行清理。

### 点云方向与删除范围补充（2026-11-17）

- 点云视图内显示原始高度范围、单位与蓝到红色标；等高数据使用单一绿色。坐标轴根据相机方向投影，在俯视、正视、旋转和切换投影时更新；单色模式隐藏高度色标。使用已导入的 900 点合成样本在开发服务核对亮暗 1024×768、俯视和着色切换；截图位于 `docs/design/frontend/verification/dataset-cloud-20261117/`。
- 删除版本确认补充关联导入、导出记录及任务也会删除的说明；依赖来自 Workflow 快照时显示服务返回的快照路径。实际页面核对亮暗短屏确认后取消；完整确认组件测试注入后端 409 契约并验证阻止删除。只读预检现有测试版本没有依赖阻止，未触碰业务数据构造 409。
- 清理失败、重复重试与恢复沿用隔离后端和前端组件测试，实际页面复用了上一轮亮暗清理确认截图；本轮没有人为锁定或清理现有用户导出，故未生成真实清理失败页面截图。
- 最终数据集、资源删除和点云相关前端测试 28 文件、132 项通过，1 项需要 `AMVISION_I2_DISPLAY` 的点云证据测试跳过；TypeScript 检查及生产构建通过。没有启动、停止或重启后端。

### 模型场景 26、版本来源、模型包与目标检测评估（2026-11-18）

- 场景 26 在 TensorRT 10.16.1.11 上使用实际 YOLO11 权重。正式转换 Worker 用 5 张 train 图校准，以独立 val 图核对 min 1×3×64×96、opt 1×3×128×128、max 2×3×192×160，最大归一化误差约 0.0000251。已登记并通过文件接口下载 4,281,476 字节的 engine。样本不足由预检阻止，train 和 val 内容重复由 Worker 阻止。
- 开发服务中打开真实模型版本，核对数据集版本、训练完成时间和初始化权重。真实模型包在隔离 Worker 完成生成、下载、同名阻止及改名导入，登记原始权重、ONNX、TensorRT 及来源信息。
- 开发服务中两个 YOLO11 版本分别用同一 test 划分的 61 张图片完成评估。比较页切换基线时，mAP50–95 差值由 +0.0887 切换为 −0.0887。新版样本快照及真实图片读取通过隔离 Worker 验证。
- 1024×768 和 1366×768 下核对亮暗主题的动态 INT8 参数、模型版本来源、模型包导出抽屉和目标检测评估比较。开发环境的 Worker 仍需更新，模型包登记成功态及新版样本标注框仍待开发服务复验。其他任务类型的评估设计尚未验收。

### 模型短屏、数值显示与专项评估（2026-11-18）

- 使用开发库数据，在 1024×768 和 1366×768 的亮暗主题下复核模型版本、训练任务、转换与导入、评估四个列表以及基础模型抽屉，未出现横向溢出。1024×768 另查版本详情、引用和转换来源抽屉。训练列表显示实际 epoch 进度，失败态使用失败颜色。
- 使用真实训练任务核对详情指标 `0.949` 和版本抽屉指标 `0.954`。评估指标显示三位小数；学习率最多四位，极小非零值用科学计数法；毫秒值取整。计算和报告导出仍使用原始精度。
- 真实姿态报告 `task-31af141b0671` 与旋转框报告 `task-09e49426d739` 核对漏检、误检和零结果筛选。专项指标由几何比较生成，测试覆盖关键点偏差、旋转框角度偏差和定位偏差命中。
- 正式 Worker 以真实原图、标签和预计算预测生成语义分割报告 `task-a3bad030321142f2b1cf86545faa6fb4`（mIoU `0.081`）和异常检测报告 `task-833d9440001b416a97b33da722ef30a6`（图像 AUROC `0.273`，像素 AUROC `0.626`）。异常热图由 OpenCV 基线生成；这两条评估链路不直接执行注册模型。用两种短屏和亮暗主题复核样本切换、语义图层、异常热图及失败页。提交不匹配的预测包，实际 Worker 拒绝并在详情展示原因。

### 目标检测错误样本与读取失败复核（2026-11-18）

- 场景 83、90：开发环境使用同一个 61 张图的检测报告核对 39 张问题样本、按类别和文件名缩小结果、漏检仅显示未匹配标注框、无结果状态和图片读取重试。该任务无误检；有误检的过滤和类别配对以隔离 API 测试覆盖。
- 真实旧报告没有保存样本级诊断及框数据，列表失败重试后仍可预览原图，界面明确提示缺失，快照不改动。两份报告均核对 1024×768、1366×768 和亮暗主题，未发现横向溢出。

### 模型异常与空状态复核（2026-11-19）

- 场景 70：隔离 Worker 使用 Barcode 数据集中的实际样本生成部分成功报告。开发页面核对文件缺失、解码失败及标注异常，验证补回文件后重试、预览原图、跳到版本样本及下载报告。
- 场景 85：实际 YOLO11 Barcode 权重和 12 张校准图用于 TensorRT INT8 转换。4 张独立验证图和动态输入最小、最大尺寸全部记录数值，超限时阻止产物登记。用实际结果核对失败表、抽屉和诊断下载；后端测试核对项目隔离及失败产物无法作为成功包下载。常规转换的采样输入为生成张量，页面按张量编号展示。
- 场景 88：隔离环境用实际训练权重构造模型包，注入写入失败，核对回滚后的数据库、文件及已有版本的权重校验值。浏览器核对登记失败页、保留 ZIP 时重新检查及 ZIP 过期时重新上传。
- 场景 89：开发库两个空项目验证切换项目、创建训练、导入模型包和返回路径。场景 87：使用开发库既有训练记录及输出文件验证取消确认；在浏览器用受控响应验证继续训练、失败重试及等待执行器确认，实际终止接口用隔离测试复核，未取消开发库任务。
- 上述场景在 1024×768、1366×768 的亮暗主题下复核，未发现横向滚动。全量前端测试 262 文件、1,368 项通过、2 项跳过；生产构建通过。

### 模型场景 86：提交结果待确认（2026-11-19）

- 训练和转换的检查页保留原配置，显示断线提示和查询卡。查询失败时继续禁止重新提交；服务端明确确认原请求未创建任务后才恢复提交。回到列表并刷新后，可以用同一回执查到原任务。
- 隔离 API 测试覆盖两种顺序：先创建时返回原任务编号并拒绝重复创建；先确认未创建时拒绝迟到请求。SQLite 隔离库已验证迁移、降级和重新升级。
- 在开发前端使用真实 YOLOX 源版本及 YOLO11 训练用数据集导出记录，模拟提交断线和查询失败，逐项核对 1024×768、1366×768 的亮暗主题、查询失败仍锁定和确认未创建后恢复，无横向滚动。另以开发库既有转换任务验证列表刷新后打开原任务详情；浏览器故障注入未实际重复创建任务。
- 全量前端 1,368 项通过、2 项跳过；最终界面改动另通过类型检查和训练浏览器复验。当前开发 API 仍在运行旧进程，新接口需迁移后重启，再做开发环境端到端复验。
- 下一项为场景 77、78：版本详情中单独删除转换产物，按部署直接绑定（含已停止的部署）阻止删除。需先明确产物登记和文件的所有权，保留版本、其他产物和训练／转换历史。

### 模型场景 77、78：单独删除模型产物（2026-11-19）

- 版本详情增加转换产物行级删除。确认框显示具体版本、格式、精度和文件名，必须输入首个登记文件名；保留原始训练权重、版本、其他产物、转换报告和任务历史。
- 预检和执行都检查绑定与文件归属。隔离 HTTP 测试及清理 Worker 验证仅删除 OpenVINO XML 和同名 BIN；同一次转换的 ONNX 和报告、训练权重及两个任务保留。预检后新增已停止部署时，提交返回 409，文件和登记均保留；绑定其他产物的部署不影响目标产物删除。
- 开发库只读核对 `model-build-bba72a7b211b`，确有一个仍绑定该 OpenVINO 产物的部署，同步、异步都已停止。浏览器使用此真实模型与实际部署回读核对阻止状态；提交成功和预检后新增绑定用受控响应核对，未发出删除现有产物的请求。部署只读核对与隔离 HTTP 测试分开记录。
- 1024×768、1366×768 的亮暗主题通过：单一整屏遮罩，底层无法操作，无横向溢出；文件名错误禁用确认，晚到的绑定打开引用阻止态，删除受理后仅目标行消失并留在原版本。Browser 插件未在会话中提供，使用 Playwright 和 Chrome。相关前端 15 项，后端删除回归 5 项、最终聚焦复测 2 项及生产构建通过。本轮未修改开发库或重启服务。
- 下一项场景 76、84：目前 ZIP 清理复用记录的 `expired` 状态，会丢失生成成功的展示；若文件在后台更新前丢失，记录仍给出下载按钮。后续分开记录任务状态与 ZIP 可用性，复核失效后按原选项重新生成。

### 模型场景 74–76、84：模型包导出记录与文件可用性（2026-11-19）

- 转换与导入页增加导出记录抽屉，可按模型名、文件名或状态筛选。导出详情分别显示任务状态和文件状态；生成中、失败、文件已清理或缺失时禁止下载。失败提示不暴露系统异常及本地路径。
- 隔离 API 和后台消费者使用开发库 OpenVINO 产物的真实 XML（132,231 字节）与 BIN（21,762,288 字节）完成导出与下载。测试覆盖截断和缺失拒绝下载、到期清理后保留完成状态及摘要、兼容旧回执、按原选项创建新导出、源 BIN 缺失导致生成失败。没有改动开发库或原文件。
- 浏览器在开发前端使用隔离 API 真实回执核对 1024×768、1366×768 的亮暗主题；生成中和点击下载时突然丢失用受控响应。验证筛选、返回保留筛选、重新生成请求复用原选项、失效后关闭下载入口，抽屉无横向滚动，底层不可操作。Browser 插件未在会话中提供，使用 Playwright 和 Chrome。
- 相关前端测试 13 项、隔离后端导出与导入回归 2 项、类型检查及生产构建通过。新行为需要开发 API 和处理模型包的 Worker 更新后生效；本轮未重启服务，无新增数据库迁移。

### 模型场景 8、30–33、72–73：模型包导入检查与登记（2026-11-19）

- 文件页明确目标项目；检查页分别呈现可确认的归档、路径、结构和输入信息。未选择目标时不会冒称资源无冲突。CRC 错误只公开包内文件路径，保留更换文件和复制错误信息，禁止进入下一步。
- 类别对照包括两侧所有索引，缺项注明；冲突禁止追加，必须选择新建独立模型并复检，或返回更换文件。登记结果及详情区分目标项目、登记版本、来源包版本及登记时间，并可查看已登记产物和跳转版本；不把登记等同部署或现场文件可用性。
- 隔离 API 和后台消费者使用开发库的实际 OpenVINO XML、BIN 文件构造两份有意改变类别顺序的测试包。实测 CRC 损坏、类别冲突拒绝提交、同类别追加成功、新建独立模型成功。记录删除在文件占用时返回 409 并保留原记录，解除后删除暂存文件；三个已登记版本及各自文件均保留。
- 浏览器在开发前端用隔离服务真实回执测试，覆盖 1024×768、1366×768 的亮暗主题。验证错误复制、选择新包、差异表和禁用状态、重新检查、登记详情、取消及确认删除记录；无横向溢出。实际导入和删除在隔离环境执行，浏览器没有修改开发库。Browser 插件未在会话中提供，使用 Playwright 和 Chrome。
- 后端相关回归 18 项通过，补充追加分支和文件锁后聚焦测试通过；前端相关测试 13 项、类型检查和生产构建通过。本轮未重启开发 API 与 Worker，无新增数据库迁移。
- 下一项重点为场景 56：现有模型目录在刷新失败时用整区错误替换已成功加载的列表；按设计核对断线保留上次结果、保持筛选，以及只读和重试边界。

### 模型场景 56：筛选、刷新、断线与只读（2026-11-19）

- 模型目录保留当前条件的最后一次成功结果。刷新显示局部进度，断线标注更新时间并提供重连；浏览器恢复连接只重读目录，不重新提交任务。项目、账号、筛选或页码不匹配时不混用旧行，权限拒绝时清除旧结果。
- 筛选无结果保留关键词并提供清除入口，不显示空分页。只读账号可打开版本详情，训练创建、版本删除和模型包导出操作禁用；有写权限但列表断线时，旧列表不提供编辑操作。
- 训练与转换任务列表各自刷新与记时，不因另一个接口慢或失败而丢弃本列表已读结果。开发环境模拟训练读取失败，转换仍展示真实转换记录，切回时仍可读取。
- 真实开发库模型用于 1024×768、1366×768 亮暗复核。受控响应模拟断线和只读权限；验证加载保留行、断线、重连保持搜索、无结果与清除、只读查看，未提交训练或转换，无横向滚动。Browser 插件未在会话中提供，使用 Playwright 和 Chrome。
- 模型相关前端 23 文件、179 项测试通过，生产构建通过。本轮只改前端，无需迁移或重启 API。
- 下一项重点为场景 58：版本详情当前的操作按钮随内容滚动，尚未提供按当前版本进入转换和部署的路径。需接上真实支持的入口，再验证短屏独立滚动、固定底部操作与只读边界。

### 模型场景 58：短屏版本抽屉（2026-11-19）

- 版本抽屉正文独立滚动，页脚保持可见；已有说明超过两行时可展开。转换入口核对所选版本的权重和类别信息，部署入口只列出当前版本已登记的转换产物。继续沿用现有转换和部署表单，由操作者确认配置和提交。
- 用开发库中的真实分类模型 `model-273c16c1cc3f` 核对：转换带入 `model-version-d6641a11124f`，部署选择该版本的实际产物 `model-build-dbbad4b4b922`。模拟权重缺失时停留在抽屉并显示原因；其他项目的入口不会载入模型。验证覆盖 1024×768、1366×768 的亮暗主题，正文滚动时页脚位置固定，无横向滚动，也未创建任务或部署。
- 模型和部署相关前端 25 文件、207 项测试通过，生产构建通过。Browser 插件未提供，使用 Playwright 和 Chrome。

### 模型场景 59：短屏错误样本预览（2026-11-19）

- 错误样本打开独立查看页，包含上下张、标注与预测开关、缩放及适应窗口。对象信息为可关闭的非模态浮层，显示当前框的匹配状态、数据划分和报告的评分阈值；漏检预览只叠加 GT 框。
- 上下张跨列表页时沿用当前筛选。读取下一页失败保留当前图片和位置，可再次切换。返回评估详情后保留筛选、页码并聚焦当前样本。旧报告只展示已有数据，图片读取失败可重试。
- 开发库报告 `task-f866f7152e47` 的 39 张真实漏检样本用于浏览器核对，以 `barcode201.jpg` 实测第 12 和 13 张的跨页切换、异常恢复、缩放与浮层开关。1024×768、1366×768 亮暗主题均无横向滚动，无遮罩，原图保持原亮度。复跑旧报告、图片失败及筛选无结果场景通过。

### 模型场景 60、61：ONNX 和 OpenVINO 参数（2026-11-19）

- ONNX 参数展示受支持的 Opset、只读 FP32、输入名和动态维度。YOLO11 目标检测的普通 ONNX 支持动态批次，宽高沿用源模型。OpenVINO 将 FP16 标明为权重压缩，显示配对的 XML、BIN 产物与 Worker CPU 校验环境。OpenVINO 转换目前提供 FP32 和 FP16。
- 实际 YOLO11 训练版本 `model-version-f553108fc2ba` 的 Opset 19、动态批次及 OpenVINO FP16 均通过开发服务预检。两种短屏的亮暗主题核对了 Opset 控件宽度、固定底部操作和无横向滚动。浏览器运行到预检完成，未新建转换任务。
- 全量前端 262 文件，1,372 项测试通过，2 项跳过。生产构建通过。

### 模型场景 63：训练参数的任务规则（2026-11-19）

- 参数页按当前任务显示规则。分类沿用导出类别顺序和训练后端的 Top-1 主指标。实例分割独立编辑掩码损失权重。姿态从 YOLO 导出清单或 COCO 导出读取关键点，也可显示所选数据集版本已有的骨架资料。OBB 显示实际角度约定，并复用数据增强开关与旋转角度。
- 以四份真实训练导出验证浏览器送出的预检。分类使用三类导出顺序，COCO 姿态读取 21 个关键点，分割权重 2.5 和 OBB 旋转 ±13° 被送入真实服务。四类均通过预检，覆盖 1024×768、1366×768 的亮暗主题，无横向滚动。自动化测试覆盖切换导出时丢弃旧响应、读取失败重试和截断的预览。

### 模型场景 64：转换目标环境阻止（2026-11-19）

- 转换目标页展示可用格式。查看不可用目标的要求时，区分目标格式、执行环境和适配器条件，禁用下一步，并保留上一次可用选择。返回后焦点回到该格式。CoreML 和 ARM NPU 的环境要求分别对应 Apple 校验环境和芯片厂商工具链。
- 使用真实 YOLO11 版本 `model-version-f553108fc2ba` 验证 CoreML、ARM NPU 阻止及返回 ONNX，通过服务预检。1024×768、1366×768 的亮暗主题下操作可见，无横向滚动。Browser 插件未提供，使用 Playwright 和 Chrome。

### 模型场景 65：创建训练的预检阻止（2026-11-19）

- 预检分项报告数据导出、初始化权重、输出模型名称和执行环境。检查清单及必需文件和目录；初始化权重有登记的 SHA-256 时检查摘要。执行环境的状态始终明确由 Worker 确认。检查失败可展开缺失路径、返回对应步骤或重新检查，保留草稿并禁用提交。
- 在隔离 API 复制开发库的 COCO 导出 `dataset-export-5515e019b157` 和 YOLO11 基础模型权重 `mv-pretrained-yolo11-detection-s`。验证集标注文件缺失和权重摘要变化同时得到两项失败；还原两个文件后预检通过，任务列表保持为空。
- 开发前端使用隔离 API 的实际响应检查 1024×768、1366×768 的亮暗主题。展开缺失文件、返回数据及初始化、保留草稿、重新检查和提交禁用均通过。浏览器使用 Playwright 和 Chrome。

### 模型场景 66、67：取消训练状态与恢复检查（2026-11-19）

- 取消状态显示中性进度、已完成轮数、真实时间和版本登记情况。恢复检查改为右侧模态抽屉，展示训练进度、检查点、原数据集以及已验证的条件。已取消的任务可查看阻止原因。
- 使用开发库的失败任务 `task-a3dd070bb78b` 验证检查点缺失时禁止恢复，重试走开发服务并通过预检。使用真实训练快照验证取消的界面状态。两种短屏的亮暗主题均检查抽屉遮罩、收起后焦点回归、禁用状态与无横向滚动。隔离 API 测试覆盖缺失恢复检查点、文件恢复后预检通过及 Worker 继续训练。
- 场景 66 的取消详情显示中性进度、精简的配置摘要、已保存的训练与验证曲线。输出区可切换已有文件、任务事件和原参数。运行日志页使用任务事件记录，训练接口当前未登记独立日志文件。
- 已取消、失败及完成的训练可按原配置打开可编辑向导。复用模型规格、原数据导出、初始化权重、输出模型系列及训练参数，提交使用一次新的训练请求。原数据失效时要求重新选择，异项目记录无法带入。
- 开发前端使用真实姿态 `task-70ca1c09a3f2` 和分类 `task-b4ee915e0f7a` 验证券重、输入尺寸、批次、增强和轮数。两种短屏亮暗主题下修改轮数后实际预检通过，关闭草稿并刷新回到训练列表，全程未提交训练。取消布局使用同一批真实数据模拟任务终态，覆盖文件、日志和参数三个标签及无横向溢出。
- 分类旧记录的完成轮数由已保存的轮次记录补齐。训练图的纵轴刻度最多保留四位小数，指标提示保留三位，修复刻度序号被误用为小数位数的问题。耗时继续以整数毫秒显示。

### 模型场景 68、69：转换校验失败与已取消（2026-11-19）

- 校验失败页显示当前规则、误差、校验总数、通过数和失败数。失败明细支持切换统计、查看张量差异及下载诊断。TensorRT INT8 的动态 profile 会对同一图片做多项校验，总数按实际校验项计算。失败报告使用真实 Barcode 图片和 YOLO11 权重生成的 6 项诊断，浏览器复放这份结果，核对失败阶段与尚未登记的产物。
- 隔离 API 使用真实来源 `model-version-f553108fc2ba` 创建 ONNX 转换并取消排队任务。详情包含取消日志，登记产物为零。对已开始的任务，现有记录可展示总用时；缺少相应阶段记录时标明未记录。旧记录没有单阶段用时。
- 1024×768、1366×768 亮暗主题核对失败、取消、日志与诊断抽屉，页面无横向溢出。两种「按原配置」入口均打开可编辑草稿。ONNX Opset 19 和动态批次在四种组合下完成开发服务预检。TensorRT INT8 在 1024×768 暗色核对动态形状、Workspace 和校准／校验选择恢复，开发服务预检通过。浏览器验收只预检，未向开发库提交转换。

### 模型场景 71：目标检测评估已取消（2026-11-19）

- 取消页使用最后保存的进度。显示实际划分、运行时、样本数量、中性进度、最近三条样本记录和运行日志。取消时最终指标留空，报告及比较不可用，执行记录可下载。旧记录缺少计数时显示空值。
- 用正式评估 Worker 的隔离队列运行开发库 YOLO11 权重 `model-version-f553108fc2ba` 和 Barcode COCO 导出 `dataset-export-3d69efd5184b`。实际取消时已成功 21 张，失败 0 张，尚有 40 张未处理。核对取消后进度冻结、报告 API 返回 404、磁盘未留下报告。另用 API 回归覆盖写入报告之后、完成提交之前的取消及清理。
- 开发前端使用该真实取消回执核对 1024×768、1366×768 的亮暗主题。核对三条样本、下载的执行记录、列表禁用比较、原配置重评及取消草稿。模型、数据、阈值、划分和结果包开关均传到真实开发服务预检。四种组合预检返回 200，无横向溢出。浏览器未提交评估。

### 模型场景 40、41、81：评估比较（2026-11-19）

- 分别核对三组亮暗设计图。双结果显示指标、类别 AP 和类别均值的独立差值列，打开错误样本后恢复原比较与基线。四结果可更换基线、移除非基线列、切换配置和下载 JSON。指标与差值显示三位小数，下载保留报告精度。
- 开发库的四份目标检测报告（`task-e70f4049cba5`、`task-ba41a14002ee`、`task-84101f2ecc10`、`task-f866f7152e47`）对同一数据版本的 61 张测试图评估。浏览器核对 mAP50–95 的 0.243、0.155，基线切换后的 −0.089、+0.089 和 0.000，以及类别 AP 和均值。对比报告读取失败后可重试。
- 隔离 Worker 生成高置信阈值 YOLO11 报告 `task-758a3e7177dd`（61 张）和另一数据版本的 YOLOX 报告 `task-54b7d7d77928`（117 张）。两份报告均记录实际 PyTorch FP32、输入尺寸及预处理契约。开发前端复放报告，核对数据、样本范围、规则、类别冲突及返回时的选择。仅规则不同的重评草稿在开发服务预检通过，类别不匹配时向导提示并禁止进入下一步。
- 开发环境使用 Chrome 核对 1024×768、1366×768 的亮暗主题。双结果、四结果、配置、样本导航、冲突弹窗及重评向导均无横向溢出。开发库原有报告使用 PyTorch 检查点，旧报告缺少的精度和预处理显示为未记录。浏览器核对未提交评估任务。

### 模型场景 2、49、80：版本来源、历史选择与部署引用（2026-11-19）

- 分别核对六张亮暗设计图。版本来源展示已解析的数据集版本、训练完成时间和初始化来源。评估指标优先读取该版本的登记快照，实际 YOLO11 版本 `model-version-f553108fc2ba` 显示 mAP50–95 0.628、最佳轮次 1 / 1。读取训练任务失败时保留指标。最佳轮次只使用明确记录或可唯一对应的验证轮次，无法确定时省略。
- 真实 RF-DETR 系列的最佳检查点 `model-version-c23cb50107d6` 和手动登记检查点 `model-version-cfa30d650925` 来自同一任务。切换时检查两者的来源、产物和指标均按版本更新，手动版本无已保存指标时不继承最佳检查点的 0。历史记录沿用登记 ID 和已保存的检查点类型。
- 真实 YOLOX 版本 `model-version-3720563c7b99` 的两条直接部署引用验证了格式、同步与异步状态及详情跳转。将开发库部署记录复制到隔离数据库后，验证 8 条记录按 6 条和 2 条分两页，通过 API 按名称筛选。复放 API 结果核对失败重试、无匹配结果、返回后总数及焦点恢复。
- Chrome 验收覆盖 1024×768、1366×768 和亮暗主题。引用页从顶部打开，分页与固定关闭按钮在短屏可见，各抽屉无横向溢出。浏览器验收未向开发库写入数据。

### 模型场景 51：产物文件与契约（2026-11-19）

- 对照亮暗设计图，版本抽屉内显示产物格式、精度、文件状态、已记录的数值校验、路径和输入输出契约。复制路径、按需展开 SHA256、下载及返回后的焦点均已核对。按产物格式识别校验记录，OpenVINO 使用自己的运行时校验记录。
- 用开发库 YOLOX 的 ONNX `model-build-10997bfd6559` 和 OpenVINO `model-build-f9e993c0f4e5` 核对实际输入、输出、三类名称及预处理。隔离 API 用原文件复制件验证 ONNX、XML、BIN 的存在性、大小、SHA256 与下载字节，并覆盖错误项目或错误文件关联。浏览器使用真实开发数据和隔离 API 的旧 BIN 状态回执，核对文件缺失、重试恢复、SHA256 失败重试以及实际 ONNX 下载。BIN 的完整下载字节由隔离 API 验证，浏览器另核对 BIN 请求参数和下载文件名。
- 从产物详情进入部署时只加载该版本指定的构建。使用真实 OpenVINO 产物确认部署草稿选中正确 ID，并验证指定构建失效时的提醒。1024×768、1366×768 的亮暗主题均无横向溢出，浏览器未提交部署。

### 模型场景 4、19、20、22：训练详情和运行日志（2026-11-19）

- 逐张核对运行中、完成、失败及日志的八张亮暗设计图。详情区分已完成轮次、进行中的轮次和已保存的最佳轮次。主视图显示训练／验证损失和主验证指标，现有运行时、学习率及分项指标收纳在详细指标区。文件表使用实际文件名、类型、大小、可确认的检查点轮次和时间。
- 开发库 YOLOX 任务 `task-521feff540fe` 实际完成 200 轮，使用真实指标和输出文件验证页面。查看模型版本进入 `model-version-3720563c7b99`。创建评估带入该版本及 `dataset-export-f9d1058afe36`，在四种视口主题组合下预检返回 200。真实失败任务 `task-a3dd070bb78b` 验证错误说明、检查点和恢复条件。
- 读取 YOLOX 任务真实保存的日志事件，验证最近 200 条、加载更早、搜索、空匹配结果和下载。复放第 37 轮时保存的 48 条事件呈现运行状态，通过测试连接送入真实第 38 轮事件，核对进度更新、暂停滚动和恢复滚动。旧任务没有保存独立 `train.log` 文件时，日志下载使用已保存的任务事件。
- Chrome 验收覆盖 1024×768、1366×768 和亮暗主题，页面及日志抽屉均无横向溢出。运行状态通过实际事件复放验证，浏览器未启动、取消或提交训练，也未提交评估。

### 模型场景 7、27–29、85 转换详情、运行环境和数值差异（2026-11-19）

- 对照完成、运行中、失败、执行环境和输出差异的亮暗设计图。转换详情按任务状态显示阶段、输出、日志、参数和环境。转换 Worker 从受监督子进程转发实际阶段及其时间，注册开始由父任务记录，完成时以发布事务的结束时间为准。历史任务缺少阶段用时或硬件信息时展示已记录的字段。下载使用实际登记的模型文件、权重和转换报告。
- 隔离环境复制了开发库 YOLO11 Barcode 权重 `model-version-f553108fc2ba`。正式转换 Worker 导出 Opset 19、动态批次 ONNX，保存导出、校验和登记事件，校验通过并登记一个产物。另一个任务在导出中取消后无新产物。仅对隔离副本制造损坏权重，验证准备阶段失败和原配置复用。
- 开发服务直接读取 OpenVINO 任务 `task-ea61996024cd`，核对真实权重和报告下载、`openvino-cpu` 执行环境及指定对应 IR 产物的部署草稿。浏览器复放隔离 Worker 的真实记录，核对自动更新、日志下载、取消失败后重试、错误复制和重新转换预检。数值差异使用既有 TensorRT INT8 六项真实诊断复验分页、诊断下载和参数恢复。浏览器未提交开发库转换及部署。
- 两种短屏 1024×768、1366×768 均核对亮暗主题，页面与抽屉无横向溢出，本次使用 Chrome 和 Playwright。

### 模型场景 50、52、53、79、89 模型编辑、版本删除和首次空列表（2026-11-19）

- 对照五组亮暗设计图。编辑抽屉仅修改展示名称与说明，任务类型、模型系列和真实更新时间使用只读行。关闭或浏览器返回需要确认未保存的变更。保存遇到 409 时，保留草稿并可读取服务端最新信息；继续提交须显式采用最新 revision。
- 删除框展示待删除版本的登记范围、保留项和服务端预检结果。确认字段使用登记的版本 ID。开发项目的 `model-version-3720563c7b99` 有两个直接部署引用，浏览器验证同步、异步状态和两种引用入口。预检读取失败可重试，依赖阻止时不显示删除确认输入。
- 隔离复制开发库中的 RF-DETR 模型 `model-ce02d6019372`。测试实际保存、过期 revision 冲突和更新回读。删除 `model-version-c23cb50107d6` 后，另一个版本 `model-version-cfa30d650925` 和训练 `task-da42fbb4b9b3` 仍可读取，四份真实文件的 SHA-256 保持一致。训练历史显示输出版本已删除，仍可查看保存的训练文件。浏览器用隔离 API 的真实回执验证写入交互。
- 使用开发库中模型数为零的“测试1”项目检查创建训练、模型包导入和基础模型入口。Chrome 覆盖 1024×768、1366×768 及亮暗主题。

### 模型场景 36–39：创建目标检测评估和运行详情（2026-11-19）

- 三步向导按设计分组显示模型与导出、类别映射、预处理、评估规则和执行检查。每次选择一个 val 或 test。类别映射只读，已知类别或顺序不一致时禁止进入下一步。AP 和完整 PR 曲线使用候选最低分，工作点阈值用于样本诊断和对应的 Precision、Recall。预检失败可以重试，返回上一步保留参数。
- 开发服务用 YOLOX 权重 `model-version-3720563c7b99` 和 Barcode 导出 `dataset-export-f9d1058afe36` 读取 117 张 test 图像和 158 个标注对象。隔离 API 和正式 Worker 使用同一份真实数据和浏览器核对的阈值 0.3125 提交评估，全部 117 张处理完成并输出报告。执行设置沿用实际 PyTorch 权重、设备和逐图推理能力，批大小显示为 1。
- 共用运行和取消详情的布局。真实 YOLO11 隔离任务 `task-3c93f2af493c` 保存了 12/61 的样本进度和最近三条处理记录。运行中显示已处理、失败和剩余样本，最终指标及下载等待报告生成。实际取消后保留相同计数，报告接口返回 404。
- Chrome 和 Playwright 核对 1024×768、1366×768 的亮暗主题。验证向导操作栏在短屏可见、切换划分、类别不匹配、预检中断后重试、真实运行快照和日志复放、取消请求失败后重试、取消终态。页面无横向溢出。浏览器未向开发库提交评估。

### 模型场景 42、43：目标检测曲线与执行条件（2026-11-19）

- 对照四张亮暗设计图。PR 轴使用 Recall 和 Precision，标题显示报告的 IoU。F1 曲线标记实际置信度工作点，切换类别保持该标记。曲线 JSON 下载保留报告原值，混淆矩阵延用该工作点的数据。
- 执行条件分组显示模型、权重、数据版本、预处理、评估规则和运行配置，支持键盘展开折叠。旧报告缺少的字段显示为未记录。修改规则后使用原报告的有效阈值和划分进入新评估草稿。
- 直接读取开发库的 `task-f866f7152e47` 验证历史报告。隔离 Worker 使用开发库 YOLO11 权重 `model-version-f553108fc2ba` 和 Barcode 导出 `dataset-export-3d69efd5184b` 实际评估 61 张 test 图像。生成的报告记录 CPU、PyTorch FP32、批大小 1、输入 320 × 320 和工作点 0.3125。浏览器复放该报告并用真实开发服务执行重评预检。
- Browser 插件未提供，使用 Chrome 和 Playwright 验证 1024×768、1366×768 的亮暗主题、图表随主题重绘、分组和实际下载，没有横向溢出。浏览器验收到预检为止。

### 模型场景 44–47：分类、实例分割、姿态和旋转框报告（2026-11-19）

- 逐张对照八张设计图。分类报告区分类别分布、Top-1、混淆矩阵和错分预览。真实记录 `task-73dd933f41f7` 的矩阵共 195 张，主对角线共 191 张，Top-1 显示 97.95%，4 张错分分两页。记录 `task-486de8212ada` 验证没有错分时的提示。
- 实例分割记录 `task-d55424b84b59` 以实际报告分别显示 BBox 和 Mask 指标及报告均值。原图、叠加、前景差异均使用真实资源。浏览器模拟差异图层读取失败，另一图层保留，单独重试恢复。切换原图后仍可使用已加载图层，放大预览可查看两种叠加。
- 姿态记录 `task-31af141b0671` 显示 21 个真实关键点定义与标注编号，保留真实 OKS 参数和独立 BBox 指标。该记录无骨架连线定义，页面显示对应说明。旋转框记录 `task-09e49426d739` 使用实际四角点、Rotated IoU 范围和错误样本筛选。已有记录的角度和定位偏差筛选均为空。
- 基于真实图像和标注构造三种受控预测偏差，用服务端诊断得到一例关键点偏差、一例旋转框角度偏差和一例定位偏差。浏览器复放对应样本响应，成功打开非空筛选和几何叠加。
- Browser 插件未提供，使用 Chrome 和 Playwright 核对 1024×768、1366×768 亮暗主题，覆盖样本翻页、放大、分层重试、原图亮度、错误筛选、旧记录和空状态。修复长文件名造成的放大窗口横向溢出，复验通过。

### 模型评估和列表复验（2026-11-20）

- 场景 48、82。异常检测记录 `task-833d9440001b416a97b33da722ef30a6` 含 11 张异常和 1 张正常样本。预览在异常类别内从第 1 张翻到第 2 张，右侧结果独立从第 1 页翻到第 2 页。语义分割记录 `task-a3bad030321142f2b1cf86545faa6fb4` 保留三层预览和日志。复验真实失败记录，并对预测图层单独返回一次 404，确认其余图层仍显示，重试恢复预测图层。
- 场景 9、10。开发项目的四个目标检测任务用同一真实 API 验证两页各两条且标识不重复。页面核对模型搜索、数据版本与划分筛选、零匹配、每页条数和报告比较。报告 `task-f866f7152e47` 的 GT 合计 92，AP50–95 均值 0.243。漏检示例用真实样本和标注打开，返回后回到原类别页和操作焦点。错误样本直达链接可读取列表。
- 模型版本、训练任务、转换与导入。选中页签沿用数据集页颜色和背景，页签、操作区和版本抽屉三块内容保有明确间距。核对检测任务深链接、模型分页、抽屉展开和引用返回、训练列表详情返回后搜索恢复、转换格式和精度、已完成及失败的模型包记录。实际版本元数据缺少可判定的先后顺序时显示“未记录”。当前真实检测报告保留了漏检样本，误检示例仅在报告提供时显示。
- 对照亮暗设计图和同主题开发环境截图。使用 Chrome 和 Playwright 在 1024×768、1366×768 验证本轮页面。列表、详情和抽屉无横向溢出。设计图示例的项目名、版本号、样本和指标与开发数据不同。

final result: passed（本轮交互与短屏核对范围）

### 模型剩余场景与异常交互（2026-11-20）

- 训练异常使用开发库真实失败任务 `task-a3dd070bb78b` 和已写入的检查点。另用同一路由的数据核对超时终态、可复制配置及不可恢复提示，用实际姿态任务及输出文件复放取消请求失败、重试、等待确认和已取消状态。
- 转换用真实 YOLO11 版本检查可用来源、ONNX Opset 19、动态批次、OpenVINO FP16 和替代目标，用真实 TensorRT Worker 的失败回执检查 6 项超限、抽屉导航、诊断下载、底部关闭及无产物登记。旧 TensorRT INT8 草稿缺少校准参数时会恢复可编辑参数。
- 模型包复验开发库已有成功登记和历史检查失败。使用隔离 Worker 实际回执复放登记失败、暂存包过期、导出文件清理及重新生成。在开发页面受控返回一次状态读取失败，确认操作锁定、手动重试成功后清除错误。
- 目标检测用真实报告 `task-f866f7152e47` 核对报告未就绪后恢复、失败时打开原配置草稿、定位偏差的空结果。命中分支使用同一报告的真实图像与 GT，加受控偏移预测验证定位偏差示例、类别和文件名筛选、IoU 0.250 与双框叠加。隔离 API 另测 IoU 0.200 以及类别不匹配排除。
- 使用 Chrome 和 Playwright 在 1024×768、1366×768 的亮暗主题核对上述状态，页面及抽屉无横向溢出。受控异常只在浏览器响应中复放，开发项目未收到新的取消、登记、转换或者评估提交。
- 剩余为场景 62 的 OpenVINO INT8。当前转换脚本仅接受 FP32、FP16，开发环境没有 NNCF，校准、独立校验和 INT8 IR 登记均未接通。场景 64 的 CoreML 和 ARM NPU 可以查看阻止原因及返回可用目标，当前平台缺少可供选择的转换环境。

final result: blocked（模型整体，场景 62）

### 模型场景 62 和 64 复验（2026-11-20）

- 场景 62。使用开发库真实 YOLO11 版本 `model-version-f553108fc2ba` 和 COCO 导出 `dataset-export-3d69efd5184b`。隔离 Worker 使用 200 张 train 图校准，从生成的 IR 重新加载并与 ONNX Runtime 核对 30 张独立 val 图。106 个量化算子，最高逐图 P99 误差 0.0766，平均误差 0.0058。登记并通过 API 下载 XML 和 BIN，分别为 624,964 和 2,665,320 字节。
- 从真实模型产物的副本注入输出偏差，独立校验拒绝该 IR。真实 COCO 数据还覆盖了 val 样本不足和校准、校验图片内容重复的预检阻止。浏览器使用真实预检接口，并在详情页复放隔离 Worker 回执和受控数值失败诊断。
- 场景 64。使用同一真实模型核对 CoreML 的 ML Program、最低 macOS 12，及 ARM NPU 的厂商适配器要求。执行环境显示未选择，选择器没有可用项，下一步禁用且不会提交任务。切回 ONNX 可继续通过预检。当前本地版本没有 CoreML 或 ARM NPU 转换与校验消费者，验收覆盖该设计场景的环境选择和不可用分支。
- Browser 插件在当前会话不可用，使用 Chrome 和 Playwright 在 1024×768、1366×768 的亮暗主题核对两组页面与交互。页面、参数和环境选择区域无横向溢出。

final result: passed（模型页面剩余设计场景）

### 模型版本名称与详情复验（2026-11-20）

- 开发库的 126 个历史版本完成编号迁移。真实 RF-DETR 模型从 `v2` 切换到 `v1`，模型包导出使用选中的版本。真实 YOLOX 版本以旧链接打开后显示 `v1`，创建转换保留相同版本。后端回归覆盖通过展示名称继续训练以及删除后分配 `v3`。
- 从两条原始训练指标文件复核最佳轮次 `1 / 1` 和 `200 / 200`。模型产物显示原始 PyTorch 文件的可用性与已有转换校验证据，OpenVINO 详情可返回到原版本。
- 使用内置浏览器核对 1024×768、1366×768 的亮暗主题。版本抽屉、内容和产物表格无横向溢出。真实基础模型选择后默认训练输出名称为 `RFDETR-l`。
