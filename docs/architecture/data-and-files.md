# 数据和文件关系

## 文档目的

本文档用于说明平台里的关键对象、对象关系、版本链路和追踪方式，明确哪些内容放在权威元数据里，哪些内容放在对象存储里的大文件里。

本文档主要回答三个问题：平台里有哪些关键对象、这些对象怎么连起来、训练/转换/部署/推理/流程执行的结果怎么追踪。

## 适用范围

- 项目、数据集、模型、任务、部署、插件和集成对象的关系
- 后端服务中与数据集、模型、转换输出和结果暂存相关的领域层级
- 文件记录与文件内容分开保存的原则
- 版本链路、引用规则和回滚追踪关系
- 数据对象与运行时对象的权责边界

## 总体原则

- 元数据以数据库中的权威对象为主，文件内容以 ObjectStore 中的大对象为主
- 文件一旦对外可见，尽量当成不可变内容处理，用新版本替代原地覆盖
- 任务产生的结果应通过结果引用与版本链路挂接，而不是写成孤立文件
- 训练、转换、部署、推理和流程执行之间应通过对象关系而不是临时路径字符串衔接

## 对象分组

### 项目与空间对象

- Project：对象归属的顶层空间边界
- RuntimeProfile：运行时类型、目标环境与能力描述
- IntegrationEndpoint：外部系统接入配置与回调边界

### 数据对象

- Dataset：逻辑数据集定义
- DatasetVersion：可被训练、验证、推理或流程使用的具体数据版本

### 模型对象

- Model：逻辑模型条目，用来放同一条模型线的身份、业务标签和管理边界
- ModelVersion：模型的源版本，可来自预训练导入、训练产出或人工上传
- ModelBuild：面向特定运行时、硬件平台、精度或部署形态的派生 build，通常由转换任务产生

### 任务对象

- TrainingTask
- ValidationTask
- ConversionTask
- InferenceTask
- PipelineRun or PipelineExecution task

### 模型文件与结果文件对象

- ModelFile：模型文件、转换输出、benchmark 结果、配置包等文件记录
- FileRef：数据库中对 ObjectStore 内容的引用记录
- ResultFile：推理、流程执行、评估或后处理生成的结果文件记录

### 部署与流程对象

- DeploymentInstance：部署实例与已绑定的模型版本、运行时和配置
- PipelineTemplate：流程模板、节点图、参数和版本引用

### 插件对象

- PluginManifest：插件身份、能力、入口点和权限声明
- PluginVersion：插件的具体可启用版本与兼容性信息
- NodeDefinition：插件或核心节点的输入输出、参数和分类定义

## 核心关系链

### 数据到模型

- Project 之下可管理多个 Dataset
- Dataset 之下可生成多个 DatasetVersion
- TrainingTask 和 ValidationTask 引用 DatasetVersion 作为输入
- TrainingTask 产出新的 ModelVersion，并挂接一个或多个 ModelFile

### 预训练导入到模型注册

- 外部预训练模型导入后，应先落为 Project 下的一个 Model
- 首次导入形成一个 ModelVersion，source kind 标记为 pretrained-import
- 预训练模型原始权重、配置和来源说明通过 ModelFile 与 FileRef 挂接
- 后续微调训练可选择引用该 ModelVersion 作为 warm start 来源

### 模型到转换

- ConversionTask 默认读取某个 ModelVersion 或已有 ModelBuild
- ConversionTask 产出新的 ModelBuild，并挂接面向特定运行时或平台的新 ModelFile
- 转换前后对象之间应保留来源链路、兼容性信息、目标平台信息和 benchmark 记录

### 模型到部署

- DeploymentInstance 绑定某个可部署 ModelBuild；如未转换，也可绑定满足运行条件的 ModelVersion
- DeploymentInstance 同时绑定 RuntimeProfile、部署配置和回滚候选版本
- InferenceTask 引用 DeploymentInstance，而不是直接引用裸模型文件路径

### 推理与结果

- InferenceTask 读取 DeploymentInstance，并通过其绑定的 ModelVersion 或 ModelBuild 执行
- InferenceTask 产生临时运行结果、结构化摘要和可选持久化结果引用
- 需要保留的结果应提升为 ResultFile；仅用于短期查看或回传的结果应保留在 task-scoped staging 区

### 流程与插件关系

- PipelineTemplate 引用 NodeDefinition、PluginVersion、参数 schema 和节点连接关系
- PipelineTemplate 可引用逻辑输入类型、模型版本占位或具体集成端点
- 流程执行任务产出的结果也应形成可追踪的文件记录或结果引用

### 集成与回传关系

