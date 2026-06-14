# 模型 core 实现计划

## 文档目的

本文档固定 `YOLOX / YOLOv8 / YOLO11 / YOLO26 / RF-DETR` 在本项目中的完整 core 实现边界。

这里的重点不是再新增一个模型分类，而是把当前“平台链路已接通”的实现继续收成“模型结构、训练逻辑、权重加载、评估和导出都可长期维护”的项目内 core。

## 保存位置

- `projectsrc/` 只作为开发阶段参考源码目录，不作为运行时代码来源。
- 项目运行时代码只能依赖 `backend/`、`custom_nodes/`、`frontend/`、`runtimes/` 和明确登记的本项目代码。
- 预训练模型和转换产物继续放在 `data/files/models/` 约定目录，不放进 git。
- 模型结构 core、训练 loss、权重映射、导出 forward 边界统一放在 `backend/service/application/models/`。
- `backend/service/application/runtime/` 只放 deployment runtime、长期驻留会话、加载器、推理包装和运行时后端适配，不放模型结构 core。

## 命名

目标 core 包按模型分类命名：

- `yolox_core`
- `yolov8_core`
- `yolo11_core`
- `yolo26_core`
- `rfdetr_core`

公开 API 和前端仍使用 `model_type`、`task_type` 和现有任务入口。`*-core` 是模型实现层，不直接暴露给外部系统。

## 适用范围

本文档集中承担 YOLO 系列规划职责，后续不再维护第二份 YOLO 规划文档。

普通 YOLO 主线当前只覆盖这些模型分类：

- `yolox`
- `yolov8`
- `yolo11`
- `yolo26`

普通 YOLO 主线当前按这些任务分类拆分：

- `detection`
- `segmentation`
- `classification`
- `pose`
- `obb`

`yolo-world`、`yoloe` 不纳入普通 YOLO full core 主线。它们包含 text prompt、visual prompt、open-vocabulary 或动态类别能力，后续按 prompt / open-vocabulary 扩展模型单独规划，不和 `YOLOv8 / YOLO11 / YOLO26` 的普通任务 core 混在一起。

`projectsrc/ultralytics` 中可见的 `v3`、`v5`、`v6`、`v9`、`v10`、`12` 等历史或其他版本当前不优先进入主线。后续如确有现场需求，也必须按本文档的 `models/*_core`、`task_type` 和验收规则进入，不为单个版本复制一条新架构。

## 分层关系

YOLO 系列长期按下面五层理解：

- 平台通用层：DatasetVersion、DatasetExport、ModelVersion、ModelBuild、DeploymentInstance、TrainingBackend、ConversionBackend、ModelRuntime、workflow 和任务系统。
- YOLO 共用层：`yolo_core_common` 中真正跨 `YOLOv8 / YOLO11 / YOLO26` 共用的基础层、几何工具、decode 辅助和后续通用 loss / target 工具。
- 任务分类层：detection、segmentation、classification、pose、obb 各自的输入输出、loss、assigner、decode、postprocess 和评估规则。
- 模型分类层：`yolox_core`、`yolov8_core`、`yolo11_core`、`yolo26_core` 各自的配置、head 差异、权重映射和训练/导出细节。
- 运行时后端层：PyTorch、ONNXRuntime、OpenVINO、TensorRT 等 deployment backend，只负责加载、warmup、reset、资源释放和同步/异步推理包装。

这五层不能互相替代。尤其是 runtime backend 不是模型 core，平台 service / worker 也不承载模型结构细节。

## 目录归属规则

`models/` 和 `runtime/` 的职责不能混用：

- `backend/service/application/models/*_core/`：放模型结构、head、decoder、loss、assigner、target 编码、权重加载、导出 forward 和 core 验收工具。
- `backend/service/application/models/*_training_service.py`、`*_evaluation_task_service.py`、`*_inference_task_service.py` 这类文件属于应用服务层，负责任务参数、状态、产物登记和数据库交互，不属于模型 core。
- `backend/service/application/models/*_training.py`、`*_evaluation.py` 里如果包含 loss、assigner、target 编码、数据增强或权重映射，应逐步拆入对应 `*_core/`；如果只是任务执行外壳，则保留在应用服务层或后续再按任务目录整理。
- `backend/service/application/runtime/`：放推理后端加载、长驻会话、同步/异步推理包装、进程健康检查、warmup、reset 和资源释放。
- `backend/service/application/runtime/*_predictor.py` 可以后续按任务或模型整理成子目录，但不应整体移动到 `*_core/`。predictor 依赖 ONNXRuntime、OpenVINO、TensorRT、CUDA buffer、session pool 和结果序列化，属于 deployment runtime 外壳。
- service / worker 层只调用 core 的正式入口，不直接理解 head、loss、assigner 内部细节。

当前 `backend/service/application/runtime/yolox_core/` 是早期实现留下的历史落点，不是新的目标目录。下一批第一步应完成 YOLOX core 迁移，把模型结构相关代码收敛到 `backend/service/application/models/yolox_core/`，runtime 目录只保留 YOLOX 推理加载和会话外壳。

在 YOLOX core 完成迁移前，不应继续往 `runtime/yolox_core/` 扩展新的模型结构能力；除 bugfix 外，新 core 能力统一落到 `models/*_core/`。

## 完整 core 的含义

完整 core 至少包含这些内容：

