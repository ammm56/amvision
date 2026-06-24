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
- 旧 `yolo_primary_*` 过渡模型构建入口
- 会让 YOLOv8、YOLO11、YOLO26 隐式混线的任务训练入口

## 残留关键词分类

本轮使用下面的范围扫描了 `primary / legacy / minimal / compat / lightweight / stub / NotImplemented / 过渡 / 旧 / 兼容 / 轻量`：

```powershell
rg -n "primary|legacy|minimal|compat|lightweight|stub|TODO|NotImplemented|过渡|旧|兼容|轻量" backend/service/application/models backend/service/application/runtime backend/workers custom_nodes tests docs/architecture docs/api -g "*.py" -g "*.md"
```

扫描结果分为四类处理。

### 已完成第一批入口收口

这些入口已经从 `yolo_primary` 收成更直白的 YOLO 主线命名，后续不再使用旧文件名。

- `backend/workers/training/yolo_primary_training_queue_worker.py` 已改为 `backend/workers/training/yolo_training_queue_worker.py`
- `backend/workers/training/yolo_primary_trainer_runner.py` 已改为 `backend/workers/training/yolo_training_runner.py`
- `backend/workers/evaluation/yolo_primary_evaluation_queue_worker.py` 已改为 `backend/workers/evaluation/model_evaluation_queue_worker.py`
- classification 训练与 evaluation 已收成 `yolov8_classification_*`，YOLO11 / YOLO26 classification 使用各自专属 service。
- pose / OBB 训练已收成 `yolov8_pose_*`、`yolov8_obb_*`，YOLO11 / YOLO26 pose / OBB 使用各自专属 service。
- segmentation 训练与 evaluation 已收成中性 `segmentation_training_*` 和 `segmentation_evaluation*`，只保留 YOLOv8 与 RF-DETR 的共享任务状态、队列、对象存储和登记分发。
- 普通 YOLO non-detection 训练 worker 已收成 `backend/workers/training/yolo_training_queue_worker.py`，执行器已收成 `backend/workers/training/yolo_training_runner.py`。
- 普通 YOLO 模型构建入口已收成 `build_yolo_model` / `get_yolo_model_config`，evaluation runtime resolver 已收成 `get_yolo_evaluation_runtime_target_resolver`。
- `tests/integration/yolo_primary_full_chain_smoke.py` 已改为 `tests/integration/yolo_model_full_chain_smoke.py`
- `tests/integration/yolov8_full_chain_smoke.py` 已删除，YOLOv8 真实短链路统一通过 `tests.integration.yolo_model_full_chain_smoke --model-type yolov8` 执行

### 已清理的过渡入口

这些命名和入口曾经会让后续误以为还存在一条通用 `YOLO primary` 模型线，现在已经改成中性共享层或迁回各自 core。

- 旧共享 detection 训练入口已删除。YOLOv8 detection 训练执行已下沉到 `backend/service/application/models/yolov8_core/training/detection_execution.py`，应用层只保留 `yolov8_detection_training.py` 入口。
- YOLO11 / YOLO26 detection 已使用各自专属训练入口，不再走共享 detection 训练文件。
- 文档历史记录中仍会出现已经删除的 `yolo_primary` 旧路径，但不能作为当前实现边界或新代码模板

处理规则：

- 如果是真共享能力，改成 `yolo_*`、`model_task_*` 或更具体的任务层命名，避免再使用会被误读为过渡层的旧 task 前缀。
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
| 状态 | `需验收`，API full chain、workflow 和前端页面操作已补记录 |
| 已有基础 | `models`、`datasets`、`training`、`evaluation`、`export`、`utilities` 已进入 core |
| 明确缺口 | `deploy`、`platform`、部分 CLI 能力没有完整映射；如果不纳入平台 core，必须写明不支持或迁移到 service / runtime。`supervision_compat` 是项目内替代 `supervision` 的受控子集，已覆盖当前 `datasets / export / visualize` 调用，不等同于完整 `supervision` 包。 |
| 风险点 | LoRA / PEFT 当前未启用；早期 checkpoint 转换保留 `legacy_checkpoint_format / legacy_ema_state_dict` 是读取 RF-DETR 旧训练产物所需，不属于旧平台入口；长时训练和更长 release/full 常驻 soak 仍需要单独记录 |
| 下一步 | 长时间训练、更长 release/full 常驻 soak、资源占用和异常恢复基线单独跑，不放默认测试 |

