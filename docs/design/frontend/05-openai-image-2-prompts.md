# OpenAI Image 2 前端页面提示词

## 1. 使用方式

OpenAI Image 2 适合先确定视觉方向、布局比例、信息密度和关键状态，不负责生成最终可运行界面。推荐采用“固定基础提示 + 单页提示 + 固定排除项”的组合方式。

每次只生成一个页面或一个明确状态。不要在一张图中要求同时展示多个页面。需要设计同一页面的不同状态时，先选定标准状态，再基于选定图生成运行中、失败、空状态等变体。

## 2. 固定基础提示

将以下内容放在每条单页提示之前：

```text
为 AMVision 本地优先工业视觉服务平台设计一张高保真桌面端 Web 应用界面截图。整体风格是“人工、洁净、未来感”：人主导、可信、可追溯的工程工具感；稳定网格、克制留白、精细分隔线和高信息密度；未来感来自实时状态、精密图像叠加、节点连线和微型数据可视化，不来自科幻装饰。

使用 Vue 3 工业工作台可实现的平面 UI，正面正交视角，不放在笔记本电脑或手机模型中。16:10 宽屏构图，目标接近 1920×1200。默认浅色主题：#F6F7F9 页面背景、白色主表面、#171A1F 强文字、#667085 次要文字、#E4E7EC 细边框、#087A56 深翡翠绿主操作；沉浸画布可使用 #101010 和 #171918。圆角仅 4–8px，阴影很轻，只用于浮层。中文界面，模型名、runtime、format、ID 保持英文。

左侧 232px 紧凑导航，分组为工作空间、数据与模型、自动化、系统；顶部 54px 上下文栏显示当前 Project、全局搜索、连接状态、运行任务和用户菜单。图标为一致的细线图标。界面真实、清晰、可实现，所有信息有明确层级和对齐。
```

## 3. 固定排除项

将以下内容放在每条单页提示之后：

```text
不要生成营销官网、通用 SaaS KPI 大屏、云服务宣传页、人物插画、机器人、3D 等距服务器、全息 HUD、赛博朋克、蓝紫霓虹、彩虹渐变、大面积玻璃拟态、夸张光晕、巨大圆角卡片、超大空白、悬浮设备模型、随机代码雨或无意义图表。不要出现 React/Angular 品牌，不要出现相机和 PLC 的核心直连控制台。避免乱码、重复按钮、无法辨认的小字和逻辑冲突的状态。
```

## 4. 建议生成参数与迭代

- 构图：宽屏、正面、完整应用截图、无环境背景。
- 第一轮：一次生成 2–4 个构图变体，只评价网格、密度、视觉语言。
- 第二轮：选一张作为参考，要求保持外壳、颜色、字体、间距，只修改页面内容。
- 第三轮：基于同一参考图生成运行中、失败、空状态和右侧检查器打开状态。
- 文字：图像生成文字可能不完全准确，评审重点是信息位置和视觉层级；最终文案以逐页规格为准。

## 5. 全局外壳提示

### G01 浅色工作台外壳

```text
设计 AMVision 浅色主工作台外壳。左侧导航顶部是简洁 AMVision 字标和 Project 切换器“产线视觉验证”，导航当前项为“数据集”；顶部栏有面包屑、搜索框“搜索资源或 ID”、绿色连接状态点、3 个运行任务提示和用户 amvar。主内容区展示一个中性页面占位，重点表现导航密度、边框、字体、状态和 12 列网格。界面像成熟的工程工具，不像模板后台。
```

### G02 深色沉浸工作台外壳

```text
设计 AMVision 深色沉浸工作台外壳，用于流程图和图像检查。保留紧凑顶部命令栏，左侧工具区可以折叠，中间为大画布，右侧为 360px 检查器。背景为深墨黑和炭灰，翡翠绿只用于选择、运行正常和主要操作。加入很轻的点阵网格、坐标刻度和清楚的分隔线，不能有霓虹光晕。
```

### G03 资源列表状态参考

```text
创建 AMVision ResourceList States 设计系统参考画板。统一展示首次加载、筛选无结果、后端重连三种列表内容区状态，保持 PageHeader、FilterBar 和表头结构稳定。加载使用行骨架；筛选无结果保留筛选标签并提供清除筛选；重连保留只读缓存、最后同步、服务地址、重试次数并禁用写操作。标明适用于 P01、T01、D01、M01、M04、R01、W01、X01、N01。
```