- 模型结构：backbone、neck、head、decoder、query、attention、mask head 等核心模块。
- 配置解析：从项目内配置构建模型，不依赖 `projectsrc/` 或官方 pip 包。
- 权重加载：支持本项目训练权重、预训练权重和继续训练权重，记录加载覆盖率和跳过原因。
- 训练损失：classification / box / DFL / mask / keypoint / angle / matcher / assigner 等实际训练损失。
- 数据处理：训练和评估所需的输入缩放、归一化、label 编码和必要增强。
- 后处理：NMS、top-k、mask decode、pose decode、obb decode、score 和类别过滤。
- 评估：按任务输出可追踪指标，和训练结果登记一致。
- 导出：ONNX、OpenVINO、TensorRT 路径使用同一套 core forward 边界。
- 测试：结构快照、state_dict 加载、tiny dataset overfit、转换、部署、推理都要有定向回归。

不把下面这些内容称为完整 core：

- 只用 YAML 配置加少量共享模块拼出 forward。
- 只跑通 smoke，但 loss / assigner / 数据增强和参考实现明显不同。
- 只做权重 shape 能加载，但没有记录覆盖率。
- 运行时回退到已安装 `ultralytics`、`rfdetr` 或 `projectsrc` 目录。

## 大重构目标状态

本轮模型 core 收口按一次大重构理解，不再继续把模型核心能力分散在 `models/`、`runtime/`、`workers/` 和历史 helper 文件里零散推进。

目标状态只有一套：

```text
backend/service/application/models/
  yolox_core/
  yolov8_core/
  yolo11_core/
  yolo26_core/
  rfdetr_core/
  yolo_core_common/
```

核心边界：

- `*_core/` 放模型结构、配置、head、loss、assigner、matcher、target 编码、postprocess、权重加载、训练/评估核心、导出 forward。
- `yolo_core_common/` 只放 `YOLOv8 / YOLO11 / YOLO26` 真正共用且不判断 `model_type` 的基础层和数学工具。
- `runtime/` 只放 deployment runtime、session、predictor、backend adapter、warmup、reset、同步/异步推理包装。
- `workers/` 只放任务执行、对象存储读写、进度事件、产物登记和子进程调用，不放模型结构、head、loss、matcher。
- `*_training_service.py`、`*_conversion_task_service.py`、`*_evaluation_task_service.py` 只做应用服务外壳，不放模型训练核心逻辑。
- `projectsrc/` 只做参考和迁移来源，迁移完成后运行时代码不得 import `projectsrc`。

必须删除或迁走的历史落点：

- `backend/service/application/runtime/yolox_core/` 必须整体迁到 `backend/service/application/models/yolox_core/`，迁移后删除 runtime 下的 `yolox_core` 目录。
- `backend/service/application/models/rfdetr_model.py`、`rfdetr_segmentation_model.py` 中的模型结构应迁入 `rfdetr_core/`，原文件只允许短期保留应用层兼容入口；最终删除或降级为薄入口。
- `backend/service/application/models/yolo_detection_model.py` 中的 YOLO 主线模型结构、head、decode、loss、postprocess 应迁入 `yolo_core_common/` 和对应 `yolov8_core / yolo11_core / yolo26_core`，最终删除或降级为测试工具。
- `yolo_primary_*_training.py`、`pose_loss.py`、`obb_loss.py`、`rfdetr_*_training.py` 里如果还包含 loss、assigner、target、matcher、数据增强或权重映射，必须迁入对应 core。

迁移规则：

- 不保留 legacy alias 作为长期路径。
- 不为了兼容旧数据保留双目录。
- 不用“轻量实现”冒充 full core。
- 删除旧路径前必须先完成 import graph 替换，不能留下隐藏引用。
- 每个大批次结束后跑一次定向回归，不要求每移动一个函数都单独跑完整测试。

runtime 目录也要同步收口，但收口方式不是把所有 runtime 文件移进 core：

- `*_predictor.py`、`*_model_runtime.py`、`*_runtime_contracts.py`、`*_runtime_serialization.py` 仍属于 runtime，只是要按 `predictors/`、`tasks/`、`contracts/`、`serialization/` 拆目录。
- `deployment_process_*`、`deployment_runtime_pool.py`、`deployment_events.py` 仍属于 runtime 的 `deployment/`。
- `runtime_target.py` 和各模型 `*_runtime_target.py` 仍属于 runtime 的 `targets/`。
- 只有 runtime 文件里残留的模型结构、网络层、loss、matcher、训练逻辑、权重映射，才迁入对应 `*_core`。
- 当前必须迁入 core 的 runtime 目录是 `runtime/yolox_core`；迁完后删除旧目录。

## 参考仓库使用规则

参考仓库优先级按许可证和项目目标分开处理：

| 模型 | 参考目录 | 许可证处理 | 本项目落地方式 |
| --- | --- | --- | --- |
| `YOLOX` | `projectsrc/YOLOX_2026/yolox` | Apache-2.0，允许复制适配并保留来源说明 | 优先把参考仓库中模型、loss、训练、评估、EMA、scheduler、utils 按本项目目录整理到 `models/yolox_core/`。 |
| `RF-DETR` | `projectsrc/rf-detr/src/rfdetr` | Apache-2.0，允许复制适配并保留来源说明 | 优先按参考仓库结构建立 `models/rfdetr_core/`，完整迁入 backbone、LW-DETR、matcher、criterion、postprocess、export、training。 |
| `YOLOv8 / YOLO11 / YOLO26` | `projectsrc/ultralytics/ultralytics` | AGPL-3.0，不能默认当 permissive 代码整包复制 | 默认按结构、配置和数学行为参考重写；如决定复制 AGPL 文件，必须先新增许可证决策记录并接受分发影响。 |

