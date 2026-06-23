# 模型 full core 审计与验收清单

## 文档目的

本文档用于固定 `RF-DETR / YOLOX / YOLOv8 / YOLO11 / YOLO26` 的 full core 审计口径、残留问题分类和真实链路验收顺序。

本文档不是新的模型架构规划。长期目录边界仍以 [model-core-implementation-plan.md](model-core-implementation-plan.md) 为准。本文档只回答三个问题：

- 当前哪些模型可以认为已经进入 full core 验收阶段
- 哪些实现仍然是过渡残留、旧入口或轻量近似实现
- 进入第五批 custom node 前，哪些真实链路必须先跑通并记录结果

## 当前结论

当前不能直接进入第五批 custom nodes。

原因是模型主链路还没有形成统一、可追溯、逐模型逐任务的验收记录。YOLOE / SAM3 这类 custom node 当前还依赖模型服务、deployment runtime、workflow 调用和 payload contract；如果 `RF-DETR / YOLOX / YOLOv8 / YOLO11 / YOLO26` 的训练、转换、部署和推理边界没有先稳定，后续 custom node 会跟着旧 predictor、旧 `yolo_primary_*` 或旧 workflow payload 反复返工。

## 判断状态

- `完成`：代码边界清楚，核心结构与参考实现对齐，真实数据短链路和 deployment sync / async 已记录，已知不支持项已经显式写明。
- `需修复`：存在模型行为、训练、评估、导出、postprocess 或 runtime 语义差距，需要改代码。
- `过渡残留`：功能可能能跑，但仍依赖旧命名、旧入口、共享大文件或临时 smoke，容易误导后续实现。
- `不支持`：参考实现里有，但本项目当前明确不做。必须写清原因和边界，不能伪装成已实现。
- `需验收`：实现看起来完整，但还缺真实数据、真实 checkpoint、转换产物或长期 runtime 验收记录。

## 参考源码目录

以下目录只作为开发阶段参考，不作为运行时代码依赖。

- `projectsrc/rf-detr/src/rfdetr`
- `projectsrc/YOLOX_2026/yolox`
- `projectsrc/ultralytics/ultralytics`
- `projectsrc/supervision/src/supervision`

对照规则：

- `RF-DETR` 参考 `rfdetr/models`、`rfdetr/datasets`、`rfdetr/training`、`rfdetr/evaluation`、`rfdetr/export` 和 `rfdetr/utilities`。
- `YOLOX` 参考 `yolox/models`、`yolox/data`、`yolox/evaluators`、`yolox/utils` 和训练导出工具链。
- `YOLOv8 / YOLO11 / YOLO26` 参考 `ultralytics/cfg/models`、`ultralytics/nn`、`ultralytics/data`、`ultralytics/engine`、`ultralytics/models`、`ultralytics/utils/loss.py`、`tal.py`、`ops.py` 和 export 相关逻辑。
- `supervision` 只能作为结果对象、可视化和几何工具参考；不能让项目运行时代码直接依赖 `projectsrc`。

## 当前 core 目录

当前模型 core 目录已经具备基础分层，但这不等于所有 full core 行为都已验收完成。

- `backend/service/application/models/rfdetr_core`
- `backend/service/application/models/yolox_core`
- `backend/service/application/models/yolov8_core`
- `backend/service/application/models/yolo11_core`
- `backend/service/application/models/yolo26_core`
- `backend/service/application/models/yolo_core_common`

`yolo_core_common` 只允许放真正跨 `YOLOv8 / YOLO11 / YOLO26` 共用、且不包含模型代际和任务语义的底层能力。以下内容不应长期放在 `yolo_core_common`：

- 某个 `model_type` 专属 cfg、head、decode、postprocess
- 某个 `task_type` 专属 loss、assigner、target、evaluation
- `yolo_primary_*` 这类过渡模型构建入口
- 会让 YOLOv8、YOLO11、YOLO26 隐式混线的任务训练入口

## 残留关键词分类

本轮使用下面的范围扫描了 `primary / legacy / minimal / compat / lightweight / stub / NotImplemented / 过渡 / 旧 / 兼容 / 轻量`：

```powershell
rg -n "primary|legacy|minimal|compat|lightweight|stub|TODO|NotImplemented|过渡|旧|兼容|轻量" backend/service/application/models backend/service/application/runtime backend/workers custom_nodes tests docs/architecture docs/api -g "*.py" -g "*.md"
```

扫描结果分为四类处理。