### G04 有限任务生命周期参考

```text
创建 AMVision Finite TaskRecord Lifecycle 设计系统参考画板。用相同列结构展示 queued、running、succeeded、failed、cancelled 的状态徽标、阶段/进度、时间、结果/原因、允许操作和事件序列。终态不再接收 cancel；failed 重试创建新 TaskRecord；cancelled 的当前节点必须是最后的 terminal/cancelled。明确它不等同于 DeploymentInstance 或 WorkflowAppRuntime。
```

### G05 长期实例生命周期参考

```text
创建 AMVision Long-running Runtime Lifecycle 设计系统参考画板，适用于 DeploymentInstance 与 WorkflowAppRuntime。使用 RuntimeStateBadge、RuntimeActions、RuntimeHealthPanel、RuntimeEventTimeline，以一致结构展示 stopped、starting、healthy、degraded、failed。包含进程、heartbeat、uptime、endpoint、P95、queue depth、恢复预算和允许操作；degraded 仍在服务，不自动停止。底部展示 stopped → starting → healthy → degraded / failed 事件序列，并明确停止或删除前检查 WorkflowAppRuntime 与 TriggerSource 引用。说明长期实例不使用 succeeded/cancelled 这类有限 TaskRecord 终态。
```

### G06 危险操作确认参考

```text
创建 AMVision Destructive Action Confirmation 设计系统参考画板，统一展示删除 DatasetImport、删除 DatasetExport、删除 TrainingTask、删除 ConversionTask、停止 DeploymentInstance、删除 WorkflowAppRuntime、禁用高权限 NodePack 七种模式。每个确认框包含 ResourceIdentity、ImpactSummary、DependencyBlocker、恢复边界和 SafeDefaultActions。DatasetImport/Export 删除不删除 DatasetVersion；被登记或被部署使用的训练/转换结果阻止删除；停止 DeploymentInstance 可恢复；WorkflowAppRuntime 必须先处理 TriggerSource 和 active run；NodePack 禁用不删除包文件。取消为默认焦点，输入为空、输入不匹配或 REST 预检存在 blocker 时危险按钮禁用。
```

## 6. 系统入口页面提示

### S01 启动检查

```text
创建 AMVision 启动检查页面。全屏浅灰背景，左上显示产品名和版本 v0.1.4，中间是宽约 520px 的克制检查面板。垂直列出“连接本地 API、恢复会话、检查数据库、加载节点目录、启动工作台”，前三项绿色完成，第四项正在检查并带低调活动指示，第五项待处理。底部显示 http://127.0.0.1:8000、耗时和“查看诊断”次按钮。没有插画。
```

### S02 登录

```text
创建 AMVision 登录页。左侧 34% 是深墨色品牌区域，只有 AMVision 字标、短句“本地视觉服务平台”和一组非常克制的细线网格；右侧是浅色登录区域。表单标题“进入工作台”，用户名 amvar、密码、显示密码、绿色实心登录按钮，下方显示本地服务地址和版本。页面稳重、专业、离线优先，没有社交登录和营销内容。
```

### S03 离线状态

```text
创建 AMVision 后端离线状态页。保留简化工作台外壳，内容中心显示断开连接线性图标、标题“本地服务不可用”、最后连接时间、服务地址和说明“只读缓存仍可查看”。提供绿色“重新连接”和次按钮“进入只读模式”，顶部连接状态为红色并写“离线”。
```

## 7. 项目与任务提示

### P01 项目列表

```text
创建 AMVision 项目页面。页面标题“项目”，右上主按钮“新建项目”、次按钮“生成 SDK 配置包”。主体是紧凑表格，包含“产线视觉验证、包装缺陷、条码识别”三个项目，字段为名称、短 ID、描述、数据集、模型、流程应用、更新时间，当前项目行用浅绿色选择态。右侧打开新建项目抽屉，只有名称和描述两个清楚字段。表格下方不要放无意义图表。
```

### P02 项目概览

