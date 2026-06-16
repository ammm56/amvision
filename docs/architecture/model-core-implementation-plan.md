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
- `backend/service/application/runtime/predictors/*.py` 放 deployment predictor 外壳，不应整体移动到 `*_core/`。predictor 依赖 ONNXRuntime、OpenVINO、TensorRT、CUDA buffer、session pool 和结果序列化，属于 deployment runtime 外壳。
- service / worker 层只调用 core 的正式入口，不直接理解 head、loss、assigner 内部细节。

`YOLOX` core 已从历史 `backend/service/application/runtime/yolox_core/` 迁到 `backend/service/application/models/yolox_core/`。runtime 目录不再保留 YOLOX core 旧目录，只保留 YOLOX 推理加载和会话外壳。

后续不得继续往 `runtime/yolox_core/` 恢复或扩展模型结构能力；新 core 能力统一落到 `models/*_core/`。

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

## ONNX 导出规则

本项目默认优先使用 PyTorch 2.8 的新 ONNX exporter：

- 默认优先调用 `torch.onnx.export(..., dynamo=True)`。
- 转换环境必须安装 `onnxscript`，该依赖已经写入 `requirements.txt`。
- 当前 PyTorch 2.8 + `onnxscript` 新 exporter 的项目默认 opset 为 `18`。当前环境下 `opset 17` 对基础 `aten.convolution` lowering 不稳定，因此新 exporter 路径不再把 17 作为默认值。
- 转换报告中的 `exporter_mode` 必须写明真实导出路径，不能让调用方误以为全部模型都走同一 exporter。
- 不再把旧 ONNX 导出器当成默认路径，也不允许静默回退旧路径。
- 如果某个模型导出失败，优先修对应 core 的 export forward、输出包装、shape 处理或算子边界。
- OpenVINO / TensorRT 继续以 ONNX 或 optimized ONNX 作为输入，不直接绕过 core export 边界。

`RF-DETR` 当前是显式例外：项目会先尝试 PyTorch 2.8 新 exporter；当当前 RF-DETR full-core 结构触发新 exporter 尚未支持的 `aten.convolution` 等 lowering 路径时，受控回退到 TorchScript exporter，并在 ONNX metadata 中写入 `rfdetr_exporter_mode`。这不是静默兼容层，而是当前 PyTorch 2.8 + RF-DETR full-core 的稳定导出边界。

这一条适用于 `YOLOX`、`YOLOv8 / YOLO11 / YOLO26` 主线和 `RF-DETR`。后续如果某个模型必须新增特殊导出路径，必须在本文件记录原因、范围和退出条件。

## 导出代码归属

模型导出实现必须归属于各自模型 core，不再长期堆在单一 conversion runner 或共享 helper 文件里。

- `backend/service/application/models/yolox_core/export/`：放 YOLOX detection 的导出逻辑，`onnx.py` 负责 ONNX export / simplify / 数值校验，`openvino.py` 负责 OpenVINO IR 构建，`tensorrt.py` 负责 TensorRT engine 构建，`execution.py` 只保留薄入口。
- `backend/service/application/models/yolov8_core/export/`：放 YOLOv8 各 task 的导出 forward、输出包装和 task-specific shape 规则。
- `backend/service/application/models/yolo11_core/export/`：放 YOLO11 各 task 的导出 forward、输出包装和 task-specific shape 规则。
- `backend/service/application/models/yolo26_core/export/`：放 YOLO26 各 task 的导出 forward、输出包装和 task-specific shape 规则。
- `backend/service/application/models/rfdetr_core/export/`：对齐 `projectsrc/rf-detr/src/rfdetr/export` 的职责，放 RF-DETR detection / segmentation 的稳定导出前向、输出规范、导出配置、校验辅助和后续 builder 切换入口。
- `backend/service/application/models/yolo_core_common/export/`：只放真正跨 `YOLOv8 / YOLO11 / YOLO26` 共享且不判断 `model_type` 的导出工具，例如 PyTorch 2.8 ONNX exporter 包装、通用 export plan 值对象和通用文件输出规则。

`backend/workers/conversion/` 只做任务编排：读取 ModelVersion、准备 dummy input、调用对应 core 的 export 入口、登记 ModelBuild、触发 OpenVINO / TensorRT 构建并写回状态。worker 不应该理解某个模型的 head、mask 输出、keypoint 输出、query 输出或 state_dict 映射细节。

新增模型时，只允许新增对应 `backend/service/application/models/<model_type>_core/export/` 和注册入口；不得为了新模型修改已有模型 core 的导出内部逻辑，也不得把新模型导出逻辑塞回共享 conversion runner。

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

实施顺序按模型纵向闭环推进：

1. `RF-DETR` 是当前大重构第一条主线。先按 `projectsrc/rf-detr/src/rfdetr` 的目录职责收完整 `rfdetr_core`，再清理 `rfdetr_*` service、worker、conversion runner 和 runtime predictor 外壳。
2. `YOLOX` 是第二条主线。它只有 detection，参考仓库是 Apache-2.0；当前 detection full core 主链已经落到 `models/yolox_core/`，后续只继续清应用服务和 runtime 外壳。
3. `YOLOv8 / YOLO11 / YOLO26` 是第三条主线。这三类普通 YOLO 模型结构相近、文件更多，最后按普通 YOLO 主线统一规划，但仍分别落到各自 `*_core`，不合并成一个模糊的大 core。

