# 逐页设计规格

## 1. 使用说明

本文件定义每个页面的目标、信息层级、主要组件、关键操作和必须生成的状态。页面视觉统一遵循 [视觉与组件系统](03-visual-component-system.md)。工具提示词见 [OpenAI Image 2 提示词](05-openai-image-2-prompts.md) 和 [Google Stitch 提示词](06-google-stitch-prompts.md)。

每个页面至少生成一个标准桌面状态。标记为“关键”的页面还应生成运行中、错误或选中状态。

## 2. 系统入口与全局状态

### S01 启动检查页

- 状态：`系统状态`。
- 目标：在本地应用启动时检查 API、会话、数据库迁移、静态资源和核心服务，不制造“加载卡死”的感觉。
- 布局：全屏中性背景，中间为窄检查面板；左上保留 AMVision 标识和版本。
- 内容：五步垂直检查列表，每步有图标、名称、状态和短说明；底部显示当前服务地址和“查看诊断”。
- 状态：检查中、自动进入、需要登录、后端离线、版本不兼容。
- 视觉：克制的逐项点亮，避免品牌宣传插画和大动画。

### S02 登录页

- 状态：`现有增强`。
- 目标：支持默认本地用户自动进入失败后的手动登录，并明确当前连接的本地服务。
- 布局：左侧约 34% 深墨色品牌区，右侧浅色登录区；登录卡不悬浮过度。
- 内容：用户名、密码、显示密码、登录按钮、后端地址、版本、离线提示。
- 文案：标题“进入 AMVision 工作台”，说明“本地视觉服务平台”。
- 状态：正常、凭据错误、服务不可用、会话过期。
- 禁止：人物插画、云端协作宣传、第三方社交登录。

### S03 离线、无权限与未找到

- 状态：`系统状态`。
- 目标：直接说明原因、当前仍可做什么和恢复路径。
- 布局：保留简单外壳或空白外壳；中心显示小图标、状态码、标题、说明和操作。
- 离线：显示最后连接时间、“重新连接”和“进入只读缓存”。
- 无权限：显示所需 scope 和“返回上一页”。
- 未找到：显示资源类型/ID 和“回到对应列表”。

## 3. 项目与任务

### P01 项目列表

- 状态：`现有增强`。
- 目标：创建、切换、查看和删除 Project，并生成外部 SDK 配置包。
- 页面标题：项目；主操作“新建项目”；次操作“生成 SDK 配置包”。
- 主区：项目表格或紧凑两列列表。字段为名称、短 ID、描述、数据集数、模型数、流程应用数、更新时间。
- 右侧抽屉：新建项目，字段为名称、描述；创建后自动切换。
- SDK 面板：选择项目、目标接口类型，生成并下载 zip，显示最近生成记录。
- 删除：确认框显示依赖资源数量；不能只显示“确定删除吗”。
- 空状态：引导创建第一个项目，不展示虚构业务数据。

### P02 项目概览

- 状态：`规划`。
- 目标：作为项目级起点呈现端到端链路进展，不做通用 KPI 大屏。
- 顶部：项目名称、短 ID、描述、编辑和生成 SDK 配置包。
- 第一行：数据集版本、可用模型版本、健康部署、运行流程四个紧凑指标。
- 中部左：最近资源时间线；中部右：当前运行任务和异常实例。
- 下部：四个“继续工作”区域——导入数据、训练模型、部署模型、编辑流程，每个只显示最近对象和一个操作。
- 状态：新项目空状态、活跃项目、存在失败任务。

### T01 任务中心

- 状态：`现有增强`，关键。
- 目标：统一观察有开始和结束的后台任务，不混入 DeploymentInstance 和 WorkflowAppRuntime。
- 顶部统计：运行中、排队、失败、今日完成。
- 筛选：Project、任务类型、状态、worker queue、时间；支持按 task ID 搜索。
- 表格：任务名称/ID、类型、关联资源、阶段、进度、状态、开始时间、耗时、操作。
- 运行行：显示阶段文字和真实进度；未知进度使用活动指示，不伪造百分比。
- 行操作：查看、取消；失败任务提供“查看错误”。
- 实时：WebSocket 更新行状态，右上显示最后同步时间。
- 关键状态：多个并行任务、一个失败任务、连接重连中。
- 首次空状态：统计全部为 0，保留筛选和表头；说明任务从数据集、模型、评估、有限推理或流程运行入口创建，不提供通用“新建任务”。明确 `DeploymentInstance` 与 `WorkflowAppRuntime` 不进入任务中心。