```text
创建“产线视觉验证”项目概览。顶部显示项目名、短 ID、编辑和生成 SDK 配置包。第一行四个紧凑指标：数据版本 12、可用模型 7、健康部署 3、运行流程 2。中部是最近资源时间线和当前运行任务列表，下部四个继续工作区域分别为导入数据、训练模型、部署模型、编辑流程。一个训练任务显示 epoch 37/100，一个 TensorRT 部署显示健康。避免销售仪表盘风格。
```

### T01 任务中心

```text
创建 AMVision 任务中心。顶部四个小型状态统计：运行中 3、排队 2、失败 1、今日完成 14。下方筛选栏包含 Project、任务类型、状态、时间和按 task ID 搜索。主表格显示 dataset-import、dataset-export、training、conversion、evaluation、inference 六类任务，运行任务有真实阶段和进度，失败任务有暗红色状态和“查看错误”，右上角显示 WebSocket 已连接与最后同步时间。信息密集但不拥挤。
```

空状态补充提示：

```text
保持 T01 外壳、四项统计、筛选和表头不变，所有数量为 0。内容区显示“还没有有限任务记录”，说明 DatasetImport/Export、TrainingTask、ConversionTask、EvaluationTask、有限 inference 或 WorkflowRun 从各自业务入口创建；不提供通用新建任务按钮。用小型生命周期说明 queued → running → succeeded/failed/cancelled，并明确 DeploymentInstance 与 WorkflowAppRuntime 是长期资源，不进入任务中心。主操作为打开项目概览。
```

### T02 任务详情

```text
创建一个失败的 conversion task 详情页。顶部显示 task ID、conversion、失败状态、所属项目和“重新查看来源”操作。摘要区有队列、worker、阶段、开始时间、耗时和重试次数。中间是事件时间线，从 queued 到 claimed、running，最后在 TensorRT build 阶段失败。下方错误区清楚显示错误码、简短原因、版本兼容建议和可展开 stack trace，右侧有复制诊断信息按钮。
```

## 8. 数据集页面提示

### D01 数据集工作台

```text
创建 AMVision 数据集工作台。标题“数据集”，右上“导入数据集”主按钮和“创建导出”次按钮。局部标签为数据集、导入记录、数据版本、导出记录，当前是“数据集”。筛选任务类型和格式。表格包含 VOC2012 Detection、Medical Pills、Construction PPE、BarcodeQR、Industrial Parts OBB，显示 task type、来源格式、当前版本、train/val/test 数量、类别数、更新时间。VOC2012 行显示 detection、VOC、v1、11,540 samples、20 classes。界面清洁、紧凑、有浅绿色选中行。
```

### D02 导入向导

```text
创建 AMVision 数据集导入向导的“预检查”步骤。顶部五步进度：上传、数据定义、split 与类别、预检查、提交，当前第四步。左侧摘要显示文件 VOC2012.zip、detection、VOC；中间显示目录树 JPEGImages、Annotations、ImageSets/Main；右侧校验摘要显示 11,540 images、11,540 XML、train 5,717、val 5,823、20 classes、0 errors、2 warnings。底部有返回和绿色“提交导入”。像工程校验工具，不像云上传营销页。
```

### D03 导入详情

```text
创建成功的 VOC2012 数据集导入详情。顶部是 import ID、成功状态、detection/VOC、刷新和删除。阶段条从上传到版本落盘全部完成。下方左右两列：校验报告只有两个黄色 warning；检测结果显示目录结构与 split；类别映射表列出 person、car、dog 等；底部突出已生成 DatasetVersion v1，并提供“查看版本”和绿色“创建导出”。
```

### D04 数据版本详情

```text
创建 VOC2012 Detection 数据版本 v1 详情。顶部显示只读版本、来源 import。指标为 11,540 samples、27,450 objects、20 classes、train 5,717、val 5,823。局部标签概览、样本、类别、标注质量、导出记录、元数据，当前打开“样本”。主体左侧是高密度工业/街景图像网格，图片上有克制橙色检测框；顶部可筛选 split、类别和空标注；右侧检查器显示选中图像尺寸、split、对象列表和坐标。主按钮“创建导出”。
```

### D05 创建导出

