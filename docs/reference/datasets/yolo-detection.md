# YOLO 目标检测数据集导入格式规范

## 文档目的

本文档定义平台当前 YOLO 矩形边界框目标检测数据集的标准导入目录、配置文件、标签行、类别映射、图片要求和不符合规范的结构。

本文档只覆盖目标检测 detection，不覆盖图像分类、实例分割、姿态估计和 OBB 旋转框检测。YOLO segmentation、YOLO pose 和 YOLO OBB 后续应分别维护独立导入格式规范。

## 适用范围

当前 YOLO 目标检测导入格式对应 DatasetImport 的：

- `task_type=detection`
- `format_type=yolo`

可复用该 detection DatasetVersion 的模型：

- `YOLOv8 detection`
- `YOLO11 detection`
- `YOLO26 detection`

YOLOX 和 RF-DETR 的 detection 训练默认不直接消费 YOLO detection 导出格式；同一份 YOLO detection 导入数据可以先生成 DatasetVersion，再按需要导出为 `coco-detection-v1` 或 `voc-detection-v1` 后供 YOLOX / RF-DETR 使用。

## 核心定义

YOLO 目标检测数据集中，一张图像可以包含零个、一个或多个目标。每个目标用一行文本表示，包含类别编号和归一化边界框。

标签行格式固定为：

```text
class_id x_center y_center width height
```

其中后四个字段为相对图像宽高归一化后的中心点坐标和宽高。

## 标准目录结构

```text
dataset/
├─ images/
│  ├─ train/
│  │  ├─ image_001.jpg
│  │  └─ ...
│  ├─ val/
│  │  ├─ image_101.jpg
│  │  └─ ...
│  └─ test/
│     ├─ image_201.jpg
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
- `labels`：YOLO txt 标注文件目录。
- `train`：训练集目录。
- `val`：验证集目录。
- `test`：测试集目录，可选。
- `data.yaml`：数据集配置文件，定义 split 路径和类别名称。

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

训练集和验证集是标准 detection 数据集的基本组成部分。测试集可选。

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

每个 txt 标注文件对应一张图像。每一行表示一个目标：

```text
class_id x_center y_center width height
```

示例：

```text
0 0.512500 0.437500 0.250000 0.300000
2 0.720000 0.610000 0.180000 0.220000
```

字段定义：

| 字段 | 含义 |
| --- | --- |
| `class_id` | 目标类别编号，从 0 开始 |
| `x_center` | 边界框中心点的归一化横坐标 |
| `y_center` | 边界框中心点的归一化纵坐标 |
| `width` | 边界框归一化宽度 |
| `height` | 边界框归一化高度 |

字段之间使用一个或多个空格分隔。标注文件中不得包含表头、注释、类别名称或其他无关内容。

## 坐标规则

边界框采用归一化中心点格式：

```text
x_center y_center width height
```

归一化规则：

```text
x_center = 边界框中心点横坐标 / 图像宽度
y_center = 边界框中心点纵坐标 / 图像高度
width    = 边界框宽度 / 图像宽度
height   = 边界框高度 / 图像高度
```

字段范围：

```text
0 <= x_center <= 1
0 <= y_center <= 1
0 < width <= 1
0 < height <= 1
```

边界框实际范围不得超出图像边界：

```text
x_min = x_center - width / 2
x_max = x_center + width / 2
y_min = y_center - height / 2
y_max = y_center + height / 2
```

应满足：

```text
0 <= x_min < x_max <= 1
0 <= y_min < y_max <= 1
```

导入后，平台会把 YOLO 归一化坐标转换为 DatasetVersion 内部使用的像素 `bbox_xywh`。

## 坐标计算示例

原图尺寸：

```text
图像宽度 = 1000
图像高度 = 800
```

目标框像素坐标：

```text
左上角：(200, 160)
右下角：(600, 560)
```

计算：

```text
框宽度 = 600 - 200 = 400
框高度 = 560 - 160 = 400
中心点 x = (200 + 600) / 2 = 400
中心点 y = (160 + 560) / 2 = 360
```

归一化：

```text
x_center = 400 / 1000 = 0.4
y_center = 360 / 800  = 0.45
width    = 400 / 1000 = 0.4
height   = 400 / 800  = 0.5
```

类别编号为 `1` 时，标注内容为：

```text
1 0.4 0.45 0.4 0.5
```

## 类别定义

类别编号必须从 `0` 开始，并保持连续。

示例：

```text
0: type1
1: type2
2: type3
```

类别数量为 `N` 时，合法类别编号范围为：

```text
0 到 N-1
```

标注文件中的 `class_id` 必须存在于类别定义中。训练、验证、测试和部署阶段必须使用相同的类别编号与类别名称映射。

导入后 DatasetVersion 会把类别重排为连续 0-based `category_id`，并在 metadata 中保留原始 `source_class_id` 和 `source_class_name`。

## data.yaml 规则

标准配置文件推荐命名为 `data.yaml`。

最小配置：

```yaml
train: images/train
val: images/val