### T02 通用任务详情

- 状态：`现有增强`。
- 目标：为未进入专用详情页的任务提供统一诊断入口。
- 顶部：task ID、类型、状态、Project、创建时间；操作为刷新、取消、进入关联资源。
- 摘要：队列、worker、阶段、进度、开始/结束、重试次数。
- 时间线：queued、claimed、running、progress、succeeded/failed 事件。
- 错误区：错误码、摘要、可展开 stack trace、复制诊断信息。
- 原始数据：request/result JSON 折叠区。
- 状态：运行中事件流、失败详情、成功产物链接。

## 4. 数据集

### D01 数据集工作台

- 状态：`现有增强`，关键。
- 目标：把 Dataset、Import、DatasetVersion 和 DatasetExport 清楚组织在同一工作区。
- 顶部：标题“数据集”，主操作“导入数据集”，次操作“创建导出”。
- 局部标签：数据集、导入记录、数据版本、导出记录；每项显示数量。
- 数据集表：名称、任务类型、格式来源、当前版本、样本数、类别数、更新时间。
- 导入表：文件名、任务、检测格式、校验状态、进度、创建时间。
- 数据版本表：版本号、split 摘要、样本数、标注数、来源导入。
- 导出表：格式、模型兼容性、状态、包大小、来源版本。
- 筛选：classification/detection/segmentation/pose/obb、格式、状态。
- 关键状态：数据集标签页有真实数据；导入任务正在运行；存在格式校验失败。

### D02 导入数据集向导

- 状态：`规划为独立体验`，关键。
- 目标：上传 zip，明确任务和外部格式，校验后创建 DatasetVersion。
- 步骤 1 上传：拖放区、文件名、大小、SHA 摘要；只接受 zip。
- 步骤 2 数据定义：Dataset 名称、任务类型、格式。格式随任务动态变化。
- 步骤 3 split 与类别：`auto/train/val/test` 策略、类别映射 JSON 可选、检测摘要。
- 步骤 4 预检查：目录树摘要、图片数、标注数、split、类别、warning/error。
- 步骤 5 提交：配置摘要，创建 DatasetImport 后进入详情。
- 格式规则：classification 仅 ImageNet；detection 为 COCO/VOC/YOLO；segmentation 和 pose 为 COCO/YOLO；obb 为 DOTA/YOLO。
- 错误：不安全路径、缺图片、标注语法错误、类别不一致、格式与任务不匹配。
- 视觉：上传区朴素、工程化，目录和校验报告优先，不使用云朵插画。

### D03 导入详情

- 状态：`现有增强`。
- 目标：查看导入阶段、校验报告、识别格式、类别映射和生成的数据版本。
- 顶部：import ID、状态、任务类型、格式、刷新、删除。
- 摘要：zip 名称、大小、staging 路径、queue、创建/完成时间。
- 阶段条：上传、解压、检测、校验、统一化、版本落盘。
- 校验报告：错误、警告、信息三级；支持下载问题列表。
- 检测结果：目录结构、图片类型、split 数量。
- 类别映射：外部 ID、内部 ID、类别名。
- 成功状态：突出生成的 DatasetVersion，并提供“查看版本”“创建导出”。

### D04 数据版本详情

- 状态：`规划`，关键。
- 目标：稳定展示内部数据版本、样本、标注、split 和可导出能力。
- 顶部：Dataset 名称、版本号、任务、来源 import、只读标识。
- 指标：总样本、train/val/test、类别、标注、空标注图像。
- 主区标签：概览、样本、类别、标注质量、导出记录、元数据。
- 样本：可筛选图像网格与表格切换；点击样本打开大图检查器。
- 任务叠加：classification 显示类别；detection 显示框；segmentation 显示 mask；pose 显示关键点；obb 显示旋转框。
- 质量：缺标注、越界、极小目标、类别分布、split 分布，只显示平台确有数据。
- 主操作：“创建导出”；次操作“回到来源导入”。

### D05 创建数据集导出