### 已完成第一批入口收口

这些入口已经从 `yolo_primary` 收成更直白的 YOLO 主线命名，后续不再使用旧文件名。

- `backend/workers/training/yolo_primary_training_queue_worker.py` 已改为 `backend/workers/training/yolo_task_training_queue_worker.py`
- `backend/workers/training/yolo_primary_trainer_runner.py` 已改为 `backend/workers/training/yolo_task_trainer_runner.py`
- `backend/workers/evaluation/yolo_primary_evaluation_queue_worker.py` 已改为 `backend/workers/evaluation/model_evaluation_queue_worker.py`
- `SqlAlchemyYoloPrimary*EvaluationTaskService` 已改为 `SqlAlchemyYoloTask*EvaluationService`
- non-detection `SqlAlchemyYoloPrimary*TrainingTaskService` 已改为 `SqlAlchemyYoloTask*TrainingService`
- non-detection `yolo_primary_*_task_dataset / payload / control / events / registration` 已改为 `yolo_task_*_training_dataset / payload / control / events / registration`
- non-detection `yolo_primary_*_training.py` 共享执行层已改为 `yolo_task_*_training.py`
- non-detection `yolo_primary_*_evaluation.py` 共享评估执行层已改为 `yolo_task_*_evaluation.py`
- non-detection `YOLO_PRIMARY_*` 默认参数常量、DatasetExport helper 和 evaluation runtime resolver 已改为 `YOLO_TASK_*` / `yolo_task_*`
- `tests/integration/yolo_primary_full_chain_smoke.py` 已改为 `tests/integration/yolo_model_full_chain_smoke.py`
- `tests/integration/yolov8_full_chain_smoke.py` 已删除，YOLOv8 真实短链路统一通过 `tests.integration.yolo_model_full_chain_smoke --model-type yolov8` 执行

### 必须继续清理的过渡残留

这些命名和入口会让后续误以为还存在一条通用 `YOLO primary` 模型线，需要逐步改成中性共享层或迁回各自 core。

- `backend/service/application/models/training/yolo_task_detection_training.py` 现在只保留 YOLOv8 detection 过渡训练入口；YOLO11 / YOLO26 已明确拒绝走该共享入口
- `tests/test_yolo_primary_*` 中仍用于检查旧 primary / common 入口的测试命名
- 文档中的 `yolo_primary` 示例和执行顺序说明

处理规则：

- 如果是真共享能力，改成 `yolo_task_*`、`model_task_*` 或更具体的任务层命名。
- 如果是 YOLOv8、YOLO11、YOLO26 某一代专属能力，迁回对应 `*_core` 或对应 service helper。
- 如果只是旧兼容入口，删除，不保留长期壳。

### 不能按关键词直接删除的兼容点

以下命名虽然包含 `legacy` 或 `compat`，但可能是读取真实权重或匹配参考实现所需，不能盲删。

- `legacy_class_head`：YOLO head 的结构行为标记，必须和参考实现及 checkpoint 形态对应。
- checkpoint 反序列化里的旧模块路径映射：用于读取真实预训练权重，不等于旧业务路径。
- `NotImplementedError` 在抽象基类、必须由子类实现的 runtime service 中可以保留。
- `primary_sample`、`primary_metrics` 这类普通变量名不是架构残留，不需要强行改。

处理规则：

- 只保留技术上必要的兼容点。
- 保留时必须写清楚为什么存在、对应什么 checkpoint 或参考实现行为。
- 不能把兼容点扩散成新的业务入口。

### 需要专项重构的 custom model node

以下 custom node 不能在第五批前继续扩展功能，必须先按模型主链路稳定后的边界重新审计：

- `custom_nodes/yoloe_open_vocab_nodes/backend/nodes/_project_native_runtime.py`
- `custom_nodes/sam3_segment_nodes/backend/nodes/_project_native_runtime.py`

处理规则：

- 先拆 core / runtime / node adapter / payload helper。
- 权重读取、模型结构、prompt 处理、postprocess、preview render 分层放置。
- 旧 lightweight、compat、checkpoint 占位逻辑要按真实功能重写或删除。

### 文档里的泛用兼容词

API 文档里的“向后兼容字段”“轻量详情”“旧 session 数据回退”等不全部属于模型 full core 问题。只有涉及模型训练、转换、runtime、workflow 的旧入口才纳入本清单。

## 逐模型审计表