names:
  0: type1
  1: type2
```

完整配置：

```yaml
path: .

train: images/train
val: images/val
test: images/test

names:
  0: type1
  1: type2
  2: type3
```

字段说明：

- `path`：可选，数据集根路径。zip 导入时推荐使用 `.` 或省略，避免写入本机绝对路径。
- `train`：训练集图像路径。
- `val`：验证集图像路径。
- `test`：测试集图像路径，可选。
- `names`：类别编号与类别名称映射，可为列表或 `{id: name}` 字典。

`train / val / test` 支持字符串路径、图片列表 `.txt` 或字符串数组。标准结构推荐直接使用 `images/train`、`images/val`、`images/test`。

## 图像文件要求

YOLO detection 标准导入图片只支持以下扩展名：

```text
.jpg
.jpeg
.png
.bmp
```

图像文件要求：

- 文件能够正常读取。
- 文件内容与扩展名一致。
- 图像具有有效宽度和高度。
- 图像文件不为空或损坏。
- 图像与标注文件正确对应。
- 图像存放在正确的 split 目录中。
- train、val、test 之间不存在重复样本。
- 同一来源的高度相似样本应放在同一个 split 中，避免数据泄漏。

`.webp / .tif / .tiff` 不属于当前 YOLO detection 标准导入图片格式。

## 标注文件要求

标注文件要求：

- 使用 UTF-8 或兼容的普通文本编码。
- 每行只描述一个目标。
- 每行必须包含 5 个字段。
- `class_id` 必须为非负整数。
- 坐标值必须是有限数字。
- 坐标必须采用归一化中心点格式。
- 不包含表头、注释或空字段。
- 不包含面积为零的边界框。
- 标注目标应与图像中的实际目标一致。

同一图像中可以存在多个相同类别或不同类别目标。

示例：

```text
0 0.250000 0.300000 0.200000 0.180000
0 0.600000 0.500000 0.150000 0.220000
1 0.800000 0.700000 0.100000 0.120000
```

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
- `test`：用于模型训练完成后的独立评估。

`valid` 目录名会在导入时归一化为 `val`。标准目录仍推荐使用 `val`。

## zip 包要求

导入接口只接受 zip 压缩包。zip 内可以包含一层或多层单目录包裹，导入器会连续消除单目录包裹后再识别数据集根目录。

推荐 zip 内结构：

```text
yolo-detection-dataset.zip
└─ dataset/
   ├─ images/
   ├─ labels/
   └─ data.yaml
