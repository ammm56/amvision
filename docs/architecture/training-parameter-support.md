# 训练参数支持清单

## 文档目的

本文档用于同步当前主干训练参数的真实支持范围，作为训练页面参数实现、后端公开接口和执行层收口的依据。

本文档只回答三件事：

- 后端公开训练接口当前接受哪些参数
- 训练执行层当前真正使用哪些参数
- 前端 `/models` 页面当前已经暴露了哪些参数，还有哪些还没暴露

## 适用范围

- detection / classification / segmentation / pose / obb 五类训练任务
- `yolox / yolov8 / yolo11 / yolo26 / rfdetr` 当前主干已接入的训练链
- 训练任务创建参数，不展开数据集导出、转换、部署和推理参数

## 判断口径

| 标记 | 含义 |
| --- | --- |
| `公开` | REST 创建训练任务接口已经显式定义并接受该参数 |
| `执行` | 训练 service 或训练执行函数已经真正读取并使用该参数 |
| `前端` | 当前 `/models` 页面已经提供可见输入项或选择面板 |
| `缺口` | 后端已经支持但前端还没暴露，或者前端有输入但当前公开接口 / 执行层并没有真正生效 |

## 当前结论

- 当前训练页面已经收成两层：
  - 通用参数层
  - `model_type` 高级参数层
- `recipe_id` 仍然保留在请求里，但当前实际只有 `default` 这一套生效，前端已固定为默认值，不再单独显示输入框。
- 前端创建训练任务时，已经按 `task_type / model_type` 组装对应的 `extra_options`，不再固定传空字典。
- 前端当前统一显示 `验证间隔`，其中：
  - detection / pose / obb 走顶层公开字段
  - classification / segmentation 走 `extra_options.evaluation_interval`
- 前端当前只在 detection 显示 `Warm start`，不再把它暴露到非 detection 任务页面。
- detection 公开接口里的 `extra_options` 是一份合并后的公开字段说明，不同 `model_type` 真正使用的字段并不相同。
- 当前版本训练链路统一按单 GPU 或 CPU 执行；`gpu_count` 只作为 detection 公开接口的保留字段接受空值或 `1`，前端不再显示该输入，传入大于 `1` 会被拒绝。
- 训练输入尺寸的模型差异以 [模型训练输入尺寸规则](model-training-input-size-rules.md) 为准：YOLOX 可按参考实现使用 `(height, width)`，RF-DETR 使用方形 `resolution`，YOLOv8 / YOLO11 / YOLO26 训练阶段按单整数 `imgsz=N` 收口为 `N x N`。

## 通用参数层现状

| 参数 | detection | classification | segmentation | pose | obb | 当前前端 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `output_model_name` | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 已暴露 | 当前已自动按基础模型生成默认名 |
| `max_epochs` | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 已暴露 | 默认值当前为 `100` |
| `batch_size` | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 已暴露 | 默认值当前为 `1` |
| `precision` | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 已暴露 | 当前页面默认 `fp32` |
| `input_size` | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 已暴露 | 当前页面用宽高两个输入框表达 |
| `display_name` | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 已暴露 | 当前页面字段名已收成“训练任务名称（可选）” |
| `recipe_id` | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 公开 + 执行 | 固定默认值 | 当前实际只有 `default` 生效，前端不再单独暴露 |
| `evaluation_interval` | 公开 + 执行 | 执行层已有，公开接口未收 | 执行层已有，公开接口未收 | 公开 + 执行 | 公开 + 执行 | 已暴露 | classification / segmentation 当前由前端写入 `extra_options.evaluation_interval` |
| `warm_start_model_version_id` | 公开 + 部分执行 | 未公开 | 未公开 | 未公开 | 未公开 | detection 已暴露 | 当前只在 detection 前端显示 |
| `gpu_count` | 公开保留 | 未公开 | 未公开 | 未公开 | 未公开 | 未暴露 | 当前只接受空值或 `1`；大于 `1` 会被拒绝 |

## 当前前端页面已暴露的训练输入