### YOLOX

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/YOLOX_2026/yolox` |
| 当前 core | `backend/service/application/models/yolox_core` |
| 任务范围 | detection |
| 状态 | `需验收`，API full chain、workflow 和前端页面操作已补记录，局部能力需明示范围 |
| 已有基础 | `cfg`、`data`、`evaluators`、`export`、`models`、`postprocess`、`training`、`utils` 已进入 core |
| 明确缺口 | `TrainTransform / ValTransform / MosaicDetection / MixUp / random affine / HSV / EMA / yoloxwarmcos scheduler` 已进入 core；半监督 `yoloxsemiwarmcos` 不在当前平台训练范围内，需要明示为不支持。VOC DatasetExport 已接入 `voc-python` 原生 AP 评估，不再通过 COCO-style ground truth 替代 VOC evaluation。 |
| 风险点 | COCO / VOC 训练评估要各自记录真实短链路；如果现场要求 VOC 2007 11 点 AP 口径，需要通过评估参数显式开启 `use_07_metric`，不能和默认 0.5:0.95 AP 口径混用 |
| 下一步 | 长时间训练、更长 release/full 常驻 soak、资源占用和异常恢复基线单独跑 |

### YOLOv8

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/ultralytics/ultralytics` |
| 当前 core | `backend/service/application/models/yolov8_core` |
| 任务范围 | detection、classification、segmentation、pose、obb |
| 状态 | `需验收`，API full chain、workflow 和前端页面操作已补记录；局部 evaluator 仍需靠近官方口径 |
| 已有基础 | cfg、nn、losses、assigners、targets、data、training、evaluation、export、postprocess、inference 已成目录 |
| 明确缺口 | `yolo_core_common/primary` 已删除；`yolo_primary` 和旧 task 前缀命名的 worker、training、evaluation、catalog 和测试入口已收口；YOLOv8 detection 执行编排已进入 `yolov8_core/training/detection_execution.py` |
| 风险点 | segmentation mask AP、pose OKS、OBB rotated AP 当前是项目内 COCO-style AP 实现，不等同于 Ultralytics 完整 `SegmentationValidator / PoseValidator / OBBValidator` 及 pycocotools / 专用 rotated evaluator 的全部输出口径；全 scale checkpoint 和更长 release/full soak 仍需单独记录 |
| 2026-06-24 复核 | 已对照 Ultralytics 普通 YOLO `Detect / Segment / Pose / OBB` export 行为修正 YOLOv8 detection、segmentation、pose、OBB 的 export forward：export 使用 `[B, C, N]` channel-first 布局；runtime/postprocess 入口统一转为平台内部 `[B, N, C]` 消费。非 export PyTorch runtime 仍保留平台现有 decoded tensor 入口，不把 raw head 输出误传给部署服务。 |
| 下一步 | 继续核对 v8 loss / assigner / data augmentation；长时间训练、更长 release/full 常驻 soak、资源占用和异常恢复基线单独跑 |

