# YOLO 系列模型规划

## 文档目的

本文档用于把 `projectsrc/ultralytics` 作为参考源码面，整理出 amvision 后续接入 YOLO 系列模型时的分层方式、层级关系、实现边界和优先顺序。

`YOLOv8 / YOLO11 / YOLO26` 的完整 core 目录、任务拆分、Ultralytics 参考映射、许可证边界和验收规则，统一维护在 [model-core-implementation-plan.md](model-core-implementation-plan.md)。本文档只保留 YOLO 系列在平台中的高层分层和进入顺序，不重复展开 full core 实现清单。

本文档重点回答下面几个问题：

- `projectsrc/ultralytics` 中哪些结构适合作为参考
- 哪些层继续保持平台通用
- 哪些层按任务分类拆分
- 哪些层按 YOLO 模型分类做适配
- YOLOv8、YOLO11、YOLO26 以及后续扩展项的最小接入范围和进入顺序

## 适用范围

- backend-service、worker、runtime、workflow 和 deployment 的 YOLO 系列扩展
- YOLO 系列训练、验证、评估、转换、推理和长期稳定运行服务的接入方式
- `projectsrc/ultralytics` 参考源码与本项目正式实现之间的边界

## 当前参考事实

当前 `projectsrc/ultralytics` 已经体现出比较清楚的三层结构：

- `ultralytics/models/yolo/` 主要按任务分类拆分，当前可见 `detect`、`segment`、`classify`、`pose`、`obb`、`world`、`yoloe`
- `ultralytics/cfg/models/` 主要按模型分类或版本拆分，当前可见 `v8`、`11`、`12`、`26`、`v9`、`v10`、`v6`、`v5`、`v3`
- `engine/model.py`、`engine/exporter.py`、`nn/backends/` 负责共享的训练入口、导出入口和运行时后端

这说明参考源码本身并不是“每个版本复制一整套仓库”，而是：

- 先有共用执行骨架
- 再按任务分类拆训练、验证和预测
- 最后按模型分类补配置、权重和少量差异

这个方向与 amvision 当前“平台通用层 + 任务分类层 + 模型分类适配层”的规划是一致的。

## 硬性边界

`projectsrc/ultralytics` 只作为开发阶段参考，不作为 amvision 运行时直接依赖。

后续接入 YOLO 系列模型时应遵守下面这些边界：

- 不从 `projectsrc/ultralytics` 直接导入运行时代码
- 不把 upstream `Model`、`Results`、CLI 参数或本地目录规则直接当作本项目公开接口
- 不把 upstream 的自动下载、HUB、在线平台和云端流程作为本项目默认依赖
- 不让训练、转换、推理直接围绕 `data=*.yaml`、本地样本目录和脚本参数运行
- 不让 deployment 直接调用 upstream CLI 或 demo 入口

如果后续确实需要复用 upstream 发行包，也应通过受控 third-party dependency 方式引入，并且只能落在本项目自己的适配层里，不能越过平台边界直接进入 API、workflow 或公开 schema。

## 规划核心

YOLO 系列后续接入建议同时区分三个维度：

| 维度 | 取值 | 作用 |
| --- | --- | --- |
| 任务分类 | `detection`、`segmentation`、`pose`、`obb`、`classification` | 决定输入输出规则、训练数据规则、评估规则和结果结构 |
| 模型分类 | `yolov8`、`yolo11`、`yolo26`、`yolo-world`、`yoloe` | 决定模型配置、权重命名、训练差异、导出差异和特殊能力 |
| 运行时类型 | `pytorch`、`onnxruntime`、`openvino`、`tensorrt`，后续可扩 `coreml`、`rknn` | 决定部署 build、长期运行服务加载方式和目标机器依赖 |

这三个维度不能混用。

任务分类负责“做什么”，模型分类负责“是哪种 YOLO”，运行时类型负责“在哪个后端上长期运行”。

## 层级关系

YOLO 系列模型建议长期维持下面五层：

1. 平台通用层
2. YOLO 共用层
3. 任务分类层
4. 模型分类层
5. 运行时后端层

### 1. 平台通用层

这一层继续复用现有主干，不按 YOLO 模型分类复制实现。

包含内容：

- `Model`、`ModelVersion`、`ModelBuild`、`ModelFile`
- `DatasetExport`
- `TaskRecord`
- `DeploymentInstance`
- backend-service / worker / workflow / node pack / release 装配
- deployment 子进程 supervisor、runtime pool、health、warmup、restart、stop、reset

