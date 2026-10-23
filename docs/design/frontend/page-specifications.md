# 当前页面规格

## 适用范围

本文定义当前 Vue 3 Web UI 已注册页面的职责、信息层级和交互边界。路径清单见 [信息架构](information-architecture.md)，通用样式见 [设计系统](design-system.md)。未注册路由和未来页面见[完整导航与页面规划](navigation-and-page-plan.md)，包括[数据集完整管理](dataset-management-plan.md)与[异常/连接器/3D 视觉扩展](workflow-vision-ui-plan.md)；不混入本文的当前事实。

2026-10-22 核对：下面的状态与排版要求用于下一轮设计，不代表每一项已完成浏览器交互验收。普通页不恢复已隐藏的页面大标题；旧图不作为路由或功能存在的证据。

2026-10-23 补充：[逐页中文设计与提示词](prompts/README.md)为当前页面和目标扩展分别说明来源、保留项、修正项、容器和状态。本文保留当前职责边界，不将目标样本管理、评估或3D工作区写成已注册页面。

## 系统入口

### 启动检查 `/`

- 检查 runtime config、backend API、版本兼容和会话状态。
- 检查完成后进入登录或业务页面；失败时显示服务地址、错误原因和重试操作。
- 导航品牌进入 `/`，尊重个人启动偏好与显式回跳；不能固定跳转项目页。
- 禁止以无限 spinner 掩盖后端离线、版本不兼容或鉴权失败。

### 登录 `/login`

- 支持本地账号登录并显示当前 backend 地址。
- 覆盖正常、凭据错误、后端不可用和会话失效状态。
- 不显示未实现的第三方登录或云端协作入口。

### 离线、无权限与未找到

- 直接显示原因、资源或路径、可执行恢复动作。
- 无权限页面说明缺少的 scope；离线页面提供重试；未找到页面返回相应列表。

## 工作空间

### 项目 `/projects`

- 当前支持创建、选择和删除 Project，生成外部 SDK 配置包；行点击选择项目，尚无独立“查看”路由。
- 当前列表展示项目名称/id、来源及数据集、训练、部署、Workflow 摘要；不能将设计稿中的模型数量和更新时间认作现有字段。
- 目标新增 `/projects/:projectId` 项目概览，列表“查看”进入完整页面；简短项目信息仍可用抽屉。此路由及最近更新等契约尚待实现，见[目标设计](project-overview-design.md)。
- 删除前显示聚合资源预检，存在阻断时给出对象类型和 id，不静默级联生产资源。
- 空状态只引导创建首个 Project，不展示虚构业务数据。

### 任务 `/tasks`

- 统一显示数据集、训练、转换、评估和异步推理等有限任务。
- 支持 Project、类型、状态和文本筛选；分页从服务端读取。
- 运行项显示真实阶段和进度；未知进度不伪造百分比。
- DeploymentInstance、WorkflowAppRuntime 和 TriggerSource 不进入任务列表。

### 任务详情 `/tasks/:taskId`

- 显示任务状态、队列、worker、阶段、事件、请求、结果和错误。
- 取消只对后端允许的状态开放；终态保留产物和诊断。
- 关联资源使用明确链接返回所属数据集、模型或推理页面。

## 数据集

### 数据集工作台 `/datasets`

- 在同一工作台管理 Dataset、DatasetVersion、Import 和 Export。
- 主页面保留导入/导出操作和记录；版本列表放在“管理数据集”对话框中，由页内操作区进入，不重新占据主页面。
- 删除导入记录清理记录、关联任务、上传 zip 和导入暂存文件，保留版本、图片和标注。管理数据集内删除版本才清理该版本、图片、标注及关联导入/导出记录；存在外部引用时阻止删除。不增加“删除整个数据集”功能。
- 创建操作使用当前后端 capability 提供的任务类型和格式，不显示未实现格式。
- 表格、筛选和创建面板保持上下文稳定；任务提交后进入对应详情。

### 导入详情 `/datasets/imports/:datasetImportId`

- 显示 received、extracting、validating、normalizing、succeeded 或 failed 阶段。
- 展示识别格式、类别摘要、警告、错误和生成的 DatasetVersion。
- 删除只删除导入任务及其受控临时资产，不暗示删除已生成版本。

### 导出详情 `/datasets/exports/:datasetExportId`

- 展示来源 DatasetVersion、目标格式、split、类别、文件清单和产物位置。
- 成功后提供与模型支持矩阵一致的训练入口。
- 删除前区分导出产物与上游 DatasetVersion，不混淆影响范围。

## 模型

### 模型工作台 `/models`