这条规则不是“少实现”，而是把 full core 和许可证风险分开。`YOLOX`、`RF-DETR` 可以按参考仓库优先复制适配；`YOLOv8 / YOLO11 / YOLO26` 必须在许可证决策清楚后才能直接复制 AGPL 文件。

## 目标目录结构

### YOLOX

`YOLOX` 只有 detection 任务，目标目录按参考仓库结构收口：

```text
backend/service/application/models/yolox_core/
  __init__.py
  cfg/
    detection.py
  models/
    __init__.py
    build.py
    darknet.py
    losses.py
    network_blocks.py
    yolo_fpn.py
    yolo_head.py
    yolo_pafpn.py
    yolox.py
  data/
    __init__.py
    augment.py
    detection.py
  evaluators/
    __init__.py
    coco.py
    voc.py
  training/
    __init__.py
    trainer.py
    ema.py
    scheduler.py
    checkpoint.py
  export/
    __init__.py
    onnx.py
    openvino.py
    tensorrt.py
  postprocess/
    __init__.py
    detection.py
  weights.py
  validation.py
```

迁移动作：

- 先整体移动 `runtime/yolox_core/models` 和 `runtime/yolox_core/utils` 到 `models/yolox_core/`。
- 再把 `yolox_detection_training.py` 中的数据增强、训练循环、loss 调用、EMA、scheduler 和 checkpoint 逻辑下沉到 `yolox_core/training/`。
- `yolox_detection_runtime.py` 只保留 runtime session、输入输出序列化、backend adapter 和 deployment 资源管理。
- 迁移完成后删除 `backend/service/application/runtime/yolox_core/`。

### YOLOv8 / YOLO11 / YOLO26

三个模型代际外层必须分开，内部任务目录一致：

```text
backend/service/application/models/yolov8_core/
backend/service/application/models/yolo11_core/
backend/service/application/models/yolo26_core/
  __init__.py
  cfg/
    detection.py
    segmentation.py
    classification.py
    pose.py
    obb.py
  nn/
    __init__.py
    modules/
      conv.py
      block.py
      head.py
      transformer.py
    tasks/
      detection.py
      segmentation.py
      classification.py
      pose.py
      obb.py
  losses/
    detection.py
    segmentation.py
    classification.py
    pose.py
    obb.py
  assigners/
    detection.py
    segmentation.py
    pose.py
    obb.py
  targets/
    detection.py
    segmentation.py
    classification.py
    pose.py
    obb.py
  postprocess/
    detection.py
    segmentation.py
    classification.py
    pose.py
    obb.py
  data/
    detection.py
    segmentation.py
    classification.py
    pose.py
    obb.py
    augment.py
  training/
    trainer.py
    optimizer.py
    scheduler.py
    ema.py
    checkpoint.py
  validation/
    detection.py
    segmentation.py
    classification.py
    pose.py
    obb.py
  export/
    onnx.py
    openvino.py
    tensorrt.py
  weights.py
```

落地规则：

- `yolov8_core`、`yolo11_core`、`yolo26_core` 不能共用一个 `yolo_primary` 大模型文件表达差异。
- YOLO26 的 `Segment26 / Pose26 / OBB26` 必须只在 `yolo26_core` 内部出现。
- `yolo_core_common` 只承接 anchor、bbox、DFL、通用 NMS 前过滤、通用 tensor 工具等不含模型代际判断的能力。
- `yolo_primary_*` 文件最终只保留平台共享 service / worker 外壳；模型结构和训练细节必须进各自 core。

### RF-DETR

`RF-DETR` 目标是按参考仓库建立完整 `rfdetr_core`，不再保留项目内轻量模型作为长期方案：

```text
backend/service/application/models/rfdetr_core/
  __init__.py
  config.py
  variants.py
  assets/
    coco_classes.py
    model_weights.py
  models/
    __init__.py
    backbone/
      base.py
      backbone.py
      dinov2.py
      dinov2_with_windowed_attn.py
      projector.py
    heads/
      detection.py
      segmentation.py
    ops/
      functions/
      modules/
    criterion.py
    matcher.py
    math.py
    lwdetr.py
    position_encoding.py
    postprocess.py
    segmentation_head.py
    transformer.py
    weights.py
  training/
    trainer.py
    checkpoint.py
    module_data.py
    module_model.py
    model_ema.py
    param_groups.py
    drop_schedule.py
    callbacks/
  evaluation/
    coco_eval.py
    matching.py
    f1_sweep.py
  export/
    onnx.py
    tensorrt.py
    openvino.py
  inference.py
  weights.py
```

迁移动作：

- 先按 `projectsrc/rf-detr/src/rfdetr/models` 建立 `rfdetr_core/models`，保证 backbone、LW-DETR transformer、matcher、criterion、postprocess 和 segmentation head 都在 core 内。
- 再把 `rfdetr_model.py`、`rfdetr_segmentation_model.py` 改成从 `rfdetr_core` 调用正式 builder；确认无业务引用后删除旧模型结构文件。
- 再把 `rfdetr_training.py`、`rfdetr_segmentation_training.py` 中的训练核心迁入 `rfdetr_core/training/`。
- `runtime/rfdetr_predictor.py` 和 `runtime/rfdetr_segmentation_predictor.py` 只保留 deployment session 和结果序列化。

## 依赖边界

允许使用项目 requirements 中明确列出的基础依赖，例如：