当前 `frontend/web-ui/src/modules/models/pages/ModelOperationsPage.vue` 已经暴露的训练输入如下：

- 基础模型选择面板：用于选择 `model_type`、`model_scale`，以及 detection 当前可用的 warm start 来源版本
- 数据集导出选择面板：用于选择 `dataset_export_id`
- `output_model_name`
- `max_epochs`
- `batch_size`
- `evaluation_interval`
- `precision`
- `input_width`
- `input_height`
- `display_name`
- 按 `task_type / model_type` 切换的高级训练参数
  - segmentation / YOLO 主线：包含验证置信度阈值、验证 NMS 阈值
  - pose / YOLO 主线：包含验证置信度阈值、验证 NMS 阈值、关键点置信度阈值
  - OBB / YOLO 主线：包含验证置信度阈值、验证 NMS 阈值

当前页面还没有暴露的训练输入如下：

- 当前没有新增独立的 `task_type` 参数层
- 仍未把所有训练后端字段都完全前端化
- 当前高级参数还没有按“数据增强 / 优化器 / 损失权重 / 运行设备”继续分组显示

## 按任务和模型整理

### detection

支持的 `model_type`：

- `yolox`
- `yolov8`
- `yolo11`
- `yolo26`
- `rfdetr`

#### detection / yolox

| 项目 | 内容 |
| --- | --- |
| 后端公开参数 | `recipe_id`、`warm_start_model_version_id`、`evaluation_interval`、`max_epochs`、`batch_size`、`gpu_count`、`precision`、`input_size`、`display_name`、`extra_options` |
| 执行层真正使用 | `warm_start_model_version_id`、`evaluation_interval`、`max_epochs`、`batch_size`、`precision`、`input_size`、`extra_options.device`、`seed`、`num_workers`、`max_labels`、`evaluation_confidence_threshold`、`evaluation_nms_threshold`、`flip_prob`、`hsv_prob`、`mosaic_prob`、`mixup_prob`、`enable_mixup`、`mosaic_scale`、`mixup_scale`、`multiscale_range`、`ema`、`warmup_epochs`、`no_aug_epochs`、`min_lr_ratio` |
| 当前前端已暴露 | 通用层字段 + warm start 选择 + YOLOX 高级参数面 |
| 当前缺口 | 公开字段里常见的 `learning_rate / weight_decay` 对当前 YOLOX 执行并没有实际切换作用；高级参数当前还没有继续按能力组分块显示；多 GPU 训练当前不支持 |

#### detection / yolov8、yolo11、yolo26

| 项目 | 内容 |
| --- | --- |
| 后端公开参数 | `recipe_id`、`warm_start_model_version_id`、`evaluation_interval`、`max_epochs`、`batch_size`、`gpu_count`、`precision`、`input_size`、`display_name`、`extra_options` |
| 执行层真正使用 | `warm_start_model_version_id`、`evaluation_interval`、`max_epochs`、`batch_size`、`precision`、`input_size`、`extra_options.learning_rate`、`weight_decay`、`class_loss_weight`、`box_loss_weight`、`dfl_loss_weight`、`evaluation_confidence_threshold`、`evaluation_nms_threshold`、`assign_topk`、`assign_alpha`、`assign_beta`、`grad_clip_norm`、`flip_prob`、`hsv_prob`、`mosaic_prob`、`mixup_prob`、`enable_mixup`、`degrees`、`translate`、`shear`、`mosaic_scale`、`mixup_scale` |
| 当前前端已暴露 | 通用层字段 + warm start 选择 + detection / YOLO 主线高级参数面 |
| 当前缺口 | 多 GPU 训练当前不支持；`gpu_count` 只保留空值或 `1` |

#### detection / rfdetr