- 状态：`规划为独立体验`。
- 目标：从 DatasetVersion 生成训练/评估可消费的 DatasetExport。
- 步骤 1 来源：选择 Dataset 和版本，展示任务类型与 split 完整性。
- 步骤 2 目标：可先选择模型系列，也可直接选择 format_id；只显示兼容格式。
- 步骤 3 规则：图像链接/复制策略、必要的任务特定限制、输出摘要。
- 步骤 4 检查：train/val/test、类别、格式兼容性、预计文件数和磁盘空间。
- 说明：训练必须消费 DatasetExport，不直接读取 DatasetVersion 原始目录。
- 结果：提交后进入导出详情。

### D06 导出详情

- 状态：`现有增强`。
- 目标：查看 DatasetExport 状态、格式、包文件、运行数据、split 和类别，并进入训练。
- 顶部：export ID、状态、format_id、下载、创建训练任务、删除。
- 摘要：来源 DatasetVersion、任务、模型兼容范围、queue、时间。
- 包文件：文件名、路径、大小、校验值、下载按钮。
- 运行数据：导出根目录、manifest、入口配置文件。
- split 与类别：紧凑表格。
- 成功状态主操作：“用此导出创建训练任务”。

## 5. 模型、训练与评估

### M01 模型工作台

- 状态：`现有增强`，关键。
- 目标：按 task type 管理平台基础模型、Project 模型、训练任务、模型版本、转换任务和构建产物。
- 顶部：标题“模型”，主操作“创建训练”，次操作“转换模型”。
- 第一层任务标签：classification、detection、segmentation、pose、obb。
- 第二层资源标签：模型版本、训练任务、转换任务、构建产物。
- 模型版本表：模型名、系列、任务、版本、来源、主指标、runtime 产物、更新时间。
- 训练任务表：数据导出、模型、状态、epoch、best 指标、耗时。
- 构建矩阵：同一 ModelVersion 对应 PyTorch、ONNX、OpenVINO、TensorRT 状态。
- 模型选择器：平台预置基础模型和 Project 训练模型分组，不允许上传任意预训练模型。
- 关键状态：detection 标签；一个训练运行中；一个版本有多种构建产物。

### M02 创建训练任务

- 状态：`现有能力重组`，关键。
- 目标：选择受支持的模型任务组合、DatasetExport、训练方式和参数。
- 步骤 1 任务与模型：先选任务，再显示兼容模型。明确 YOLOX 仅 detection，RF-DETR 仅 detection/segmentation。
- 步骤 2 数据：选择 DatasetExport；显示格式、split、类别、样本和与模型的兼容性。缺 val 时阻止提交。
- 步骤 3 初始化：从平台基础模型 warm start、从 ModelVersion warm start、或从同任务 checkpoint resume；三者文案和语义分开。
- 步骤 4 参数：epochs、batch size/AutoBatch、input size、device、AMP、optimizer、学习率、workers、checkpoint 周期；不支持参数不显示。
- 步骤 5 摘要：模型、数据、train/val/test、初始化方式、关键参数、预计输出和设备检查。
- 提交：创建异步 training task，进入详情。
- 错误：格式不兼容、无 val、resume 来源不匹配、设备不可用。

### M03 训练详情

- 状态：`现有增强`，关键。
- 目标：实时观察训练、理解 best/latest、查看验证指标和输出文件。
- 顶部：任务名称、model/task、状态；操作为刷新、取消、注册结果、删除。
- 摘要：DatasetExport、基础模型/恢复点、device、epoch、batch、input size、开始时间。
- 进度：当前 epoch/总 epoch、batch、ETA、数据加载/训练/验证阶段。
- 曲线：train loss、val loss、主指标；best epoch 垂直标记。
- 指标：完成 epoch、当前 batch、validation 分区展示。
- 输出：best checkpoint、latest checkpoint、训练配置、metrics、日志、图表文件；支持预览和下载。
- 最终状态：明确说明最终 test 是否可用；训练完成后提供“查看模型版本”“创建转换”“创建评估”。
- 失败状态：保留最后 epoch、latest checkpoint 和错误区，提供符合后端规则的恢复入口。

### M04 验证与评估中心