### RF-DETR

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/rf-detr/src/rfdetr` |
| 当前 core | `backend/service/application/models/rfdetr_core` |
| 任务范围 | detection、segmentation |
| 状态 | `需验收`，局部 `需修复` |
| 已有基础 | `models`、`datasets`、`training`、`evaluation`、`export`、`utilities` 已进入 core |
| 明确缺口 | `deploy`、`platform`、`util`、部分 CLI 能力没有完整映射；如果不纳入平台 core，必须写明不支持或迁移到 service / runtime |
| 风险点 | LoRA / PEFT 当前未启用；checkpoint 覆盖率、真实 mAP、长时训练和 deployment soak 仍需要显式记录 |
| 下一步 | 先跑真实 checkpoint 覆盖率和 detection / segmentation 全链路，再决定 `rfdetr_core` 里哪些参考目录继续复制适配，哪些明确标为不支持 |

### YOLOX

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/YOLOX_2026/yolox` |
| 当前 core | `backend/service/application/models/yolox_core` |
| 任务范围 | detection |
| 状态 | `需验收`，局部 `需修复` |
| 已有基础 | `cfg`、`data`、`evaluators`、`export`、`models`、`postprocess`、`training`、`utils` 已进入 core |
| 明确缺口 | `data_augment.py` 中仍有“最小训练预处理”描述，需要核对是否已完整覆盖 YOLOX 训练增强；COCO / VOC 训练评估要各自记录真实短链路 |
| 风险点 | 训练服务和 runtime 已拆过，但仍要检查是否有旧 evaluation / conversion helper 直接绕过 core |
| 下一步 | 核对 YOLOX data augment、scheduler、EMA、COCO/VOC evaluator、ONNX/OpenVINO/TensorRT export；跑 YOLOX COCO / VOC 全链路 |

### YOLOv8

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/ultralytics/ultralytics` |
| 当前 core | `backend/service/application/models/yolov8_core` |
| 任务范围 | detection、classification、segmentation、pose、obb |
| 状态 | `过渡残留` + `需验收` |
| 已有基础 | cfg、nn、losses、assigners、targets、data、training、evaluation、export、postprocess、inference 已成目录 |
| 明确缺口 | `yolo_core_common/primary` 已删除；detection 过渡训练入口已改为 `yolo_task_detection_training.py`，当前只剩 YOLOv8 过渡执行逻辑需要继续下沉到 `yolov8_core` |
| 风险点 | evaluation 中 mask AP、OKS、rotated AP 已靠近 COCO-style，但仍要和参考实现继续核对；全 scale checkpoint 和真实短链路需要统一记录 |
| 下一步 | 清 `yolo_primary` 过渡入口，逐项核对 v8 loss / assigner / data augmentation / export forward / runtime output layout；跑五任务全链路 |

### YOLO11

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/ultralytics/ultralytics` |
| 当前 core | `backend/service/application/models/yolo11_core` |
| 任务范围 | detection、classification、segmentation、pose、obb |
| 状态 | `过渡残留` + `需验收` |
| 已有基础 | YOLO11 专属 cfg、nn、loss、data、training、evaluation、export、runtime backend 目录已建立 |
| 明确缺口 | non-detection service / worker / evaluation 命名已收成 `yolo_task_*`，`yolo_core_common/primary` 已删除；YOLO26 detection 已切到专属入口，仍需继续清 YOLOv8 在 `yolo_task_detection_training.py` 中的 detection 过渡执行逻辑 |
| 风险点 | YOLO11 与 YOLOv8 结构相近，但不能直接复用 YOLOv8 core；只允许依赖 `yolo_core_common` 的底层能力 |
| 下一步 | 以 detection 为样板，逐任务确认 service、training、evaluation、export、runtime 不走 primary；跑五任务全链路 |