### YOLO11

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/ultralytics/ultralytics` |
| 当前 core | `backend/service/application/models/yolo11_core` |
| 任务范围 | detection、classification、segmentation、pose、obb |
| 状态 | `需验收`，API full chain、workflow 和前端页面操作已补记录；后续补更长 soak 和全 scale checkpoint |
| 已有基础 | YOLO11 专属 cfg、nn、loss、data、training、evaluation、export、runtime backend 目录已建立 |
| 明确缺口 | non-detection service / worker / evaluation 命名已收成 YOLOv8 专属、YOLO11/YOLO26 专属或中性 segmentation 命名；`yolo_core_common/primary` 已删除；YOLOv8 / YOLO11 / YOLO26 detection 均已切到各自专属训练入口 |
| 风险点 | YOLO11 与 YOLOv8 结构相近，但不能直接复用 YOLOv8 core；只允许依赖 `yolo_core_common` 的底层能力 |
| 2026-06-24 复核 | 已对照 Ultralytics 普通 YOLO `Detect / Segment / Pose / OBB` export 行为修正 YOLO11 pose、OBB 的 export forward，并确认 detection、segmentation 已保持 `[B, C, N]` channel-first export；runtime/postprocess 入口统一转为平台内部 `[B, N, C]` 消费。 |
| 下一步 | 继续补全 scale checkpoint、更长 release/full 常驻 soak、资源占用和异常恢复基线 |

### YOLO26

| 项 | 当前判断 |
| --- | --- |
| 参考目录 | `projectsrc/ultralytics/ultralytics` |
| 当前 core | `backend/service/application/models/yolo26_core` |
| 任务范围 | detection、classification、segmentation、pose、obb |
| 状态 | `已记录`，processed layout 已用真实转换产物复验 |
| 已有基础 | YOLO26 专属 cfg、nn、decode、loss、data、training、evaluation、export、postprocess、runtime backend 已建立 |
| 本轮修复 | 已对照 `Detect26 / Segment26 / Pose26 / OBB26` 修正 end2end forward/export 语义：训练态保留 raw head 输出，推理非 export 返回 processed + raw，export 返回 processed；detection processed 输出为 `[x1, y1, x2, y2, score, class]`，segmentation / pose 在相同前 6 列后追加 mask coeff 或 keypoints，OBB 输出为 `[x, y, w, h, score, class, angle]`。同时修复 `Segment26` 的 `Proto26 npr` 参数传递，并为 YOLO26 PyTorch runtime 增加 detection / segmentation 输出适配。2026-06-24 又修复 segmentation 训练期 evaluation 对 `((processed, proto), raw)` nested output 的解包，避免把 processed/raw 双输出误当成普通数组。 |
| 风险点 | YOLO26 默认 end2end 行为与 YOLOv8 / YOLO11 不同；不能回落到旧 NMS 或旧 primary postprocess |
| 复验结果 | 2026-06-24 已用真实转换产物复跑 ONNX / OpenVINO / TensorRT conversion 与 deployment sync / async smoke。detection / classification 结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-processed-layout-smoke-20260624-r2/result.json`；segmentation / pose / OBB 结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-processed-layout-smoke-20260624-r3/result.json`。三种 runtime backend 均按 processed layout 正常解析。 |

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

### 真实全链路验收记录表

本表只记录已经能追溯到命令、结果目录、测试文件或明确待办的事实。`current-implementation-status.md` 可以保留时间线流水，本表作为模型 full core 验收的总入口。

状态说明：

- `已记录`：已跑通短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async、推理和 stop / reset，并写明结果位置。
- `部分已跑`：已经跑过 checkpoint、转换、runtime backend 或某个 task 子集，但没有覆盖完整链路。
- `待补记录`：实现和历史调试显示可用，但缺少可追踪结果目录或命令记录。
- `待跑`：还没有按本文档要求跑完整链路。
- `不适用`：该模型不支持该 task。

| 模型 | 任务 / 数据集范围 | 导入 / 导出 | 短训练 / 评估 | ONNX / OpenVINO / TensorRT | deployment sync / async / stop-reset | workflow / 前端 | 当前状态 | 记录与下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RF-DETR | detection | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/model-full-core-validation/rfdetr-api-onnx-20260623-fix3`、`.tmp/model-full-core-validation/rfdetr-api-openvino-20260623-fix1`、`.tmp/model-full-core-validation/rfdetr-api-tensorrt-20260623`。workflow 结果目录：`.tmp/model-full-core-validation/rfdetr-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| RF-DETR | segmentation | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/model-full-core-validation/rfdetr-api-seg-onnx-20260623-fix4`、`.tmp/model-full-core-validation/rfdetr-api-openvino-20260623-fix1`、`.tmp/model-full-core-validation/rfdetr-api-tensorrt-20260623`。workflow 结果目录：`.tmp/model-full-core-validation/rfdetr-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOX | detection，COCO DatasetExport | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/model-full-core-validation/yolox-api-onnx-20260623`、`.tmp/model-full-core-validation/yolox-api-openvino-20260623`、`.tmp/model-full-core-validation/yolox-api-tensorrt-20260623`。workflow 结果目录：`.tmp/model-full-core-validation/yolox-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOX | detection，VOC DatasetExport | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、VOC DatasetExport 原生评估入口、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录同 COCO 行；workflow 结果目录：`.tmp/model-full-core-validation/yolox-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOv8 | detection | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-api-full-chain-20260623`。该 run 后续因 segmentation ONNX 校验失败整体标记 failed，但 detection 子链路已完整成功；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOv8 | classification | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-api-full-chain-20260623`。该 run 后续因 segmentation ONNX 校验失败整体标记 failed，但 classification 子链路已完整成功；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOv8 | segmentation | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-23 修复 YOLOv8 ONNX 数值校验输入和 mean-ratio accepted 摘要后，已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-segmentation-full-chain-20260623-fix1`；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOv8 | pose | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-pose-obb-full-chain-20260623-fix1`；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLOv8 | obb | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-23 已跑真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT、deployment sync / async / stop-reset。结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-pose-obb-full-chain-20260623-fix1`；workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolov8-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | detection | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-20 已跑 `tests.integration.yolo_model_full_chain_smoke --model-type yolo11 --tasks detection classification segmentation pose obb --target-formats onnx openvino-ir tensorrt-engine --max-epochs 1 --batch-size 1 --max-images-per-split 4 --start-processes`，结果在 `.tmp/yolo-model-full-chain-smoke/20260620110947/result.json`。workflow 结果目录：`.tmp/yolo-model-full-chain-smoke/yolo11-workflow-record-20260623`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | classification | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 同 YOLO11 detection 记录；2026-06-23 另有 classification workflow probe 修复记录，结果使用 `yolo11-classification-workflow-probe-20260623-fix2`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | segmentation | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 同 YOLO11 detection 记录；前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | pose | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-19 另有 pose / OBB ONNX 子集记录 `.tmp/yolo11-pose-obb-20260619161813`；完整三格式链路见 2026-06-20 记录，workflow 见 2026-06-23 记录。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO11 | obb | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 同 YOLO11 pose 记录；前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | detection | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 2026-06-24 processed layout 和普通 YOLO export layout 修复后，已跑严格真实转换产物 smoke：真实 DatasetImport / DatasetExport、短训练、评估、ONNX / OpenVINO / TensorRT conversion、deployment sync / async、workflow 调用均成功。结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | classification | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 同 YOLO26 detection 严格真实转换产物 smoke；结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | segmentation | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 同 YOLO26 detection 严格真实转换产物 smoke；已覆盖 `((processed, proto), raw)` 非 export 调试输出与 export processed layout 的 runtime 解析边界。结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | pose | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 同 YOLO26 detection 严格真实转换产物 smoke；结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |
| YOLO26 | obb | 已记录 | 已记录 | 已记录 | 已记录 | workflow / 前端已记录 | 已记录 | 同 YOLO26 detection 严格真实转换产物 smoke；结果目录：`.tmp/yolo-model-full-chain-smoke/yolo26-strict-real-artifact-smoke-20260624-r1/result.json`。前端页面操作记录：`.tmp/frontend-operation-record-20260623`。 |

当前最小补缺顺序：

1. RF-DETR detection / segmentation：API 链路、workflow 和前端页面操作已补；后续补更长时间 soak。
2. YOLOX detection COCO / VOC：API 链路、workflow 和前端页面操作已补；后续补更长时间 soak。
3. YOLOv8 五任务：API 链路、workflow 和前端页面操作已补；后续补全 scale checkpoint 和更长时间 soak。
4. YOLO11 / YOLO26：workflow 调用和前端页面操作已补记录。如果模型 core 后续继续修复，需要重新跑对应 task 行。
5. 所有模型：release/full 60 秒短 soak、资源占用和异常恢复基线已补；更长时间 soak 单独记录，不放进默认 pytest。

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

前端页面操作记录：

- 2026-06-23 已跑模型页、部署页、推理页、workflow 应用列表和 workflow 应用详情页。
- 部署页和推理页已切换 detection / classification / segmentation / pose / obb 五个 `task_type`，没有 Bad Request、Internal Server Error 或 Not Found。
- 模型页当前没有全局 `task_type` 下拉，任务类型通过基础模型和数据集选择面板进入训练 / 转换表单。
- 结果目录：`.tmp/frontend-operation-record-20260623`。

release/full 短 soak 记录：

- 2026-06-23 已跑 `tests/integration/test_release_full_stack_acceptance.py`，`AMVISION_RELEASE_FULL_SOAK_SECONDS=60`，端口 `18080`。
- 已验证 `/api/v1/system/health`、`/docs`、`/openapi.json`、full stack 组件日志、资源采样、stop 脚本回收和进程残留检查。
- 资源基线文件：`release/full/logs/release-full-short-soak-20260623/resource-baseline.json`。
- 日志目录：`release/full/logs/release-full-short-soak-20260623`。日志中未发现 `ERROR`、`Traceback`、`Exception`、`failed` 等异常关键词。
- 60 秒采样内 backend-service、dataset-import、dataset-export、training、conversion、evaluation、inference 组件 RSS 没有增长，stop 后 `runtime-state.json` 已删除，端口 `18080` 无残留监听。

真实长时间训练、更长 release/full 常驻 soak、资源占用和异常恢复基线单独记录，不放默认 pytest。

## 下一步执行顺序

1. 逐模型做 full core 对照复核，重点确认没有轻量近似、旧入口或错误共享；如果复核发现代码修复，修复后重新跑对应 task 行。
2. 按需补更长时间训练、更长 release/full 常驻 soak、资源占用和异常恢复基线。
3. 模型主链路稳定后，单独审计 YOLOE / SAM3 custom node。
4. YOLOE / SAM3 按新边界收口后，再进入第五批 custom nodes。

## 第五批进入条件

只有满足以下条件，才允许进入第五批 custom nodes：

- 本文档中 RF-DETR、YOLOX、YOLOv8、YOLO11、YOLO26 没有 `需修复` 状态。
- 旧 `yolo_primary_*` 入口已经删除或改为中性命名；旧共享 detection 训练入口也已删除或完全下沉到 `yolov8_core`。
- 每个模型的支持 task 都有真实全链路验收结果。
- deployment sync / async 和 workflow 调用已经确认不依赖旧 predictor。
- YOLOE / SAM3 已按最新 runtime/deployment/workflow 边界完成审计。