- 状态：`规划`。
- 目标：集中查看 ValidationSession 和 EvaluationTask，避免评估结果只能从通用任务或 API 找到。
- 顶部：主操作“创建评估”。
- 标签：验证会话、评估任务、比较。
- 筛选：任务、模型、数据版本/导出、状态、时间。
- 表格：模型版本、数据集、split、主指标、状态、运行时、完成时间。
- 比较：选择二到四个评估结果，对齐任务和数据集后比较；不允许跨任务比较单一“准确率”。
- 首次空状态：保留标签、筛选、表头和空比较篮；缺少可用 `ModelVersion` 或兼容 `DatasetExport` 的 val/test split 时禁用“创建评估”，并显示前置关系与对应业务入口。

### M05 评估详情

- 状态：`规划`，关键。
- 目标：解释模型在指定 DatasetExport/split 上的指标、类别表现和错误样本。
- 顶部：模型版本、任务、数据集、split、状态；操作为导出报告、打开模型版本。
- 核心指标：根据任务显示 mAP/precision/recall、top-1/top-5、mask AP、OKS AP 或 rotated IoU/AP。
- 标签：概览、按类别、曲线/矩阵、样本、运行信息。
- 样本画廊：TP、FP、FN、低置信度筛选；点击进入大图对比预测与 GT。
- 运行信息：runtime、device、阈值、最大检测数、耗时、评估契约版本。
- 空缺：无 test split 时明确显示“最终测试不可用”，不能用 val 冒充 test。

### M06 模型版本详情

- 状态：`规划`。
- 目标：展示可部署模型资源的完整来源、指标、文件和构建矩阵。
- 顶部：模型名、版本、task/model type、可用状态；主操作“创建转换”。
- 来源链：TrainingTask → DatasetExport → DatasetVersion，或预置基础模型来源。
- 摘要：best 指标、类别/关键点 schema、输入尺寸、创建时间。
- 构建矩阵：PyTorch、ONNX、ONNX optimized、OpenVINO IR、TensorRT engine；显示精度、设备、状态和部署数。
- 文件：checkpoint、config、label schema、provenance、checksum。
- 关联：评估、部署、workflow 引用。

### M07 创建转换任务

- 状态：`现有能力重组`。
- 目标：从 ModelVersion 生成受支持的 runtime 产物，并在提交前解释设备兼容性。
- 步骤 1 来源：选择 Project ModelVersion 或已登记来源。
- 步骤 2 目标：ONNX、ONNX optimized、OpenVINO IR、TensorRT engine。
- 步骤 3 参数：opset、动态/静态 shape、precision、workspace、device profile；按目标显示。
- 步骤 4 检查：模型任务、输入输出 schema、设备、TensorRT/CUDA 版本、预计产物。
- 禁止：显示 CoreML/ARM NPU 为当前可用目标；它们属于长期产品范围但当前主链未实现。

### M08 转换详情

- 状态：`现有增强`。
- 目标：查看转换任务、一个或多个 ModelBuild、结果和完整 spec。
- 顶部：任务名称/ID、状态、目标 runtime、刷新、取消、删除。
- 摘要：来源 ModelVersion、task/model、目标格式、precision、device profile、时间。
- 构建产物：format、文件、大小、checksum、兼容设备、状态；成功行提供“创建部署”。
- 结果：阶段、验证结果、数值一致性摘要。
- spec：可读字段优先，原始 JSON 折叠。
- 失败：突出转换阶段和兼容性错误，不隐藏在原始日志中。

## 6. 部署与推理

### R01 部署工作台

- 状态：`现有增强`，关键。
- 目标：创建和管理长期运行 DeploymentInstance，区分 sync/async 两类独立监督单元。
- 顶部：主操作“新建部署”，刷新和设备能力入口。
- 创建区或向导：选择 ModelBuild、服务模式 sync/async、runtime、device、precision、实例名称、并发/队列参数。
- 动态约束：PyTorch、ONNX Runtime、OpenVINO、TensorRT 的设备和精度选项按后端能力变化。
- 列表：名称、模型/任务、runtime、device、模式、健康、uptime、P95、更新时间。
- 行操作：启动、停止、重启、预热、重置、打开推理、删除。
- 右侧运行面板：选中实例后显示进程、端点、输入 schema、健康、事件。
- 关键状态：一个 OpenVINO NPU 健康实例、一个 TensorRT FP16 启动中、一个停止实例。

### R02 部署实例详情

