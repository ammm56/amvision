# YOLO 姿态估计数据集导入格式规范

## 文档目的

本文档定义平台当前 YOLO keypoints 姿态估计数据集的标准导入目录、配置文件、标注行、关键点形状、类别映射、图片要求和不符合规范的结构。

本文档只覆盖二维姿态估计 pose，不覆盖目标检测 detection、实例分割 segmentation、语义分割 semantic segmentation 和 OBB 旋转框检测。

## 适用范围

当前 YOLO 姿态估计导入格式对应 DatasetImport 的：

- `task_type=pose`
- `format_type=yolo`

可复用该 pose DatasetVersion 的模型：

- `YOLOv8 pose`
- `YOLO11 pose`
- `YOLO26 pose`

YOLOX 当前不作为平台公开 pose 训练能力。RF-DETR 当前不作为平台公开 pose 训练能力。

## 核心定义

YOLO pose 数据集中，一张图像可以包含零个、一个或多个目标实例。每个目标实例用一行文本表示，包含类别编号、归一化水平 bbox 和固定顺序的关键点。

标签行支持两种形式：

```text
class_id x_center y_center width height kpt_x1 kpt_y1 kpt_x2 kpt_y2 ... kpt_xn kpt_yn
```

```text
class_id x_center y_center width height kpt_x1 kpt_y1 visibility1 kpt_x2 kpt_y2 visibility2 ... kpt_xn kpt_yn visibilityn
```

其中 bbox 和关键点坐标都按图像宽高归一化到 0 到 1。导入后平台会把 bbox 和 keypoints 转换为像素坐标写入 DatasetVersion。

## 标准目录结构

```text
dataset/
├─ images/
│  ├─ train/
│  │  ├─ image_001.jpg
│  │  └─ ...
│  ├─ val/
│  │  ├─ image_101.png
│  │  └─ ...
│  └─ test/
│     ├─ image_201.bmp
│     └─ ...
├─ labels/
│  ├─ train/
│  │  ├─ image_001.txt
│  │  └─ ...
│  ├─ val/
│  │  ├─ image_101.txt
│  │  └─ ...
│  └─ test/
│     ├─ image_201.txt
│     └─ ...
└─ data.yaml
```

目录含义：

- `images`：图像文件目录。
- `labels`：YOLO pose 标注文件目录。
- `train`：训练集目录。
- `val`：验证集目录。
- `test`：测试集目录，可选。
- `data.yaml`：数据集配置文件，定义 split 路径、类别名称和关键点形状。

当前导入器会优先识别根目录下的 `data.yaml / data.yml / dataset.yaml / dataset.yml`，也会扫描根目录下其他 `.yaml / .yml` 文件。为减少歧义，标准导入包推荐使用 `data.yaml`。

## 最小标准目录结构

```text
dataset/
├─ images/
│  ├─ train/
│  └─ val/
├─ labels/
│  ├─ train/
│  └─ val/
└─ data.yaml
```

训练集和验证集是标准 pose 数据集的基本组成部分。测试集可选。

## 图像与标注对应关系

每张图像应对应一个同名 `.txt` 标注文件。

示例：

```text
images/train/image_001.jpg
labels/train/image_001.txt
```

对应关系要求：

- 基础文件名一致。
- 所属 split 一致。
- `images/{split}` 与 `labels/{split}` 层级对应。
- 图像文件使用受支持图片扩展名。
- 标注文件使用 `.txt` 扩展名。

无目标图像推荐提供同名空 txt 文件：

```text
images/train/image_002.jpg
labels/train/image_002.txt
```

当前导入器允许缺失 label 文件的图片按空标注导入，并在 validation_report 中写入 warning。标准数据集仍推荐显式提供空 label 文件，便于人工检查和外部工具兼容。

## 标注文件格式

每个 txt 标注文件对应一张图像。每一行表示一个目标实例。

不包含 visibility 的格式：

```text
class_id x_center y_center width height kpt_x1 kpt_y1 kpt_x2 kpt_y2 ... kpt_xn kpt_yn
```

包含 visibility 的格式：

```text
class_id x_center y_center width height kpt_x1 kpt_y1 visibility1 kpt_x2 kpt_y2 visibility2 ... kpt_xn kpt_yn visibilityn
```

