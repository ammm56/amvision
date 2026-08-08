# 训练参数协议

## 目标

训练创建接口使用同一套 v1 规则覆盖 detection、classification、segmentation、pose、OBB，参数按任务和模型族隔离。公开请求不接受无类型字典，不允许未知字段，也不保留旧扁平参数入口。

本协议解决以下问题：

- 参数在 OpenAPI、前端、任务快照和 runner 之间含义一致。
- 只公开实际被对应 runner 读取的字段。
- 模型族之间不能互传无效参数，例如 RF-DETR 不接受 Mosaic 字段。
- 数值在任务入队前完成有限值、范围和资源上限校验。
- 数据增强可以整体关闭，并在任务快照中固化最终配置。

## 创建请求结构

五类训练创建接口共享以下顶层字段：

| 字段 | 规则 |
| --- | --- |
| `project_id` | 必填 |
| `model_type` | 必须属于当前任务支持矩阵 |
| `dataset_export_id` / `dataset_export_manifest_key` | 由服务解析为同一个已完成 DatasetExport |
| `recipe_id` | 非空 recipe id |
| `model_scale` | 必须属于所选模型的 scale |
| `output_model_name` | 必填，最大 128 字符 |
| `warm_start_model_version_id` | 可选，由训练 service 校验任务、模型和权重兼容性 |
| `evaluation_interval` | `1..10000`，所有任务统一为顶层字段 |
| `max_epochs` | `1..10000` |
| `batch_size` | `1..4096` |
| `precision` | `fp16` 或 `fp32` |
| `input_size` | `{"width": W, "height": H}` |
| `parameters` | 按当前 `task_type / model_type` 解析的严格参数对象 |
| `display_name` | 可选，最大 256 字符 |

单任务不再接收 `gpu_count`。当前训练架构是一任务一设备；设备选择由 `parameters.runtime.device` 表达，多卡并发由 worker 的设备租约调度，不等于单任务 DDP。

## 参数分组

`parameters` 只包含当前模型实际需要的分组：

| 分组 | 用途 |
| --- | --- |
| `runtime` | 单设备选择、随机种子、DataLoader worker 和预取参数 |
| `data` | 模型特有的样本资源上限，目前只用于 YOLOX 单图标签上限 |
| `optimization` | optimizer、学习率、weight decay、学习率调度和梯度裁剪 |
| `loss` | 当前任务实际开放的损失权重 |
| `matching` | YOLO 正样本匹配或 RF-DETR Hungarian matching 参数 |
| `evaluation` | 训练期验证阈值和最大检测数 |
| `augmentation` | 当前任务的增强参数和总开关 |
| `advanced` | 不属于通用优化器或增强的模型行为参数 |

公开 schema 统一设置 `additionalProperties=false`。字段拼写错误、模型族不匹配或旧扁平字段会返回 422，不会进入队列。

## 支持矩阵

| 任务 | 模型 | 参数 schema |
| --- | --- | --- |
| detection | YOLOX | `YoloXDetectionTrainingParameters` |
| detection | YOLOv8 / YOLO11 / YOLO26 | `YoloDetectionTrainingParameters` |
| detection | RF-DETR | `RfdetrDetectionTrainingParameters` |
| classification | YOLOv8 / YOLO11 / YOLO26 | `YoloClassificationTrainingParameters` |
| segmentation | YOLOv8 / YOLO11 / YOLO26 | `YoloSegmentationTrainingParameters` |
| segmentation | RF-DETR | `RfdetrSegmentationTrainingParameters` |
| pose | YOLOv8 / YOLO11 / YOLO26 | `YoloPoseTrainingParameters` |
| OBB | YOLOv8 / YOLO11 / YOLO26 | `YoloObbTrainingParameters` |

完整机器可读目录由 `GET /api/v1/models/training-parameter-schemas` 返回。目录包含 18 个 `task_type / model_type` 组合、JSON Schema 和默认参数，供前端、SDK 和外部集成读取。

## 通用运行参数

YOLO 主线支持：

- `device=auto | cpu | cuda | cuda:<index>`
- `seed=0..4294967295`
- `num_workers=0..64`
- `prefetch_factor=1..32`
- `pin_memory`
- `persistent_workers`

`num_workers=0` 时禁止 `persistent_workers=true`。RF-DETR 当前只公开 `device` 和 `num_workers`；YOLOX 默认 `num_workers=0`，避免 Windows queue worker 再次 spawn 时引入不可序列化上下文。

## 优化器规则

YOLOv8、YOLO11、YOLO26 支持：