- 状态：`规划`，关键。
- 目标：为现场运行实例提供稳定操作和诊断页面。
- 顶部：实例名、健康状态、sync/async、启动/停止/重启、打开推理。
- 第一行：模型、build、runtime、device、precision、uptime。
- 监视：请求率、平均/P95 时延、错误率、队列深度；没有可靠数据时不显示虚构曲线。
- 标签：概览、接口、输入输出、事件、日志、配置、引用。
- 接口：内部/公开 endpoint、请求示例、复制按钮、鉴权提示。
- 引用：被哪些 WorkflowAppRuntime 使用，停止前显示影响。
- 失败状态：子进程退出码、最近心跳、runtime 错误、恢复建议。

### I01 推理实验室

- 状态：`现有增强`，关键。
- 目标：选择部署实例，完成同步或异步推理，并同时检查视觉结果、结构化输出和性能。
- 布局：顶部目标与调用方式；主体三栏为输入配置、图像画布、结果检查器；底部为异步任务/历史。
- 目标：DeploymentInstance 选择器显示 model/task/runtime/device/health。
- 输入：上传图片、粘贴 URL/结构化 payload、LocalBuffer 引用；只显示实例支持的方式。
- 参数：confidence、IoU、top-k 等按任务和模型 schema 动态生成。
- 调用：同步“立即推理”，异步“提交任务”；两个按钮语义清楚。
- 画布：按 classification/detection/segmentation/pose/obb 渲染对应叠加。
- 结果：耗时、类别、score、坐标、JSON；支持原图/叠加对比和下载。
- 异步区：task ID、状态、进度、创建时间、结果入口。
- 关键状态：detection 结果有多类框；切换 segmentation 可见半透明 mask；异步任务运行中。

## 7. 流程编排与集成

### W01 流程应用列表

- 状态：`现有增强`。
- 目标：管理已发布 FlowApplication 和运行实例，不把草稿图与已发布应用混为一谈。
- 顶部：主操作“新建流程”，次操作“刷新”。
- 运行概况：健康 runtime、停止 runtime、异常 runtime。
- 应用表：名称、当前模板版本、runtime 数、触发源数、最近运行、状态、更新时间。
- 行操作：查看应用、打开图编辑器、创建 runtime、删除。
- 空状态：引导先创建流程图并发布。

### W02 流程应用详情

- 状态：`现有增强`，关键。
- 目标：管理应用契约、多个 WorkflowAppRuntime、HTTP 调用、最近 run 和 TriggerSource。
- 顶部：应用名、版本、状态；操作为编辑流程、创建 runtime、删除。
- 摘要：模板版本、输入输出契约、创建时间、最近发布。
- App Contract：输入/输出端口、类型、是否必需、示例。
- Runtime 列表：实例名、状态、worker、uptime、健康、触发源；操作为设为当前、启动、停止、重启、健康检查、添加触发、删除。
- HTTP 区：当前 runtime endpoint、方法、请求示例和复制。
- 最近回执：run ID、状态、耗时、输出摘要、错误节点。
- TriggerSource：类型、endpoint/topic、启用状态、最近触发。

### W03 流程编辑器

- 状态：`现有增强`，关键。
- 目标：创建、编辑、校验、试跑和发布视觉流程图。
- 布局：全屏深色工作台。顶部命令栏；左侧节点库；中间无限画布；右侧参数检查器；底部可展开运行面板。
- 顶部：返回、流程名/版本、保存状态、撤销/重做、校验、试跑、发布、更多。
- 节点库：搜索和分类 Input、IO、Vision、Model、Logic、Service、Support、Video、Custom。
- 画布：节点、端口、连线、节点组、缩放小地图；显示未保存和只读状态。
- 检查器：节点说明、输入输出、参数 schema、部署实例选择、权限和错误。
- 运行面板：输入绑定、逐节点状态、耗时、输出预览、日志；错误时自动定位节点。
- 发布：显示版本说明、App Contract 变化、兼容性检查。
- 关键状态：包含图像输入、OpenCV、已部署 YOLO11、规则判断和 HTTP 输出节点；一个节点选中；底部有成功试跑结果。

### X01 触发源页面

