# 模型 core 实现计划

## 文档目的

本文档固定 `YOLOv8 / YOLO11 / YOLO26 / RF-DETR` 在本项目中的完整 core 实现边界。

这里的重点不是再新增一个模型分类，而是把当前“平台链路已接通”的实现继续收成“模型结构、训练逻辑、权重加载、评估和导出都可长期维护”的项目内 core。

## 保存位置

- `projectsrc/` 只作为开发阶段参考源码目录，不作为运行时代码来源。
- 项目运行时代码只能依赖 `backend/`、`custom_nodes/`、`frontend/`、`runtimes/` 和明确登记的本项目代码。
- 预训练模型和转换产物继续放在 `data/files/models/` 约定目录，不放进 git。

## 命名

目标 core 包按模型分类命名：

- `yolov8_core`
- `yolo11_core`
- `yolo26_core`
- `rfdetr_core`

公开 API 和前端仍使用 `model_type`、`task_type` 和现有任务入口。`*-core` 是模型实现层，不直接暴露给外部系统。

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

本节是 `YOLOv8 / YOLO11 / YOLO26` 完整 core 实现的唯一详细计划。其他文档只保留导航、边界或阶段摘要，不重复维护本节内容。

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

### 目标目录

完整形态建议如下：

```text
backend/service/application/models/
  yolo_core_common/
    __init__.py
    nn/
      __init__.py
      modules/
        __init__.py
        conv.py
        blocks.py
        dfl.py
    utils/
      __init__.py
      anchors.py
      boxes.py
      ops.py
      tensors.py
    losses/
      __init__.py
      boxes.py
      classification.py
    targets/
      __init__.py
      labels.py

  yolov8_core/
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
        blocks.py
        heads_detection.py
        heads_segmentation.py
        heads_classification.py
        heads_pose.py
        heads_obb.py
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
    postprocess/
      detection.py
      segmentation.py
      classification.py
      pose.py
      obb.py
    weights.py
    export.py
    train.py
    val.py
    predict.py

  yolo11_core/
    ...同 yolov8_core，保留 YOLO11 自己的 cfg、head 和任务差异

  yolo26_core/
    ...同 yolov8_core，保留 Segment26 / Pose26 / OBB26 等 YOLO26 差异
```

`yolo_core_common` 只收真正共用能力，例如基础卷积块、anchor 生成、bbox decode、DFL、NMS 前置 ops、通用 target 辅助函数。禁止在 common 里写 `if model_type == ...` 这类混线逻辑。

### 任务分类实现边界

每个 core 内部按任务拆分，不再把五类任务混在一个大文件里。

| task_type | core 内部必须单独实现的内容 |
| --- | --- |
| `detection` | Detect head、bbox decode、TAL assigner、box/class/DFL loss、NMS postprocess。 |
| `segmentation` | Segment head、proto/mask decode、mask target、mask loss、mask postprocess。 |
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

### YOLO core 迁移顺序

迁移必须按小步推进，每步都保持测试绿。

1. 建立 `yolo_core_common`，先迁出不含模型代际判断的基础函数和基础层。
2. 把 `Detect / Classify` 的具体实现迁到任务文件，保持输出形状和 state_dict key 覆盖率不变。
3. 把 `Segment / Pose / OBB` 迁到任务文件，YOLO26 的 `Segment26 / Pose26 / OBB26` 必须留在 `yolo26_core`。
4. 把 decode 逻辑从 head 类内部拆到各任务的 `postprocess` 或 `decode` 边界。
5. 把 loss、assigner、target 编码从训练 service 下沉到 core。
6. 把 checkpoint 加载和覆盖率报告收进各 core 的 `weights.py`。
7. 把 ONNX / OpenVINO / TensorRT 导出 forward 边界收进各 core 的 `export.py`。
8. service、worker、runtime 只保留任务、文件、状态、产物登记和长期运行外壳。
9. 删除或降级旧 `yolo_detection_model.py` 中已迁出的生产路径，只保留必要的兼容测试工具或完全删除。

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

`YOLOX` 已有 `backend/service/application/runtime/yolox_core/`，模型结构与训练主线相对完整，后续主要是保持命名边界和回归稳定。

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

已新增 `tests/test_yolo_core_entrypoints.py`，覆盖：