```text
创建数据集导出向导的兼容性检查步骤。来源为 VOC2012 Detection v1，目标模型 YOLO11 detection，导出格式 yolo-detection-v1。展示 train/val 完整、20 classes、11,540 images、预计磁盘 1.8 GB，全部检查通过。旁边用简洁关系图显示 DatasetVersion → DatasetExport → TrainingTask。底部绿色按钮“创建导出”。
```

### D06 导出详情

```text
创建成功的 yolo-detection-v1 DatasetExport 详情。顶部显示 export ID、成功、下载、绿色“用此导出创建训练任务”。摘要显示来源 VOC2012 v1、任务 detection、兼容 YOLOv8/YOLO11/YOLO26。包文件区显示 data.yaml、images、labels、package.zip、大小和 checksum；下方 split 表与 20 类别表紧凑排列，原始 metadata 折叠。
```

## 9. 模型、训练与评估提示

### M01 模型工作台

```text
创建 AMVision 模型工作台。顶部任务标签 classification、detection、segmentation、pose、obb，当前 detection。第二层标签为模型版本、训练任务、转换任务、构建产物。主表格显示 YOLOX、YOLOv8、YOLO11、YOLO26、RF-DETR 的 detection 模型版本，字段包括来源、版本、mAP、PyTorch/ONNX/OpenVINO/TensorRT 构建状态和更新时间。右上“创建训练”和“转换模型”。突出 YOLO11-s v4 有四种构建产物，不要显示 RF-DETR 的 pose/obb。
```

### M02 创建训练任务

```text
创建 AMVision 创建训练任务向导的参数步骤。顶部五步：任务与模型、数据、初始化、参数、确认。当前模型 YOLO11-s detection，数据 VOC2012 yolo-detection-v1，初始化为平台预训练权重 warm start。主体为专业参数表单：epochs 100、batch Auto、input size 640×640、device CUDA:0、AMP 开启、optimizer AdamW、learning rate、workers、checkpoint interval。右侧固定摘要显示 train 5,717、val 5,823、20 classes 和兼容性全通过。高级参数折叠，底部绿色“下一步”。
```

### M03 训练详情

```text
创建运行中的 YOLO11-s detection 训练详情。顶部显示任务名、running、epoch 37/100、取消按钮。摘要显示 VOC2012 export、CUDA:0、640、AutoBatch、AMP。中间有三个精密折线图：train loss、val loss、mAP50-95，best epoch 34 有竖直标记；图表不使用渐变面积。右侧进度显示当前 batch 112/179、ETA 1h42m。下方分区显示完成 epoch 指标、当前 batch 指标、validation 指标和输出文件 best.pt、latest.pt、metrics.json、train.log。
```

### M04 验证与评估中心

```text
创建 AMVision 验证与评估中心。顶部“创建评估”，标签为验证会话、评估任务、比较。表格显示不同 ModelVersion 在 VOC2012 val、Medical Pills test 等数据上的任务、split、主指标、runtime、状态、完成时间。顶部筛选 model/task/dataset/status。右侧有小型比较篮，已选择 YOLO11-s v3 和 v4，提示只能比较相同任务与数据。
```

空状态补充提示：

```text
保持 M04 的验证会话、评估任务、比较标签、筛选、表头和比较篮。所有数量为 0，比较篮为空。展示 ModelVersion → 兼容 DatasetExport val/test split → EvaluationTask 三步前置关系；缺少前两项时禁用创建评估和比较结果，主操作为打开模型工作台，次入口为数据集导出。说明 ValidationSession 不产生正式归档结果，EvaluationTask 是有限任务，无 test split 时不能用 val 冒充 test。
```

### M05 评估详情

```text
创建 YOLO11-s 在 VOC2012 val 上的 detection 评估详情。顶部核心指标 mAP50-95 0.482、mAP50 0.721、precision 0.764、recall 0.688。下方标签概览、按类别、PR 曲线、混淆矩阵、样本，当前是按类别与错误样本组合视图。左侧紧凑类别表突出 person、car、bottle；中部是克制 PR 曲线；右侧/下部为 FP、FN 图像样本画廊，框和 GT/Prediction 图例清楚。提供导出报告。
```

### M06 模型版本详情

