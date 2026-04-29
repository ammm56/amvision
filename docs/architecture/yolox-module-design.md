# YOLOX 模块设计

## 文档目的

本文档用于说明 YOLOX 在 amvision 里的目录位置、模块拆分、对象边界和分阶段实现方式。

本文档关注的是如何把现有的 YOLOX_2026 训练、验证、导出、转换和推理能力，重组为更适合 amvision 的后端服务、worker 和运行时模块，而不是复述单个脚本如何执行。

## 适用范围

- YOLOX 在 amvision 里的模块划分
- 训练、验证、转换、部署和推理的职责边界
- DatasetVersion、ModelVersion、ModelBuild 与 YOLOX 运行链路的对应关系
- backend/service、backend/workers、backend/contracts 的建议目录位置
- 当前 YOLOX_2026 代码向 amvision 重构时的迁移策略

## 设计目标

- 让 YOLOX 成为 amvision 中一个可管理的模型类型，而不是一个独立脚本仓库
- 让训练、验证、转换和推理都通过统一任务模型接入 backend-service
- 让数据输入统一建立在 DatasetVersion 和数据集导出结果之上，而不是直接依赖本地目录布局
- 让 checkpoint、ONNX、OpenVINO IR、TensorRT engine 等文件都进入 ModelVersion 与 ModelBuild 的版本链路
- 让运行时与接口层解耦，避免把模型文件路径、设备选择和前后处理逻辑直接暴露到 API 层

## 非目标

- 不直接在本文档中定义 YOLOX 训练参数的完整字段列表
- 不把 YOLOX 的底层模型结构、loss 公式和算子细节作为平台长期规则
- 不要求在第一阶段同时完成所有推理后端实现
- 不把 YOLOX 当前仓库中的所有工具脚本原样迁移到 amvision

## 当前代码事实

当前 YOLOX_2026 已经覆盖以下能力：

- 基于 exp 的模型装配、数据集接入与训练调度
- 训练与验证 CLI 脚本
- ckpt 到 ONNX 的导出
- TensorRT engine 的直接生成
- 基于 OpenVINO 的 Python CLI 推理和 FastAPI demo

当前实现也存在以下耦合：

- exp 文件同时放模型规格、类别定义、数据路径、增强策略、评估器和训练入口
- tools 脚本默认围绕本地路径、checkpoint 文件和输出目录运行
- 数据输入直接依赖 VOC 或 COCO 风格目录，而不是平台生成后的 DatasetVersion
- OpenVINO FastAPI 入口仍然依赖本地 JSON 配置和进程内对象工厂，不适合作为平台正式部署入口

## 在 amvision 中的位置

YOLOX 在 amvision 中不应作为 backend-service 的直接依赖实现，而应分散到以下三个层面：

- domain 与 application：处理模型规则、数据集导出、文件登记、转换规划和部署校验
- workers：跑训练、验证、转换和推理
- contracts：放数据集导出格式、文件命名、运行时输入输出规则

backend-service 只处理任务、元数据和状态，不直接持有 YOLOX 的底层训练器或 OpenVINO 会话。

## 模块拆分原则

### 1. 先拆模型信息，再拆执行逻辑

YOLOX 的模型规格、任务类型、默认数据集导出格式、支持的 build 类型，应先成为稳定对象，再决定如何执行训练和推理。

### 2. 先统一数据入口，再复用训练器

YOLOX 训练不能再直接读取项目内 datasets 目录，而应由 DatasetVersion 先导出成目标数据集格式，再交给训练 worker。

### 3. 先统一文件登记，再接转换链路

best_ckpt.pth、onnx、xml、bin、engine 不应直接散落在输出目录中，而应按 ModelVersion 或 ModelBuild 挂接为文件记录。

### 4. 推理运行时与 Web 接口分离

OpenVINO 会话缓存、适配器、前后处理和统一结果结构可以保留为运行时模块，但 FastAPI 入口应由 amvision 的 backend-service 统一托管。

## 命名与落位约定