| 项目 | 内容 |
| --- | --- |
| 后端公开参数 | `recipe_id`、`warm_start_model_version_id`、`evaluation_interval`、`max_epochs`、`batch_size`、`gpu_count`、`precision`、`input_size`、`display_name`、`extra_options` |
| 执行层真正使用 | `max_epochs`、`batch_size`、`precision`、`input_size`、`extra_options.device`、`learning_rate`、`class_cost`、`bbox_cost`、`giou_cost`、`class_loss_weight`、`bbox_loss_weight`、`giou_loss_weight` |
| 当前前端已暴露 | 通用层字段 + warm start 选择 + RF-DETR detection 高级参数面 |
| 当前缺口 | `warm_start_model_version_id`、`evaluation_interval` 当前没有真正进入执行；公开接口说明里的 `weight_decay` 当前执行层也没有按请求值切换；多 GPU 训练当前不支持 |

### classification

支持的 `model_type`：

- `yolov8`
- `yolo11`
- `yolo26`

#### classification / yolov8、yolo11、yolo26

| 项目 | 内容 |
| --- | --- |
| 后端公开参数 | `recipe_id`、`max_epochs`、`batch_size`、`precision`、`input_size`、`display_name`、`extra_options` |
| 执行层真正使用 | `max_epochs`、`batch_size`、`precision`、`input_size`、`extra_options.device`、`learning_rate`、`weight_decay`、`min_lr_ratio`、`evaluation_interval` |
| 当前前端已暴露 | 通用层字段 + classification 高级参数面 |
| 当前缺口 | 公开接口没有显式 `evaluation_interval` 字段；当前靠 `extra_options` 传递；warm start 仍没有 classification 公开入口 |

### segmentation

支持的 `model_type`：

- `yolov8`
- `yolo11`
- `yolo26`
- `rfdetr`

#### segmentation / yolov8、yolo11、yolo26

| 项目 | 内容 |
| --- | --- |
| 后端公开参数 | `recipe_id`、`max_epochs`、`batch_size`、`precision`、`input_size`、`display_name`、`extra_options` |
| 执行层真正使用 | `max_epochs`、`batch_size`、`precision`、`input_size`、`extra_options.device`、`learning_rate`、`weight_decay`、`min_lr_ratio`、`evaluation_interval`、`evaluation_confidence_threshold`、`evaluation_nms_threshold`、`class_loss_weight`、`box_loss_weight`、`dfl_loss_weight`、`mask_loss_weight`、`assign_topk`、`assign_alpha`、`assign_beta`、`grad_clip_norm` |
| 当前前端已暴露 | 通用层字段 + segmentation / YOLO 主线高级参数面 |
| 当前缺口 | 公开接口没有显式 `evaluation_interval` 字段；当前靠 `extra_options` 传递；warm start 当前也没有 segmentation 公开入口 |

#### segmentation / rfdetr

| 项目 | 内容 |
| --- | --- |
| 后端公开参数 | `recipe_id`、`max_epochs`、`batch_size`、`precision`、`input_size`、`display_name`、`extra_options` |
| 执行层真正使用 | `max_epochs`、`batch_size`、`precision`、`input_size`、`extra_options.device`、`learning_rate`、`weight_decay`、`min_lr_ratio`、`evaluation_interval`、`class_cost`、`bbox_cost`、`giou_cost`、`class_loss_weight`、`bbox_loss_weight`、`giou_loss_weight`、`mask_ce_weight`、`mask_dice_weight` |
| 当前前端已暴露 | 通用层字段 + segmentation / RF-DETR 高级参数面 |
| 当前缺口 | 公开接口仍是原始 `extra_options`，没有分割任务下按 `model_type` 区分的正式参数 schema |

### pose

支持的 `model_type`：

- `yolov8`
- `yolo11`
- `yolo26`

#### pose / yolov8、yolo11、yolo26

| 项目 | 内容 |
| --- | --- |
| 后端公开参数 | `recipe_id`、`evaluation_interval`、`max_epochs`、`batch_size`、`precision`、`input_size`、`display_name`、`extra_options` |
| 执行层真正使用 | `evaluation_interval`、`max_epochs`、`batch_size`、`precision`、`input_size`、`extra_options.device`、`learning_rate`、`weight_decay`、`min_lr_ratio`、`evaluation_confidence_threshold`、`evaluation_nms_threshold`、`keypoint_confidence_threshold`、`class_loss_weight`、`box_loss_weight`、`dfl_loss_weight`、`kpt_loss_weight`、`assign_topk`、`assign_alpha`、`assign_beta`、`grad_clip_norm` |
| 当前前端已暴露 | 通用层字段 + pose 高级参数面；`evaluation_interval` 当前对 pose 是有效的 |
| 当前缺口 | warm start 当前没有 pose 公开入口 |