```text
创建 YOLO11-s Detection v4 模型版本详情。顶部可用状态和“创建转换”。显示来源链 TrainingTask → VOC2012 yolo export → DatasetVersion v1。摘要有 best mAP、20 classes、640×640、创建时间。主体是构建矩阵，行是 PyTorch、ONNX、ONNX optimized、OpenVINO IR、TensorRT FP16，列为状态、文件大小、设备、部署数。底部列出评估、部署和 workflow 引用。
```

### M07 创建转换

```text
创建模型转换向导的目标参数步骤。来源 YOLO11-s Detection v4，左侧目标格式四选一：ONNX、ONNX optimized、OpenVINO IR、TensorRT engine，当前 TensorRT。参数显示 FP16、static shape 1×3×640×640、workspace 4 GB、CUDA:0、TensorRT 10.16。右侧兼容性检查显示 NVIDIA driver、CUDA、TensorRT wheel/DLL/trtexec 版本一致。不要显示 CoreML 或 ARM NPU 为可用选项。
```

### M08 转换详情

```text
创建成功的 TensorRT conversion task 详情。顶部显示 succeeded、YOLO11-s Detection、TensorRT FP16。摘要下方是转换阶段时间线：export ONNX、simplify、build engine、validate outputs、register ModelBuild 全部完成。构建产物表显示 model.engine、大小、checksum、CUDA 设备、绿色“创建部署”。下方数值一致性摘要清楚，原始 spec JSON 默认折叠。
```

## 10. 部署与推理提示

### R01 部署工作台

```text
创建 AMVision 部署工作台。顶部“新建部署”和设备能力。表格显示三个长期实例：YOLO11 TensorRT FP16 sync 在 CUDA:0 健康，RF-DETR OpenVINO FP16 async 在 NPU 健康，YOLOv8 ONNX Runtime CPU 已停止。字段为名称、model/task、runtime、device、模式、health、uptime、P95。选中第一行，右侧运行面板显示进程、endpoint、输入 schema 和事件，操作有启动/停止/重启/预热/打开推理。必须像服务控制面，不像任务列表。
```

### R02 部署实例详情

```text
创建 YOLO11 TensorRT FP16 同步部署实例详情。顶部健康绿色状态、uptime 3d 14h、停止/重启/打开推理。第一行显示 ModelBuild、CUDA:0、FP16、sync。中部监视图显示最近 30 分钟请求率、平均/P95 时延、错误率，克制细线图。下方标签接口、输入输出、事件、日志、配置、引用；当前接口页展示 POST endpoint、请求示例、复制按钮和被两个 Workflow Runtime 引用的提示。
```

### I01 推理实验室

```text
创建 AMVision 推理实验室。顶部选择健康的 YOLO11-s Detection / TensorRT FP16 / CUDA:0，切换为同步推理。主体左栏是图片上传、confidence 0.35、IoU 0.7、类别筛选和“立即推理”；中间是深色大图画布，真实工业包装图片上有精细橙色检测框、类别和分数；右栏显示总耗时 12.8 ms、preprocess/inference/postprocess 分解、结果对象列表和结构化 JSON 标签。底部异步任务历史表。界面以图像结果为核心。
```

## 11. 流程与扩展提示

### W01 流程应用列表

```text
创建 AMVision 流程应用列表。顶部“新建流程”。上方小型运行概况显示健康 runtime 4、停止 2、异常 1。表格显示“包装缺陷检测、条码读取、空盘检测”等应用，字段为模板版本、runtime 数、触发源、最近 run、状态、更新时间。行操作为查看、打开图编辑器、创建 runtime。用资源列表风格，不要画成自动化营销模板市场。
```

### W02 流程应用详情

```text
创建“包装缺陷检测”FlowApplication 详情。顶部显示版本 v7、编辑流程和创建 runtime。上部摘要和 App Contract 表列出 image 输入、result 输出。中部 Runtime 表有两个实例，显示健康、worker、uptime、触发源和启动/停止/重启/健康检查。下部左侧是 HTTP endpoint 与请求示例，右侧是最近回执 run ID、耗时、输出摘要；底部 TriggerSource 表显示 ZeroMQ image trigger 和 HTTP trigger。
```

### W03 流程编辑器