这一层只关心平台资源、任务和长期运行外壳，不关心具体是 YOLOX、YOLOv8 还是 YOLO26。

### 2. YOLO 共用层

这一层只放所有 YOLO 系列共用的能力，不按版本拆顶层目录。

建议放入的内容：

- YOLO 预置模型登记规则
- YOLO 通用 model spec
- YOLO 通用 file type 和 build format 规则
- YOLO 通用 prediction request / result 归一化
- YOLO 通用 runtime target 解析
- YOLO 通用 conversion planner
- YOLO 通用 deployment binding 外壳

这一层的目标是避免后续出现：

- `yolov8_*`
- `yolo11_*`
- `yolo26_*`

三套几乎重复的顶层 service、worker 和 runtime 文件。

### 3. 任务分类层

这一层按任务分类拆开，因为任务分类决定输入输出和数据规则。

YOLO 系列当前建议拆成下面五类：

- `detection`
- `segmentation`
- `pose`
- `obb`
- `classification`

其中前四类更符合当前项目长期方向，`classification` 暂不作为第一批主线。

### 4. 模型分类层

这一层只保留 `yolov8`、`yolo11`、`yolo26` 等模型分类自己的差异。

这一层主要负责：

- 模型配置名和默认权重名
- 支持的任务分类矩阵
- 默认输入尺寸和模型 scale 规则
- 训练、导出和推理中的差异项
- 特殊后处理或特殊导出限制

如果某个差异只是一组默认值，不应新建整套 service 或 worker，更适合放在 model profile、registry 或 spec 配置里。

### 5. 运行时后端层

这一层继续按部署后端拆，不按模型分类重写长期运行服务外壳。

第一阶段重点保持与当前 YOLOX 一致：

- `pytorch`
- `onnxruntime`
- `openvino`
- `tensorrt`

第二阶段再评估：

- `coreml`
- `rknn`
- 其他 ARM NPU 目标

## 推荐目录关系

下面的目录关系重点表达层级，不表示当前必须一次性全部实现。

```text
backend/
├─ service/
│  ├─ domain/
│  │  ├─ models/
│  │  │  ├─ yolo_model_spec.py
│  │  │  ├─ yolo_model_profiles.py
│  │  │  └─ yolo_task_profiles.py
│  │  └─ tasks/
│  │     └─ yolo_task_specs.py
│  ├─ application/
│  │  ├─ models/
│  │  │  ├─ yolo_model_service.py
│  │  │  ├─ yolo_detection_training_service.py
│  │  │  ├─ yolo_segmentation_training_service.py
│  │  │  ├─ yolo_pose_training_service.py
│  │  │  └─ yolo_obb_training_service.py
│  │  ├─ conversions/
│  │  │  └─ yolo_conversion_task_service.py
│  │  ├─ deployments/
│  │  │  └─ yolo_deployment_service.py
│  │  └─ runtime/
│  │     ├─ yolo_runtime_target.py
│  │     ├─ yolo_runtime_loader.py
│  │     └─ yolo_prediction_contracts.py
├─ workers/
│  ├─ training/
│  │  ├─ yolo_detection_training_queue_worker.py
│  │  ├─ yolo_segmentation_training_queue_worker.py
│  │  ├─ yolo_pose_training_queue_worker.py
│  │  └─ yolo_obb_training_queue_worker.py
│  ├─ conversion/
│  │  └─ yolo_conversion_queue_worker.py
│  └─ inference/
│     └─ yolo_inference_queue_worker.py
└─ contracts/
   ├─ datasets/
   │  └─ exports/
   │     ├─ coco_detection_export.py
   │     ├─ coco_segmentation_export.py
   │     ├─ coco_pose_export.py
   │     └─ dota_obb_export.py
   └─ files/
      └─ yolo_model_files.py
```

这个目录关系强调两点：

- 先按平台职责落位，再在职责目录里放 YOLO 模块
- 先按任务分类拆服务和 worker，不先按 `yolov8`、`yolo11`、`yolo26` 复制完整链路

## 哪些内容适合参考 Ultralytics

下面这些结构适合作为参考：

- 先做一层共用 `Model` 外壳，再按任务分类挂 train / val / predict / export
- `detect` 作为主干任务，`segment`、`pose`、`obb` 在它上面补任务差异
- 模型配置、默认权重和任务入口分开管理
- 导出和运行时后端有独立共享层

这些思路适合转成 amvision 的：

- `TrainingBackend`
- `ConversionBackend`
- `ModelRuntime`
- `RuntimeTargetResolver`
- `DeploymentBinding`

