# 模型数据集格式规范

## 文档目的

本文档统一定义当前模型和任务类型的数据集导入、DatasetVersion 内部表示、DatasetExport 导出格式和训练输入格式选择规则。

本文档按模型顺序 `YOLOX / YOLOv8 / YOLO11 / YOLO26 / RF-DETR`，以及任务顺序 `classification / detection / segmentation / pose / obb` 整理。未列为支持的组合不得在前端、API 示例或训练任务中作为可用能力暴露。

## 边界

- DatasetImport 只按 `task_type` 和外部格式导入，不绑定 `model_type`。
- DatasetVersion 是平台内部稳定数据版本，训练、评估和导出均以它为来源。
- DatasetExport 按 `format_id` 生成目标训练或评估输入，模型差异在这一层体现。
- 模型 conversion 任务消费 `ModelVersion`，不消费数据集；本文中的“导出转换数据集”指 `DatasetVersion -> DatasetExport` 的数据格式转换。

## 当前支持总表

| task_type | 已实现导入格式 | 已实现导出格式 |
| --- | --- | --- |
| `classification` | `imagenet` | `imagenet-classification-v1` |
| `detection` | `coco / voc / yolo` | `yolo-detection-v1 / coco-detection-v1 / voc-detection-v1` |
| `segmentation` | `coco / yolo` | `yolo-instance-seg-v1 / coco-instance-seg-v1` |
| `pose` | `coco / yolo` | `yolo-pose-v1 / coco-keypoints-v1` |
| `obb` | `dota / yolo` | `dota-obb-v1` |

`semantic-mask-dir-v1` 和 `sam-promptable-seg-v1` 仍是预留格式，当前不得当作已实现导出格式使用。

## 模型任务规范

### YOLOX

| task_type | 支持状态 | 导入数据集 | 默认导出格式 | 备选导出格式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `classification` | 不支持 | - | - | - | YOLOX 当前只进入 detection 主链。 |
| `detection` | 支持 | `coco / voc / yolo` | `coco-detection-v1` | `voc-detection-v1` | 训练和评估默认使用 COCO detection；VOC 已接通。 |
| `segmentation` | 不支持 | - | - | - | 不作为 YOLOX 公开能力。 |
| `pose` | 不支持 | - | - | - | 不作为 YOLOX 公开能力。 |
| `obb` | 不支持 | - | - | - | 不作为 YOLOX 公开能力。 |

### YOLOv8

| task_type | 支持状态 | 导入数据集 | 默认导出格式 | 备选导出格式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `classification` | 支持 | `imagenet` | `imagenet-classification-v1` | - | 每个样本必须且只能有一条 classification 标注。 |
| `detection` | 支持 | `coco / voc / yolo` | `yolo-detection-v1` | `coco-detection-v1` | YOLO 原生目录为默认训练格式。 |
| `segmentation` | 支持 | `coco / yolo` | `yolo-instance-seg-v1` | `coco-instance-seg-v1` | YOLO 导出不接受 RLE 或多 polygon 无损表达不了的样本。 |
| `pose` | 支持 | `coco / yolo` | `yolo-pose-v1` | `coco-keypoints-v1` | YOLO pose 导出要求全部标注关键点数量一致。 |
| `obb` | 支持 | `dota / yolo` | `dota-obb-v1` | - | OBB 统一用四角点 polygon 表达。 |

### YOLO11

| task_type | 支持状态 | 导入数据集 | 默认导出格式 | 备选导出格式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `classification` | 支持 | `imagenet` | `imagenet-classification-v1` | - | 与 YOLOv8 classification 共用数据边界。 |
| `detection` | 支持 | `coco / voc / yolo` | `yolo-detection-v1` | `coco-detection-v1` | 与 YOLOv8 detection 共用导入导出格式。 |
| `segmentation` | 支持 | `coco / yolo` | `yolo-instance-seg-v1` | `coco-instance-seg-v1` | 与 YOLOv8 segmentation 共用格式规则。 |
| `pose` | 支持 | `coco / yolo` | `yolo-pose-v1` | `coco-keypoints-v1` | 与 YOLOv8 pose 共用格式规则。 |
| `obb` | 支持 | `dota / yolo` | `dota-obb-v1` | - | 与 YOLOv8 OBB 共用格式规则。 |

### YOLO26

| task_type | 支持状态 | 导入数据集 | 默认导出格式 | 备选导出格式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `classification` | 支持 | `imagenet` | `imagenet-classification-v1` | - | 与 YOLOv8 classification 共用数据边界。 |
| `detection` | 支持 | `coco / voc / yolo` | `yolo-detection-v1` | `coco-detection-v1` | 与 YOLOv8 detection 共用导入导出格式。 |
| `segmentation` | 支持 | `coco / yolo` | `yolo-instance-seg-v1` | `coco-instance-seg-v1` | 与 YOLOv8 segmentation 共用格式规则。 |
| `pose` | 支持 | `coco / yolo` | `yolo-pose-v1` | `coco-keypoints-v1` | 与 YOLOv8 pose 共用格式规则。 |
| `obb` | 支持 | `dota / yolo` | `dota-obb-v1` | - | 与 YOLOv8 OBB 共用格式规则。 |

