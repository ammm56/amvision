# DOTA OBB 数据集导入格式规范

## 文档目的

本文档定义平台当前 DOTA 风格旋转框数据集的标准导入目录、TXT 标注行、类别映射、图片要求和不符合规范的结构。

本文档覆盖 OBB 旋转框任务。DOTA 在平台中归入 `obb` task type，不归入普通 `detection` task type。普通 detection 使用水平矩形框，OBB 使用四点 polygon 表示任意方向目标。

## 适用范围

当前 DOTA OBB 导入格式对应 DatasetImport 的：

- `task_type=obb`
- `format_type=dota`

可复用该 OBB DatasetVersion 的模型：

- `YOLOv8 obb`
- `YOLO11 obb`
- `YOLO26 obb`

YOLOX 和 RF-DETR 当前不作为平台公开 OBB 训练能力。

## 核心定义

DOTA OBB 数据集中，一张图像可以包含零个、一个或多个旋转目标。每个目标使用四个顶点表示，顶点坐标使用像素单位。

标准标注行格式为：

```text
x1 y1 x2 y2 x3 y3 x4 y4 class_name [difficult]
```

其中前 8 个字段为四个顶点坐标，`class_name` 为类别名称，`difficult` 为可选困难目标标记。

## 标准目录结构

平台标准导入目录使用 `images/{split}` 与 `labels/{split}`：

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
└─ labels/
   ├─ train/
   │  ├─ image_001.txt
   │  └─ ...
   ├─ val/
   │  ├─ image_101.txt
   │  └─ ...
   └─ test/
      ├─ image_201.txt
      └─ ...
```

目录含义：

- `images`：图像文件目录。
- `labels`：DOTA TXT 标注目录。
- `train`：训练集目录。
- `val`：验证集目录。
- `test`：测试集目录，可选。

平台也支持 `labels/{split}_original`：

```text
dataset/
├─ images/
│  ├─ train/
│  └─ val/
└─ labels/
   ├─ train_original/
   └─ val_original/
```

若同时存在 `labels/{split}_original` 和 `labels/{split}`，导入器优先读取 `labels/{split}_original`。

## 最小标准目录结构

```text
dataset/
├─ images/
│  ├─ train/
│  └─ val/
└─ labels/
   ├─ train/
   └─ val/
```

训练集和验证集是标准 OBB 数据集的基本组成部分。测试集可选。

## 与外部 DOTA labelTxt 的关系

外部 DOTA 数据常见目录名为 `labelTxt`，例如：

```text
train/
├─ images/
└─ labelTxt/
```

当前平台标准导入目录统一使用根目录下的 `images/{split}` 与 `labels/{split}`。从外部工具导出的 `labelTxt` 数据进入平台前，应整理为：

```text
dataset/
├─ images/train/
└─ labels/train/
```

这样可以和 YOLO OBB、平台 DatasetVersion 与 DatasetExport 目录规则保持一致。

## 图像与标注对应关系

每张 train 和 val 图像必须对应一个同名 `.txt` 标注文件。

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

test split 可用于无公开标注数据。若 test 用于平台内部评估，应提供对应 label 文件。若 test 仅用于推理或提交结果生成，可以允许单张 test 图像缺少对应 label 文件。

## 标注文件格式

每个 TXT 文件对应一张图像。每一行表示一个 OBB 目标：

```text
x1 y1 x2 y2 x3 y3 x4 y4 class_name [difficult]
```

示例：

```text
200 160 600 180 580 560 180 540 type1 0
650 300 830 320 810 520 630 500 type2 1
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `x1, y1` | 第 1 个顶点的像素坐标 |
| `x2, y2` | 第 2 个顶点的像素坐标 |
| `x3, y3` | 第 3 个顶点的像素坐标 |
| `x4, y4` | 第 4 个顶点的像素坐标 |
| `class_name` | 目标类别名称 |
| `difficult` | 困难目标标记，可选 |

字段使用一个或多个空白字符分隔。`class_name` 不能包含空格。

## 坐标规则

坐标单位为像素，不使用归一化坐标。

假设图像尺寸为：

```text
W = 图像宽度
H = 图像高度
```

每个顶点应满足：

```text
0 <= xi < W
0 <= yi < H
```

其中 `i` 为 `1 / 2 / 3 / 4`。

四点 polygon 应满足：

- 四个顶点构成有效四边形。
- 四边形面积大于 0。
- 相邻顶点不得完全重合。
- 四边形边界不得自相交。
- 标注范围不应超出图像有效区域。

导入后 DatasetVersion 会同时保存：