- `torch`
- `torchvision`
- `numpy`
- `opencv-python`
- `scipy`
- `pycocotools`
- `onnx`
- `onnxruntime`
- `openvino`
- `tensorrt`

不允许把下面内容作为运行时依赖：

- `ultralytics` pip 包
- `rfdetr` pip 包
- `projectsrc/ultralytics`
- `projectsrc/rf-detr`
- `projectsrc/YOLOX_2026`

如果确实需要新增第三方依赖，必须先进入 `requirements.txt`，并在文档中说明用途、许可证和是否为可选依赖。

## 许可证边界

- `YOLOX_2026` 和 `rf-detr` 参考仓库是 Apache-2.0，允许在保留许可证和来源说明的前提下做项目内适配。
- `ultralytics` 参考仓库是 AGPL-3.0。不能把它当作普通 permissive 代码直接整包复制进本项目。
- `YOLOv8 / YOLO11 / YOLO26` 的项目内 core 应以本项目代码重新实现模型结构和训练逻辑，参考公开配置、结构和数学行为，避免运行时依赖官方包。
- 如果后续决定直接引入 AGPL 代码，必须先把项目分发和服务使用的许可证影响单独评估并形成决策记录。

## YOLO 主线 full core 详细计划

本节是 `YOLOv8 / YOLO11 / YOLO26` 完整 core 实现的唯一详细计划。其他文档只保留导航，不重复维护 YOLO 目录、任务拆分或进入顺序。

目标是把当前共享的 `yolo_primary` 实现继续收成清晰的两层结构：

- 第一层按 `model_type` 隔离模型代际：`yolov8_core`、`yolo11_core`、`yolo26_core`。
- 第二层按 `task_type` 隔离任务能力：`detection`、`segmentation`、`classification`、`pose`、`obb`。

### Ultralytics 参考边界

`projectsrc/ultralytics/ultralytics` 只作为参考源码面。目录结构、模块职责、配置组织和数学行为可以对齐；运行时代码默认采用本项目内重写实现，不直接复制 AGPL 源码。

如后续确实需要复制某个 AGPL 文件，必须先新增单独决策记录，说明：

- 文件来源和原始许可证。
- 复制原因和不能重写的具体理由。
- 对本项目分发、部署和服务使用的影响。
- 是否需要在源文件头部和文档中保留 AGPL-derived 标记。

默认禁止下面做法：

- 直接把 `ultralytics` 包作为 requirements 运行时依赖。
- 从 `projectsrc/ultralytics` import 运行时代码。
- 复制 upstream `engine`、HUB、自动下载、遥测、CLI 或在线服务代码作为平台默认路径。
- 把 upstream 的公开参数、目录规则或 `Results` 对象直接暴露成本项目 API。

### 参考目录映射

| Ultralytics 参考位置 | 本项目目标位置 | 落地规则 |
| --- | --- | --- |
| `ultralytics/nn/modules/*` | `yolo_core_common/nn/modules/` 和各 `*_core/nn/modules/` | 基础层进入 common；模型代际或任务专属 head 留在各自 core。 |
| `ultralytics/nn/tasks.py` | 各 core 的 `nn/tasks/*.py` | 按 `task_type` 拆成 detection、segmentation、classification、pose、obb，不保留一个大 tasks 文件。 |
| `ultralytics/utils/loss.py` | 各 core 的 `losses/*.py` 和 `yolo_core_common/losses/` | 通用数学函数放 common；任务 loss 放任务文件。 |
| `ultralytics/utils/tal.py` | 各 core 的 `assigners/*.py` | detection / segmentation / pose / obb 的 target 分配按任务拆开。 |
| `ultralytics/utils/ops.py` | `yolo_core_common/utils/ops.py` 与各 core `postprocess/*.py` | bbox、mask、keypoint、rotated box 后处理按任务边界拆开。 |
| `ultralytics/cfg/models/v8` | `yolov8_core/cfg/` | 只保留 YOLOv8 需要的 detection、segmentation、classification、pose、obb 配置。 |
| `ultralytics/cfg/models/11` | `yolo11_core/cfg/` | 只保留 YOLO11 需要的五类任务配置。 |
| `ultralytics/cfg/models/26` | `yolo26_core/cfg/` | 只保留 YOLO26 需要的五类任务配置，YOLO26 特有 head 不和 YOLOv8/11 混用。 |
| `ultralytics/engine/*` | 本项目 `train.py`、`val.py`、`predict.py`、`export.py` | 不照搬 engine 生命周期；只按本项目 service / worker / deployment 边界实现。 |
| `ultralytics/models/yolo/*` | 各 core 的任务入口和平台 service 适配层 | 参考任务职责，不复制 upstream 对外 API。 |

### 任务分类实现边界

每个 core 内部按任务拆分，不再把五类任务混在一个大文件里。

| task_type | core 内部必须单独实现的内容 |
| --- | --- |
| `detection` | Detect head、bbox decode、TAL assigner、box/class/DFL loss、NMS postprocess。 |
| `segmentation` | Segment head、proto/mask decode、mask target、assigner、box/class loss、mask loss、mask postprocess。 |
| `classification` | Classify head、classification loss、top-k / score postprocess。 |
| `pose` | Pose / Pose26 head、keypoint decode、keypoint target、pose loss、pose postprocess。 |
| `obb` | OBB / OBB26 head、angle decode、rotated target、probiou / angle loss、rotated postprocess。 |

`weights.py` 每个 core 都必须输出 state_dict 加载覆盖率，不允许静默跳过。最低摘要字段包括：