```text
创建 AMVision 深色全屏流程编辑器。顶部紧凑命令栏显示“包装缺陷检测 v7”、已保存、撤销重做、校验、试跑、绿色发布。左侧节点库按 Input、Vision、Model、Logic、Output、Custom 分类。中间大画布有清晰节点链：Image Input → Resize → YOLO11 Deployment → Filter Detections → Count Objects → Rule Decision → HTTP Response，另有 Draw Detections 分支；连线和端口类型清楚，节点组边界低调。YOLO11 节点被选中有翡翠绿边框。右侧检查器显示 deployment instance、confidence、输入输出。底部运行面板展示每节点耗时和成功图像预览。未来感精密但无霓虹。
```

### X01 触发源

```text
创建 AMVision TriggerSource 页面。顶部“新建触发源”。上方创建区选中一个健康 Workflow Runtime 和 ZeroMQ Image Trigger 模板，表单显示 endpoint、topic、idempotency key path、LocalBuffer pool，以及输入字段到 App Contract 的映射。下方表格显示 HTTP、WebSocket、ZeroMQ 触发源的 runtime、endpoint/topic、启用、最近触发和健康。没有相机或 PLC 核心驱动配置。
```

空状态补充提示：

```text
保持 X01 的选择 Runtime、选择模板、配置与检查三步结构，当前停在第一步。没有 WorkflowAppRuntime 时禁用协议模板、endpoint/topic、字段映射、LocalBuffer、测试与保存，并展示 FlowApplication 发布 → 创建并启动 healthy WorkflowAppRuntime → 创建 TriggerSource 的前置链。下方保留 0 条触发源表头。主操作打开流程应用；Camera/PLC 直连仍只属于受控 Custom Node 或外部代理。
```

### N01 自定义节点目录

```text
创建 AMVision 自定义节点目录。三栏布局：左侧包与分类，包含 barcode、camera、database、http、opencv、plc、sam3、yoloe；中间为节点定义列表，字段有名称、node_type_id、phase、enabled、capabilities；右侧检查器打开 OpenCV 节点包，显示 manifest version、permissions、isolation、timeout、inputs、outputs、parameters。下方标签为版本、依赖、日志、审计。使用克制的能力标签和清楚的启用状态。
```

空状态补充提示：

```text
保持 N01 三栏、搜索、筛选和节点定义表头，本地 custom_nodes/ 最近扫描结果为 0。左栏显示没有已登记的扩展 NodePack，主操作重新扫描；中栏展示 manifest、version、capabilities、config schema、timeout、禁用机制、依赖、权限、entrypoint、compatibility 和 isolation 要求；右栏为未选择状态，启用、禁用、回滚均禁用。说明目录扫描不上传云端，也不会自动启用包。
```

## 12. 设置提示

### C01 设置与诊断

```text
创建 AMVision 设置与诊断页面。全宽三栏设置布局：左侧一级分类“常规、系统、访问与安全”，中间子项“关于、主机、Python、设备”，右侧为设备诊断。显示 NVIDIA GPU 可用、CUDA 和 TensorRT 版本一致、OpenVINO CPU/GPU 可用、NPU 不可用并给出简短原因；下方显示 dataset-import、dataset-export、training、conversion、evaluation、inference 六类 worker 状态。顶部有“刷新”和“下载诊断包”，信息精确、不做消费级设置页。
```

## 13. 关键状态变体提示

### 运行中变体

```text
保持参考页面的所有布局、色彩、字体、导航和组件不变，只把核心任务改为运行中状态。显示真实阶段名、当前进度、开始时间、ETA、低调活动指示和可用的取消操作。不要更改页面结构，不要增加装饰。
```

### 失败变体

```text
保持参考页面视觉系统不变，把核心任务或运行实例改为失败状态。使用暗红色文字、图标和细边框，不使用大面积红底。首屏显示错误摘要、失败阶段、最后成功步骤、可复制错误码和明确恢复操作；原始 stack trace 放在折叠区。
```

### 空状态变体

```text
保持参考页面外壳和筛选结构不变，生成真实的空状态。使用小型线性图标、直接标题、原因说明和一个主操作，不使用人物插画。空状态需要说明创建第一个资源所需的上一步条件。
```

### 窄桌面变体

```text
保持相同设计系统，将页面适配到 1366×768。左侧导航收为 64px 图标栏，隐藏次要表格列，右侧检查器改为覆盖式面板，主操作和关键状态仍可见。不要转成手机页面。
```