- 管理平台预训练模型、项目模型、ModelVersion、ModelBuild、训练和转换入口。
- 任务类型、模型系列、scale、数据格式、设备和 precision 由后端 schema 联动约束。
- 版本、构建产物和训练血缘清楚展示；不把 ModelBuild 当作新 Model。
- 导入模型区域位于转换任务列表下方，不在页面顶部再放一套入口。
- 旧图的独立评估中心和独立评估详情不属于当前路由。指标/评估能力须按当前页面与 API 确认，不能为了复刻图而新增业务页。

### 训练详情 `/models/:taskType/training-tasks/:taskId`

- 展示训练阶段、epoch、batch、指标、资源、日志和 checkpoint。
- WebSocket 更新实时状态，REST 快照负责重连和最终一致性。
- 成功后链接 ModelVersion；失败和取消保留最新安全 checkpoint 与结构化错误。

### 转换详情 `/models/:taskType/conversion-tasks/:taskId`

- 展示来源 ModelVersion、目标 runtime、precision、设备约束、阶段和生成的 ModelBuild。
- ONNX、OpenVINO、TensorRT 等状态名称与后端转换任务一致。
- 失败时显示规划、worker 错误和已有安全产物，不伪报可部署。

## 部署与推理

### 部署 `/deployments`

- 创建和管理 DeploymentInstance，展示模型来源、runtime、device、precision、实例数和状态。
- desired / observed 状态、generation、健康实例、PID、预热和最近错误分开展示。
- 启动、预热、停止、重置和删除遵守后端控制状态；常驻不等于正在占用全部推理并发。
- 页面不按仓库 Deployment 数量计算全局线程配额。
- 导入部署实例对话框：运行配置按标签/控件列对齐，资源映射逐项展示来源、目标和解析状态；单条失败信息有独立清除动作，清除提示不等于重试或删除资源。
- 详情沿用现有抽屉/页内区域，不为旧图中的独立实例详情凭空增加路由。

### 推理 `/inference`

- 选择 DeploymentInstance 和其任务类型，构造同步或异步推理请求。
- 输入支持页面公开的 URI、File id、上传、Base64 或 image-ref 形状；不把本机 mmap 引用伪装成跨机器稳定输入。
- 结果展示结构化预测、预览图和阶段耗时；原始 JSON 保留在次级区域。
- 同步和异步入口明确区分，不以异步队列模拟同步调用。

## Workflow

### 流程应用列表 `/workflows/apps`

- 显示 FlowApplication、最新发布版本、Runtime 和 Trigger 摘要。
- 进入详情、打开编辑器和创建应用使用稳定 application id。
- 列表按服务端分页，不通过“前 100 条再本地过滤”判断资源是否存在。
- 列表名称下不重复展示 `workflow-app-*` ID；详情提供完整 ID。运行实例选中使用品牌软底，普通悬停使用中性灰。

### 流程应用详情 `/workflows/apps/:applicationId`

- 管理不可变 AppVersion、稳定 Runtime、revision、generation、Run 和 Trigger。
- 发布、归档、恢复和选择版本显示准确的 active -> target 关系；详情已有“与草稿比较”，按实际比较结果显示，不扩展为编辑器内任意两个历史图的可视化差异工具。
- App 草稿更新不自动修改已运行 Runtime；切版保留 Runtime 和 Trigger id。
- Runtime failed 后允许 reset、重新选择同一版本并启动。
- 同步 invoke 和异步 run 分开呈现；运行来源保留 version、revision、generation、fingerprint 和 worker epoch。

### 流程编辑器 `/workflows/graph/new`、`/workflows/graph/apps/:applicationId`

- 画布、节点组、连线、属性面板、Preview 输入和运行结果构成主工作区。
- 节点定义、端口、参数和多语言名称来自 Node Catalog，不在前端复制第二套节点契约。
- 鼠标左键只在按下期间拖动画布或节点；松开、窗口失焦和 pointer cancel 必须结束拖动。
- Preview 在独立可复用 Worker 执行，逐节点通过 WebSocket 交付进度、JPEG 图片和值；临时共享内存按消费者和完整接收确认释放。模型节点调用已部署服务，部署调用仍走既有网关/LocalBuffer。除明确保存节点外，不创建 Preview 磁盘交换或永久结果记录。见[Preview 执行](../../architecture/workflows/preview-execution.md)。
- 已执行节点在节点下方显示低干扰耗时角标；重复节点显示最后一次耗时，For Each End 和 Parallel End 显示聚合耗时。
- 属性面板保持面向使用者的字段名；内部 type id、格式版本和实现路径不占据主界面。
- Ctrl 框选、内部连线与完整节点组复制按[多节点复制规格](../../development/workflow-multi-node-copy.md)呈现，不绘制尚未实现的通用撤销/重做工具。
- 连接器定位、PIN 排列、测量、标定配置在对应节点的图形/表格编辑器中完成，复用现有资源选择。Core 通用显示和公差控件不写入产品规则；不增加连接器专用导航。资源、单位、坐标系、当前观察与失效结果必须区分，详见[连接器实施记录](../../development/connector-usability-implementation.md)。

