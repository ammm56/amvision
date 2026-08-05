# YOLO 实例分割数据集导入格式规范

## 文档目的

本文档定义平台当前 YOLO polygon 实例分割数据集的标准导入目录、配置文件、标注行、类别映射、图片要求和不符合规范的结构。

本文档只覆盖实例分割 segmentation，不覆盖目标检测 detection、语义分割 semantic segmentation、姿态估计 pose 和 OBB 旋转框检测。

## 适用范围

当前 YOLO 实例分割导入格式对应 DatasetImport 的：

- `task_type=segmentation`
- `format_type=yolo`

可复用该 segmentation DatasetVersion 的模型：

- `YOLOv8 segmentation`
- `YOLO11 segmentation`
- `YOLO26 segmentation`

RF-DETR segmentation 默认使用 COCO instance segmentation 导出格式。YOLOX 当前不作为平台公开 segmentation 训练能力。

## 核心定义

YOLO 实例分割数据集中，一张图像可以包含零个、一个或多个目标实例。每个目标实例用一行文本表示，包含类别编号和归一化 polygon 顶点。

标签行格式固定为：

```text
class_id x1 y1 x2 y2 x3 y3 ... xn yn
```

其中 `x1 y1 ... xn yn` 为相对图像宽高归一化后的 polygon 顶点坐标。导入后平台会转换为像素 polygon。

实例分割 segmentation 与语义分割 semantic segmentation 不同。YOLO segmentation 使用每个实例一条 polygon；semantic segmentation 通常使用像素级 mask 或类别值图。

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
- `labels`：YOLO polygon 标注文件目录。
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

训练集和验证集是标准 segmentation 数据集的基本组成部分。测试集可选。

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

每个 txt 标注文件对应一张图像。每一行表示一个目标实例：

```text
class_id x1 y1 x2 y2 x3 y3 ... xn yn
```

示例：

```text
0 0.200000 0.200000 0.600000 0.180000 0.650000 0.500000 0.400000 0.700000 0.180000 0.500000
1 0.700000 0.300000 0.850000 0.320000 0.880000 0.600000 0.720000 0.650000
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `class_id` | 目标类别编号，从 0 开始 |
| `x1, y1` | polygon 第 1 个顶点的归一化坐标 |
| `x2, y2` | polygon 第 2 个顶点的归一化坐标 |
| `...` | 中间顶点的归一化坐标 |
| `xn, yn` | polygon 最后一个顶点的归一化坐标 |

字段使用一个或多个空白字符分隔。标注文件不应包含表头、注释或无关字段。

## polygon 点数要求

每个目标实例至少应包含三个顶点：

```text
class_id x1 y1 x2 y2 x3 y3
```

因此，每行至少包含 7 个字段：

- 1 个类别字段。
- 3 组坐标点。
- 共 6 个坐标字段。

类别字段之后的坐标数量必须为偶数。不同实例可以使用不同数量的 polygon 顶点。

## 坐标规则

YOLO segmentation 坐标全部按 0 到 1 的归一化坐标读取。

归一化规则：

```text
x_normalized = x_pixel / image_width
y_normalized = y_pixel / image_height
```

每个坐标应满足：

```text
0 <= xi <= 1
0 <= yi <= 1
```

导入后，平台会把归一化 polygon 转换为像素 polygon：

```text
x_pixel = x_normalized * image_width
y_pixel = y_normalized * image_height
```

DatasetVersion 会同时保存：

- `segmentation`：像素 polygon。
- `bbox_xywh`：由 polygon 外接水平框计算出的 bbox。
- `area`：polygon 面积。

## 坐标计算示例

假设图像尺寸为：

```text
width = 1000
height = 800
```

某个实例的像素 polygon 为：

```text
P1 = (200, 160)
P2 = (600, 160)
P3 = (650, 560)
P4 = (180, 520)
```

归一化后为：

```text
P1 = (0.20, 0.20)
P2 = (0.60, 0.20)
P3 = (0.65, 0.70)
P4 = (0.18, 0.65)
```

若类别编号为 `1`，标注行为：

```text
1 0.20 0.20 0.60 0.20 0.65 0.70 0.18 0.65
```

## 顶点顺序规则

同一实例的顶点应沿目标轮廓依次排列。可以统一使用顺时针或逆时针方向，但同一数据集应保持一致。

标注文件通常不需要重复写入第一个顶点。训练和导入程序会把最后一个点与第一个点连接形成闭合 polygon。

polygon 应满足：

- 至少包含三个不同顶点。
- 顶点顺序不得形成自交 polygon。
- polygon 面积必须大于 0。
- 不应在同一行混合多个互不相连的区域。

## 类别定义

类别编号应从 `0` 开始，并保持连续。

示例：

```text
0: type1
1: type2
2: type3
```

类别数量为 `N` 时，合法类别编号范围为：

```text
0 <= class_id <= N - 1
```

标注文件中的 `class_id` 必须存在于 `data.yaml` 的 `names` 中。导入后 DatasetVersion 会把类别重排为连续 0-based `category_id`，并在 metadata 中保留原始 `source_class_id` 和 `source_class_name`。

## data.yaml 规则

标准导入包推荐在根目录提供 `data.yaml`：

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

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `path` | 否 | 数据集根目录 |
| `train` | 是 | 训练集图像路径 |
| `val` | 是 | 验证集图像路径 |
| `test` | 否 | 测试集图像路径 |
| `names` | 是 | 类别编号到类别名称的映射 |

`names` 支持列表或字典：

```yaml
names:
  - type1
  - type2