```

或：

```text
yolo-detection-dataset.zip
├─ images/
├─ labels/
└─ data.yaml
```

zip 内文件路径必须是安全相对路径，不允许绝对路径和 `..`。

## DatasetVersion 结果

导入成功后生成的 DatasetVersion 满足：

- `task_type=detection`
- `categories` 为导入后的类别列表
- 每张图片对应一个 `DatasetSample`
- 每个目标对应一条 `DetectionAnnotation`
- 无目标图片保留为 annotations 为空的样本
- 标注 bbox 写为像素 `bbox_xywh`
- 样本 `split` 为 `train / val / test`
- 原始类别编号和类别名称写入 annotation metadata

## 导出和训练关系

YOLO detection DatasetVersion 当前可导出为：

```text
yolo-detection-v1
coco-detection-v1
voc-detection-v1
```

默认训练格式：

- `YOLOv8 / YOLO11 / YOLO26 detection`：默认使用 `yolo-detection-v1`，可使用 `coco-detection-v1`。
- `YOLOX detection`：默认使用 `coco-detection-v1`，可使用 `voc-detection-v1`。
- `RF-DETR detection`：使用 `coco-detection-v1`。

训练任务应消费 DatasetExport 的 `manifest_object_key` 或 `dataset_export_id`，不直接读取原始导入 zip。

## 完整示例

目录结构：

```text
dataset/
├─ images/
│  ├─ train/
│  │  ├─ image_001.jpg
│  │  └─ image_002.jpg
│  └─ val/
│     └─ image_101.png
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

names:
  0: type1
  1: type2
  2: type3
```

`labels/train/image_001.txt`：

```text
0 0.512500 0.437500 0.250000 0.300000
2 0.720000 0.610000 0.180000 0.220000
```

## 不符合规范的结构

### 图像与标注文件名不一致

```text
images/train/image_001.jpg
labels/train/label_001.txt
```

图像与标注无法通过基础文件名正确对应。

### 图像与标注 split 不一致

```text
images/train/image_001.jpg
labels/val/image_001.txt
```

图像和标注所属 split 不一致。

### 使用像素坐标

```text
0 320 240 100 80
```

YOLO detection 标注必须使用归一化坐标。

### 使用左上角和右下角格式

```text
0 x_min y_min x_max y_max
```

该格式不是 YOLO detection 标准边界框格式。

### 类别编号超出范围

类别仅定义为：

```text
0: type1
1: type2
```

标注中出现：

```text
2 0.5 0.5 0.2 0.2
```

类别编号 `2` 不存在。

### 坐标超出有效范围

```text
0 1.2 0.5 0.3 0.3
```

`x_center` 超出归一化坐标范围。

### 边界框超出图像范围

```text
0 0.95 0.50 0.20 0.30
```

该标注的横向范围为：

```text
x_min = 0.95 - 0.20 / 2 = 0.85
x_max = 0.95 + 0.20 / 2 = 1.05
```

由于 `x_max > 1`，边界框超出图像范围。

### 标注字段数量错误

```text
0 0.5 0.5 0.2
```

该行只有 4 个字段，不符合 5 字段格式要求。

### 类别编号不是整数

```text
1.5 0.5 0.5 0.2 0.2
```

`class_id` 必须为整数。

### 边界框宽度或高度无效

```text
0 0.5 0.5 0 0.2
```

边界框宽度为 0，属于无效标注。

### 使用不支持的图片格式

```text
images/train/image_001.webp
images/train/image_002.tiff
```

当前 YOLO detection 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。

## 标准定义总结

YOLO 目标检测数据集推荐结构：

```text
数据集根目录/
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

- 类别编号从 `0` 开始并保持连续。
- 标注中的类别编号必须存在于 `names`。
- 每一行只表示一个目标。
- 一张图像可以包含多行标注。
- bbox 使用归一化中心点 `xywh`。
- 不使用像素坐标。
- 不使用 `x_min y_min x_max y_max`。
- 图像与标注文件基础文件名一致。
- `images/train` 对应 `labels/train`。
- `images/val` 对应 `labels/val`。
- `images/test` 对应 `labels/test`。
- 无目标图像推荐使用空 txt 标注文件。
- train、val、test 之间不得存在重复样本。
- 导入图片只支持 `.jpg / .jpeg / .png / .bmp`。

## 相关文档

- [imports.md](imports.md)
- [model-contract.md](model-contract.md)
- [exports.md](exports.md)