### RF-DETR

| task_type | 支持状态 | 导入数据集 | 默认导出格式 | 备选导出格式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `classification` | 不支持 | - | - | - | 不作为 RF-DETR 公开能力。 |
| `detection` | 支持 | `coco / voc / yolo` | `coco-detection-v1` | - | 训练和评估当前只接受 COCO detection 导出。 |
| `segmentation` | 支持 | `coco / yolo` | `coco-instance-seg-v1` | - | 当前只接受 COCO instance segmentation 导出。 |
| `pose` | 不支持 | - | - | - | RF-DETR keypoint 分支未进入平台公开 pose 主链。 |
| `obb` | 不支持 | - | - | - | 不作为 RF-DETR 公开能力。 |

## 导入格式规范

### 通用 zip 规则

- 导入接口只接受 `.zip`。
- zip 内允许一层或多层单目录包裹，导入器会连续消除单目录包裹。
- 当前标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`；各任务的细节以对应导入格式规范为准。
- `split_strategy` 允许 `auto / train / val / test`；`train / val / test` 会强制全部样本归入对应 split。
- 自动 split 统一归一化为 `train / val / test`，`valid` 归一化为 `val`。
- 文件路径必须是安全相对路径，不允许绝对路径和 `..`。

### COCO 导入

适用任务：`detection / segmentation / pose`。

COCO detection 的标准导入目录、JSON 字段、类别映射、图片格式限制和不符合规范的结构见 [coco-detection-dataset-import-format.md](coco-detection-dataset-import-format.md)。本文只保留 COCO 系列格式摘要。

COCO segmentation 的标准导入目录、polygon/RLE segmentation、类别映射、图片格式限制和不符合规范的结构见 [coco-segmentation-dataset-import-format.md](coco-segmentation-dataset-import-format.md)。本文只保留 COCO 系列格式摘要。

COCO pose 的标准导入目录、keypoints 字段、num_keypoints、类别和骨架定义、图片格式限制和不符合规范的结构见 [coco-pose-dataset-import-format.md](coco-pose-dataset-import-format.md)。本文只保留 COCO 系列格式摘要。

推荐目录：

```text
dataset-root/
├─ annotations/
│  ├─ instances_train.json
│  ├─ instances_val.json
│  └─ person_keypoints_train.json
├─ images/
│  ├─ train/
│  └─ val/
└─ test/
```

也支持 Roboflow 常见 split-local manifest：

```text
dataset-root/
├─ train/
│  ├─ _annotations.coco.json
│  └─ image-1.jpg
├─ valid/
│  ├─ _annotations.coco.json
│  └─ image-2.jpg
└─ test/
   ├─ _annotations.coco.json
   └─ image-3.jpg
```

最小 JSON 字段：

- 顶层必须包含 `images / annotations / categories`。
- `images[]` 必须包含 `id / file_name / width / height`。
- `categories[]` 必须包含 `id / name`。
- `annotations[]` 必须包含 `image_id / category_id / bbox`。
- `bbox` 固定为 `[x, y, width, height]` 像素坐标，宽高必须大于 0。
- `segmentation` 任务要求 annotation 具备合法 polygon 或 RLE。
- `pose` 任务要求 `keypoints` 非空且长度为 3 的倍数，`visibility` 只能是 `0 / 1 / 2`，`num_keypoints` 必须等于可见关键点数量。

COCO detection 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。`.webp / .tif / .tiff` 不属于当前 COCO detection 标准导入格式。

COCO segmentation 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。`.webp / .tif / .tiff` 不属于当前 COCO segmentation 标准导入格式。

COCO pose 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。`.webp / .tif / .tiff` 不属于当前 COCO pose 标准导入格式。

### Pascal VOC 导入

适用任务：`detection`。

VOC detection 的标准导入目录、XML 字段、split 文件、图片格式限制和不符合规范的结构见 [voc-detection-dataset-import-format.md](voc-detection-dataset-import-format.md)。本文只保留 Pascal VOC detection 格式摘要。

目录：

```text
dataset-root/
├─ JPEGImages/
├─ Annotations/
└─ ImageSets/
   └─ Main/
      ├─ train.txt
      ├─ val.txt
      ├─ trainval.txt
      └─ test.txt