- loaded key count
- missing keys
- unexpected keys
- shape mismatch keys
- ignored keys
- loadable ratio

`export.py` 每个 core 都必须定义 ONNX / OpenVINO / TensorRT 使用的稳定 forward 边界。转换 service 只调用 core 的导出入口，不直接拼接 head 内部输出。

service / worker 层最终只调用 core 的正式入口，不再理解 head、loss、assigner、decode 的内部细节。

### 大批次迁移顺序

本轮按大批次迁移，不再把每个 helper 作为独立阶段推进。每个大批次结束后跑定向回归，确认 import graph、训练最小链、转换最小链和 deployment 推理链没有断。

1. `YOLOX` core 迁移：把 `runtime/yolox_core` 一次性迁到 `models/yolox_core`，同步修正 `yolox_detection_runtime.py`、`yolox_detection_training.py`、`yolox_conversion_runner.py` 的 import，确认无引用后删除 `runtime/yolox_core`。
2. `RF-DETR` full core：按 `projectsrc/rf-detr/src/rfdetr` 的结构建立 `models/rfdetr_core`，优先复制并适配 Apache-2.0 参考实现中的 `models/`、`training/`、`evaluation/`、`export/`、`util/` 关键代码，替换当前 `rfdetr_model.py`、`rfdetr_segmentation_model.py` 中的轻量模型结构。
3. `YOLOv8 / YOLO11 / YOLO26` full core：按 `model_type` 分别补齐 `cfg`、`nn/modules`、`nn/tasks`、`losses`、`assigners`、`targets`、`postprocess`、`data`、`training`、`validation`、`export`、`weights`。Ultralytics 代码只按许可证规则参考；未做 AGPL 决策前不直接复制源码。
4. 清理 `models/` 中散落的历史模型文件：把 `yolo_detection_model.py`、`yolo_primary_*_training.py`、`pose_loss.py`、`obb_loss.py`、`rfdetr_*_training.py` 中的模型核心迁走，剩余 service 外壳按任务或模型归档。
5. 清理 `runtime/`：保留 predictor、session、backend adapter、runtime target、序列化和长期驻留管理；删除或迁出所有模型结构、loss、matcher、head、训练逻辑。
6. 清理 `workers/`：转换和训练 worker 只调用 core 的正式入口，不再直接拼 ONNX 输出、head 输出、loss 或 matcher。
7. 全链路验收：按 `model_type × task_type` 跑数据集导入/导出、训练、验证、评估、转换、deployment sync/async、推理、workflow invoke 和前端创建任务查看结果。

### YOLO core 验收规则

每个 `model_type × task_type` 组合必须至少通过：

- 结构快照和输出形状测试。
- state_dict 自身完整覆盖率测试。
- 带外层前缀 checkpoint 的 key 归一测试。
- shape mismatch 覆盖率测试。
- loss backward smoke。
- tiny dataset overfit smoke。
- ONNX -> ONNXRuntime smoke。
- OpenVINO / TensorRT 定点 smoke。
- deployment sync / async 推理 smoke。
- workflow direct model node smoke。
- 运行时代码不得直接导入 `ultralytics`，不得引用 `projectsrc`。

## 当前真实状态

### core 验收工具

已新增 `backend/service/application/models/model_core_validation.py`，作为后续拆 core 前的统一验收工具。

当前工具覆盖：

- 参数量、可训练参数量、buffer 数、state_dict key 数和叶子模块类型统计。
- 模型输出形状摘要，支持 tensor、tuple、list 和 dict 输出。
- state_dict 加载覆盖率分析，支持精确 key 匹配、常见外层前缀剥离、missing / unexpected / shape mismatch 分类记录。

已新增 `tests/test_model_core_validation_tools.py`，覆盖 `YOLOv8 / YOLO11 / YOLO26` 的 detection、classification、segmentation、pose、obb nano 结构快照和输出形状，并验证项目内 state_dict、带 `module.model.` 外层前缀的 state_dict、shape mismatch 三类加载覆盖率场景。

已新增 `tests/test_model_core_dependency_boundaries.py`，检查模型和运行时实现不得直接导入 `ultralytics` / `rfdetr`，不得把 `projectsrc/` 作为运行时代码来源。

### YOLOX

`YOLOX` 当前已有 `backend/service/application/runtime/yolox_core/`，模型结构与训练主线相对完整，但这个位置是历史落点，不符合当前统一的 core 目录规则。

目标状态：

- `backend/service/application/models/yolox_core/`：放 YOLOX 模型结构、loss、权重加载、训练/导出 core 边界和验收工具。
- `backend/service/application/runtime/`：只保留 YOLOX deployment runtime、长期驻留会话、加载器和推理包装。

下一批第一步应单独完成 YOLOX core 迁移，不和 YOLOv8 / YOLO11 / YOLO26 的 full core 补齐混在同一个提交里。

### YOLOv8 / YOLO11 / YOLO26

当前三类模型已接入平台主链，支持：

- detection
- classification
- segmentation
- pose
- obb

当前实现已开始从 `yolo_primary` 共享外壳拆出模型分类 core：

- `backend/service/application/models/yolov8_core/`
- `backend/service/application/models/yolo11_core/`
- `backend/service/application/models/yolo26_core/`

第一阶段已经把每个模型分类的任务配置和 builder 入口放入各自 core 包。`yolo_primary_model_configs.py` 只保留平台统一分发职责，不再承载三类模型的任务配置。

每个 core 包已经显式登记自己的 head/decode 入口：