## 哪些内容不直接照搬

下面这些内容不应直接搬进 amvision：

- upstream `YOLO(...)` 的对象接口
- upstream `Results` 结果结构
- upstream CLI 参数名和命令组合
- upstream 的 dataset yaml、自动下载和目录命名规则
- upstream HUB、Triton、云端训练或在线平台流程
- upstream 本地脚本直接读写输出目录的方式

amvision 正式输入应继续是：

- `DatasetVersion`
- `DatasetExport`
- `ModelVersion`
- `ModelBuild`
- `DeploymentInstance`

正式输出应继续是：

- 结构化任务结果
- 正式文件登记
- 部署态统一推理结果

## 哪些层按任务分类拆分

### detection

这是 YOLO 系列接入的第一条主线。

适用模型分类：

- `yolov8`
- `yolo11`
- `yolo26`

建议第一阶段稳定的内容：

- detection 数据集导出格式
- detection 训练输入规则
- detection 推理输入规则
- detection 结果结构
- detection 评估规则
- detection 部署输入输出规则

这条线应尽量复用当前 YOLOX detection 已经收口的正式对象和 deployment 外壳。

### segmentation

这是 YOLO 系列中第二条建议打开的任务分类。

适用模型分类：

- `yolov8`
- `yolo11`
- `yolo26`

建议第一阶段稳定的内容：

- 实例分割训练输入规则
- mask 结果结构
- mask 可视化规则
- segmentation 评估规则
- segmentation 部署输入输出规则

这一层与 SAM2/3 的 prompt segmentation 不是同一件事。当前更适合先把它定义为实例分割主线。

### pose

这是 YOLO 系列较适合由上游直接带入的平台能力。

适用模型分类：

- `yolov8`
- `yolo11`
- `yolo26`

建议第一阶段稳定的内容：

- keypoint 数据规则
- keypoint 结果结构
- pose 评估规则
- pose 部署输入输出规则

### obb

这是工业场景比较有价值的一条任务分类。

适用模型分类：

- `yolov8`
- `yolo11`
- `yolo26`

建议第一阶段稳定的内容：

- 旋转框数据规则
- angle 结果结构
- OBB 评估规则
- OBB 部署输入输出规则

### classification

参考源码中已经支持，但当前不建议作为第一批主线。

原因：

- 当前项目主线更偏视觉检测、分割、规则处理、部署和长期稳定推理服务
- classification 与当前已完成的 YOLOX detection 主链复用度相对更低
- 如果当前阶段同时打开 classification，会明显扩大平台对象和前端展示范围

classification 可以保留为后续可进入任务分类，但不应排在 detection、segmentation、pose、obb 之前。

## 哪些层按模型分类做适配

### yolov8

定位：

- 第一批进入平台的 YOLO 模型分类

原因：

- 生态成熟
- 训练、导出、推理资料完整
- 与后续 `yolo11`、`yolo26` 的接口抽象最容易形成共用层

最小差异适配内容：

- 模型配置与默认权重名
- 支持任务矩阵
- detection / segmentation / pose / obb 的默认 profile

### yolo11

定位：

- 第二批进入平台的 YOLO 模型分类

原因：

- 与 `yolov8` 接近，适合验证共用层是否真的稳定
- 与 `yolo26` 相比，进入风险更容易控制

最小差异适配内容：

- 模型配置与默认权重名
- 导出兼容矩阵差异
- 任务 profile 默认值差异

### yolo26

定位：

- 第三批进入平台的 YOLO 模型分类

原因：

- 参考源码当前已把它作为主线能力展示
- 适合在前两批稳定后接入，避免把最新版本差异和平台抽象工作混在一起

最小差异适配内容：

- 模型配置与默认权重名
- 各任务 profile 默认值
- 导出和后处理中的新增差异项

### yolo-world

定位：

- 暂不进入第一阶段主线

原因：

- open-vocabulary detection 会引入文本输入和类别动态变化
- 它已经不只是普通 detection 模型，而是 detection + text prompt 组合能力

建议进入条件：

- detection 主线已经稳定
- 多输入 schema 已经比当前 YOLOX 更成熟

### yoloe

定位：

- 暂不进入第一阶段主线

原因：

- 它已经引入 visual prompt、text prompt 和更复杂的类别设定
- 输入输出规则明显超出普通 detection / segmentation 范围

建议进入条件：

- `yolo-world` 或 `QwenVL` 一类多输入模型已经验证过平台 schema

## 当前不进入第一阶段的版本