```

```yaml
names:
  0: type1
  1: type2
```

zip 包内推荐使用 `path: .` 或省略 `path`，避免指向本机绝对路径。`train / val / test` 可以是图像目录、图片文件路径、图片列表 `.txt`，或字符串数组。标准数据集推荐使用 `images/{split}` 目录。

## 图像文件要求

YOLO segmentation 标准导入图片只支持以下扩展名：

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

`.webp / .tif / .tiff` 不属于当前 YOLO segmentation 标准导入图片格式。

## 标注文件要求

YOLO segmentation txt 标注文件应满足：

- 推荐使用 UTF-8 编码。
- 每个文件只对应一张图像。
- 每个目标实例占一行。
- 每行第一个字段为类别编号。
- 类别编号必须为非负整数。
- 类别编号必须存在于类别定义中。
- 类别编号后必须包含成对的坐标字段。
- 每个实例至少包含三个顶点。
- 所有坐标必须为有限数值。
- 所有坐标必须位于 0 到 1。
- 顶点应沿轮廓依次排列。
- polygon 不得自交。
- polygon 面积必须大于 0。
- 不应包含重复实例或重复轮廓。

## 分离区域与孔洞

标准 YOLO polygon 标注行通常表示一个连续外轮廓。

若一个实例由多个彼此分离的区域组成，或内部存在孔洞，YOLO polygon 格式不能稳定无损表达。此类数据应优先保留 COCO instance segmentation 或 mask 原始标注，并在转换为 YOLO 前做可视化检查。

平台导入 YOLO segmentation 时，会按每一行读取为一个实例 polygon，不把一行解释为多个独立区域。

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
- 不应混入 detection、pose、obb、semantic segmentation 等其他任务的独立标注格式。
- 不应混入不受支持的图片扩展名。

## DatasetVersion 结果

导入成功后生成的 DatasetVersion 满足：

- `task_type=segmentation`。
- `source_format=yolo`。
- 图像按 `train / val / test` split 归档。
- 类别映射统一为连续 0-based 内部 category id。
- 每个实例保存像素 polygon segmentation。
- 每个实例同时保存由 polygon 计算出的 `bbox_xywh`。
- 原始 `source_class_id` 和 `source_class_name` 保留到 metadata。

## 导出和训练关系

YOLO segmentation DatasetVersion 当前可导出为：

```text
yolo-instance-seg-v1
coco-instance-seg-v1
```

模型默认训练格式：

- `YOLOv8 segmentation`：默认使用 `yolo-instance-seg-v1`，可使用 `coco-instance-seg-v1`。
- `YOLO11 segmentation`：默认使用 `yolo-instance-seg-v1`，可使用 `coco-instance-seg-v1`。
- `YOLO26 segmentation`：默认使用 `yolo-instance-seg-v1`，可使用 `coco-instance-seg-v1`。
- `RF-DETR segmentation`：使用 `coco-instance-seg-v1`。

导入格式不等同于训练格式。同一份 YOLO segmentation 导入数据先生成 DatasetVersion，再按训练任务需要导出为对应格式。

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

names:
  0: type1
  1: type2
```