- `yolov8_core/heads.py`：`Detect / Segment / Pose / OBB / Classify`
- `yolo11_core/heads.py`：`Detect / Segment / Pose / OBB / Classify`
- `yolo26_core/heads.py`：`Detect / Segment26 / Pose26 / OBB26 / Classify`

通用解析器 `yolo_detection_model.py` 现在支持由 core builder 注入 head module map，避免再由共享解析器写死所有模型代际的 head。

当前底层算子、head 类实现、loss、assigner 和 decode 方法仍主要复用 `yolo_detection_model.py`、训练 service 与相关任务模块，还没有全部移动到独立 core 文件。

已新增 `backend/service/application/models/yolo_core_common/`，作为 YOLO 主线共用基础层和几何工具包。当前已迁出：

- `Conv / DWConv`
- `DistributionFocalLossDecoder`
- `make_anchors`
- `dist2bbox_xyxy`
- `dist2rbox`
- `make_divisible`

这些能力不包含模型代际判断，后续 loss、assigner、target 编码、postprocess 继续下沉时都应优先复用 common。

`Detect / Classify / Segment / Pose / OBB` 已从 `yolo_detection_model.py` 迁到 task 文件：

- `backend/service/application/models/yolo_core_common/tasks/detection.py`
- `backend/service/application/models/yolo_core_common/tasks/classification.py`
- `backend/service/application/models/yolo_core_common/tasks/segmentation.py`
- `backend/service/application/models/yolo_core_common/tasks/pose.py`
- `backend/service/application/models/yolo_core_common/tasks/obb.py`

`yolov8_core/heads.py`、`yolo11_core/heads.py` 已直接引用这些 common task head，不再从 `yolo_detection_model.py` 中转。

YOLO26 专用 head 已放入 `yolo26_core/tasks/`：

- `backend/service/application/models/yolo26_core/tasks/segmentation.py`
- `backend/service/application/models/yolo26_core/tasks/pose.py`
- `backend/service/application/models/yolo26_core/tasks/obb.py`

`yolo26_core/heads.py` 直接引用 `Segment26 / Pose26 / OBB26`，避免与 YOLOv8/YOLO11 混用。`yolo_detection_model.py` 当前只保留配置解析、通用骨干模块和模型构建入口。

Detection 推理 decode / postprocess 已开始下沉到共用边界：

- `backend/service/application/models/yolo_core_common/decode/detection.py`：负责 detection bbox decode 和 prediction 张量组装。
- `backend/service/application/models/yolo_core_common/decode/segmentation.py`：负责 segmentation proto + mask coeff 到原图二值 mask 的 decode。
- `backend/service/application/models/yolo_core_common/decode/pose.py`：负责 pose keypoint decode，标准 YOLO 和 YOLO26 通过 offset 参数区分。
- `backend/service/application/models/yolo_core_common/decode/obb.py`：负责 obb angle decode 和 rotated box prediction 组装，标准 YOLO 和 YOLO26 通过 angle decode mode 区分。
- `backend/service/application/models/yolo_core_common/postprocess/detection.py`：负责 NMS 前的 score / class / candidate 过滤。
- `backend/service/application/models/yolo_core_common/postprocess/segmentation.py`：负责 segmentation NMS 前的 score / class / candidate / mask coeff 过滤。
- `backend/service/application/models/detection_postprocess.py`：继续保留 runtime array 后处理和 NMS 调用，但候选筛选已经复用 core postprocess 入口。

Detection 训练态 loss / assigner / target 编码已开始下沉到共用边界：

- `backend/service/application/models/yolo_core_common/decode/detection.py`：同时负责训练态 prediction bundle 组装，提供 box、class logits、anchor points、stride 和 anchor centers。
- `backend/service/application/models/yolo_core_common/assigners/detection.py`：负责 detection TAL 正样本分配、anchor inside mask 和 bbox IoU 计算。
- `backend/service/application/models/yolo_core_common/targets/detection.py`：负责 gt bbox 到 DFL/LTRB distance target 的编码。
- `backend/service/application/models/yolo_core_common/losses/detection.py`：负责 detection DFL loss。
- `yolo_primary_detection_training.py`、`pose_loss.py`、`obb_loss.py` 已改为调用这些 common 入口，不再互相引用 detection training service 的私有函数。

Pose 专属 loss / target 编码已开始下沉到共用边界：