### YOLO26

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/ultralytics/ultralytics` |
| 当前 core | `backend/service/application/models/yolo26_core` |
| 任务范围 | detection、classification、segmentation、pose、obb |
| 状态 | `需修复` + `需验收` |
| 已有基础 | YOLO26 专属 cfg、nn、decode、loss、data、training、evaluation、export、postprocess、runtime backend 已建立 |
| 明确缺口 | 最近已发现 end2end TopK、export processed output、xyxy / xywh 语义需要继续核对，说明不能再简单标记为完成 |
| 风险点 | YOLO26 默认 end2end 行为与 YOLOv8 / YOLO11 不同；不能回落到旧 NMS 或旧 primary postprocess |
| 下一步 | 单独核对 YOLO26 Detect26 / Segment26 / Pose26 / OBB26 的 forward、export、TopK、box layout、runtime output；用真实转换产物复跑 ONNX / OpenVINO / TensorRT + deployment sync / async |

## full core 核对项

每个模型、每个 task 都按下面项目逐项检查，不能只看“能训练一次”。

| 核对项 | 必须确认 |
| --- | --- |
| cfg | scale、depth、width、input size、task 默认参数和参考配置一致 |
| nn/modules | backbone、neck、block、head、stride、bias init、export mode 和参考实现一致 |
| heads | Detect / Segment / Classify / Pose / OBB 专属 head 不混用 |
| loss | box、class、DFL、mask、keypoint、angle、rotated box 等 loss 与参考实现一致或明确差异 |
| assigner | TAL、anchor、候选筛选、top-k、tiny box / rbox 过滤与参考实现一致 |
| target | bbox、mask、keypoint、OBB target 编码和数据增强同步变换正确 |
| data augmentation | HSV、flip、random affine、perspective、mosaic、mixup、multi-scale、close-mosaic/no-aug schedule 按任务实现 |
| training loop | optimizer、scheduler、EMA、AMP、resume、checkpoint、best metric、pause/resume、manual save 清晰 |
| validation | validation session 和训练期 validation 的输入、runtime backend、输出指标一致 |
| evaluation | 数据集级评估按 task 输出明确指标，过渡指标必须标明 |
| export | ONNX / OpenVINO / TensorRT 的 forward 边界、输出名、dynamic shape、processed/raw layout 明确 |
| postprocess | raw output 和 export processed output 分开，NMS / TopK / mask / pose / OBB 处理不混线 |
| weights | state_dict 覆盖率、pickle checkpoint、旧模块路径映射、shape mismatch 处理可追溯 |
| runtime | PyTorch / ONNXRuntime / OpenVINO / TensorRT session 只放 runtime，模型语义调用 core |
| deployment | sync / async / warmup / reset / stop / health / 独立进程资源释放都要验收 |
| workflow | workflow service node 调用必须使用最新 deployment / inference API，不依赖旧 predictor |

## 真实全链路验收范围

验收前不启动第五批 custom nodes。

### RF-DETR

- detection
- segmentation

### YOLOX

- detection，COCO DatasetExport
- detection，VOC DatasetExport

### YOLOv8 / YOLO11 / YOLO26

- detection
- classification
- segmentation
- pose
- obb

### 每条链必须执行

每条链固定执行以下步骤：

1. DatasetImport
2. DatasetExport
3. 短训练，默认控制在十分钟以内
4. 验证和数据集级评估
5. ONNX 转换
6. OpenVINO 转换
7. TensorRT 转换
8. deployment sync 推理
9. deployment async 推理
10. stop / reset
11. workflow 调用

### 结果记录

结果统一记录到 `.tmp/model-full-core-validation/<timestamp>/`，每个模型和 task 保留：

- request 参数
- DatasetImport id
- DatasetExport id
- Training task id
- ModelVersion id
- Evaluation task id
- Conversion task id
- ModelBuild id
- DeploymentInstance id
- sync / async inference response 摘要
- workflow run id
- 失败原因和修复提交

真实长时间训练、release/full 常驻 soak、资源占用和异常恢复基线单独记录，不放默认 pytest。

## 下一步执行顺序

1. 清理 `yolo_primary_*` 过渡命名和旧入口，先从测试 smoke、worker、training/evaluation service 的命名和分发边界开始。
2. 逐模型做 full core 对照修复：RF-DETR -> YOLOX -> YOLOv8 -> YOLO11 -> YOLO26。
3. 对每个模型按任务跑真实全链路验收，并把结果写入本文档或对应结果索引。
4. 模型主链路稳定后，单独审计 YOLOE / SAM3 custom node。
5. YOLOE / SAM3 按新边界收口后，再进入第五批 custom nodes。

## 第五批进入条件

只有满足以下条件，才允许进入第五批 custom nodes：

- 本文档中 RF-DETR、YOLOX、YOLOv8、YOLO11、YOLO26 没有 `需修复` 状态。
- `yolo_primary_*` 过渡入口已经删除或改为中性命名，且不会误导后续模型实现。
- 每个模型的支持 task 都有真实全链路验收结果。
- deployment sync / async 和 workflow 调用已经确认不依赖旧 predictor。
- YOLOE / SAM3 已按最新 runtime/deployment/workflow 边界完成审计。