`labels/train/image_001.txt`：

```text
0 0.200000 0.200000 0.600000 0.180000 0.650000 0.500000 0.400000 0.700000 0.180000 0.500000
1 0.700000 0.300000 0.850000 0.320000 0.880000 0.600000 0.720000 0.650000
```

`labels/train/image_002.txt` 可以为空，表示无目标图像。

## 不符合规范的结构

### 图像与标注文件名不一致

```text
images/train/image_001.jpg
labels/train/label_001.txt
```

图像与标注无法通过基础文件名正确对应。

### 使用检测框格式

```text
0 0.5 0.5 0.4 0.3
```

该格式表示 `class_id x_center y_center width height`，属于 YOLO detection bbox，不是 YOLO segmentation polygon。

### 使用像素坐标

```text
0 200 160 600 160 650 560 180 520
```

YOLO segmentation 要求使用归一化坐标，不直接使用像素坐标。

### 顶点数量不足

```text
0 0.2 0.2 0.6 0.2
```

该标注只有两个顶点，无法形成有效 polygon。

### 坐标字段不成对

```text
0 0.2 0.2 0.6 0.2 0.5
```

最后一个坐标缺少对应的 `y` 值。

### 类别编号不存在

类别定义为：

```text
0: type1
1: type2
```

标注中出现：

```text
2 0.2 0.2 0.6 0.2 0.5 0.6
```

类别编号 `2` 未定义。

### 坐标超出范围

```text
0 0.2 0.2 1.2 0.3 0.5 0.7
```

其中一个横坐标为 `1.2`，超出归一化范围。

### polygon 自交

```text
0 0.2 0.2 0.7 0.7 0.7 0.2 0.2 0.7
```

顶点顺序形成交叉 polygon。

### polygon 面积为零

```text
0 0.2 0.2 0.4 0.4 0.6 0.6
```

三个点位于同一直线上，不能形成有效区域。

### 使用不支持的图片格式

```text
images/train/image_001.webp
images/train/image_002.tiff
```

当前 YOLO segmentation 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。

## 与目标检测格式的区别

YOLO detection 标注格式：

```text
class_id x_center y_center width height
```

YOLO segmentation 标注格式：

```text
class_id x1 y1 x2 y2 ... xn yn
```

主要区别：

| 项目 | detection | segmentation |
| --- | --- | --- |
| 目标位置 | 矩形边界框 | polygon 轮廓 |
| 坐标数量 | 固定 4 个 | 至少 6 个，数量可变 |
| 单行字段数 | 固定 5 个 | 至少 7 个 |
| 坐标范围 | 0 到 1 | 0 到 1 |
| 每行含义 | 一个目标框 | 一个实例轮廓 |

## 标准定义总结

YOLO 实例分割数据集推荐结构为：

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

- 导入任务固定为 `task_type=segmentation`、`format_type=yolo`。
- 每张图像推荐对应一个同名 TXT 标注文件。
- 每个目标实例占一行。
- 标注格式为 `class_id x1 y1 x2 y2 ... xn yn`。
- 类别编号从 `0` 开始，并在 `data.yaml` 的 `names` 中定义。
- 每个实例至少包含三个顶点。
- 坐标必须成对出现。
- 坐标必须归一化到 0 到 1。
- 顶点应沿目标轮廓依次排列。
- polygon 不得自交或退化。
- 一张图像可以包含多个实例，同类别不同实例必须分别占行。
- 无目标图像推荐使用空 TXT 文件。
- 导入图片只支持 `.jpg / .jpeg / .png / .bmp`。
- 导入后生成 DatasetVersion，再按训练任务导出为 `yolo-instance-seg-v1 / coco-instance-seg-v1`。

## 相关文档

- [classification-dataset-import-format.md](classification-dataset-import-format.md)
- [coco-detection-dataset-import-format.md](coco-detection-dataset-import-format.md)
- [voc-detection-dataset-import-format.md](voc-detection-dataset-import-format.md)
- [yolo-detection-dataset-import-format.md](yolo-detection-dataset-import-format.md)
- [dota-obb-dataset-import-format.md](dota-obb-dataset-import-format.md)
- [model-dataset-format-contract.md](model-dataset-format-contract.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)