示例：

```text
0 0.500000 0.450000 0.400000 0.600000 0.420000 0.250000 2 0.500000 0.400000 2 0.580000 0.650000 1
1 0.300000 0.500000 0.220000 0.360000 0.260000 0.320000 2 0.300000 0.500000 2 0.340000 0.680000 0
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `class_id` | 目标类别编号，从 0 开始 |
| `x_center` | bbox 中心点的归一化横坐标 |
| `y_center` | bbox 中心点的归一化纵坐标 |
| `width` | bbox 归一化宽度 |
| `height` | bbox 归一化高度 |
| `kpt_xi` | 第 i 个关键点的归一化横坐标 |
| `kpt_yi` | 第 i 个关键点的归一化纵坐标 |
| `visibilityi` | 第 i 个关键点的可见性，可选 |

字段使用一个或多个空白字符分隔。标注文件不应包含表头、注释或无关字段。

## bbox 规则

bbox 固定使用 YOLO 归一化中心点格式：

```text
x_center y_center width height
```

归一化规则：

```text
x_center = bbox_center_x_pixel / image_width
y_center = bbox_center_y_pixel / image_height
width    = bbox_width_pixel / image_width
height   = bbox_height_pixel / image_height
```

字段要求：

- `x_center / y_center / width / height` 必须是有限数字。
- 四个归一化值必须位于 0 到 1。
- `width` 必须大于 0。
- `height` 必须大于 0。

导入后，平台会把归一化 bbox 转换为像素 `bbox_xywh`：

```text
x_pixel = (x_center - width / 2) * image_width
y_pixel = (y_center - height / 2) * image_height
w_pixel = width * image_width
h_pixel = height * image_height
```

## 关键点规则

关键点坐标必须按固定顺序写入。所有实例应使用相同的关键点数量、维度和语义顺序。

二维关键点格式：

```text
kpt_x kpt_y
```

带可见性的关键点格式：

```text
kpt_x kpt_y visibility
```

坐标归一化规则：

```text
kpt_x = keypoint_x_pixel / image_width
kpt_y = keypoint_y_pixel / image_height
```

字段要求：

- `kpt_x / kpt_y` 必须是有限数字。
- `kpt_x / kpt_y` 必须位于 0 到 1。
- 如果存在 `visibility`，取值只能是 `0 / 1 / 2`。
- 同一行至少需要 bbox 和一个关键点。
- 缺失关键点不得删除字段位置，应保留对应坐标和 visibility。

visibility 规则：

| 值 | 含义 |
| --- | --- |
| `0` | 关键点未标注或不存在 |
| `1` | 关键点已标注但不可见或被遮挡 |
| `2` | 关键点已标注且可见 |

未提供 visibility 时，导入器按二维关键点读取，并在 DatasetVersion 中把每个关键点 visibility 设为 `2`。

## kpt_shape 规则

标准导入包推荐在 `data.yaml` 中提供 `kpt_shape`：

```yaml
kpt_shape: [关键点数量, 每个关键点字段数]
```

示例：

```yaml
kpt_shape: [17, 3]
```

表示每个实例包含 17 个关键点，每个关键点包含 `x / y / visibility` 三个字段。

```yaml
kpt_shape: [17, 2]
```

表示每个实例包含 17 个关键点，每个关键点只包含 `x / y` 两个字段。

`kpt_shape` 的第二个值只允许 `2` 或 `3`。当 `kpt_shape` 有效时，每行标注字段数量必须满足：

```text
5 + keypoint_count * point_dimensions
```

当 `kpt_shape` 缺失或无效时，导入器会根据关键点字段数量推断：

- 关键点字段数量可以被 3 整除时，按 `point_dimensions=3` 读取。
- 否则关键点字段数量可以被 2 整除时，按 `point_dimensions=2` 读取。
- 两者都不满足时，导入失败。

标准数据集仍推荐显式提供有效 `kpt_shape`，避免二维和带 visibility 的标注被误判。

## 关键点顺序和名称

关键点顺序必须预先定义，并在所有图片和实例中保持一致。

示例：

```text
0: point1
1: point2
2: point3
3: point4
4: point5
```

标注行中的关键点顺序必须始终为：

```text
point1 point2 point3 point4 point5
```

`data.yaml` 可以记录关键点名称，便于人工检查和可视化：

```yaml
kpt_names:
  0:
    - point1
    - point2
    - point3
    - point4
    - point5
