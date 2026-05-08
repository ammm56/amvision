# 数据和文件关系

## 文档目的

本文档用于说明平台里的关键对象、对象关系、版本链路和追踪方式，明确哪些内容放在正式元数据里，哪些内容放在对象存储里的大文件里。

本文档主要回答三个问题：平台里有哪些关键对象、这些对象怎么连起来、训练/转换/部署/推理/流程执行的结果怎么追踪。

## 适用范围

- 项目、数据集、模型、任务、部署、插件和集成对象的关系
- 后端服务中与数据集、模型、转换输出和结果暂存相关的领域层级
- 文件记录与文件内容分开保存的原则
- 版本链路、引用规则和回滚追踪关系
- 数据对象与运行时对象的权责边界

## 总体原则

- 元数据以数据库中的正式对象为主，文件内容以 ObjectStore 中的大对象为主
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

- Model：逻辑模型条目，用来放同一条模型线的身份、业务标签和管理边界；当前显式区分 Project 内 Model 与平台基础模型
- ModelVersion：模型的源版本，可来自预置预训练模型登记或训练产出
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

### 预置预训练模型登记到模型注册

- 开发阶段已放到磁盘中的预训练模型，应先登记为平台基础模型，而不是任何单个 Project 下的业务模型
- 首次登记形成一个 ModelVersion，source kind 标记为 pretrained-reference
- 预训练模型原始权重、配置和来源说明通过 ModelFile 与 FileRef 挂接，默认直接引用现成磁盘路径
- 后续任意 Project 的微调训练都可选择引用该 ModelVersion 作为 warm start 来源

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

- datasets：导入、切分、生成版本、归档和清理 DatasetVersion
- models：登记预置预训练模型、登记训练输出、创建版本、建立 lineage、打标签和归档
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

### DatasetImport 与通用数据格式