- IntegrationEndpoint 可以触发 InferenceTask、PipelineExecution 或插件回调任务
- 外部回调、结果上报和插件后处理应保留与原始 task id 或 deployment id 的关系

## 对象权责边界

### 后端服务里的数据和模型层级

- backend/service/domain/projects：定义 Project 聚合与归属边界
- backend/service/domain/datasets：定义 Dataset、DatasetVersion、导入记录和数据版本规则
- backend/service/domain/models：定义 Model、ModelVersion、ModelBuild、版本 lineage 和发布候选规则
- backend/service/domain/files：定义 FileRef、ModelFile、ResultFile、checksum、存储引用和保留策略
- backend/service/domain/tasks：定义 TrainingTask、ConversionTask、InferenceTask、PipelineExecutionTask 与状态迁移规则
- backend/service/domain/deployments：定义 DeploymentInstance、运行时绑定、回滚候选与发布状态

### application 层的典型用例分组

- datasets：导入、切分、冻结、归档和清理 DatasetVersion
- models：导入预训练模型、登记训练输出、创建版本、建立 lineage、打标签和归档
- conversions：提交转换任务、登记 ModelBuild、写入兼容性与 benchmark
- inference_results：写入 task staging、生成 ResultFile、执行保留或清理策略
- deployments：把 ModelVersion 或 ModelBuild 绑定到 DeploymentInstance，并维护回滚候选

### 数据库负责的内容

- 对象身份、版本号、状态、标签和元数据
- 对象之间的引用关系
- 任务状态、部署状态、插件启停状态和兼容性标记
- 文件引用信息、摘要信息和来源链路

### ObjectStore 负责的内容

- 模型文件、转换产物、样本文件、结果文件、日志归档和大对象输出
- 运行结果的原始文件内容
- 体积较大且不适合直接存放在数据库中的结构化或半结构化内容

## 关键对象定义

### Project

- 是数据、任务、模型、部署、流程和集成端点的统一归属容器
- 应作为权限、配额、审计和版本浏览的基本边界

### Dataset 与 DatasetVersion

- Dataset 表示逻辑集合
- DatasetVersion 表示一次固定输入快照，供训练、验证、流程和推理任务复用
- 任务应尽量绑定 DatasetVersion，而不是直接绑定临时文件目录

### DatasetImport 与 Canonical Annotation Schema

- 外部数据集在进入平台前可保留原始目录结构，但进入平台后应先形成一次 DatasetImport，再固化为 DatasetVersion
- DatasetImport 负责记录 source format、task type、image root、annotation root、split 信息、class map 和导入日志
- DatasetVersion 不直接等价于原始 YOLO、COCO、VOC 或其他文件夹结构，而应等价于平台冻结后的统一数据快照
- 平台内部应维护 canonical annotation schema，用统一字段描述图片、样本、类别、bbox、polygon、mask、keypoints 和元信息
- 不同模型训练前由 exporter 或 view builder 把 canonical schema 转换为对应训练后端所需的格式，而不是让每个训练后端直接面对各种原始目录结构

### 为什么不能直接靠原始目录结构统一

- YOLO、RT-DETR、SAM、传统 OpenCV 流程对输入要求并不一致，直接把原始目录结构当成系统内部主模型会导致后续扩展困难
- 同样是检测任务，不同训练后端也可能分别偏好 YOLO txt、COCO json 或自定义 manifest
- 分割任务除了 bbox 外还可能需要 polygon、mask bitmap、RLE 或 prompt 相关信息，不能假设所有“标注文本”都能直接互用
- 因此需要把“外部格式兼容”与“内部统一表示”分开：前者解决导入，后者解决平台内部管理与多模型复用

### 建议的内部统一粒度

- Project -> Dataset -> DatasetImport -> DatasetVersion
- DatasetVersion 下维护 categories、samples、annotations、splits、statistics、lineage
- Sample 负责 image_ref、尺寸、采集信息、来源路径和 split 标识
- Annotation 负责 task type、class id、bbox、polygon、mask ref、keypoints、attributes 和 iscrowd 等字段

### 推荐支持的外部数据集格式

- YOLO detection / segmentation / pose 目录
- COCO detection / segmentation / keypoints json
- Pascal VOC xml
- 图像目录 + 独立标注文本目录
- 图像目录 + mask 目录
- 后续可扩展 LabelMe、CVAT、Supervisely、自定义 json 或 csv

### 自动识别与显式声明策略

- 平台可以像 Roboflow 一样做格式自动识别，但自动识别只能作为导入便利能力，不能作为唯一权威判断
- 推荐导入时允许先自动识别候选格式，再由用户确认或覆盖 format type、task type 和 class map
- 若文件结构存在歧义，例如多个 json/xml/txt 混放、图片与标注目录不对齐、同目录存在多种任务标签，则必须要求显式声明
- 数据管理层最终记录的应是 DatasetImport.format_type 与 DatasetImport.task_type，而不是某次猜测结果