```

当前导入链以 `kpt_shape` 和标注字段为主，`kpt_names` 可作为数据集元数据和人工约定使用。不同类别使用不同关键点数量或顺序时，后续训练和导出兼容性会变差，标准数据集不推荐这种结构。

## flip_idx 规则

如果训练中使用水平翻转增强，推荐在 `data.yaml` 中提供 `flip_idx`：

```yaml
flip_idx: [0, 2, 1, 4, 3]
```

`flip_idx` 表示水平翻转后关键点索引的对应关系。其长度应等于 `kpt_shape` 中的关键点数量。

`flip_idx` 主要服务训练增强和外部工具兼容。当前导入规范要求其与关键点定义保持一致，不把它作为判断图片和标注能否解析的唯一条件。

## 类别定义

类别编号应从 `0` 开始，并保持连续。

示例：

```yaml
names:
  0: type1
  1: type2
```

或：

```yaml
names:
  - type1
  - type2
```

标注文件中的 `class_id` 必须存在于类别定义中。导入后 DatasetVersion 会把类别重排为连续 0-based `category_id`，并在 metadata 中保留原始 `source_class_id` 和 `source_class_name`。

类别名称要求：

- 名称唯一。
- 拼写和大小写一致。
- 不包含前导或尾随空格。
- 避免使用不兼容的特殊字符。
- 数据集确定后不应随意修改。

## data.yaml 规则

标准导入包推荐在根目录提供 `data.yaml`：

```yaml
path: .
train: images/train
val: images/val
test: images/test

kpt_shape: [5, 3]
flip_idx: [0, 2, 1, 4, 3]

names:
  0: type1