`models/training`、`models/evaluation`、`runtime/predictors`、`runtime/tasks` 这类横向目录是最终整理形态，不是迁移批次。不能先把所有训练文件或所有 predictor 横向搬走，否则容易把模型结构、运行时外壳和任务服务混在一起。

必须删除或迁走的历史落点：

- `backend/service/application/runtime/yolox_core/` 已整体迁到 `backend/service/application/models/yolox_core/`，runtime 下的旧目录已删除。后续不得恢复这个旧路径。
- `backend/service/application/models/rfdetr_model.py`、`rfdetr_segmentation_model.py` 已迁到 `backend/service/application/models/rfdetr_core/detection.py`、`segmentation.py`，旧模型结构文件已删除；RF-DETR full-core 主要结构已进入 `rfdetr_core/models`、`training`、`datasets`、`evaluation`、`utilities` 和 `export`。后续自动验证重点是真实 checkpoint 覆盖率、短时转换 smoke 和 deployment 启停/驻留 smoke；真实长时间训练由现场调试时通过平台训练任务执行。
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
- `runtime/yolox_core` 迁移已完成；runtime 目录后续只清理残留的 session、predictor、target、serialization 平铺结构。

## 参考仓库使用规则

参考仓库优先级按许可证和项目目标分开处理：

| 模型 | 参考目录 | 许可证处理 | 本项目落地方式 |
| --- | --- | --- | --- |
| `RF-DETR` | `projectsrc/rf-detr/src/rfdetr` | Apache-2.0，允许复制适配并保留来源说明 | 优先按参考仓库结构建立 `models/rfdetr_core/`，完整迁入 backbone、LW-DETR、matcher、criterion、postprocess、export、training。 |
| `YOLOX` | `projectsrc/YOLOX_2026/yolox` | Apache-2.0，允许复制适配并保留来源说明 | detection full core 已进入 `models/yolox_core/`，包括模型结构、loss、训练、评估、EMA、scheduler、utils、export 和 postprocess；剩余只清服务外壳、runtime 会话和发布验收。 |
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

当前状态和剩余动作：

- `runtime/yolox_core/models`、`runtime/yolox_core/utils` 和 `runtime/yolox_core/data` 已整体迁到 `models/yolox_core/`。
- 已补 `yolox_core/cfg/detection.py`、`models/build.py` 和 `weights.py`：YOLOX scale profile、输入尺寸规则、模型构建、checkpoint state_dict 提取、warm start 加载和覆盖率摘要已经有正式 core 入口。
- 已补 `yolox_core/data/datasets/`：`coco.py` 承接本项目 `coco-detection-v1` DatasetExport 读取、split 解析和 COCO ground truth 静默加载；`voc.py` 承接本项目 `voc-detection-v1` DatasetExport 读取、VOC XML annotation 解析、ImageSets split 解析和评估用 COCO ground truth 生成。`data/datasets/detection.py` 现在是 YOLOX detection 数据入口，训练和评估链都通过它按 DatasetExport format 选择 COCO 或 VOC。
- 已补 `yolox_core/evaluators/`：`coco.py` 提供 COCO bbox mAP 和 per-class 指标工具，`pytorch.py` 承接 DatasetExport split 选择、PyTorch checkpoint 加载、DataLoader 构建和 evaluator 执行；VOC 输入会在 core 内生成评估用 COCO ground truth 后复用同一套 bbox mAP 指标。`models/evaluation/yolox_detection.py` 只保留应用层稳定入口。
- 已补 `yolox_core/training/trainer.py` 和 `training/execution.py`：YOLOX 训练进度、batch heartbeat、pause/save 控制对象、默认训练参数、schedule/no-aug 规则、batch 预处理、optimizer、LR scheduler、ModelEMA、resume checkpoint 校验、checkpoint state 构建、序列化、训练参数解析、数据链构建、验证评估闭包和训练执行入口已经从应用层迁入 core。
- `models/training/yolox_detection.py` 已收成薄应用入口，只保留 `run_yolox_detection_training` 稳定调用名和训练任务服务需要的公开类型导出；`models/training/yolox_detection_task_service.py` 承接 YOLOX detection 训练任务服务。
- `models/evaluation/yolox_detection_task_service.py` 已承接 YOLOX detection 数据集级评估任务服务，新建 `models/evaluation/` 目录作为评估任务服务归类位置。
- 旧的 YOLOX 专用 validation session 服务已删除；五类 validation session 服务已统一归类到 `models/validation/`，包括 `detection_session_service.py`、`classification_session_service.py`、`segmentation_session_service.py`、`pose_session_service.py` 和 `obb_session_service.py`。
- 已补 `yolox_core/export/`：ONNX 导出、ONNX 数值校验、ONNX simplify、OpenVINO IR 构建和 TensorRT engine 构建前置规则已从 `yolox_conversion_runner.py` 迁入 core，并按 `onnx.py / openvino.py / tensorrt.py` 拆分；worker 只保留转换计划执行、object key 组装、文件类型登记和结果 metadata 汇总。
- 已补 `yolox_core/postprocess/detection.py`：ONNXRuntime / OpenVINO / TensorRT 推理输出数组规范化、score / class 过滤、batched NMS 和 detection record 组装已从 YOLOX predictor 外壳迁入 core。
- `runtime/predictors/yolox*.py` 已承接 YOLOX deployment predictor 外壳，并按 PyTorch / ONNXRuntime / OpenVINO / TensorRT、backend、buffer、serialization 和 preview render 拆小文件；YOLOX detection 预览画框已拆到 `yolox_core/postprocess/preview.py`，runtime 只按推理请求里的 `save_result_image` 参数决定是否调用。独立 detection 推理服务默认输出带框预览，workflow 模型节点可以显式传 `save_result_image=false` 关闭。原平铺 `runtime/yolox_detection_runtime.py` 已删除。
- `runtime/support/detection.py` 已承接 detection runtime 共享 helper 的路径归类；原平铺 `runtime/detection_runtime_support.py` 已删除，后续共享 helper 不再继续放到 runtime 根目录。
- `backend/service/application/runtime/yolox_core/` 已删除，后续不得恢复旧目录。

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
    transformer.py
    weights.py
  training/
    platform_runner.py
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
    validation.py
    onnx_optimize.py
    openvino.py
    _onnx/
      exporter.py
      inference.py
      symbolic.py
    _tensorrt.py
  datasets/
    coco.py
    transforms.py
    yolo.py
  utilities/
  inference.py
  weights.py
