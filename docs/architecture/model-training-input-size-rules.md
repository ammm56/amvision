# 模型训练输入尺寸规则

## 文档目的

本文档用于固定模型训练页面里“输入宽度 / 输入高度”或 `imgsz / input_size / resolution` 的解释规则。

这里说的是训练任务的目标输入尺寸，不是要求原始图片必须提前裁成这个尺寸。实际训练流程会按模型参考实现做 resize、LetterBox、padding 或固定 resolution 预处理，并在验证、评估、转换和 runtime 后处理里按同一套规则还原到原图坐标或任务原生输出。

## 总体规则

- 公开结果里 detection box 统一输出原图坐标 `xyxy`，不把模型内部训练格式直接泄漏到平台外部。
- segmentation、pose 和 OBB 不强行转成 `xyxy`：segmentation 以 mask / polygon / instance result 为主，pose 以 keypoints 为主，OBB 以 `xywhr` 或 rotated box 任务格式为主。
- 模型 core 内部必须保持训练、验证、评估、转换和 runtime 使用同一套预处理与坐标反算规则。
- 不为了项目表面一致性强行把所有模型改成同一种 LetterBox。YOLOX、RF-DETR、Ultralytics YOLO 主线分别按各自参考实现保留模型差异。
- 公开 API、任务快照、ModelVersion、ModelBuild 和部署响应统一使用 `{"width": W, "height": H}`，不接受有顺序歧义的二元素数组。
- 模型 core 和张量层统一使用 `(height, width)`；OpenCV resize 参数只在调用点转换为 `(width, height)`。
- ModelVersion 必须固化完整 `model_input_spec`，ModelBuild 必须继承并校验实际 NCHW 输入张量。转换、推理和部署不得用默认值掩盖契约缺失。

## 训练输入尺寸矩阵

| 模型族 | 支持的任务类型 | 训练输入宽高规则 | 常用 / 默认尺寸 |
| --- | --- | --- | --- |
| YOLOX | detection | 参考实现使用 `input_size=(height, width)`，可设置矩形输入；多尺度训练尺寸通常按 32 的倍数变化。 | 多数模型默认 `640 x 640`；`yolox-tiny`、`yolox-nano` 常用 `416 x 416`。若 `input_size=640` 且默认 `multiscale_range=5`，实际多尺度范围通常是 `480-800`。 |
| RF-DETR | detection | 使用方形 `resolution x resolution`；当前 detection checkpoint 常用 32 的倍数。 | 常用 `384 x 384`、`512 x 512`、`576 x 576`、`704 x 704`；部分更大 scale 会使用 `700 x 700`、`880 x 880` 这类分辨率。 |
| RF-DETR Seg | segmentation | 使用方形 `resolution x resolution`；多数 segmentation 模型要求尺寸可被 `patch_size * num_windows` 整除，Nano 可能对应更小倍数。 | 常用 `312 x 312`、`384 x 384`、`432 x 432`、`504 x 504`、`624 x 624`、`768 x 768`。 |
| YOLOv8 / YOLO11 / YOLO26 Detect | detection | 支持显式矩形目标尺寸。训练随机增强、验证确定性 LetterBox、导出和 runtime 均共享 `(height, width)` 几何契约。 | 默认 `640 x 640`；可按显存和小目标需求使用 `640 x 384`、`960 x 544` 或方形尺寸。 |
| YOLOv8 / YOLO11 / YOLO26 Segment | instance segmentation | 与 detection 共用中心 LetterBox；polygon、mask 和输出还原使用相同 gain/padding。 | 默认 `640 x 640`，也支持显式矩形尺寸。 |
| YOLOv8 / YOLO11 / YOLO26 Pose | pose / keypoints | 与 detection 共用中心 LetterBox；keypoint 与 bbox 使用同一几何变换。 | 默认 `640 x 640`，也支持显式矩形尺寸。 |
| YOLOv8 / YOLO11 / YOLO26 OBB | oriented bounding box | 与 detection 共用中心 LetterBox；rotated box 角点和尺度按同一几何契约转换。 | 默认 `640 x 640`，也支持显式矩形尺寸。 |
| YOLOv8 / YOLO11 / YOLO26 Classification | classification | 训练使用随机比例裁剪，验证和 runtime 使用保持比例缩放后中心裁剪；目标张量支持显式宽高。 | 默认 `224 x 224`；特殊任务可使用显式矩形尺寸。 |

## 前端训练页面规则

### YOLOX

- detection 可以保留“输入宽度 / 输入高度”两个字段。
- 提交到执行层时要清楚映射到 core 所需的 `(height, width)`，避免把 UI 的 `width / height` 顺序误传成 `height / width`。
- 如果启用多尺度训练，前端应说明最终训练尺寸会围绕基础尺寸变化，不等于每个 batch 都固定为表单尺寸。

### RF-DETR

- detection / segmentation 建议以前端单个 `resolution` 概念展示；如果页面继续显示宽高，必须要求宽高一致。
- 未显式指定时，detection 按 scale 使用 `nano=384`、`s=512`、`m=576`、`l=704` 的方形 resolution；segmentation 使用 `nano=312`、`s=384`、`m=432`、`l=504`、`x=624`。
- 平台收到矩形或未对齐尺寸时，先按当前 full core 的约束向上对齐，再取较长边作为实际 `resolution`，最终训练尺寸始终登记为 `resolution x resolution`。
- segmentation 必须按所选模型的 `patch_size * num_windows` 校验，不能只做 32 倍数的通用判断。

### YOLOv8 / YOLO11 / YOLO26

- detection / segmentation / pose / OBB / classification 页面使用明确的“输入宽度 / 输入高度”字段，并按同名 JSON 字段提交。
- 实际原图可以是任意宽高比。detection / segmentation / pose / OBB 由公共 LetterBox 保持比例缩放和填充；classification 使用训练随机裁剪与验证确定性中心裁剪。
- 页面展示、任务详情、模型版本、转换构建和部署实例必须显示同一尺寸，不得交换宽高或在中途回退到默认值。

## 推荐选型

- detection / segmentation / pose：先用 `640 x 640`。
- 小目标多、显存足够：可试 `960`、`1024`、`1280`。
- classification：先用 `224 x 224`。
- OBB 航拍类数据：可优先试 `1024 x 1024`。
- 显存不足：降到 `512`、`416` 或更小，并同步观察 batch size、训练速度和 mAP。

## 关联文档

- [训练参数支持清单](training-parameter-support.md)
- [模型 full core 审计与验收清单](model-full-core-audit-checklist.md)
- [模型 core 完整实现计划](model-core-implementation-plan.md)