```

字段说明：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `path` | 否 | 数据集根目录 |
| `train` | 是 | 训练集图像路径 |
| `val` | 是 | 验证集图像路径 |
| `test` | 否 | 测试集图像路径 |
| `names` | 是 | 类别编号到类别名称的映射 |
| `kpt_shape` | 推荐 | 关键点数量和每个关键点字段数 |
| `flip_idx` | 否 | 水平翻转时的关键点索引映射 |
| `kpt_names` | 否 | 关键点名称定义 |

zip 包内推荐使用 `path: .` 或省略 `path`，避免指向本机绝对路径。`train / val / test` 可以是图像目录、图片文件路径、图片列表 `.txt`，或字符串数组。标准数据集推荐使用 `images/{split}` 目录。

## 图像文件要求

YOLO pose 标准导入图片只支持以下扩展名：

```text
.jpg
.jpeg
.png
.bmp
```

扩展名大小写不敏感。导入时按小写形式归一化判断。

图像文件应满足：

- 文件能够正常读取。
- 文件内容与扩展名一致。
- 图像宽度和高度有效。
- 图像文件不为空、不损坏。
- 图像与标注文件基础名称一致。
- 图像存放在正确 split 中。
- train、val、test 之间不存在重复样本。
- 同一来源的高度相似样本应放在同一个 split 中，避免数据泄漏。

`.webp / .tif / .tiff` 不属于当前 YOLO pose 标准导入图片格式。

## 标注文件要求

YOLO pose txt 标注文件应满足：

- 推荐使用 UTF-8 编码。
- 每个文件只对应一张图像。
- 每个目标实例占一行。
- 每行第一个字段为类别编号。
- 每行前 5 个字段为类别和 bbox。
- 后续字段必须能组成关键点。
- 类别编号必须为非负整数。
- 类别编号必须存在于类别定义中。
- bbox 和关键点坐标必须是有限数字。
- bbox 和关键点坐标必须归一化到 0 到 1。
- bbox 宽高必须大于 0。
- visibility 只能是 `0 / 1 / 2`。
- 当 `kpt_shape` 有效时，每行字段数量必须与 `kpt_shape` 匹配。
- 所有实例的关键点数量和顺序必须一致。
- 缺失关键点不得删除字段位置。
- 不应包含重复实例或明显错误的关键点。

## 数据划分要求

训练集、验证集和测试集应相互独立：

```text
train ∩ val = ∅
train ∩ test = ∅
val ∩ test = ∅
```

各 split 用途：

- `train`：用于模型参数学习。
- `val`：用于训练过程中的性能评估和参数选择。
- `test`：用于模型训练完成后的独立评估，可选。

视频帧、连续拍摄图像或同一来源的高度相似样本，应按照来源整体划分，避免数据泄漏。

## zip 包要求

当前阶段默认通过 FastAPI 上传 zip 数据集压缩包。

zip 包应满足：

- zip 内允许存在一层额外包裹目录。
- `images`、`labels` 和 `data.yaml` 应位于同一个数据集根目录下。
- 图片和标注文件必须位于 zip 内部。
- `data.yaml` 不应使用 zip 外绝对路径。
- `train` 和 `val` 应能解析到有效图像。
- train 和 val 图像推荐提供同名 label 文件。
- 不应包含同名但大小写不同的图片或 label 路径。
- 不应混入 detection、segmentation、obb、semantic segmentation 等其他任务的独立标注格式。
- 不应混入不受支持的图片扩展名。

## DatasetVersion 结果

导入成功后生成的 DatasetVersion 满足：

- `task_type=pose`。
- `source_format=yolo`。
- 图像按 `train / val / test` split 归档。
- 类别映射统一为连续 0-based 内部 category id。
- 每个实例保存像素 `bbox_xywh`。
- 每个实例保存像素 keypoints，格式为 `[x, y, visibility]` 展平数组。
- `num_keypoints` 等于 visibility 大于 0 的关键点数量。
- `area` 由 bbox 宽高计算。
- 原始 `source_class_id` 和 `source_class_name` 保留到 metadata。
- metadata 记录 `keypoint_count` 和 `point_dimensions`。

## 导出和训练关系

YOLO pose DatasetVersion 当前可导出为：

```text
yolo-pose-v1
coco-keypoints-v1
```

模型默认训练格式：

- `YOLOv8 pose`：默认使用 `yolo-pose-v1`，可使用 `coco-keypoints-v1`。
- `YOLO11 pose`：默认使用 `yolo-pose-v1`，可使用 `coco-keypoints-v1`。
- `YOLO26 pose`：默认使用 `yolo-pose-v1`，可使用 `coco-keypoints-v1`。

导入格式不等同于训练格式。同一份 YOLO pose 导入数据先生成 DatasetVersion，再按训练任务需要导出为对应格式。

## 完整示例

目录：

```text
dataset/
├─ images/
│  ├─ train/
│  │  ├─ image_001.jpg
│  │  └─ image_002.png
│  └─ val/
│     └─ image_101.bmp
├─ labels/
│  ├─ train/
│  │  ├─ image_001.txt
│  │  └─ image_002.txt
│  └─ val/
│     └─ image_101.txt
└─ data.yaml
```

`data.yaml`：

```yaml
path: .
train: images/train
val: images/val

kpt_shape: [3, 3]
flip_idx: [0, 2, 1]

names:
  0: type1
  1: type2
```

`labels/train/image_001.txt`：

```text
0 0.500000 0.450000 0.400000 0.600000 0.420000 0.250000 2 0.500000 0.400000 2 0.580000 0.650000 1
1 0.300000 0.500000 0.220000 0.360000 0.260000 0.320000 2 0.300000 0.500000 2 0.340000 0.680000 0
```

`labels/train/image_002.txt` 可以为空，表示无目标图像。

## 不符合规范的结构

### 图像与标注文件名不一致

```text
images/train/image_001.jpg
labels/train/label_001.txt
```

图像与标注无法通过基础文件名正确对应。

### 缺少 bbox 字段

```text
0 0.420000 0.250000 2 0.500000 0.400000 2
```

YOLO pose 每行必须先写入类别和完整 bbox：

```text
class_id x_center y_center width height
```

### 使用 detection 标签行

```text
0 0.5 0.5 0.4 0.3
```

该格式只有 bbox，属于 YOLO detection，不是 YOLO pose。

### 使用像素坐标

```text
0 500 400 400 600 420 250 2
```

YOLO pose 要求 bbox 和关键点坐标使用归一化坐标，不直接使用像素坐标。

### 关键点字段不成组

```text
0 0.50 0.45 0.40 0.60 0.42 0.25 2 0.50
```

关键点字段必须按 `x y` 或 `x y visibility` 成组出现。

### 标注与 kpt_shape 不匹配

配置文件定义：

```yaml
kpt_shape: [5, 3]
```

但标注行只包含 3 个关键点，则字段数量不符合配置要求。

### 删除不可见关键点

不可见或缺失关键点不能直接从标注行中删除，应保留字段位置并设置 visibility：

```text
0 0.50 0.45 0.40 0.60 0.42 0.25 2 0.50 0.40 2 0.00 0.00 0
```

### visibility 值无效

```text
0 0.50 0.45 0.40 0.60 0.42 0.25 3
```

visibility 只能是 `0 / 1 / 2`。

### 类别编号不存在

类别定义为：

```yaml
names:
  0: type1