- `backend/service/application/models/yolo_core_common/losses/pose.py`：负责 OKS keypoint loss、visibility loss、Pose26 RLE loss、pose keypoint decode 辅助、OKS sigma 和 RLE target weight。
- `backend/service/application/models/yolo_core_common/targets/pose.py`：负责 batch target 中 keypoints 的固定形状归一。
- `backend/service/application/models/yolo_core_common/losses/obb.py`：负责 probiou 和 OBB angle loss。
- `backend/service/application/models/yolo_core_common/targets/obb.py`：负责 rotated target 编码、旋转框角点、anchor inside 检查和 xywhr 到 xyxy 的几何转换。
- `backend/service/application/models/yolo_core_common/assigners/segmentation.py`：负责 segmentation 正样本分配和 mask target 关联。
- `backend/service/application/models/yolo_core_common/losses/segmentation.py`：负责 segmentation bbox decode 辅助、box/class loss 编排和 proto + mask coeff 的实例 mask BCE loss。
- `backend/service/application/models/yolo_core_common/targets/segmentation.py`：负责 segmentation polygon 选择和 letterbox 后 mask target 栅格化。
- `backend/service/application/models/yolo_core_common/weights.py`：负责 YOLO 主线 state_dict 覆盖率分析、checkpoint 文件读取、完整模型 pickle fallback、带前缀 key 归一和加载结果报告。
- `backend/service/application/models/yolov8_core/weights.py`、`yolo11_core/weights.py`、`yolo26_core/weights.py`：负责各模型代际的权重覆盖率、state_dict 加载和 checkpoint 文件加载正式入口。
- `backend/service/application/models/yolo_core_common/export/plan.py`：负责 YOLO 主线 ONNX / ONNX optimized / OpenVINO IR / TensorRT engine 的导出目标和构建步骤说明。
- `backend/service/application/models/yolo_core_common/export/execution.py`：负责 YOLO 主线 ONNX 导出执行、ONNXRuntime 数值校验、OpenVINO IR 构建产物检查和 TensorRT engine 构建产物检查。
- `backend/service/application/models/yolov8_core/export.py`、`yolo11_core/export.py`、`yolo26_core/export.py`：负责各模型代际的 segmentation export 双输出和导出计划正式入口。
- `backend/workers/conversion/yolo_conversion_common.py`：负责 worker 侧共享的 ONNX 依赖导入、ONNX simplify、输出文件名前缀、conversion phase / options 摘要、OpenVINO / TensorRT 构建精度解析和转换脚本调用。该模块不放模型结构、head、loss 或 assigner。
- `pose_loss.py` 继续保留完整 pose loss 组装入口，负责把 detection loss、pose loss、visibility loss 和 RLE loss 汇总成训练指标。

已新增 `tests/test_yolo_core_entrypoints.py`，覆盖：

- `YOLOv8 / YOLO11 / YOLO26` 独立 core builder 可以构建 detection。
- 三个 core 的任务配置都覆盖 detection、classification、segmentation、pose、obb。
- 三个 core 的五类任务都能通过各自 `weights.py` 完整覆盖并加载自身 state_dict，也能从真实 checkpoint 文件读取并加载。
- checkpoint 文件读取覆盖纯 state_dict 载荷和完整模型 pickle 载荷。
- 三个 core 的 segmentation export 入口都固定为 `predictions/proto` 双输出，导出计划包含 ONNX / ONNX optimized / OpenVINO IR / TensorRT engine 构建步骤，并被各自 conversion runner 使用。
- YOLO 主线 conversion runner 的 ONNX 导出、ONNXRuntime 数值校验、OpenVINO / TensorRT 构建检查已经改为调用 core export execution。
- YOLO 主线、YOLOX 和 RF-DETR runner 共享的 ONNX 依赖导入、ONNX simplify、输出文件名前缀、conversion phase / options 摘要和构建精度解析已经从 YOLOX 历史 helper 挪到 `yolo_conversion_common.py`。
- YOLO26 的 head/decode 入口必须使用 `Segment26 / Pose26 / OBB26`，避免与 YOLOv8/YOLO11 混用。

当前需要继续补齐：

- YOLOX core 从 `runtime/yolox_core` 迁到 `models/yolox_core`，删除 runtime 下的历史 core 目录。
- RF-DETR 建立 `models/rfdetr_core`，用完整参考结构替换当前轻量模型结构。
- YOLOv8 / YOLO11 / YOLO26 按各自 core 包补齐完整训练、评估、导出和 postprocess 边界。
- 每个 `model_type × task_type` 的 tiny dataset overfit、真实转换、deployment 和 workflow 回归。

### RF-DETR

当前 `RF-DETR` 已接入 detection 和 segmentation 主链，也已经通过 OpenVINO / TensorRT smoke。当前实现仍是 project-native lightweight 版本，不是完整 upstream RF-DETR/LW-DETR/DINOv2 实现。下一批目标不是继续修补轻量实现，而是建立 `models/rfdetr_core` 并按参考仓库结构完成 full core。

当前已补 `tests/test_rfdetr_core_validation_tools.py`，覆盖：

- detection / segmentation 的 nano 模型结构快照。
- detection / segmentation 的前向输出形状。
- 项目内 state_dict 完整覆盖。
- 带 `module.model.` 外层前缀的 checkpoint key 归一。
- shape mismatch 的覆盖率报告。

当前 full core 需要补齐：

- `backend/service/application/models/rfdetr_core/` 独立包。
- DINOv2 / DINOv2 with registers / windowed attention backbone。
- LW-DETR transformer、matcher、criterion、postprocess。
- state_dict key mapping、位置编码插值、backbone 权重加载覆盖率。
- 官方训练策略中的优化器参数组、EMA、drop schedule、数据增强、resume 和评估路径。
- detection 与 segmentation 共同使用的完整 core forward、export 和 postprocess 边界。

#### RF-DETR upstream 差距清单

参考源码只作为开发阶段对照，不作为运行时依赖。当前差距按文件和能力归类如下：