- 外部数据集在进入平台前可保留原始目录结构，但进入平台后应先形成一次 DatasetImport，再固化为 DatasetVersion
- DatasetImport 负责记录 source format、task type、image root、annotation root、split 信息、class map 和导入日志
- DatasetVersion 不直接等价于原始 YOLO、COCO、VOC 或其他文件夹结构，而是平台整理后的统一数据版本
- 平台内部应维护通用数据格式，用统一字段描述图片、样本、类别、bbox、polygon、mask、keypoints 和元信息
- 不同模型训练前由 exporter 把通用数据格式转换为对应训练后端所需的格式，而不是让每个训练后端直接面对各种原始目录结构
- 当前第一阶段导入实现只支持 COCO detection json 和 Pascal VOC detection xml，并统一生成 detection 类型的 DatasetVersion
- COCO detection 第一阶段同时兼容传统 annotations/*.json 布局，以及 Roboflow 风格 train、val、valid、test 目录内各自携带 _annotations.coco.json 的 split-local manifest 布局
- 第一阶段生成版本时统一把类别表重排为连续 0-based category_id，把 VOC 的 xyxy 框转换为 xywh absolute bbox

### 为什么不能直接靠原始目录结构统一

- YOLO、RT-DETR、SAM、传统 OpenCV 流程对输入要求并不一致，直接把原始目录结构当成系统内部主模型会导致后续扩展困难
- 同样是检测任务，不同训练后端也可能分别偏好 YOLO txt、COCO json 或自定义 manifest
- 分割任务除了 bbox 外还可能需要 polygon、mask bitmap、RLE 或 prompt 相关信息，不能假设所有“标注文本”都能直接互用
- 因此需要把“外部格式兼容”与“内部通用格式”分开：前者解决导入，后者解决平台内部管理与多模型复用

### 建议的内部统一粒度

- Project -> Dataset -> DatasetImport -> DatasetVersion
- DatasetVersion 下维护 categories、samples、annotations、splits、statistics、lineage
- Sample 负责 image_ref、尺寸、采集信息、来源路径和 split 标识
- Annotation 负责 task type、class id、bbox、polygon、mask ref、keypoints、attributes 和 iscrowd 等字段

### 推荐支持的外部数据集格式

- 第一阶段导入：COCO detection json、Pascal VOC detection xml
- 扩展导入：YOLO detection / segmentation / pose 目录
- 扩展导入：COCO segmentation / keypoints json
- 图像目录 + 独立标注文本目录
- 图像目录 + mask 目录
- 后续可扩展 LabelMe、CVAT、Supervisely、自定义 json 或 csv

### 自动识别与显式声明策略

- 平台可以像 Roboflow 一样做格式自动识别，但自动识别只能作为导入便利能力，不能作为最终判断
- 推荐导入时允许先自动识别候选格式，再由用户确认或覆盖 format type、task type 和 class map
- COCO detection 的 split 推断应先看 manifest 父目录，再看 manifest 文件名；valid 统一归一化为 val
- 若文件结构存在歧义，例如多个 json/xml/txt 混放、图片与标注目录不对齐、同目录存在多种任务标签，则必须要求显式声明
- 数据管理层最终记录的应是 DatasetImport.format_type 与 DatasetImport.task_type，而不是某次猜测结果

### 建议的导入最小声明

- format type：如 yolo, coco, voc, masks, custom-json
- task type：如 detection, instance-segmentation, semantic-segmentation, pose
- image root
- annotation root or manifest file
- split strategy：显式 train/val/test 或导入后切分
- class map：类别 id 与名称映射
- optional attributes：难例标记、采集来源、场景标签、传感器信息等

### 通用数据格式的目标

- 不要求所有模型共享同一种原始文件结构
- 只要求同一任务类型在平台内部共享同一组逻辑字段和版本管理方式
- 训练前再按模型后端导出为 YOLO、COCO 或其他特定数据集结构
- 推理和评估结果也可回写到同一逻辑对象体系中，而不是变成新的孤立目录格式

### 模型与数据任务的关系

- YOLO 系列通常对应 detection、instance-segmentation、pose 等任务类型
- RT-DETR 主要对应 detection，也可沿 detection 通用数据格式导出目标数据集结构
- SAM 更接近 segmentation 与 prompt-driven 交互能力，不应和检测模型简单视为同一训练格式，只能共享更高层的 segmentation 数据对象
- 因此平台统一的不是“所有模型共用一套原始标注文本”，而是“所有模型先映射到 task type，再共享通用数据格式”

### 当前手头已有数据时的操作流程

1. 在 Project 下创建 Dataset
2. 通过 FastAPI 上传 zip 数据集压缩包，并提供或确认格式、任务类型、class map 和 split 信息
3. 第一阶段让系统自动识别 COCO detection / Pascal VOC detection 候选格式，并由用户确认 task type、class map 和 split 信息
4. 系统生成一次 DatasetImport 记录，把原始 zip 包和解压 staging 归档到 datasets/{dataset_id}/imports 路径
5. 系统把原始标签转换为通用数据格式，生成 DatasetVersion
6. 将开发阶段预置在磁盘中的预训练权重登记到 models，形成 Model + ModelVersion
7. 创建训练任务时，选择 DatasetVersion、任务类型、训练 recipe 和 warm start 的 ModelVersion
8. 对应训练后端从通用数据格式导出适配自己的数据集结构，再启动训练
9. 训练产出登记为新的 ModelVersion，后续如需部署再转换为一个或多个 ModelBuild

### 对目录结构的建议

- 平台外部导入时需要识别图片目录和标注目录，但不要求所有用户先手工整理成唯一固定树
- 平台内部需要定义标准化的导入声明和通用数据格式，否则后端无法长期统一管理多模型训练
- 外部目录结构可以多样，内部 DatasetVersion 结构必须统一

### Model、ModelVersion 与 ModelBuild

- Model 是逻辑模型容器，不直接等价于某个具体权重文件
- Model 当前显式分为两类：Project 内 Model 和平台基础模型；前者服务于某个具体项目训练线，后者承载跨项目共享的预训练底座
- ModelVersion 是源模型版本，表示一次明确可追踪的模型状态
- 预置预训练模型登记后应先形成 ModelVersion，而不是作为游离文件直接给任务使用
- 训练产出应登记为新的 ModelVersion，并保留训练来源、父版本和输入数据版本关系
- ModelBuild 是源模型转出来的部署 build，通常对应 ONNX、OpenVINO、TensorRT、CoreML 或特定量化版本
- ModelVersion 与 ModelBuild 都通过 ModelFile 挂接具体文件，但所在层级不同，不应混成一个对象

### ModelFile

- 是统一文件记录，不只代表训练得到的权重文件
- 也可以代表转换输出、benchmark 报告、推理结果包和模型配置包
- 应包含 file type、source lineage、compatibility、checksum 和 storage reference

### ResultFile 和 task staging

- ResultFile 用于保存需要复查、下载、复现、上报或再次进入流程的结果对象
- task staging 只用于短期暂存推理中间结果、上传回包、预览图和临时日志，不作为长期正式存储
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
- 每个 ModelVersion 都应能追到来源类型：pretrained-reference 或 training-output；后续再扩展其他来源类型
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
		│     ├─ imports/
		│     │  └─ {dataset_import_id}/
		│     │     ├─ package.zip
		│     │     ├─ manifests/
		│     │     │  ├─ upload-request.json
		│     │     │  └─ detected-profile.json
		│     │     ├─ staging/
		│     │     │  └─ extracted/
		│     │     └─ logs/
		│     │        ├─ validation-report.json
		│     │        └─ import.log
		│     ├─ versions/
		│     │  └─ {dataset_version_id}/
		│     │     ├─ manifests/
		│     │     ├─ images/
		│     │     ├─ samples/
		│     │     └─ indexes/
		│     └─ exports/
		│        └─ {dataset_export_id}/
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

- imports/{dataset_import_id}/package.zip 保存原始上传包，后续审计与复查都以此为准
- imports/{dataset_import_id}/staging/extracted 只保存安全解压后的短期工作目录，不作为训练或导出的长期输入；当前导入成功后会清空并重建为空目录
- versions/{dataset_version_id} 保存生成后的统一版本内容，是平台内部的正式输入版本
- 第一阶段 versions 目录应至少包含 manifests、images、samples、indexes 四层，以支撑 COCO/VOC detection 导入后的统一读取

## 当前本地 data 目录

当前开发态默认使用本地 data 目录保存 SQLite 元数据和 ObjectStore 文件内容。当前路径约定如下。

```text
data/
├─ amvision.db
├─ queue/
├─ files/
│  └─ projects/
│     └─ {project_id}/
│        └─ datasets/
│           └─ {dataset_id}/
│              ├─ imports/
│              └─ versions/
├─ worker/
└─ maintenance/
```

| 路径 | 当前用途 |
| --- | --- |
| data/amvision.db | 默认开发数据库文件，保存 DatasetImport、DatasetVersion、Model、ModelVersion、ModelBuild 等正式元数据。 |
| data/queue | backend-service 与 backend-worker 共用的本地持久化队列根目录。当前 DatasetImport 提交后会先在这里登记一条待消费任务。 |
| data/files | backend-service 默认 ObjectStore 根目录。当前数据集导入的原始包、版本文件和后续导出结果都放在这里。 |
| data/worker | worker 进程的默认本地工作目录。当前只是 bootstrap 级目录约定，还没有落正式任务内容。 |
| data/maintenance | maintenance 进程的默认本地工作目录。当前只是 bootstrap 级目录约定，还没有落正式运维产物。 |

### DatasetImport 目录用途

当前测试样例落盘后，对应目录结构如下。

```text
data/files/projects/{project_id}/datasets/{dataset_id}/imports/{dataset_import_id}/
├─ package.zip
├─ manifests/
│  ├─ upload-request.json
│  └─ detected-profile.json
├─ staging/
│  └─ extracted/
└─ logs/
	├─ validation-report.json
	└─ import.log
```

| 路径 | 当前用途 |
| --- | --- |
| package.zip | 保存原始上传 zip 包，是导入审计、问题复查和重新解析的原始输入。 |
| manifests/upload-request.json | 保存接口收到的显式请求参数，例如 project_id、dataset_id、package_file_name、format_type、task_type、split_strategy、class_map、metadata。 |
| manifests/detected-profile.json | 保存导入器识别出来的格式签名、目录根路径、split 名称和 split 数量。 |
| staging/extracted | 保存安全解压后的短期工作目录。解析器从这里读取原始图片和标注。这个目录不应作为训练和导出的长期输入；当前导入成功后会被清空并重建为空目录。 |
| logs/validation-report.json | 保存结构化校验结果。成功时包含 sample_count、category_count、split_counts；失败时包含 error code 和 message。 |
| logs/import.log | 保存一次导入的简短处理日志，便于人工排查。 |

### DatasetVersion 目录用途

导入成功后，平台会把原始数据固化成一个正式版本目录。

```text
data/files/projects/{project_id}/datasets/{dataset_id}/versions/{dataset_version_id}/
├─ manifests/
│  ├─ dataset-version.json
│  └─ categories.json
├─ images/
│  ├─ train/
│  ├─ val/
│  └─ test/
├─ samples/
│  ├─ train/
│  ├─ val/
│  └─ test/
└─ indexes/
	├─ train.json
	├─ val.json
	└─ test.json
```

| 路径 | 当前用途 |
| --- | --- |
| manifests/dataset-version.json | 保存版本级摘要，包括 dataset_version_id、dataset_id、project_id、task_type、source_import_id、format_type、sample_count、category_count、split_counts。 |
| manifests/categories.json | 保存归一化后的类别表。当前导入器会把类别重排为连续 0-based category_id。 |
| images/{split}/ | 保存当前 DatasetVersion 的正式图片副本。训练、验证或导出时如果需要真实图像文件，应从这里读取。 |
| samples/{split}/{sample_id}.json | 保存单样本的结构化记录，包括图片尺寸、split、image_object_key、source_image_ref 和 annotations。 |
| indexes/{split}.json | 保存 split 级索引，便于快速枚举当前 split 的样本和文件路径，不必逐个扫描 samples 目录。 |

### 当前版本目录里的正式输入边界

- imports 目录保存“原始输入”和“导入过程信息”。
- versions 目录保存“平台内部正式版本”。
- 训练、验证、导出和后续离线批处理不应直接依赖 imports/staging/extracted。
- 如果后续需要重做解析或审计，可以重新使用 package.zip，但正式任务应绑定 DatasetVersion id。

## 训练、验证、推理、发布如何使用 data 目录

### 数据集导入阶段

- 上传接口先把原始 zip 落到 imports/{dataset_import_id}/package.zip。
- 当 POST /imports 返回 202 时，表示 package.zip 已经持久化完成，同时一条导入任务已经写入 data/queue；此时上传成功，但解析与版本生成尚未完成。
- 当前服务内部只负责登记 DatasetImport、写 package.zip 和入队；真正的解析、校验和版本生成由 worker 异步执行。
- 解析器在 staging/extracted 中识别格式、读取原始标注和图片。
- 导入成功后再把正式结果写入 versions/{dataset_version_id}，并把结构化元数据写入数据库中的 DatasetVersion 聚合。
- 导入成功后会清空 staging/extracted 中的临时解压内容，只保留 package.zip、识别结果和校验报告作为审计与重跑锚点。

### 上传进度与处理进度边界

- 当前单次 multipart 上传接口只在请求结束后才生成 uploaded 状态，因此服务端只能回答“上传是否已经成功落盘”，不能在请求尚未结束前返回实时上传百分比。
- 浏览器或桌面客户端如果需要显示上传进度，应使用 HTTP 客户端自己的 upload progress 事件统计已发送字节数。
- 服务端能提供的是“上传完成后的处理进度”：客户端可通过 DatasetImport.status 轮询当前状态，received 表示已入队，extracted 或 validated 表示 worker 正在运行，completed 表示版本已生成，failed 表示处理失败。
- 如果后续需要真正的断点续传、分片重试和服务端可查询上传进度，应新增 upload session + chunk API，或改为对象存储 multipart 直传方案。

### 训练阶段

- 训练任务应绑定 DatasetVersion id，而不是绑定 imports 目录路径。
- 当前最小实现里，DatasetVersion 的正式内容同时存在两处：数据库中的结构化聚合，以及 data/files 下的版本目录。
- 当前 exporter 直接从数据库读取 DatasetVersion 聚合生成导出结果，并把 manifest、annotations、images 正式写到 datasets/{dataset_id}/exports/{dataset_export_id}；如果调用方显式提供 output_object_prefix，也可以把导出结果写到 task-runs/training/{task_id}/dataset-export 一类的任务目录。
- 如果训练后端需要真实图片文件，应优先使用 versions/{dataset_version_id}/images 和 indexes/{split}.json 组合出的样本清单。

### 验证阶段

- 验证任务应与训练一样绑定 DatasetVersion id。
- val/test 的筛选应优先依据数据库中的 sample.split 或版本目录中的 indexes/val.json、indexes/test.json。
- 当前仓库还没有单独的 ValidationTask 实现，因此验证阶段如何把 DatasetVersion 转成具体验证输入仍需继续落地。

### 推理阶段

- 在线推理当前不直接读取 DatasetVersion。
- 当前 InferenceTask 规格使用的是 deployment_instance_id、input_file_id 或 input_uri，说明在线推理更接近“单输入或批输入文件”模式，而不是直接消费整个数据集版本。
- 如果后续要做离线批量评估、回归测试或基准测试，应新增显式的评估任务，让它绑定 DatasetVersion 或导出后的评估数据包。

### 发布阶段

- 发布和部署直接绑定的是 ModelVersion 或 ModelBuild，而不是 data/files 下的数据集目录。
- 数据集在发布阶段的主要作用是保留 lineage：训练输出模型应记录 dataset_version_id，便于追溯模型来自哪个数据版本。
- 如果部署前需要做回归验证，应该由验证或 benchmark 任务读取 DatasetVersion，而不是让 DeploymentInstance 直接读取数据集目录。

### 导出阶段

- 当前最小导出器已经能把 DatasetVersion 转成 COCO detection 结构化结果。
- 当导出器绑定 LocalDatasetStorage 时，会把 manifest.json、annotations/instances_{split}.json 和 images/{split}/ 正式写回 data/files/projects/{project_id}/datasets/{dataset_id}/exports/{dataset_export_id}。
- 如果训练或评估任务需要把导出结果落到任务作用域目录，可以通过 output_object_prefix 把导出目标切到 task-runs/training/{task_id}/dataset-export 等自定义路径。
- worker 侧后续只需要消费 manifest_object_key 或 export_path，就可以直接复用同一份正式导出结果。

## 放置与管理规则

### 数据集放哪里

- 逻辑上放在 Project 下的 Dataset 与 DatasetVersion 中管理
- 文件内容放在 ObjectStore 的 datasets 路径下，按 dataset id 和 dataset version id 分层
- 管理动作由后端服务的 datasets 用例处理，包括导入、生成版本、标记、归档和清理

### 预训练模型放哪里

- 当前默认物理根目录是 data/files/models/pretrained/yolox
- 推荐按 models/pretrained/yolox/{model_scale}/{entry_name} 分层，每个条目目录至少包含 manifest.json 和 checkpoints/{checkpoint_file}.pth
- 开发阶段当前直接以这套规范目录作为唯一物理落盘位置，不再保留根目录平铺权重副本
- 可选附带 README.md、LICENSE、来源说明和下载说明等辅助文件，但这些文件不参与训练标签语义
- manifest.json 当前至少应声明 model_name、model_scale、model_version_id、checkpoint_path；checkpoint_file_id、task_type、metadata 可选
- backend-service 启动时会自动扫描上述目录下的 manifest.json，并把每条记录登记为一个平台级基础 Model + ModelVersion，source kind 标记为 pretrained-reference
- 预训练目录不绑定具体 Project；登记后的平台基础模型 project_id 为空，只用 scope_kind=platform-base 表达作用域
- warm_start_model_version_id 直接使用 manifest.json 中声明的 model_version_id；训练阶段会沿 ModelVersion -> ModelFile -> checkpoint 链路加载权重

#### 推荐目录示例

```text
data/files/models/pretrained/yolox/
	nano/
		default/
			manifest.json
			checkpoints/
				yolox_nano.pth
			README.md
```

#### manifest.json 最小示例

```json
{
	"model_name": "yolox",
	"model_scale": "nano",
	"model_version_id": "model-version-pretrained-yolox-nano",
	"checkpoint_path": "checkpoints/yolox_nano.pth",
	"metadata": {
		"catalog_name": "default",
		"source": "local-pretrained"
	}
}
```

### 训练后模型放哪里

- 训练完成后先登记为新的 ModelVersion，不直接覆盖预训练版本
- 当前真实训练输出文件先写到 data/files/task-runs/training/{task_id}/artifacts
- 当前最小实现会写出 checkpoints/best_ckpt.pth、checkpoints/latest_ckpt.pth、reports/train-metrics.json、reports/validation-metrics.json、training-summary.json 和 labels.txt
- ModelVersion 侧当前登记 checkpoint 和 labels 的 ModelFile，并通过 training-summary.json 继续引用完整输出文件目录

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
- 逻辑对象用数据库做主索引，路径只做存储组织，不做业务主键
- 预置模型登记、训练产出、转换产出和推理结果分别对应不同对象层级，避免都塞进 ModelFile 一个层里
- 清理策略分三类：dataset archive、task staging cleanup、file retention，不混用同一规则
- UI 和 API 默认展示 Model -> ModelVersion -> ModelBuild 的三级结构，而不是直接暴露底层文件树

## 推荐后续文档

- [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)
- [docs/architecture/backend-service.md](backend-service.md)
- [docs/architecture/system-overview.md](system-overview.md)
- [docs/architecture/node-system.md](node-system.md)