- `polygon_xy`：原始四点 polygon。
- `bbox_xywh`：由 polygon 外接水平框计算出的 axis-aligned bbox。
- `area`：polygon 面积。

## 四点顺序规则

四个顶点应沿目标边界按统一方向排列，推荐使用顺时针顺序：

```text
P1 -> P2 -> P3 -> P4
```

示例：

```text
P1 = (200, 160)
P2 = (600, 180)
P3 = (580, 560)
P4 = (180, 540)
```

对应标注：

```text
200 160 600 180 580 560 180 540 type1 0
```

同一数据集中不应对同类目标随机选择起始点或随机改变顶点方向。起始点规则应在数据转换、训练和评估中保持一致。

## 类别定义

DOTA 标注行直接使用类别名称：

```text
type1
type2
type3
```

类别名称要求：

- 名称唯一。
- 拼写和大小写一致。
- 不包含前导或尾随空格。
- 不包含空白字符。
- 不为空字符串。
- 训练、验证、测试和部署阶段保持一致。

若类别名称需要多个词，建议使用下划线或连字符：

```text
type_group_1
type-group-2
```

导入后 DatasetVersion 会生成连续 0-based `category_id`。原始类别名称保留为 `source_class_name`。

## difficult 规则

`difficult` 是可选字段。未提供时按 `0` 处理。

支持取值：

```text
0 = 普通目标
1 = 困难目标
```

示例：

```text
200 160 600 180 580 560 180 540 type1 0
650 300 830 320 810 520 630 500 type2 1
```

当前导入器只接受 `0 / 1`。其他值会作为 validation error。

## 元数据行

DOTA TXT 可包含元数据行。当前导入器识别并忽略以下头部行：

```text
imagesource:source-name
gsd:0.5
```

这些行不作为目标标注。标准数据集可以省略元数据行。

其他未约定的元数据行不应混入目标标注文件，避免被误判为无效标注行。

## 无目标图像

无目标图像推荐提供同名空 TXT 文件：

```text
images/train/image_002.jpg
labels/train/image_002.txt
```

也可以只保留平台识别的 DOTA 元数据行：

```text
imagesource:source-name
gsd:0.5
```

train 和 val 图像不应缺少对应 label 文件。test 图像若用于无标注推理或提交结果生成，可以缺少对应 label 文件。

## 图像文件要求

DOTA OBB 标准导入图片只支持以下扩展名：

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

`.webp / .tif / .tiff` 不属于当前 DOTA OBB 标准导入图片格式。

## 标注文件要求

DOTA TXT 标注文件应满足：

- 推荐使用 UTF-8 编码。
- 每个文件只对应一张图像。
- 每个目标占一行。
- 每个目标标注至少包含 9 个字段。
- 前 8 个字段必须为有限数值。
- 第 9 个字段为有效类别名称。
- 第 10 个字段若存在，必须为 `0 / 1`。
- 四个顶点应按统一方向排列。
- 四边形不得自相交。
- 四边形面积必须大于 0。
- 坐标不应超出图像有效范围。
- 不应包含重复目标或重复 polygon。
- 元数据行与目标标注行应能够明确区分。

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
- `test`：用于模型训练完成后的独立评估或无标注推理，可选。

## zip 包要求

数据集通过 FastAPI 上传 zip 压缩包并异步导入。

zip 包应满足：

- zip 内允许存在一层额外包裹目录。
- `images` 和 `labels` 必须位于同一个数据集根目录下。
- `images/train` 和 `images/val` 应存在。
- `labels/train` 和 `labels/val` 应存在，或使用 `labels/train_original` 与 `labels/val_original`。
- train 和 val 图像必须有同名 label 文件。
- test split 可选；如提供 test 标注，推荐放在 `labels/test` 或 `labels/test_original`。
- 图片和标注文件必须位于 zip 内部。
- 不应包含同名但大小写不同的图片或 label 路径。
- 不应混入 classification、detection、segmentation、pose 等其他任务的独立标注格式。
- 不应混入不受支持的图片扩展名。

## DatasetVersion 结果

导入成功后生成的 DatasetVersion 满足：

- `task_type=obb`。
- `source_format=dota`。
- 图像按 `train / val / test` split 归档。
- 类别映射统一为连续 0-based 内部 category id。
- 每个 OBB annotation 保存 `polygon_xy`。
- 每个 OBB annotation 同时保存由 polygon 计算出的 `bbox_xywh`。
- 原始 `source_class_name` 和 `difficult` 保留到 metadata。

## 导出和训练关系

DOTA OBB DatasetVersion 当前可导出为：

```text
dota-obb-v1
```

模型默认训练格式：