### obb

支持的 `model_type`：

- `yolov8`
- `yolo11`
- `yolo26`

#### obb / yolov8、yolo11、yolo26

| 项目 | 内容 |
| --- | --- |
| 后端公开参数 | `recipe_id`、`evaluation_interval`、`max_epochs`、`batch_size`、`precision`、`input_size`、`display_name`、`extra_options` |
| 执行层真正使用 | `evaluation_interval`、`max_epochs`、`batch_size`、`precision`、`input_size`、`extra_options.device`、`learning_rate`、`weight_decay`、`evaluation_confidence_threshold`、`evaluation_nms_threshold` |
| 当前前端已暴露 | 通用层字段 + OBB 高级参数面；`evaluation_interval` 当前对 OBB 是有效的 |
| 当前缺口 | warm start 当前没有 OBB 公开入口 |

## 训练页面下一步应怎么收

当前已经先收成“通用参数层 + `model_type` 高级参数层”。下一步建议继续按下面顺序收，不要再回到同一层大表单里堆零散输入框：

1. 继续优化通用参数层，保持只放高频和跨任务稳定字段：
   - `output_model_name`
   - `max_epochs`
   - `batch_size`
   - `precision`
   - `input_size`
   - `display_name`
   - `evaluation_interval`
   - detection 下的 `warm_start_model_version_id`
2. 继续优化 `model_type` 高级参数层：
   - detection：`yolox`、`yolov8 / yolo11 / yolo26`、`rfdetr`
   - segmentation：`yolov8 / yolo11 / yolo26`、`rfdetr`
   - pose：`yolov8 / yolo11 / yolo26`
   - obb：`yolov8 / yolo11 / yolo26`
3. 把高级参数继续分成更清楚的小组，例如：
   - 训练设备
   - 学习率与优化器
   - 数据增强
   - 损失权重
   - 匹配与后处理
4. 后端公开接口如果后续要长期稳定对外，classification / segmentation 里的 `evaluation_interval` 最好也收成正式顶层字段，而不是长期只靠 `extra_options`。

## 主要代码落点

- 前端训练页面：`frontend/web-ui/src/modules/models/pages/ModelOperationsPage.vue`
- 前端训练请求：`frontend/web-ui/src/modules/models/services/model.service.ts`
- detection 训练公开接口：`backend/service/api/rest/v1/routes/detection_training_tasks.py`
- classification 训练公开接口：`backend/service/api/rest/v1/routes/classification_training_tasks/router.py`
- segmentation 训练公开接口：`backend/service/api/rest/v1/routes/segmentation_training_tasks/router.py`
- pose 训练公开接口：`backend/service/api/rest/v1/routes/pose_training_tasks/router.py`
- obb 训练公开接口：`backend/service/api/rest/v1/routes/obb_training_tasks/router.py`
- YOLOX detection 训练执行入口：`backend/service/application/models/training/yolox_detection.py`
- YOLOv8 detection 训练执行：`backend/service/application/models/yolov8_core/training/detection_execution.py`
- RF-DETR detection 训练执行：`backend/service/application/models/training/rfdetr_detection.py`
- YOLOv8 classification 训练执行：`backend/service/application/models/yolov8_core/training/classification_execution.py`
- YOLOv8 segmentation 训练执行：`backend/service/application/models/yolov8_core/training/segmentation_execution.py`
- RF-DETR segmentation 训练执行：`backend/service/application/models/training/rfdetr_segmentation.py`
- YOLOv8 pose 训练执行：`backend/service/application/models/yolov8_core/training/pose_execution.py`
- YOLOv8 obb 训练执行：`backend/service/application/models/yolov8_core/training/obb_execution.py`