- `YOLOv8 / YOLO11 / YOLO26` 独立 core builder 可以构建 detection。
- 三个 core 的任务配置都覆盖 detection、classification、segmentation、pose、obb。
- 三个 core 的五类任务都能完整覆盖自身 state_dict。
- YOLO26 的 head/decode 入口必须使用 `Segment26 / Pose26 / OBB26`，避免与 YOLOv8/YOLO11 混用。

当前需要继续补齐：

- 模型分类独立底层模块包。
- 按任务分类拆清楚 loss、assigner 和 decode 入口。
- 与参考实现对应的训练增强、优化器、scheduler、EMA、AMP、resume 等训练细节。
- 每个 `model_type × task_type` 的 tiny dataset overfit 和真实转换部署回归。

### RF-DETR

当前 `RF-DETR` 已接入 detection 和 segmentation 主链，也已经通过 OpenVINO / TensorRT smoke。当前实现仍是 project-native lightweight 版本，不是完整 upstream RF-DETR/LW-DETR/DINOv2 实现。

当前已补 `tests/test_rfdetr_core_validation_tools.py`，覆盖：

- detection / segmentation 的 nano 模型结构快照。
- detection / segmentation 的前向输出形状。
- 项目内 state_dict 完整覆盖。
- 带 `module.model.` 外层前缀的 checkpoint key 归一。
- shape mismatch 的覆盖率报告。

当前需要继续补齐：

- `rfdetr_core` 独立包。
- DINOv2 / DINOv2 with registers / windowed attention backbone 的项目内实现。
- LW-DETR transformer、matcher、criterion、postprocess 的完整边界。
- state_dict key mapping、位置编码插值、backbone 权重加载覆盖率。
- RF-DETR 官方训练策略中的优化器参数组、EMA、数据增强和评估路径。
- detection 与 segmentation 共同使用的完整 core forward / export / runtime 边界。

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

详细目录、任务拆分、Ultralytics 参考映射和 YOLO full core 迁移顺序以“YOLO 主线 full core 详细计划”为准。本节只保留阶段摘要。

- 已完成：core 验收工具、YOLO 主线结构快照、state_dict 覆盖率测试、RF-DETR detection / segmentation core 验收测试、YOLOv8 / YOLO11 / YOLO26 的初始 core 包和 head/decode 入口登记。
- 下一批：建立 `yolo_core_common`，先迁出不含模型代际判断的基础函数和基础层，再迁 `Detect / Classify`，保持输出形状和 state_dict 覆盖率不变。
- 后续批次：继续迁 `Segment / Pose / OBB`、loss、assigner、target 编码、postprocess、weights、export，service / worker 层只保留任务、文件、状态和产物登记。
- RF-DETR：在 YOLO 主线 core 收稳后进入 `rfdetr_core` full core，补齐 DINOv2 backbone、LW-DETR transformer、matcher、criterion、postprocess 和权重映射。
- 全链路切换：每个 core 包最终必须通过数据集导入/导出、训练、验证、评估、转换、deployment sync/async、推理、workflow invoke 和前端创建任务查看结果。

## 准确率影响

当前轻量实现对准确率有影响，影响程度按模型不同：

- `YOLOv8 / YOLO11 / YOLO26`：模型结构配置已对齐 YAML，主干差距小于 RF-DETR；但训练增强、optimizer、scheduler、EMA、resume、loss 细节仍会影响真实训练精度。
- `RF-DETR`：当前 lightweight 实现和 upstream 差距较大，会影响预训练权重加载覆盖率、收敛速度和准确率上限。RF-DETR 要作为生产主力前，必须完成 full core 或至少完成 mAP 对比验证。

从 0 开始训练可以避免“预训练权重结构不匹配”，但不能消除模型结构、训练策略和数据增强差异带来的准确率影响。

## 不做的事

- 不把官方 pip 包作为生产依赖。
- 不从 `projectsrc/` 运行代码。
- 不用空壳目录冒充完整 core。
- 不在一次大提交里同时改模型结构、API、前端和发布脚本。
- 不把 license 风险藏在代码实现里。

## 下一步

下一步继续按这个顺序推进：

1. 把 Detect / Segment / Pose / OBB / Classify 的具体实现继续拆到各自 core 或清晰的 shared 模块。
2. 把 loss、assigner、postprocess 从 service 层继续下沉到各自 core。
3. 补 tiny dataset overfit 和真实转换部署回归。
4. 进入 `rfdetr_core` full core，补齐 backbone、transformer、matcher、criterion、postprocess 和权重映射。