```

迁移动作：

- 已先建立 `rfdetr_core/`，把原 `rfdetr_model.py`、`rfdetr_segmentation_model.py` 的 detection / segmentation 模型结构迁到 `detection.py`、`segmentation.py`，并让 training、conversion、runtime 统一从 core 调用 builder。
- 已按 `projectsrc/rf-detr/src/rfdetr/models` 复制适配 `rfdetr_core/models/`，包含 `backbone/`、`heads/`、`ops/`、`lwdetr.py`、`transformer.py`、`postprocess.py`、`matcher.py`、`criterion.py`、`math.py`、`position_encoding.py` 等核心结构；同时复制适配 `rfdetr_core/config.py`、`_namespace.py`、`assets/`、`datasets/`、`evaluation/`、`training/`、`utilities/` 和 `visualize/`。
- 已收窄 `rfdetr_core/models/__init__.py`，默认不导入在线下载等非本项目核心入口；`deprecate` 外部依赖已用本项目内轻量装饰器替代。
- `jsonargparse` 只服务参考仓库的 `LightningCLI` 命令行入口。本项目训练由 FastAPI / worker 传结构化参数，不维护第二套 CLI 参数系统，因此不把 `jsonargparse` 写入 requirements，也不保留 `training/cli.py` 占位代码。
- `peft` 只服务 LoRA / adapter 微调和导出合并。当前 RF-DETR 主链路不启用 LoRA，`backbone_lora=True` 会在配置校验阶段明确失败，后续如需 LoRA 应单独规划并显式引入依赖。
- `projectsrc/supervision/src/supervision` 只作为参考实现。本项目不依赖 `supervision` pip 包，RF-DETR core 当前需要的 `Detections / Color / BoxAnnotator / LabelAnnotator / xywh_to_xyxy / box_iou_batch / draw_filled_polygon` 已收进 `rfdetr_core/supervision_compat.py`。
- `rfdetr_core/config.py` 和 `rfdetr_core/models/weights.py` 已改成本项目本地权重语义：裸 checkpoint 文件名解析到 `data/files/models/pretrained/rfdetr/core/checkpoints/`，权重加载只读本地文件，缺文件明确报错。`assets/model_weights.py`、`platform/`、`datasets/_develop.py` 和下载 helper 已删除，RF-DETR core 不保留隐式第三方下载路径。
- `rfdetr_core/models/backbone/dinov2.py` 已禁用 HuggingFace `from_pretrained()` 在线 backbone 加载。需要预训练能力时只能通过本项目本地 RF-DETR checkpoint 加载；未提供 checkpoint 时按配置从零初始化。
- 已新增 `rfdetr_core/factory.py` 作为 full core 受控构建门面，统一处理 `task_type / model_scale / num_classes / pretrained_path`，默认 `force_no_pretrain=True`。该门面同时提供 RF-DETR 输入尺寸对齐规则，训练、转换和前端提交都要按 `patch_size * num_windows` 自动对齐或显式校验。
- RF-DETR 公开 scale 已按真实 core 和本地预训练资产收窄：detection 只暴露 `nano / s / m / l`，segmentation 暴露 `nano / s / m / l / x`。`base`、`xxl` 等如果后续要开放，必须先补齐本地资产、训练/转换 smoke 和前端选择入口。
- RF-DETR 模型文件类型已独立为 `rfdetr-checkpoint / rfdetr-onnx / rfdetr-openvino-ir / rfdetr-tensorrt-engine` 等，不再复用 YOLOv8 的文件类型常量。
- detection / segmentation 训练共用的 Hungarian matcher、box / class / GIoU set criterion 按上游结构位于 `rfdetr_core/models/matcher.py` 和 `rfdetr_core/models/criterion.py`，外层训练 service 不再维护独立轻量 criterion。
- `build_rfdetr_model()` 和 `build_rfdetr_segmentation_model()` 当前都通过 `rfdetr_core/factory.py` 构建 full-core 模型，不再保留旧 project-native detection / segmentation 模型类作为长期入口。
- `RfdetrPostProcess` 与 `RfdetrSegmentationPostProcess` 只做后处理 adapter，内部调用 upstream-aligned `rfdetr_core/models/postprocess.py`，并转成本项目 runtime 使用的 batched dict。
- RF-DETR detection / segmentation conversion runner 的 ONNX 导出已改为调用 `rfdetr_core/export/_onnx/exporter.py`，该目录按 `projectsrc/rf-detr/src/rfdetr/export/_onnx` 复制适配，不再通过临时 wrapper/spec 自造导出层。
- RF-DETR segmentation conversion 使用 full-core `model.export()` 的真实返回顺序导出 `pred_boxes / pred_logits / pred_masks`。runtime 会按输出名重新解析为平台内部的 `pred_logits / pred_boxes / pred_masks` 使用顺序。
- `projectsrc/rf-detr/src/rfdetr/training/` 已迁入 `rfdetr_core/training/`，包含 `auto_batch.py`、`module_data.py`、`module_model.py`、`trainer.py`、`checkpoint.py`、`model_ema.py`、`param_groups.py`、`drop_schedule.py` 和 `callbacks/`。已删除 `LightningCLI`、WandB、MLflow、ClearML 和 notebook widget 输出分支，只保留本项目 worker 训练入口、CSV/TensorBoard 日志和终端输出。
- `rfdetr_core/training/platform_runner.py` 已作为平台训练桥接入口，负责把 DatasetExport manifest 组装成 RF-DETR Roboflow COCO 目录，并调用 `RFDETRModelModule`、`RFDETRDataModule` 和 `build_trainer`。`training/rfdetr_detection.py`、`training/rfdetr_segmentation.py` 已收成薄外壳，不再维护手写 loss、matcher、mask loss、target 编码或评估循环。
- `projectsrc/rf-detr/src/rfdetr/export/_onnx/` 已迁入 `rfdetr_core/export/_onnx/`，`projectsrc/rf-detr/src/rfdetr/export/_tensorrt.py` 已迁入 `rfdetr_core/export/_tensorrt.py`。ONNX 导出优先使用 PyTorch 2.8 `dynamo=True` 新 exporter；当当前 RF-DETR 结构触发新 exporter 不支持的算子路径时，会受控回退到 TorchScript exporter，并在 ONNX metadata 中写入 `rfdetr_exporter_mode`，避免 worker 或调用方误判导出路径。
- `rfdetr_core/export/execution.py` 负责 RF-DETR 导出执行边界：checkpoint state_dict 读取、full-core 模型构建、输入尺寸对齐、dummy input、ONNX 输出名、ONNX 导出、数值校验和 TensorRT 构建摘要。`rfdetr_core/export/validation.py` 负责 ONNX checker、输出名校验和 PyTorch / ONNXRuntime 数值校验；当前数值校验采用“先严格 allclose，再看 mean diff / mean ratio 边界”的规则，用来覆盖 `MSDeformAttn / grid_sample` 这类 ONNXRuntime 与 PyTorch 存在可解释微差的输出。`onnx_optimize.py` 负责 ONNX simplify；`openvino.py` 负责 OpenVINO IR 构建。
- `rfdetr_core/models/backbone/dinov2.py` 和 `dinov2_with_windowed_attn.py` 已补 ONNX / TorchScript tracing 边界：导出时禁用 antialias 位置编码插值，避免 `aten::_upsample_bicubic2d_aa` 进入 ONNX fallback 导出路径。
- `backend/workers/conversion/rfdetr_conversion_runner.py` 已瘦身为任务执行外壳，只负责 object key、输出文件类型、执行步骤、状态结果和产物登记所需摘要，不再直接 `torch.load`、构建 RF-DETR 模型、解析 output names 或保存 RF-DETR 专属数值校验细节。
- `backend/service/application/conversions/rfdetr_conversion_planner.py` 已改为 RF-DETR 自己的 `RfdetrConversionPlan / RfdetrConversionPlanningRequest` 和序列化函数，不再继承或复用 `DefaultYoloXConversionPlanner` 命名边界。
- `rfdetr_core/runtime.py` 已收口 RF-DETR runtime 语义：输入尺寸对齐、输出名解析、detection / segmentation 后处理 adapter 调用和 mask 单通道二维化。
- `runtime/predictors/rfdetr.py` 和 `runtime/predictors/rfdetr_segmentation.py` 只保留 deployment session、ONNXRuntime / OpenVINO / TensorRT backend adapter、CUDA buffer、推理执行计时和结果序列化，不再维护 RF-DETR output name 解析、input size 规则或 postprocess 细节。`runtime/targets/rfdetr.py` 只保留 RF-DETR ModelVersion / ModelBuild 到 runtime target 的解析。
- 真实本地 checkpoint 覆盖率已有显式 smoke：`AMVISION_RUN_RFDETR_CHECKPOINT_SMOKE=1` 时默认读取 `data/files/models/pretrained/rfdetr` 下 detection `nano / s / m / l` 和 segmentation `nano / s / m / l / x` 的本地预训练权重。测试同时输出 raw coverage 与 load-path coverage；最终验收以真实加载路径为准，已覆盖 segmentation large 这类 query embedding 需要按 checkpoint args 切片适配的情况。
- RF-DETR ONNX 导出链已经统一关闭 DINOv2 positional embedding 的 bicubic `antialias`，避免导出 `aten::_upsample_bicubic2d_aa` 这类 TensorRT/ONNX 不支持路径。对应配置中的 `interpolate_antialias` 也统一为 `false`。
- RF-DETR TensorRT conversion 已改为优先使用项目内 TensorRT runtime：开发态读取 `runtimes/tensorrt_bin/bin/trtexec.exe`，发布态读取 `release/full/tools/tensorrt/bin/trtexec.exe`，找不到时才 fallback 到系统 `PATH`。
- 2026-06-15 已用真实本地预训练 checkpoint 跑通 RF-DETR detection nano 与 segmentation nano 的短时转换验收：ONNX 导出、ONNXRuntime 数值校验、ONNX simplify、OpenVINO IR 和 TensorRT 10.16 engine 构建均通过；TensorRT 使用项目内 `runtimes/tensorrt_bin/bin/trtexec.exe` 和项目内 cuDNN runtime 路径。
- 2026-06-15 已用真实 TensorRT engine 跑通 RF-DETR detection / segmentation 的 deployment runtime pool smoke：分别模拟 sync / async 常驻池，完成 warmup、一次推理和 reset，reset 后 warmed 实例数回到 0 且 healthy 状态保持正常。该 smoke 验证的是 deployment session 复用和状态清理；真正长时间独立进程 soak 仍放到 release/full 或现场调试任务中执行。

当前 RF-DETR full core 依赖边界：

- 必要依赖：`torch`、`torchvision`、`numpy`、`opencv-python`、`Pillow`、`scipy`、`pycocotools`。
- 训练与评估依赖：`pytorch-lightning`、`torchmetrics`、`albumentations`、`kornia`、`tqdm`；mAP 底层评估复用已有 `pycocotools`，不额外依赖 `faster-coco-eval`。
- 导出依赖：`onnx`、`onnxscript`、`onnxsim`、`onnxruntime`、`openvino`、`TensorRT`、`cuda-python`。
- 不作为当前必装依赖：`jsonargparse`、`peft`、`supervision`、`requests`、`faster-coco-eval`。

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

本轮按大批次迁移，不再把每个 helper 作为独立阶段推进。每个大批次结束后跑定向回归，确认 import graph、训练短链路、转换短链路和 deployment 推理链没有断。

1. 先收 `RF-DETR`：`models/rfdetr_core` 已建立，原 `rfdetr_model.py`、`rfdetr_segmentation_model.py` 已删除并迁到 core；`projectsrc/rf-detr/src/rfdetr/models`、`training`、`datasets`、`evaluation`、`utilities` 和 `export` 相关结构已复制适配进 core。conversion runner 已收成任务执行外壳，runtime predictor 已把 input size、output name 和 postprocess 语义下沉到 `rfdetr_core/runtime.py`。当前已补全 scale checkpoint 覆盖率、tiny backward、ONNX conversion smoke、真实 checkpoint 的 OpenVINO / TensorRT 短时转换验收和 deployment runtime pool sync / async smoke。真实长时间训练和 release/full soak 由现场平台任务调试产生基线，不放进默认测试。
2. 再收 `YOLOX`：`runtime/yolox_core` 已迁到 `models/yolox_core`，旧 runtime core 目录已删除；当前已完成 COCO / VOC 训练与评估、权重加载、ONNX / OpenVINO / TensorRT 导出、postprocess 和 deployment predictor 拆分，后续只继续瘦身任务服务、runtime session 外壳和发布验收。
3. 最后收 `YOLOv8 / YOLO11 / YOLO26` full core：按 `model_type` 分别补齐 `cfg`、`nn/modules`、`nn/tasks`、`losses`、`assigners`、`targets`、`postprocess`、`data`、`training`、`validation`、`export`、`weights`。Ultralytics 代码只按许可证规则参考；未做 AGPL 决策前不直接复制源码。
4. 每收一个模型，就同步清理它在 `models/`、`runtime/` 和 `workers/` 中散落的历史文件；不要先把所有模型的训练文件或 predictor 横向搬走。
5. 模型纵向迁移稳定后，再整理横向目录：`models/training`、`models/evaluation`、`models/inference`、`runtime/predictors`、`runtime/targets`、`runtime/contracts`、`runtime/serialization`。
6. 清理 `workers/`：转换和训练 worker 只调用 core 的正式入口，不再直接拼 ONNX 输出、head 输出、loss 或 matcher。
7. 全链路验收：按模型和任务组合跑数据集导入/导出、训练、验证、评估、转换、deployment sync/async、推理、workflow invoke 和前端创建任务查看结果。

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

`YOLOX` core 当前位于 `backend/service/application/models/yolox_core/`，模型结构与训练主线已经从历史 runtime 落点迁入统一 core 目录。

目标状态：

- `backend/service/application/models/yolox_core/`：放 YOLOX 模型结构、loss、权重加载、训练/导出 core 边界和验收工具。
- `backend/service/application/runtime/`：只保留 YOLOX deployment runtime、长期驻留会话、加载器和推理包装。

后续 YOLOX 相关工作只继续瘦身任务服务、runtime session 外壳和发布验收，不再恢复 `runtime/yolox_core`。

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
- `backend/workers/conversion/model_conversion_common.py`：负责 worker 侧共享的 ONNX 依赖导入、ONNX simplify、输出文件名前缀、conversion phase / options 摘要、OpenVINO / TensorRT 构建精度解析和转换脚本调用。该模块不放模型结构、head、loss 或 assigner。
- `pose_loss.py` 继续保留完整 pose loss 组装入口，负责把 detection loss、pose loss、visibility loss 和 RLE loss 汇总成训练指标。

已新增 `tests/test_yolo_core_entrypoints.py`，覆盖：

- `YOLOv8 / YOLO11 / YOLO26` 独立 core builder 可以构建 detection。
- 三个 core 的任务配置都覆盖 detection、classification、segmentation、pose、obb。
- 三个 core 的五类任务都能通过各自 `weights.py` 完整覆盖并加载自身 state_dict，也能从真实 checkpoint 文件读取并加载。
- checkpoint 文件读取覆盖纯 state_dict 载荷和完整模型 pickle 载荷。
- 三个 core 的 segmentation export 入口都固定为 `predictions/proto` 双输出，导出计划包含 ONNX / ONNX optimized / OpenVINO IR / TensorRT engine 构建步骤，并被各自 conversion runner 使用。
- YOLO 主线 conversion runner 的 ONNX 导出、ONNXRuntime 数值校验、OpenVINO / TensorRT 构建检查已经改为调用 core export execution。
- YOLO 主线、YOLOX 和 RF-DETR runner 共享的 ONNX 依赖导入、ONNX simplify、输出文件名前缀、conversion phase / options 摘要和构建精度解析已经从 YOLOX 历史 helper 挪到 `model_conversion_common.py`。
- YOLO26 的 head/decode 入口必须使用 `Segment26 / Pose26 / OBB26`，避免与 YOLOv8/YOLO11 混用。

当前需要继续补齐：

- RF-DETR 已补全 scale 本地 checkpoint 覆盖率读取、tiny detection / segmentation loss backward、短时 ONNX conversion 验收，以及真实 checkpoint 的 OpenVINO / TensorRT 短时转换和 deployment runtime pool sync / async smoke。后续剩余重点是长时间训练、release/full 独立进程 soak、资源占用和异常恢复基线。真实长时间训练不进入 pytest，由现场调试按实际数据集和参数手动执行。
- YOLOv8 / YOLO11 / YOLO26 按各自 core 包补齐完整训练、评估、导出和 postprocess 边界。
- 每个 `model_type × task_type` 的 tiny dataset overfit、真实转换、deployment 和 workflow 回归。

### RF-DETR

当前 `RF-DETR` 已接入 detection 和 segmentation 主链，也已经通过 OpenVINO / TensorRT smoke。`models/rfdetr_core` 独立包已建立，生产训练、转换和 runtime 已从 core 调用模型 builder、training runner、postprocess adapter 和 export helper。`rfdetr_core/models`、`rfdetr_core/utilities`、`config.py`、`_namespace.py` 已按 Apache-2.0 参考实现复制适配，当前生产 postprocess、segmentation head、matcher、criterion、training module 和 export 入口已切到 upstream-aligned 子模块。

当前已补 `tests/test_rfdetr_core_validation_tools.py`，覆盖：

- detection / segmentation 的 nano 模型结构快照。
- detection / segmentation 的前向输出形状。
- 项目内 state_dict 完整覆盖。
- 带 `module.model.` 外层前缀的 checkpoint key 归一。
- shape mismatch 的覆盖率报告。
- 本地 RF-DETR checkpoint 的 `model` payload 覆盖率读取。
- PyTorch Lightning `state_dict` checkpoint 的 `model.` / `_orig_mod.` 前缀归一。

当前已补 `tests/test_rfdetr_core_training_backward.py`，覆盖：

- detection tiny batch 的 matcher、box/class loss 和 backward。
- segmentation tiny batch 的 matcher、box/class/mask loss 和 backward。
- 默认快速测试只做小尺寸 CPU 验收，不做长时 soak。

当前已补 `tests/integration/test_rfdetr_full_core_soak_benchmark.py`，用于显式短时 smoke / benchmark：

- 设置 `AMVISION_RUN_RFDETR_CHECKPOINT_SMOKE=1` 后读取真实本地 RF-DETR detection `nano / s / m / l` 与 segmentation `nano / s / m / l / x` checkpoint，输出 raw coverage、load-path coverage、shape mismatch 明细和分类头推断结果。
- 设置 `AMVISION_RUN_RFDETR_FULL_CORE_SOAK=1` 后执行 repeated tiny backward smoke，输出 loss、CPU 内存漂移和 CUDA 显存漂移；该测试最多允许 50 次 tiny backward 迭代，避免变成长时间训练。
- 设置 `AMVISION_RUN_RFDETR_FULL_CORE_CONVERSION_SOAK=1` 后额外执行 ONNX 导出和 ONNXRuntime 数值校验。导出会优先尝试 PyTorch 2.8 新 exporter，当前不支持路径会写入 metadata 并回退到 TorchScript exporter；校验摘要会保留 strict allclose、max diff、mean diff 和 ratio，方便后续对比不同 runtime backend。
- 该文件不进入默认测试路径；目标机 deployment 常驻 soak 继续走 release/full 和真实部署任务验收。

2026-06-15 目标机短时验收结果：

- 本地 RF-DETR 预训练 checkpoint 覆盖率：detection `nano / s / m / l` 与 segmentation `nano / s / m / l / x` 全部通过真实加载路径覆盖率检查，load-path coverage 均为 `1.0`；segmentation `l` 的 raw query embedding shape mismatch 已由项目加载路径按 checkpoint args 正确适配。
- 真实 checkpoint 短时转换：detection nano 与 segmentation nano 都已完成 ONNX 导出、ONNXRuntime 数值校验、ONNX simplify、OpenVINO IR 和 TensorRT 10.16 engine 构建；detection ONNX `max_abs_diff` 约 `2.86e-06`，segmentation ONNX `max_abs_diff` 约 `3.91e-05`。
- TensorRT runtime：开发态已确认使用 `runtimes/tensorrt_bin/bin/trtexec.exe`，当前环境 TensorRT Python 包为 `10.16.1.11`，项目内 cuDNN runtime 路径已加入构建环境。
- deployment runtime pool：detection / segmentation 的 TensorRT engine 已分别跑过 sync / async 常驻池 warmup、一次推理和 reset；reset 后 warmed 实例数回到 0，healthy 状态保持正常。
- 当前仍存在 `cuda.cudart` deprecation warning，后续 runtime support 应切到 `cuda.bindings.runtime`；该 warning 当前不影响 TensorRT 真实 smoke。

当前 full core 已经进入 `backend/service/application/models/rfdetr_core/` 独立包，DINOv2 backbone、LW-DETR transformer、matcher、criterion、postprocess、training、datasets、evaluation 和 export 参考结构都已复制适配。

当前剩余重点：

- checkpoint 覆盖率已经默认覆盖当前本地预训练资产的全部公开 scale；后续如果新增 RF-DETR scale 或替换权重文件，应同步更新显式 smoke 清单并重跑覆盖率。
- 使用真实小数据集补 RF-DETR detection / segmentation 几分钟内 tiny overfit / mAP 对比 smoke。真实长时间训练基线由现场平台任务调试产生，不放入测试用例。
- 继续把 release/full 独立进程长时间 soak、资源占用、日志和异常恢复结果沉淀到发布验收文档。
- 后续整理 runtime 目录时，只移动 session / predictor / target / serialization 的平铺结构，不把 runtime predictor 迁进 core。

#### RF-DETR upstream 差距清单

参考源码只作为开发阶段对照，不作为运行时依赖。当前差距按文件和能力归类如下：

| 参考模块 | 当前项目状态 | 后续进入 `rfdetr_core` 的要求 |
| --- | --- | --- |
| `projectsrc/rf-detr/src/rfdetr/models/backbone/dinov2.py`、`dinov2_with_windowed_attn.py` | 已复制适配到 `rfdetr_core/models/backbone/`，production builder 通过 `rfdetr_core/models/lwdetr.py` 间接使用 | 继续做权重覆盖率、输入尺寸和 DINOv2 本地权重加载验收 |
| `projectsrc/rf-detr/src/rfdetr/models/lwdetr.py` | 已复制适配到 `rfdetr_core/models/lwdetr.py`，production detection / segmentation builder 已切到 `rfdetr_core/factory.py` -> `build_model_from_config()` | 继续补训练策略和导出数值基线，不再保留 project-native model 类作为对照入口 |
| `projectsrc/rf-detr/src/rfdetr/models/transformer.py` | 已复制适配到 `rfdetr_core/models/transformer.py`，production builder 通过 full-core 路径使用 | 继续做结构快照、state_dict 覆盖率和 ONNX/OpenVINO/TensorRT smoke |
| `projectsrc/rf-detr/src/rfdetr/models/matcher.py`、`criterion.py` | 已复制适配到 `rfdetr_core/models/matcher.py` 和 `rfdetr_core/models/criterion.py`，外层 `training/rfdetr_detection.py` / `training/rfdetr_segmentation.py` 已不再维护独立轻量 loss / matcher | 继续补 tiny dataset loss backward 和真实 checkpoint 覆盖率验收 |
| `projectsrc/rf-detr/src/rfdetr/models/postprocess.py` | 已复制适配到 `rfdetr_core/models/postprocess.py`，当前通过 `RfdetrPostProcess` / `RfdetrSegmentationPostProcess` adapter 转换成本项目 batched dict | 继续补多 backend runtime 结果一致性 smoke |
| `projectsrc/rf-detr/src/rfdetr/models/heads/segmentation.py` | 已复制适配到 `rfdetr_core/models/heads/segmentation.py`，production segmentation builder 已通过 full-core `LWDETR` 使用 | 继续补真实 segmentation checkpoint 覆盖率和 mAP 基线 |
| `projectsrc/rf-detr/src/rfdetr/training/` | 已复制适配到 `rfdetr_core/training/`，包含 Lightning DataModule / ModelModule、trainer、EMA、drop schedule、checkpoint、param groups 和 callbacks；平台入口走 `training/platform_runner.py` | 继续补短时训练 smoke、暂停/失败恢复和正式训练报告字段；真实长时间训练由现场任务调试验证 |
| `projectsrc/rf-detr/src/rfdetr/export/` | `_onnx`、`_tensorrt.py`、ONNX validation、ONNX simplify 和 OpenVINO builder 已进入 `rfdetr_core/export/`，detection / segmentation conversion runner 只调用 core export 入口；真实 checkpoint 的 ONNX / OpenVINO / TensorRT 短时验收已通过 | 继续补 release/full 独立进程长时间 soak 和现场资源基线 |

## 阶段摘要

详细目录、任务拆分、参考映射和 full core 迁移顺序以“大重构目标状态”和“大批次迁移顺序”为准。本节只保留阶段摘要。

- 已完成：core 验收工具、YOLO 主线结构快照、state_dict 覆盖率测试、RF-DETR detection / segmentation core 验收测试、YOLOv8 / YOLO11 / YOLO26 的初始 core 包、head/decode 入口登记、`yolo_core_common` 基础层和几何工具迁出，以及 `Detect / Classify / Segment / Pose / OBB` task head 下沉。
- 已完成本批：detection bbox decode、segmentation mask decode、pose keypoint decode、obb angle / rotated box decode、NMS 前候选过滤、detection 训练态 prediction decode、TAL assigner、bbox target 编码、DFL loss、pose 专属 OKS / visibility / RLE loss、keypoint target 归一、OBB probiou、rotated target 编码、angle loss、segmentation polygon mask target 编码、segmentation assigner、segmentation box/class loss 编排、segmentation 完整 postprocess 第一层、segmentation export 双输出边界、YOLOv8 / YOLO11 / YOLO26 的 weights 正式入口、checkpoint 文件读取入口、export plan 正式入口、export execution 正式入口、mask BCE loss 迁入 core 边界、worker 侧共享转换 helper 中性化。
- 已完成本批：YOLOX core 目录从 `runtime/yolox_core` 迁到 `models/yolox_core`，旧 runtime core 目录已删除，代码引用已改到新路径。
- 已完成本批：`rfdetr_core/export/` 已建立导出规范入口，当前包含 detection / segmentation 输出名、参考仓库输出别名、full-core export tuple 到本项目 `pred_logits / pred_boxes / pred_masks` 的稳定转换、ONNX 数值校验、ONNX simplify、OpenVINO IR 构建和 TensorRT builder 调用。
- 已完成本批：`rfdetr_core/runtime.py` 已承接 runtime 语义入口，统一处理 RF-DETR deployment 使用的输入尺寸对齐、输出名解析、detection / segmentation 后处理和 segmentation mask 单通道规整；runtime predictor 只保留 session、backend adapter、buffer、执行计时和结果序列化。
- 已完成本批：`training/rfdetr_detection.py`、`training/rfdetr_segmentation.py` 已切到 `rfdetr_core/training/platform_runner.py`，旧手写 loss、matcher、mask loss 和 eval 逻辑已删除。
- 已完成本批：YOLOX 纵向闭环已收成 detection full core。旧 COCO DatasetExport 重复块已删除，COCO / VOC DatasetExport 训练与评估入口已统一到 `yolox_core/data/datasets/detection.py`，checkpoint state、EMA、scheduler、resume 校验、训练 loop、验证评估编排、conversion export、runtime detection 后处理和 YOLOX 预览画框已分别进入 `yolox_core/training`、`evaluators`、`export` 和 `postprocess`。YOLOX deployment session 已拆到 `runtime/predictors/yolox*.py`，detection 共享 helper 已移到 `runtime/support/detection.py`。
- 后续批次：再按 YOLOv8 / YOLO11 / YOLO26 的顺序清理 service / worker / runtime 中散落的模型核心代码；YOLOX 只继续做应用服务文件拆分、runtime session 外壳瘦身和长时间运行验收。
- runtime 目录整理当前已完成 RF-DETR 第一层和 YOLOX predictor 第一层：`runtime/predictors/rfdetr*.py`、`runtime/predictors/yolox*.py`、`runtime/targets/rfdetr.py`、`runtime/support/tensorrt_runtime.py` 和 `runtime/support/detection.py` 已从平铺目录拆出；YOLOv8 / YOLO11 / YOLO26 的 predictor、target 和 serialization 平铺文件后续按模型纵向闭环再迁。
- RF-DETR：不再继续把轻量实现当长期目标，后续重点转为真实使用训练调试、多 backend 部署验收、release/full 常驻基线和 runtime 目录平铺结构整理。
- 全链路切换：每个 core 包最终必须通过数据集导入/导出、训练、验证、评估、转换、deployment sync/async、推理、workflow invoke 和前端创建任务查看结果。

## 准确率影响

当前未完成 full core 的实现对准确率有影响，影响程度按模型不同：

- `YOLOv8 / YOLO11 / YOLO26`：模型结构配置已对齐 YAML，主干差距小于 RF-DETR；但训练增强、optimizer、scheduler、EMA、resume、loss 细节仍会影响真实训练精度。
- `RF-DETR`：当前已切到 upstream-aligned full core，但如果没有加载对应本地预训练 checkpoint，模型仍然会从零初始化，训练收敛速度和准确率上限会低于预训练微调。RF-DETR 要作为生产主力，仍必须补真实 checkpoint 覆盖率、mAP 对比和现场真实训练基线。

从 0 开始训练可以避免“预训练权重结构不匹配”，但不能消除模型结构、训练策略和数据增强差异带来的准确率影响。

## 不做的事

- 不把官方 pip 包作为生产依赖。
- 不从 `projectsrc/` 运行代码。
- 不用空壳目录冒充完整 core。
- 不在一次大提交里同时改模型结构、API、前端和发布脚本。
- 不把 license 风险藏在代码实现里。

## 下一步

下一步继续按这个顺序推进：

1. 收 RF-DETR 纵向闭环：继续清 `rfdetr_*` service、worker 和 runtime 外壳，确认只保留任务、产物、session、backend adapter、buffer 和序列化边界；当前 checkpoint 覆盖率、tiny backward、ONNX conversion、真实 checkpoint OpenVINO / TensorRT 转换和 deployment runtime pool smoke 已有显式记录，下一步重点是 release/full 独立进程长时间 soak、资源/日志基线和 runtime 目录平铺结构整理。真实长时间训练由现场手动任务调试产生基线。
2. 收 YOLOX 外壳和验收：在 `models/yolox_core` 已完成 detection full core 主链的基础上，继续拆小训练任务服务和 runtime session 外壳，并补发布包长时间运行基线。
3. 收 YOLOv8 / YOLO11 / YOLO26：按各自 core 包补完整任务目录、训练、评估、导出、权重和 postprocess。
4. 最后整理横向目录和 full-chain 验收：再清 `models/training`、`runtime/predictors`、`workers` 等结构层，不把这一步提前到模型闭环之前。