```

`train.txt` 和 `val.txt` 是标准导入必需文件。`trainval.txt` 和 `test.txt` 可选，其中 `trainval.txt` 是 train 与 val 的合集，不作为独立互斥 split。

XML 最小字段：

- 根节点为 `annotation`。
- 必须包含 `filename`、`size/width`、`size/height`。
- 有目标图像的每个 `object` 必须包含 `name` 和 `bndbox/xmin/ymin/xmax/ymax`；无目标图像可以不包含 `object`。
- VOC 坐标按 1-based inclusive `xyxy` 读取，导入后转换为平台内部 0-based `xywh`。
- `difficult / truncated / pose` 写入 annotation metadata。

VOC detection 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。`.webp / .tif / .tiff` 不属于当前 VOC detection 标准导入格式。

### YOLO 导入

适用任务：`detection / segmentation / pose / obb`。

YOLO detection 的标准导入目录、标签行、类别配置、图片格式限制和不符合规范的结构见 [yolo-detection-dataset-import-format.md](yolo-detection-dataset-import-format.md)。本文只保留 YOLO 系列格式摘要。

YOLO segmentation 的标准导入目录、polygon 标注行、类别配置、图片格式限制和不符合规范的结构见 [yolo-segmentation-dataset-import-format.md](yolo-segmentation-dataset-import-format.md)。本文只保留 YOLO 系列格式摘要。

YOLO pose 的标准导入目录、bbox+keypoints 标注行、kpt_shape、类别配置、图片格式限制和不符合规范的结构见 [yolo-pose-dataset-import-format.md](yolo-pose-dataset-import-format.md)。本文只保留 YOLO 系列格式摘要。

推荐目录：

```text
dataset-root/
├─ data.yaml
├─ images/
│  ├─ train/
│  ├─ val/
│  └─ test/
└─ labels/
   ├─ train/
   ├─ val/
   └─ test/
```

`data.yaml` 支持字段：

- `path`：可选数据集根路径。
- `train / val / test`：字符串路径、图片文件路径、图片列表 `.txt`，或字符串数组。
- `names`：类别名列表或 `{id: name}` 字典。
- `kpt_shape`：pose 可选字段，格式为 `[keypoint_count, 2|3]`。

未提供可用 `data.yaml` 时，导入器会尝试按 `images/{split}` 和 `labels/{split}` 扫描。缺失 label 的图片会按空标注导入，并在 validation_report 写 warning。

标签行：

- detection：`class_id cx cy w h`
- segmentation：`class_id x1 y1 x2 y2 x3 y3 ...`
- pose：`class_id cx cy w h kpt_x kpt_y [visibility] ...`
- obb：`class_id x1 y1 x2 y2 x3 y3 x4 y4 [extra...]`

YOLO 标签坐标全部按 0 到 1 的归一化坐标读取。导入后转换为像素坐标写入 DatasetVersion。

YOLO detection 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。`.webp / .tif / .tiff` 不属于当前 YOLO detection 标准导入格式。

YOLO segmentation 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。`.webp / .tif / .tiff` 不属于当前 YOLO segmentation 标准导入格式。

YOLO pose 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。`.webp / .tif / .tiff` 不属于当前 YOLO pose 标准导入格式。

### ImageNet 导入

适用任务：`classification`。

分类导入标准目录、类别规则、图像要求和不符合规范的结构见 [classification-dataset-import-format.md](classification-dataset-import-format.md)。本文只保留格式摘要。

支持两类目录：

```text
dataset-root/
├─ train/
│  ├─ ok/
│  └─ ng/
└─ val/
   ├─ ok/
   └─ ng/
```

或无 split 根目录：

```text
dataset-root/
├─ ok/
└─ ng/
```

无 split 时默认归入 `train`，除非请求用 `split_strategy` 强制指定。类别名来自 class 目录名，`class_map_json` 可覆盖。

### DOTA 导入

适用任务：`obb`。

DOTA OBB 的标准导入目录、四点 polygon 标注行、类别规则、图片格式限制和不符合规范的结构见 [dota-obb-dataset-import-format.md](dota-obb-dataset-import-format.md)。本文只保留 DOTA OBB 格式摘要。

目录：

```text
dataset-root/
├─ images/
│  ├─ train/
│  ├─ val/
│  └─ test/
└─ labels/
   ├─ train/
   ├─ val/
   └─ test/