- backend 下的真实 Python 源码目录统一使用可直接导入的 snake_case 包名
- 目录先表达平台职责，再在目录内部放 YOLOX 模块；后续增加 SAM、RT-DETR、YOLOv8/11 等模型时继续沿用同一层级
- 代码命名优先使用 model、spec、files、contracts 这类常见工程词，不额外引入更绕的名字作为源码主命名

## 目标目录落位

以下落位遵循现有的项目结构规划，并作为第一阶段骨架的推荐目录：

```text
backend/
├─ service/
│  ├─ application/
│  │  ├─ datasets/
│  │  │  └─ dataset_export.py
│  │  ├─ models/
│  │  │  └─ yolox_model_service.py
│  │  ├─ conversions/
│  │  │  └─ yolox_conversion_planner.py
│  │  └─ deployments/
│  │     └─ yolox_deployment_binding.py
│  └─ domain/
│     ├─ models/
│     │  └─ yolox_model_spec.py
│     ├─ files/
│     │  └─ yolox_file_types.py
│     └─ tasks/
│        └─ yolox_task_specs.py
├─ workers/
│  ├─ training/
│  │  └─ yolox_trainer_runner.py
│  ├─ inference/
│  │  └─ yolox_inference_runner.py
│  ├─ conversion/
│  │  └─ yolox_conversion_runner.py
│  └─ shared/
│     └─ yolox_runtime_contracts.py
└─ contracts/
   ├─ datasets/
   │  └─ exports/
   │     └─ coco_detection_export.py
   └─ files/
      └─ yolox_model_files.py
```

## 模块职责定义

### backend/service/domain/models/yolox_model_spec.py

- 定义 YOLOX 作为一个模型类型的稳定规格
- 定义支持的 model scale，例如 nano、tiny、s、m、l、x
- 定义支持的任务类型范围，第一阶段聚焦 detection
- 定义默认数据集导出格式与支持的转换目标

### backend/service/domain/files/yolox_file_types.py

- 定义 YOLOX 训练与部署链路中的文件类型枚举
- 区分 checkpoint、onnx、openvino-ir、tensorrt-engine、label-map、metrics-report 等对象

### backend/service/domain/tasks/yolox_task_specs.py

- 定义 YOLOX 相关任务的结构化输入规格
- 明确训练任务、转换任务、推理任务需要哪些平台对象引用
- 避免 worker 直接接收零散 CLI 参数

### backend/service/application/datasets/dataset_export.py

- 把 detection 类型的 DatasetVersion 导出成指定格式的数据集结果
- 第一阶段先落 coco-detection-v1，生成稳定的类别顺序、样本 split、目录和 annotation payload
- 不直接训练模型

### backend/service/application/models/yolox_model_service.py

- 处理磁盘中预置的 YOLOX 预训练模型登记、训练输出登记和模型规格查询
- 把训练输出转成 ModelVersion 和关联文件记录
- 不直接执行训练

### backend/service/application/conversions/yolox_conversion_planner.py

- 根据源 ModelVersion 规划可转换的目标 build
- 判断哪些转换链路可用，例如 ckpt -> onnx、onnx -> openvino-ir、onnx -> tensorrt-engine
- 为 ConversionTask 生成稳定的执行规格

### backend/service/application/deployments/yolox_deployment_binding.py

- 检查 DeploymentInstance 绑定的 YOLOX ModelBuild 是否与 RuntimeProfile 兼容
- 检查输入尺寸、类别映射、设备能力和推理后端是否满足部署要求

### backend/workers/training/yolox_trainer_runner.py

- 执行训练任务
- 内部可复用现有 trainer 逻辑，但输入必须来自结构化任务规格和数据集导出目录
- 输出必须回写为文件记录和训练摘要，而不是只写本地目录

### backend/workers/inference/yolox_inference_runner.py

- 执行推理任务
- 内部复用 YOLOX 前后处理和运行时适配能力
- 输出统一结果结构，供 backend-service 持久化和对外暴露

### backend/workers/conversion/yolox_conversion_runner.py

- 执行转换任务
- 第一阶段建议覆盖 ONNX 导出与 OpenVINO IR 生成
- TensorRT 可作为同一 runner 的扩展目标，但不应阻塞第一阶段骨架落地

