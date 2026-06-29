# 模型训练输入尺寸规则

## 文档目的

本文档用于固定模型训练页面里“输入宽度 / 输入高度”或 `imgsz / input_size / resolution` 的解释规则。

这里说的是训练任务的目标输入尺寸，不是要求原始图片必须提前裁成这个尺寸。实际训练流程会按模型参考实现做 resize、LetterBox、padding 或固定 resolution 预处理，并在验证、评估、转换和 runtime 后处理里按同一套规则还原到原图坐标或任务原生输出。

## 总体规则

- 公开结果里 detection box 统一输出原图坐标 `xyxy`，不把模型内部训练格式直接泄漏到平台外部。
- segmentation、pose 和 OBB 不强行转成 `xyxy`：segmentation 以 mask / polygon / instance result 为主，pose 以 keypoints 为主，OBB 以 `xywhr` 或 rotated box 任务格式为主。
- 模型 core 内部必须保持训练、验证、评估、转换和 runtime 使用同一套预处理与坐标反算规则。
- 不为了项目表面一致性强行把所有模型改成同一种 LetterBox。YOLOX、RF-DETR、Ultralytics YOLO 主线分别按各自参考实现保留模型差异。
- 前端训练页面可以继续用“输入宽度 / 输入高度”展示，但对只支持单整数尺寸的模型，应在页面和提交校验中明确要求宽高相同，或收口为单个 `imgsz` 输入。

## 训练输入尺寸矩阵

| 模型族 | 支持的任务类型 | 训练输入宽高规则 | 常用 / 默认尺寸 |
| --- | --- | --- | --- |
| YOLOX | detection | 参考实现使用 `input_size=(height, width)`，可设置矩形输入；多尺度训练尺寸通常按 32 的倍数变化。 | 多数模型默认 `640 x 640`；`yolox-tiny`、`yolox-nano` 常用 `416 x 416`。若 `input_size=640` 且默认 `multiscale_range=5`，实际多尺度范围通常是 `480-800`。 |
| RF-DETR | detection | 使用方形 `resolution x resolution`；当前 detection checkpoint 常用 32 的倍数。 | 常用 `384 x 384`、`512 x 512`、`576 x 576`、`704 x 704`；部分更大 scale 会使用 `700 x 700`、`880 x 880` 这类分辨率。 |
| RF-DETR Seg | segmentation | 使用方形 `resolution x resolution`；多数 segmentation 模型要求尺寸可被 `patch_size * num_windows` 整除，Nano 可能对应更小倍数。 | 常用 `312 x 312`、`384 x 384`、`432 x 432`、`504 x 504`、`624 x 624`、`768 x 768`。 |
| YOLOv8 / YOLO11 / YOLO26 Detect | detection | 训练阶段按 Ultralytics 主线使用单整数 `imgsz=N`，目标输入为 `N x N`；传入 `[h, w]` 的场景应按参考规则归一，不作为任意矩形训练入口。 | 默认 `640 x 640`；可按显存和小目标需求使用 `320`、`512`、`768`、`960`、`1024`、`1280` 等，建议使用 stride 倍数，通常是 32 的倍数。 |
| YOLOv8 / YOLO11 / YOLO26 Segment | instance segmentation | 同 Ultralytics 训练规则：`imgsz=N`，目标输入为 `N x N`。 | 常用 `640 x 640`。 |
| YOLOv8 / YOLO11 / YOLO26 Pose | pose / keypoints | 同 Ultralytics 训练规则：`imgsz=N`，目标输入为 `N x N`。 | 通常 `640 x 640`；P6 或大模型场景可使用 `1280 x 1280` 训练 / 验证，但参数仍按单整数表达。 |
| YOLOv8 / YOLO11 / YOLO26 OBB | oriented bounding box | 同 Ultralytics 训练规则：`imgsz=N`，目标输入为 `N x N`。 | 常用 `640 x 640`；DOTA / 航拍类 OBB 评估常见 `1024 x 1024`。 |
| YOLOv8 / YOLO11 / YOLO26 Classification | classification | 使用单整数 `imgsz=N`，分类模型输入为方形 `N x N`。 | ImageNet 预训练分类模型通常使用 `224 x 224`；特殊小图任务可使用更小尺寸，例如 `64 x 64`。 |

## 前端训练页面规则

### YOLOX

- detection 可以保留“输入宽度 / 输入高度”两个字段。
- 提交到执行层时要清楚映射到 core 所需的 `(height, width)`，避免把 UI 的 `width / height` 顺序误传成 `height / width`。
- 如果启用多尺度训练，前端应说明最终训练尺寸会围绕基础尺寸变化，不等于每个 batch 都固定为表单尺寸。

### RF-DETR

- detection / segmentation 建议以前端单个 `resolution` 概念展示；如果页面继续显示宽高，必须要求宽高一致。
- detection 默认按当前 checkpoint scale 的方形 resolution 校验。
- segmentation 必须按所选模型的 `patch_size * num_windows` 校验，不能只做 32 倍数的通用判断。

### YOLOv8 / YOLO11 / YOLO26

- detection / segmentation / pose / OBB / classification 训练页面不应鼓励填写任意矩形宽高。
- 页面如果保留两个输入框，应在宽高不一致时给出明确提示：训练阶段按单整数 `imgsz` 进入 `N x N` 训练，不能把 `1280 x 720` 直接作为训练目标矩形。
- 实际原图可以是 `1280 x 720`、`1920 x 1080`、`3840 x 2160` 等非 1:1 图像；训练时由模型 core 的预处理按参考实现缩放和 padding。

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