```

标注中出现：

```text
1 0.5 0.5 0.4 0.6 0.4 0.2 2
```

类别编号 `1` 未定义。

### 坐标超出范围

```text
0 0.5 0.5 0.4 0.6 1.2 0.3 2
```

关键点横坐标 `1.2` 超出归一化范围。

### 使用不支持的图片格式

```text
images/train/image_001.webp
images/train/image_002.tiff
```

当前 YOLO pose 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。

## 与目标检测格式的区别

YOLO detection 标注格式：

```text
class_id x_center y_center width height
```

YOLO pose 标注格式：

```text
class_id x_center y_center width height kpt_x kpt_y [visibility] ...
```

主要区别：

| 项目 | detection | pose |
| --- | --- | --- |
| 目标位置 | bbox | bbox 和 keypoints |
| 关键点 | 无 | 有 |
| 单行字段数 | 固定 5 个 | `5 + keypoint_count * point_dimensions` |
| 坐标范围 | 0 到 1 | 0 到 1 |
| 附加配置 | `names` | `names / kpt_shape / flip_idx` |

## 标准定义总结

YOLO pose 数据集推荐结构为：

```text
dataset/
├─ images/
│  ├─ train/图像文件
│  ├─ val/图像文件
│  └─ test/图像文件
├─ labels/
│  ├─ train/TXT 标注文件
│  ├─ val/TXT 标注文件
│  └─ test/TXT 标注文件
└─ data.yaml
```

核心规则：

- 导入任务固定为 `task_type=pose`、`format_type=yolo`。
- 每张图像推荐对应一个同名 TXT 标注文件。
- 每个目标实例占一行。
- 每行首先记录 `class_id x_center y_center width height`。
- 随后按固定顺序记录全部关键点。
- 关键点格式为 `x y` 或 `x y visibility`。
- bbox 和关键点坐标必须归一化到 0 到 1。
- visibility 只能是 `0 / 1 / 2`。
- 类别编号从 `0` 开始，并在 `data.yaml` 的 `names` 中定义。
- 所有实例应使用相同的关键点数量和顺序。
- 标准数据集推荐显式提供 `kpt_shape`。
- 缺失关键点不得删除字段位置。
- 无目标图像推荐使用空 TXT 文件。
- 导入图片只支持 `.jpg / .jpeg / .png / .bmp`。
- 导入后生成 DatasetVersion，再按训练任务导出为 `yolo-pose-v1 / coco-keypoints-v1`。

## 相关文档

- [classification-dataset-import-format.md](classification-dataset-import-format.md)
- [coco-detection-dataset-import-format.md](coco-detection-dataset-import-format.md)
- [coco-segmentation-dataset-import-format.md](coco-segmentation-dataset-import-format.md)
- [coco-pose-dataset-import-format.md](coco-pose-dataset-import-format.md)
- [voc-detection-dataset-import-format.md](voc-detection-dataset-import-format.md)
- [yolo-detection-dataset-import-format.md](yolo-detection-dataset-import-format.md)
- [yolo-segmentation-dataset-import-format.md](yolo-segmentation-dataset-import-format.md)
- [dota-obb-dataset-import-format.md](dota-obb-dataset-import-format.md)
- [model-dataset-format-contract.md](model-dataset-format-contract.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)