### backend/workers/shared/yolox_runtime_contracts.py

- 定义推理运行时的最小输入输出规则
- 定义统一的推理请求、推理结果和运行时会话抽象
- 用于隔离 OpenVINO、ONNXRuntime、TensorRT 等具体实现差异

### backend/contracts/datasets/exports/coco_detection_export.py

- 定义 coco-detection-v1 的稳定格式
- 约束类别顺序、目录布局、annotation 文件和最小 COCO payload 字段
- 作为 DatasetVersion 到 COCO detection 数据集导出的共享规则

### backend/contracts/files/yolox_model_files.py

- 定义 YOLOX 模型文件的命名、标签和 lineage 规则
- 用于训练输出、转换输出和部署绑定之间的统一判断

## 关键对象映射

### DatasetVersion -> YOLOX 数据集导出

- 平台正式输入始终是 DatasetVersion
- YOLOX 训练只消费由 dataset exporter 生成的 coco-detection-v1 数据集导出结果
- 导出格式第一阶段优先对齐 [dataset-export-formats.md](dataset-export-formats.md) 中的 coco-detection-v1

### ModelVersion

- 表示一个 YOLOX 源模型版本
- 可来源于预置预训练模型登记或训练输出
- 至少挂接 checkpoint 文件、训练摘要和类别映射信息

### ModelBuild

- 表示面向具体运行时的派生部署 build
- 第一阶段优先支持 onnx 和 openvino-ir
- 后续再补充 tensorrt-engine

### DeploymentInstance

- 绑定某个 YOLOX ModelBuild 与 RuntimeProfile
- 由 deployments 模块负责兼容性校验
- 推理请求只引用 DeploymentInstance，不直接引用模型文件路径

## 推荐任务链路

### 训练链路

1. DatasetVersion 已生成
2. 创建 YOLOX 数据集导出结果
3. 创建 TrainingTask
4. training worker 读取结构化任务规格并执行训练
5. 训练输出登记为新的 ModelVersion 与关联文件记录

### 转换链路

1. 选择源 ModelVersion
2. conversion planner 生成目标 build 计划
3. 创建 ConversionTask
4. conversion worker 执行导出与转换
5. 输出登记为一个或多个 ModelBuild

### 部署与推理链路

1. DeploymentInstance 绑定 YOLOX ModelBuild
2. deployments 校验 RuntimeProfile 与模型 build 兼容性
3. inference worker 或 runtime service 执行推理
4. 推理结果回写为统一结果结构和结果文件或 task staging

## 第一阶段实现边界

第一阶段建议只落以下内容：

- detection 任务类型
- YOLOX 模型基础信息
- DatasetVersion 到 coco-detection-v1 数据集导出的规则骨架
- 训练、推理、转换三类 worker runner 的接口骨架
- checkpoint、onnx、openvino-ir 三类文件与 build 骨架

第一阶段不强制完成以下内容：

- segmentation 或 pose 任务类型
- 完整的 TensorRT 运行时接入
- WebSocket 状态推送细节
- 前端页面或工作流界面

## 迁移策略

### 从 YOLOX_2026 复用的内容

- 模型结构与训练器内核
- detection 前处理与后处理逻辑
- ONNX 导出流程的底层实现
- OpenVINO 运行时封装、会话缓存和统一结果结构的设计思路

### 不直接复用的内容

- 按数据集拆分的 exp 文件
- 以 argparse 为中心的工具脚本接口
- 直接读写项目内 datasets、models、YOLOX_outputs 的目录约定
- 直接作为正式服务入口的 demo FastAPI 应用

## 实施顺序

1. 先落 domain、contracts 和 application 骨架
2. 再落 worker runner 接口骨架
3. 再把 YOLOX detection 的数据导出、训练和 ONNX 导出接到骨架上
4. 最后把 OpenVINO runtime 纳入推理与部署链路

## 推荐关联文档

- [project-structure.md](project-structure.md)
- [backend-service.md](backend-service.md)
- [data-and-files.md](data-and-files.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)