### Runtime 运行监视与应用模式

- `/workflows/runtime/:workflowRuntimeId/monitor` 只读查看实际发布图和结果，亮暗外观一致；不在顶部堆叠版本 ID、generation、Runtime ID。
- `/workflows/runtime/:workflowRuntimeId/app-mode` 展示公开输入和配置的预览区域，不复制节点执行或创建另一套页面设计器。
- Runtime 在本次执行完成后的显示边界交接结果；不能把编辑 Preview 的逐节点动画当作 Runtime 已有能力。参见[运行显示](../../architecture/workflows/runtime-display.md)。
- Image Preview 与 Value Display 通过明确的 `Display Data` 连线关联；节点执行启用、图片数据关联和应用模式栏目选择是三个不同概念，配置 UI 必须沿用当前语义，不能再按名称或附近节点自动配对。
- 生产统计面板位于图片左上角，半透明、垂直排列；当前结果、生产总数、良品、不良、良品率由节点 Fields 决定，支持配置颜色、字号和大小。不是所有图片都显示统计。
- 双击大图保留已绑定的显示数据。测量 Results 表格和所选几何必须来自同一观察、同一原图；JPEG 仅用于显示，不作为尺寸计算输入。缺测不显示 0 或沿用上一帧 OK。
- 本页不增加 Runtime/Trigger 排队或自动业务重试，忙碌和实例满载不等于服务未就绪。

## 集成与扩展

### 触发源 `/integrations/trigger-sources`

- 绑定已存在且可用的 WorkflowAppRuntime，管理协议配置、input mapping、result binding 和运行状态。
- 支持项以当前 Trigger adapter catalog 为准；未注册 adapter 不能启用。
- 创建、启用、禁用和删除显示 Runtime 版本、generation、契约兼容和恢复错误。
- 调试输入与真实常驻监听明确区分，不把 synthetic invoke 表现为协议已经连通。
- 列表保留名称、类型、状态、触发时间、操作；无记录显示“未触发”。入口 ID、运行实例 ID、健康计数和最近错误放在操作列打开的详情抽屉，复用 Runtime 详情样式。
- 结果绑定选择器收起时使用中性输入样式；仅下拉菜单内的已选项使用品牌选中色。

### 自定义节点 `/custom-nodes`

- 展示扫描到的 Node Pack、manifest、version、capability、依赖和节点定义。
- Core 为平台内建，Custom/第三方包为受信任本地扩展；界面区分来源，不把核心节点画成需要用户安装的包。执行链不因界面新增 per-node 子进程隔离。
- 禁用或依赖错误显示具体原因；不提供不存在的云市场和自动安装流程。

## 系统

### 设置与诊断 `/settings`

- 按分类展示 backend、worker、inference daemon、数据库、队列、存储、LocalBuffer、设备、运行时和访问配置。
- “启动页面”分类可将根地址的登录后落点设为项目页面或一个明确的 Runtime App Mode；配置为浏览器本地偏好，不修改服务端资源，显式 URL 和登录回跳优先。
- 服务状态必须来自真实 health / probe；`degraded` 同时显示具体组件和错误，不只显示颜色。
- 日志、磁盘、GPU/NPU、配置路径和版本信息用于现场排障；敏感值不直接显示。
- 当前页面不承担安装向导或系统级驱动管理。
- 复用现有二级分类，顶部不重复显示“设置”；关于页保留 Community Edition，应用名称为不加粗、无词缀底色的小写 `amvar` 动态品牌。
- 运行状态显示 `Backend Worker`，不恢复冗长 Topology 解释。用户管理与启动偏好已实现，不能按旧目录说明画成“即将支持”。
- 默认本地数据库、队列等是运行信息，不画成必须先连接外部数据库/Redis/MQ 的安装配置。

## 通用交互要求

- 首次加载使用结构骨架；筛选无结果、后端重连和真正空数据使用不同状态。
- 长资源列表按现有服务端分页；节点参数表、短映射表不强加分页。所有写操作提供处理中、防重复提交和结构化失败反馈。
- 状态同时使用文字、图标和颜色；危险操作默认焦点不落在确认按钮。
- ID、路径、JSON 和日志可复制；时间和数字使用稳定格式。
- 页面标题、字段名称和操作文案通过 i18n key 提供中文、英文、日文和韩文，不直接暴露 snake_case。
- 小于 `1024px` 时优先保留监控和控制；完整图编辑与大图分析以桌面工作站为主要目标。

## 维护规则

- 当前路由、权限或页面职责变化时同步更新本文。
- 新能力只有在 Vue Router、权限门禁、API 契约和浏览器测试都落地后，才加入当前页面规格。
- 详细 API 字段以 OpenAPI 为准；节点参数以 Node Catalog 为准；本文不复制完整 schema。