### 建议的导入最小声明

- format type：如 yolo, coco, voc, masks, custom-json
- task type：如 classification, detection, instance-segmentation, semantic-segmentation, keypoints
- image root
- annotation root or manifest file
- split strategy：显式 train/val/test 或导入后切分
- class map：类别 id 与名称映射
- optional attributes：难例标记、采集来源、场景标签、传感器信息等

### Canonical Annotation Schema 的目标

- 不要求所有模型共享同一种原始文件结构
- 只要求同一任务家族在平台内部共享同一组逻辑字段和版本管理方式
- 训练前再按模型后端导出为 YOLO、COCO 或其他特定训练视图
- 推理和评估结果也可回写到同一逻辑对象体系中，而不是变成新的孤立目录格式

### 模型家族与数据任务的关系

- YOLO 系列通常对应 detection、instance-segmentation、pose 等任务族
- RT-DETR 主要对应 detection，也可沿 detection canonical schema 导出目标训练视图
- SAM 更接近 segmentation 与 prompt-driven 交互能力，不应和检测模型简单视为同一训练格式，只能共享更高层的 segmentation 数据对象
- 因此平台统一的不是“所有模型共用一套原始标注文本”，而是“所有模型先映射到 task family，再共享 canonical dataset schema”

### 当前手头已有数据时的操作流程

1. 在 Project 下创建 Dataset
2. 选择导入方式，提供 image root、annotation root 或 manifest file
3. 让系统自动识别 YOLO / COCO / VOC 等候选格式，并由用户确认 task type、class map 和 split 信息
4. 系统生成一次 DatasetImport 记录，并把原始输入归档到 datasets/{dataset_id}/source 或导入批次路径
5. 系统把原始标签转换为 canonical annotation schema，生成冻结后的 DatasetVersion
6. 将已有预训练权重导入 models，形成 Model + ModelVersion
7. 创建训练任务时，选择 DatasetVersion、任务类型、训练 recipe 和 warm start 的 ModelVersion
8. 对应训练后端从 canonical schema 导出适配自己的训练视图，再启动训练
9. 训练产出登记为新的 ModelVersion，后续如需部署再转换为一个或多个 ModelBuild

### 对目录结构的建议

- 平台外部导入时需要识别图片目录和标注目录，但不要求所有用户先手工整理成唯一固定树
- 平台内部需要定义标准化的导入声明和 canonical schema，否则后端无法长期统一管理多模型训练
- 外部目录结构可以多样，内部 DatasetVersion 结构必须统一

### Model、ModelVersion 与 ModelBuild

- Model 是逻辑模型容器，不直接等价于某个具体权重文件
- ModelVersion 是源模型版本，表示一次明确可追踪的模型状态
- 预训练模型导入后应先形成 ModelVersion，而不是作为游离文件直接给任务使用
- 训练产出应登记为新的 ModelVersion，并保留训练来源、父版本和输入数据版本关系
- ModelBuild 是源模型转出来的部署 build，通常对应 ONNX、OpenVINO、TensorRT、CoreML 或特定量化版本
- ModelVersion 与 ModelBuild 都通过 ModelFile 挂接具体文件，但所在层级不同，不应混成一个对象

### ModelFile

- 是统一文件记录，不只代表训练得到的权重文件
- 也可以代表转换输出、benchmark 报告、推理结果包和模型配置包
- 应包含 file type、source lineage、compatibility、checksum 和 storage reference

### ResultFile 和 task staging

- ResultFile 用于保存需要复查、下载、复现、上报或再次进入流程的结果对象
- task staging 只用于短期暂存推理中间结果、上传回包、预览图和临时日志，不作为长期权威存储
- task staging 必须绑定 task id、retention policy 和清理时间，避免与正式文件混用
- 从 staging 提升为 ResultFile 时，应生成新的 FileRef，而不是重写既有路径

### DeploymentInstance

- 是“可运行的部署实体”，而不是简单的模型记录
- 应绑定模型版本、运行时配置、资源约束、暴露接口和回滚候选

### PipelineTemplate

- 定义流程图结构、节点参数和节点之间的连接关系
- 可以引用核心节点和插件节点
- 版本变化应可追踪，避免流程定义被原地覆盖后失去可回放性

### PluginManifest、PluginVersion 与 NodeDefinition

- PluginManifest 负责定义插件身份和能力声明
- PluginVersion 负责定义某个具体发布版本及兼容性范围
- NodeDefinition 负责定义可在节点编辑器中展示和执行的节点能力
- 三者应关联但职责分离，避免把节点定义直接混写到启用状态记录中