- `optimizer=auto | musgd | sgd | adamw | adam | nadam | radam | rmsprop`
- `learning_rate`
- `weight_decay`
- `min_lr_ratio`
- `grad_clip_norm`

`optimizer=auto` 由 runner 根据类别数、batch 和迭代量解析，不接受伪 `learning_rate`。显式 optimizer 必须同时指定大于 0 的 `learning_rate`。

YOLOX 的基础学习率和 optimizer 按 reference 实现由 batch size 解析，公开协议只提供实际生效的 `warmup_epochs`、`no_aug_epochs`、`min_lr_ratio` 和 `ema`。短训练会把未显式填写的默认 warmup/no-aug 解析成可执行值并写入任务；显式提交的不可能调度会直接拒绝。

RF-DETR 支持 `learning_rate`、`weight_decay`、`lr_scheduler=step | cosine`、`min_lr_ratio` 和 `grad_accum_steps`。`min_lr_ratio` 只在 cosine 下进入执行配置，step 模式不会保存无效字段。

## 数据增强隔离

### YOLO detection / segmentation / pose / OBB

公开字段包括水平翻转、HSV、Mosaic、MixUp、随机仿射、透视、增强缩放区间、最后关闭 Mosaic 的 epoch 数和多尺度训练。概率范围固定为 `0..1`，角度最大 180 度，缩放区间必须为有限正数且最小值不大于最大值，多尺度比例最大 0.9。

`augmentation.enabled=false` 会生成确定性执行配置，Mosaic、MixUp、随机仿射、HSV、翻转和多尺度训练全部关闭。

### YOLOX detection

YOLOX 使用独立增强 schema，保留 reference 默认 Mosaic scale、MixUp scale 和 `multiscale_range`。它不复用 YOLO 主线的 affine/multi-scale 字段名称。

### Classification

classification 使用图像级增强协议：

- 水平翻转
- `crop_mode=none | random_resized_crop`
- crop scale 区间
- `auto_augment=none | randaugment | autoaugment | augmix`
- 手工 rotation、translation、affine scale 和颜色增强
- Random Erasing

启用 AutoAugment 策略时，手工仿射和颜色字段会被执行层忽略，因此 API 禁止同时提交非中性手工值。`enabled=false` 只保留确定性 resize/center crop/normalize。

### RF-DETR

RF-DETR 不接收 YOLO 增强字段，使用：

- `preset=default | conservative | aggressive | aerial | industrial`
- `backend=cpu | auto | gpu`
- `enabled`

任意自定义 `aug_config` 不属于公开 v1 协议，避免未审计任意结构绕过参数校验。

## 任务差异

- YOLO detection：开放 detection loss、matching、evaluation 和完整增强。
- YOLO segmentation：在 detection loss 基础上增加 `mask_weight`。
- YOLO pose：增加 `keypoint_weight` 和关键点验证置信度。
- YOLO OBB：当前 runner 的类别、box、DFL、angle 和 matching 参数仍由模型 core 固定，因此公开接口不提供这些无效字段；只开放真实生效的优化器、验证阈值和增强。
- RF-DETR segmentation：在 RF-DETR detection loss 基础上增加 mask CE/Dice 权重。

## 数值和资源边界

- 所有 float 禁止 NaN 和正负 Infinity。
- 学习率必须大于 0 且不大于 1。
- weight decay 和最小学习率比例限制在 `0..1`。
- 概率和置信度限制在 `0..1`。
- DataLoader worker 最大 64，预取因子最大 32。
- gradient accumulation 最大 1024。
- 匹配 top-k 最大 1000。
- RF-DETR 验证最大检测数限制在 `100..100000`。
- loss/cost 权重限制在 `0..1000`。

这些边界用于阻止长期运行中的整数无界增长、异常显存/内存放大和非有限值污染指标。模型输入尺寸的几何与对齐规则见 [模型训练输入尺寸规则](model-training-input-size-rules.md)。

## 执行与追溯

API schema 在任务入队前完成校验。应用服务调用 `to_execution_options()`，把分组字段一次性映射为具体 runner 的配置键。runner 配置、解析后的默认值、设备租约结果、增强摘要、训练指标、验证指标、test 指标和 checkpoint 均写入任务或模型产物，用于复查和恢复训练。

公开协议不直接依赖 `projectsrc/` 中的参考代码。新增模型或任务时必须先登记新的参数 schema 和支持矩阵，再实现执行映射、OpenAPI/目录测试、runner 消费测试和前端表单。