`projectsrc/ultralytics` 中还可以看到 `v3`、`v5`、`v6`、`v9`、`v10`、`12` 等模型配置。

这些版本当前不建议作为第一阶段主线，原因是：

- 当前项目长期目标里已明确优先 `YOLOv8`、`YOLO11`、`YOLO26`
- 历史版本兼容会迅速扩大维护范围
- 新版本过多同时进入，会稀释当前最关键的接口抽象工作

如果后续确有业务需要，仍应按本文档的层级关系进入，而不是为某个版本单独复制一条新架构。

## 实现顺序

建议顺序如下：

1. 先把 YOLOX 抽成 detection 通用参考实现
2. 再建立 YOLO 共用层
3. 先接 `yolov8` detection
4. 再接 `yolo11` detection
5. 再接 `yolo26` detection
6. detection 稳定后，再打开 YOLO segmentation
7. 然后打开 YOLO pose
8. 然后打开 YOLO obb
9. classification、`yolo-world`、`yoloe` 视实际业务再进入

这个顺序的核心目标不是“先追版本”，而是：

- 先把平台边界做稳
- 先让 detection 这一类能力形成可复用外壳
- 再逐步放开任务分类

## 每个阶段的最小接入范围

### 第一阶段：YOLO detection

范围：

- `yolov8`、`yolo11`、`yolo26`
- task_type 固定为 `detection`

最小接入范围：

- 预置模型登记
- detection 推理输入输出接入
- DeploymentInstance 创建与查询
- sync / async 推理接口
- 独立 deployment 子进程长期运行
- warmup / keep_warm / health / reset / restart
- 至少一条正式转换链
- workflow 推理节点接入

第二阶段补齐：

- 正式训练任务
- validation session
- evaluation task
- 完整转换矩阵

### 第二阶段：YOLO segmentation

范围：

- `yolov8`、`yolo11`、`yolo26`
- task_type 固定为 `segmentation`

最小接入范围：

- 实例分割推理输入输出接入
- mask 结果结构
- DeploymentInstance 创建与查询
- sync / async 推理接口
- 独立 deployment 子进程长期运行
- workflow segmentation 节点接入

第二阶段补齐：

- 正式训练任务
- segmentation 评估规则
- 完整转换矩阵

### 第三阶段：YOLO pose

最小接入范围：

- keypoint 结果结构
- DeploymentInstance 创建与查询
- sync / async 推理接口
- 独立 deployment 子进程长期运行
- workflow pose 节点接入

### 第四阶段：YOLO obb

最小接入范围：

- 旋转框结果结构
- DeploymentInstance 创建与查询
- sync / async 推理接口
- 独立 deployment 子进程长期运行
- workflow obb 节点接入

### 第五阶段：classification 或扩展模型

进入条件：

- 前四阶段已经稳定
- 前端结果展示和平台对象没有被持续拉扯
- 业务上确实需要 image-level 分类或 prompt 型 YOLO 扩展

## 与当前 YOLOX 实现的关系

YOLO 系列接入后，YOLOX 不会被替代，而是继续承担下面两项职责：

- 作为 detection 第一套完整参考实现
- 作为 `TrainingBackend`、`ConversionBackend`、`ModelRuntime`、`DeploymentBinding` 抽象的验证样板

YOLO 系列则承担第二项职责：

- 作为第二套 detection 实现，验证通用层是否真的脱离了单个模型

如果 `yolov8`、`yolo11`、`yolo26` 接入后仍需要复制 `yolox_*` 风格的大量 service、worker 和 runtime 文件，说明当前平台接口还没有抽稳。

## 当前阶段结论

对 YOLO 系列模型而言，后续最重要的工作不是“一次性把所有版本和所有任务都接进来”，而是先把层级关系收稳：

- 平台通用层不变
- YOLO 共用层负责共享逻辑
- 任务分类层决定输入输出和数据规则
- 模型分类层只保留少量差异
- 运行时后端层继续复用长期稳定运行服务外壳

这样后续无论继续接 `YOLOv8`、`YOLO11`、`YOLO26`，还是再向 `yolo-world`、`yoloe` 扩展，都不会破坏当前项目已经成型的后端、部署和 workflow 主干。

## 关联文档

- [model-platform-plan.md](model-platform-plan.md)
- [model-workflow-boundaries.md](model-workflow-boundaries.md)
- [detection-model-rules.md](detection-model-rules.md)
- [yolox-module-design.md](yolox-module-design.md)
- [current-implementation-status.md](current-implementation-status.md)
- [project-structure.md](project-structure.md)