- 状态：`现有增强`。
- 目标：把外部协议输入绑定到指定 WorkflowAppRuntime。
- 顶部：主操作“新建触发源”。
- 创建流程：先选 runtime，再选模板 HTTP/WebSocket/ZeroMQ 等，再配置 endpoint/topic、映射、幂等字段和本地 buffer。
- 推理/流程映射：可视化输入字段如何映射到 App Contract。
- 列表：名称、类型、runtime、endpoint/topic、启用、最近触发、健康。
- 行操作：启用/禁用、测试、复制配置、查看最近回执、删除。
- 边界：PLC、相机等直连只作为受控 custom node 或外部代理集成，不显示为核心平台硬件驱动。
- 首次空状态：没有 `WorkflowAppRuntime` 时停在“选择 Runtime”，禁用协议模板、映射、测试和保存；引导从已发布 `FlowApplication` 创建并启动 healthy runtime。下方仍保留空列表表头。

### N01 自定义节点目录

- 状态：`现有增强`，关键。
- 目标：查看 NodePack、节点定义、版本、依赖、权限、启用状态、日志和审计。
- 布局：左侧分类/包列表，中间节点或包表格，右侧详情检查器。
- 顶部：搜索、刷新目录、筛选 enabled/phase/capability。
- 节点详情：display name、node_type_id、分类、说明、输入、输出、参数。
- 包详情：manifest、version、capabilities、entrypoint、permissions、compatibility、timeout、isolation、enabledByDefault。
- 标签：版本、依赖、日志、审计。
- 操作：启用、禁用、重新扫描；危险权限变更需要确认。
- 关键示例：barcode、camera、database、HTTP、OpenCV、PLC、SAM3、YOLOE；明确它们是扩展包，不是核心硬件链路。
- 首次空状态：本地 `custom_nodes/` 扫描结果为 0 时，保留三栏和表头；主操作为重新扫描，展示 NodePack 的 manifest、version、capabilities、config schema、timeout、禁用、依赖、权限和 isolation 要求，不提供云市场或自动启用。

## 8. 设置与诊断

### C01 设置与诊断

- 状态：`现有增强`，关键。
- 目标：集中展示偏好、服务、系统、Python、设备、会话、项目访问和 provider 状态。
- 布局：全宽设置工作台；左侧一级分类，第二列子项，右侧内容。
- 分类：常规、系统、访问与安全。
- 常规：语言、主题、信息密度、时间格式、日志级别显示偏好。
- 服务：API、WebSocket、worker profiles、数据库、对象存储、队列；显示状态、版本和最后检查。
- 系统：应用版本、主机、OS、CPU、内存、磁盘。
- Python：bundled/development runtime、Python 版本、环境路径、依赖摘要。
- 设备：CPU、CUDA GPU、OpenVINO GPU/NPU、TensorRT/CUDA/cuDNN 版本和可用性。
- 访问：当前会话、scopes、项目访问、runtime provider。
- 操作：复制诊断摘要、下载诊断包、刷新；不在普通设置中直接修改危险系统路径。
- 关键状态：一台 NVIDIA GPU 可用、OpenVINO NPU 不可用但有明确原因、六类 worker 状态可见。

## 9. 设计稿覆盖矩阵

第一轮视觉方向至少生成以下六张关键页：

1. D01 数据集工作台，浅色。
2. M02 创建训练任务，浅色。
3. M03 训练详情，浅色。
4. I01 推理实验室，浅色主体加深色图像画布。
5. W03 流程编辑器，深色。
6. C01 设置与诊断，浅色。

第二轮补齐 P01、T01、D04、M01、M05、R01、R02、W01、W02、X01、N01。

第三轮补齐所有创建向导、详情页、空状态、失败状态和窄桌面状态。

## 10. 页面间一致性检查

- 相同 TaskRecord 在任务中心、专用详情页和顶部任务活动中使用相同状态名称。
- 相同 ModelVersion 在训练、转换、部署和 workflow 中使用相同名称、版本和 task type。
- 相同 DeploymentInstance 在部署、推理和节点参数选择器中使用相同健康状态。
- DatasetVersion 与 DatasetExport 始终是不同资源，不把“版本”和“导出包”混写。
- WorkflowGraphTemplate、FlowApplication、WorkflowAppRuntime 和 WorkflowRun 分层显示。
- 任何“创建下一步”的入口都预填来源对象，但允许用户返回修改。