- `YOLOv8 obb`：使用 `dota-obb-v1`。
- `YOLO11 obb`：使用 `dota-obb-v1`。
- `YOLO26 obb`：使用 `dota-obb-v1`。

导入格式不等同于训练格式。同一份 DOTA OBB 导入数据先生成 DatasetVersion，再按训练任务需要导出为对应格式。

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
└─ labels/
   ├─ train/
   │  ├─ image_001.txt
   │  └─ image_002.txt
   └─ val/
      └─ image_101.txt
```

`labels/train/image_001.txt`：

```text
imagesource:source-name
gsd:0.5
200 160 600 180 580 560 180 540 type1 0
650 300 830 320 810 520 630 500 type2 1
```

`labels/train/image_002.txt` 可以为空，表示无目标图像。

## 不符合规范的结构

### 使用 labelTxt 但未整理为平台标准目录

```text
dataset/
├─ train/
│  ├─ images/
│  └─ labelTxt/
└─ val/
   ├─ images/
   └─ labelTxt/
```

该结构是外部常见 DOTA 目录，但不是当前平台标准导入目录。进入平台前应整理为 `images/{split}` 与 `labels/{split}`。

### 图像与标注文件名不一致

```text
images/train/image_001.jpg
labels/train/label_001.txt
```

图像与标注无法通过基础文件名正确对应。

### train 或 val 图像缺少 label 文件

```text
images/train/image_001.jpg
labels/train/
```

train 和 val 图像必须提供同名 label 文件。无目标图像应提供空 label 文件或仅包含 DOTA 元数据行的 label 文件。

### 字段数量不足

```text
200 160 600 180 580 560 type1 0
```

该行不足 8 个顶点坐标字段，不符合 OBB polygon 标注要求。

### 使用中心点旋转框格式

```text
400 360 400 400 15 type1 0
```

该格式为 `x_center y_center width height angle`，不是 DOTA 四点 polygon 格式。

### 使用归一化坐标

```text
0.2 0.2 0.6 0.2 0.6 0.7 0.2 0.7 type1 0
```

DOTA OBB 使用像素坐标，不使用 0 到 1 的归一化坐标。

### 顶点顺序交叉

```text
200 160 580 560 600 180 180 540 type1 0
```

该顶点顺序可能形成自交四边形。

### 顶点超出图像范围

图像尺寸为：

```text
1000 x 800
```

标注为：

```text
900 600 1100 620 1080 900 880 880 type1 0
```

其中部分坐标超出图像范围。

### 类别名称无效

类别列表为：

```text
type1
type2
```

标注中出现：

```text
200 160 600 180 580 560 180 540 type3 0
```

`type3` 不在类别定义中。

### difficult 取值无效

```text
200 160 600 180 580 560 180 540 type1 unknown
```

`difficult` 必须为 `0 / 1`。

### 四边形面积为零

```text
200 160 300 160 400 160 500 160 type1 0
```

四个顶点位于同一直线上，无法形成有效目标区域。

### 使用不支持的图片格式

```text
images/train/image_001.webp
images/train/image_002.tiff
```

当前 DOTA OBB 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。

## 标准定义总结

DOTA OBB 数据集推荐结构为：

```text
dataset/
├─ images/
│  ├─ train/图像文件
│  ├─ val/图像文件
│  └─ test/图像文件
└─ labels/
   ├─ train/TXT 标注文件
   ├─ val/TXT 标注文件
   └─ test/TXT 标注文件
```

核心规则：

- 导入任务固定为 `task_type=obb`、`format_type=dota`。
- 每张 train 和 val 图像必须对应一个同名 TXT 标注文件。
- 每个目标占一行。
- 标注行格式为 `x1 y1 x2 y2 x3 y3 x4 y4 class_name [difficult]`。
- 前 8 个字段表示四个顶点的像素坐标。
- 坐标使用像素单位，不使用归一化坐标。
- 四边形不得自相交或退化，面积必须大于 0。
- `difficult` 可选，但若存在只能是 `0 / 1`。
- 可使用 `imagesource:` 和 `gsd:` 元数据行。
- 导入图片只支持 `.jpg / .jpeg / .png / .bmp`。
- 导入后生成 DatasetVersion，再按训练任务导出为 `dota-obb-v1`。

## 相关文档

- [classification-dataset-import-format.md](classification-dataset-import-format.md)
- [coco-detection-dataset-import-format.md](coco-detection-dataset-import-format.md)
- [voc-detection-dataset-import-format.md](voc-detection-dataset-import-format.md)
- [yolo-detection-dataset-import-format.md](yolo-detection-dataset-import-format.md)
- [model-dataset-format-contract.md](model-dataset-format-contract.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)