```

也支持 `labels/{split}_original`。

标签行：

```text
x1 y1 x2 y2 x3 y3 x4 y4 class_name [difficult]
```

- 坐标为像素坐标，必须组成面积大于 0 的四边形。
- `difficult` 可选，只能是 `0 / 1`。
- `imagesource:` 和 `gsd:` 行作为 DOTA 元数据头忽略。
- train/val 样本必须有 label 文件；test 可以没有 label 文件。
- DOTA OBB 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。`.webp / .tif / .tiff` 不属于当前 DOTA OBB 标准导入格式。

## DatasetVersion 内部表示

DatasetVersion 当前用任务专属 annotation 类型表达：

- `DetectionAnnotation`：`bbox_xywh / area / iscrowd / metadata`
- `InstanceSegmentationAnnotation`：`bbox_xywh / segmentation / area / iscrowd / metadata`
- `PoseAnnotation`：`bbox_xywh / keypoints / num_keypoints / area / iscrowd / metadata`
- `ClassificationAnnotation`：`category_id / metadata`
- `ObbAnnotation`：`bbox_xywh / polygon_xy / area / iscrowd / metadata`

类别在导入后统一重排为连续的 0-based `category_id`。外部原始类别 id、类别名和特殊字段写入 metadata。

## 导出格式规范

### `yolo-detection-v1`

任务：`detection`。

目录：

```text
export-root/
├─ manifest.json
├─ images/{split}/
└─ labels/{split}/
```

标签行：

```text
class_index cx cy w h
```

坐标为归一化 0 到 1，保留 6 位小数。导出前会检查 bbox 不能越界。

### `yolo-instance-seg-v1`

任务：`segmentation`。

目录同 YOLO detection。标签行：

```text
class_index x1 y1 x2 y2 x3 y3 ...
```

当前只支持单 polygon。COCO RLE 和多 polygon 会被拒绝，应改用 `coco-instance-seg-v1`。

### `yolo-pose-v1`

任务：`pose`。

目录同 YOLO detection。标签行：

```text
class_index cx cy w h kpt_x kpt_y visibility ...
```

`manifest.json.metadata.kpt_shape` 写入 `[keypoint_count, 3]`。全部 pose 标注必须使用一致关键点数量。

### `coco-detection-v1`

任务：`detection`。

目录：

```text
export-root/
├─ manifest.json
├─ images/{split}/
└─ annotations/instances_{split}.json
```

JSON 包含 `info / images / annotations / categories`。bbox 为像素 `xywh`。

### `voc-detection-v1`

任务：`detection`。

目录：

```text
export-root/
├─ manifest.json
├─ JPEGImages/
├─ Annotations/
└─ ImageSets/Main/{split}.txt
```

XML bbox 输出为 VOC 1-based inclusive `xyxy`。

### `coco-instance-seg-v1`

任务：`segmentation`。

目录：

```text
export-root/
├─ manifest.json
├─ images/{split}/
└─ annotations/instances_{split}.json
```

保留 COCO polygon 或 RLE segmentation。RLE size 必须等于 `[height, width]`。

### `coco-keypoints-v1`

任务：`pose`。

目录：

```text
export-root/
├─ manifest.json
├─ images/{split}/
└─ annotations/person_keypoints_{split}.json
```

keypoints 为 COCO `[x, y, visibility]` 展平数组，`num_keypoints` 必须与可见点数量一致。

### `imagenet-classification-v1`

任务：`classification`。

目录：

```text
export-root/
├─ manifest.json
├─ annotations/{split}.json
└─ {split}/{class_name}/
```

每个样本必须且只能有一条 classification 标注。类别名必须是安全的单层目录名。

### `dota-obb-v1`

任务：`obb`。

目录：

```text
export-root/
├─ manifest.json
├─ images/{split}/
├─ annotations/{split}.json
└─ labels/{split}/{image_stem}.txt
```

JSON annotation 写 `bbox` 和 `poly`。DOTA txt 行写：

```text
x1 y1 x2 y2 x3 y3 x4 y4 class_name difficult
```

类别名不能包含空白字符。每条 OBB 标注必须具备 8 个四角点，且面积大于 0。

## 能力读取入口

- `GET /api/v1/datasets/export-formats` 返回已实现导出格式和按 `task_type` 分组的格式列表。
- `GET /api/v1/system/bootstrap` 的 `capabilities.training_export_formats_by_task_and_model_type` 返回训练任务使用的 `task_type -> model_type -> format_id[]` 能力矩阵。
- 前端训练页应以 system bootstrap 的模型维度矩阵为准，不维护第二份静态映射。

## 相关文档

- [classification-dataset-import-format.md](classification-dataset-import-format.md)
- [coco-detection-dataset-import-format.md](coco-detection-dataset-import-format.md)
- [coco-segmentation-dataset-import-format.md](coco-segmentation-dataset-import-format.md)
- [coco-pose-dataset-import-format.md](coco-pose-dataset-import-format.md)
- [voc-detection-dataset-import-format.md](voc-detection-dataset-import-format.md)
- [yolo-detection-dataset-import-format.md](yolo-detection-dataset-import-format.md)
- [yolo-segmentation-dataset-import-format.md](yolo-segmentation-dataset-import-format.md)
- [yolo-pose-dataset-import-format.md](yolo-pose-dataset-import-format.md)
- [dota-obb-dataset-import-format.md](dota-obb-dataset-import-format.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)
- [model-support-matrix.md](model-support-matrix.md)