## 可追溯规则

- 每个任务都应能追到输入引用、执行配置、运行时环境、插件版本和结果引用
- 每个部署都应能追到来源模型、运行时 profile、配置版本和回滚候选
- 每个 ModelVersion 都应能追到来源类型：pretrained-import、training-output、manual-upload 或 conversion-promotion
- 每个 ModelBuild 都应能追到来源 ModelVersion、目标运行时、目标硬件、精度策略和转换任务
- 每个流程模板都应能追到节点定义来源和插件版本引用
- 每个外部回调或上报结果都应能追到原始任务或部署实例

## 回滚与替换原则

- 回滚通过切换版本引用实现，而不是覆盖文件内容
- 插件回滚、模型回滚和部署回滚都应保留历史链路
- 数据版本、模型版本和流程模板版本之间应能形成组合快照，支撑问题复现

## ObjectStore 推荐布局

以下布局用于说明“对象如何组织”，不是要求把业务逻辑写死到路径字符串中。业务层始终通过 FileRef 和 ObjectStore 接口访问内容。

```text
object-store/
└─ projects/
	└─ {project_id}/
		├─ datasets/
		│  └─ {dataset_id}/
		│     ├─ source/
		│     └─ versions/
		│        └─ {dataset_version_id}/
		│           ├─ manifests/
		│           ├─ samples/
		│           ├─ indexes/
		│           └─ exports/
		├─ models/
		│  └─ {model_id}/
		│     ├─ versions/
		│     │  └─ {model_version_id}/
		│     │     ├─ source/
		│     │     ├─ checkpoints/
		│     │     ├─ configs/
		│     │     └─ reports/
		│     └─ builds/
		│        └─ {model_build_id}/
		│           ├─ packages/
		│           ├─ benchmarks/
		│           └─ manifests/
		└─ task-runs/
			├─ training/{task_id}/
			├─ conversion/{task_id}/
			├─ inference/{task_id}/
			│  ├─ staging/
			│  └─ promoted-results/
			└─ pipeline/{task_id}/
```

## 放置与管理规则

### 数据集放哪里

- 逻辑上放在 Project 下的 Dataset 与 DatasetVersion 中管理
- 文件内容放在 ObjectStore 的 datasets 路径下，按 dataset id 和 dataset version id 分层
- 管理动作由后端服务的 datasets 用例处理，包括导入、冻结、标记、归档和清理

### 预训练模型放哪里

- 预训练模型不作为“系统公共裸文件夹”直接使用，而应先导入到某个 Project 的 models
- 导入后形成 Model + ModelVersion，source kind 标记为 pretrained-import
- 原始权重、配置和许可说明挂到 ModelFile 与 FileRef，物理内容放在 models/{model_id}/versions/{model_version_id}/source 下

### 训练后模型放哪里

- 训练完成后先登记为新的 ModelVersion，不直接覆盖预训练版本
- checkpoint、最佳权重、训练配置、指标报告等以 ModelFile 形式挂接
- 物理内容放在 models/{model_id}/versions/{model_version_id}/checkpoints、configs、reports 下

### 转换后的模型放哪里

- 转换结果登记为 ModelBuild，而不是与源模型版本混成同一对象
- 每个 ModelBuild 绑定目标运行时、硬件平台、精度策略和来源转换任务
- 物理内容放在 models/{model_id}/builds/{model_build_id}/packages 下，benchmark 与转换 manifest 分开存放

### 推理结果暂存放哪里

- 暂存结果放在 task-runs/inference/{task_id}/staging 下，只用于短期预览、回包或二次处理
- staging 结果必须带 TTL、大小限制和清理策略，不参与长期模型版本管理
- 需要长期保留的结果由后端服务提升为 ResultFile，并移动或复制到 promoted-results 或统一结果文件路径

## 管理组织建议

- 数据集、模型、部署、任务和结果都先按 Project 归属，再按对象 id 管理，避免直接按用户名或日期裸分目录
- 逻辑对象用数据库做权威索引，路径只做存储组织，不做业务主键
- 预训练导入、训练产出、转换产出和推理结果分别对应不同对象层级，避免都塞进 ModelFile 一个层里
- 清理策略分三类：dataset archive、task staging cleanup、file retention，不混用同一规则
- UI 和 API 默认展示 Model -> ModelVersion -> ModelBuild 的三级结构，而不是直接暴露底层文件树

## 推荐后续文档

- [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)
- [docs/architecture/backend-service.md](backend-service.md)
- [docs/architecture/system-overview.md](system-overview.md)
- [docs/architecture/plugin-system.md](plugin-system.md)