| 参考模块 | 当前项目状态 | 后续进入 `rfdetr_core` 的要求 |
| --- | --- | --- |
| `projectsrc/rf-detr/src/rfdetr/models/backbone/dinov2.py`、`dinov2_with_windowed_attn.py` | 当前是项目内轻量 ViT backbone，未完整实现 DINOv2 registers、windowed attention 和官方配置 | 补项目内 DINOv2 backbone、register token、窗口注意力、位置编码插值和权重 key 映射 |
| `projectsrc/rf-detr/src/rfdetr/models/lwdetr.py` | 当前 detection/segmentation forward 已可跑，但仍是压缩后的项目内实现 | 拆成 `rfdetr_core/tasks.py`，保留 detection/segmentation 共享 forward 边界 |
| `projectsrc/rf-detr/src/rfdetr/models/transformer.py` | 当前已有 decoder 和 cross attention 的项目内版本，但还没有按 upstream 完整模块边界拆开 | 补完整 LW-DETR transformer 模块、decoder layer、query/refpoint 初始化和导出稳定边界 |
| `projectsrc/rf-detr/src/rfdetr/models/matcher.py`、`criterion.py` | 当前训练已有 Hungarian matcher、focal / box / giou / mask loss 的项目内路径，但仍分散在 training 文件里 | 下沉到 `rfdetr_core/matcher.py` 和 `rfdetr_core/criterion.py`，并用 tiny dataset loss backward 固定行为 |
| `projectsrc/rf-detr/src/rfdetr/models/postprocess.py` | 当前已修成 query × class top-k，并由 runtime 过滤 background | 下沉到 `rfdetr_core/postprocess.py`，同时覆盖 detection 与 segmentation |
| `projectsrc/rf-detr/src/rfdetr/models/segmentation_head.py` | 当前已有项目内 segmentation head，属于轻量实现 | 对齐 upstream mask head 的空间/查询交互、mask loss 和导出形状 |
| `projectsrc/rf-detr/src/rfdetr/training/` | 当前训练能走通平台任务链，但缺官方训练策略完整复刻 | 补 optimizer 参数组、EMA、drop schedule、增强配置、resume 和评估闭环 |
| `projectsrc/rf-detr/src/rfdetr/export/` | 当前转换走平台统一 ONNX / OpenVINO / TensorRT 链路 | 保持平台统一导出入口，同时补 RF-DETR core forward 的导出稳定性回归 |

## 阶段摘要

详细目录、任务拆分、参考映射和 full core 迁移顺序以“大重构目标状态”和“大批次迁移顺序”为准。本节只保留阶段摘要。

- 已完成：core 验收工具、YOLO 主线结构快照、state_dict 覆盖率测试、RF-DETR detection / segmentation core 验收测试、YOLOv8 / YOLO11 / YOLO26 的初始 core 包、head/decode 入口登记、`yolo_core_common` 基础层和几何工具迁出，以及 `Detect / Classify / Segment / Pose / OBB` task head 下沉。
- 已完成本批：detection bbox decode、segmentation mask decode、pose keypoint decode、obb angle / rotated box decode、NMS 前候选过滤、detection 训练态 prediction decode、TAL assigner、bbox target 编码、DFL loss、pose 专属 OKS / visibility / RLE loss、keypoint target 归一、OBB probiou、rotated target 编码、angle loss、segmentation polygon mask target 编码、segmentation assigner、segmentation box/class loss 编排、segmentation 完整 postprocess 第一层、segmentation export 双输出边界、YOLOv8 / YOLO11 / YOLO26 的 weights 正式入口、checkpoint 文件读取入口、export plan 正式入口、export execution 正式入口、mask BCE loss 迁入 core 边界、worker 侧共享转换 helper 中性化。
- 下一批：先做 YOLOX core 目录迁移，再做 RF-DETR full core，再做 YOLOv8 / YOLO11 / YOLO26 full core 补齐。
- 后续批次：清理 service / worker / runtime 中散落的模型核心代码，只保留任务、文件、状态、产物登记、runtime session 和 deployment 外壳。
- RF-DETR：不再继续把轻量实现当长期目标，进入 `rfdetr_core` full core 后补齐 DINOv2 backbone、LW-DETR transformer、matcher、criterion、postprocess、training 和权重映射。
- 全链路切换：每个 core 包最终必须通过数据集导入/导出、训练、验证、评估、转换、deployment sync/async、推理、workflow invoke 和前端创建任务查看结果。

## 准确率影响

当前未完成 full core 的实现对准确率有影响，影响程度按模型不同：

- `YOLOv8 / YOLO11 / YOLO26`：模型结构配置已对齐 YAML，主干差距小于 RF-DETR；但训练增强、optimizer、scheduler、EMA、resume、loss 细节仍会影响真实训练精度。
- `RF-DETR`：当前 lightweight 实现和 upstream 差距较大，会影响预训练权重加载覆盖率、收敛速度和准确率上限。RF-DETR 要作为生产主力，必须完成 `rfdetr_core` full core 和 mAP 对比验证。

从 0 开始训练可以避免“预训练权重结构不匹配”，但不能消除模型结构、训练策略和数据增强差异带来的准确率影响。

## 不做的事

- 不把官方 pip 包作为生产依赖。
- 不从 `projectsrc/` 运行代码。
- 不用空壳目录冒充完整 core。
- 不在一次大提交里同时改模型结构、API、前端和发布脚本。
- 不把 license 风险藏在代码实现里。

## 下一步

下一步继续按这个顺序推进：

1. 迁移 YOLOX：`backend/service/application/runtime/yolox_core/` -> `backend/service/application/models/yolox_core/`，修正 import 后删除 runtime 下的历史 core。
2. 建立 RF-DETR full core：按 `projectsrc/rf-detr/src/rfdetr` 结构复制适配到 `backend/service/application/models/rfdetr_core/`，替换当前轻量结构。
3. 补齐 YOLOv8 / YOLO11 / YOLO26 full core：按各自 core 包补完整任务目录、训练、评估、导出、权重和 postprocess。
4. 清理 service / worker / runtime 中散落的模型核心代码，再做 full-chain 验收。
