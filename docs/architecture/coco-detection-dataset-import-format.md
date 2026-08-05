# COCO 目标检测数据集导入格式规范

## 文档目的

本文档定义平台当前 COCO 矩形边界框目标检测数据集的标准导入目录、JSON 结构、字段规则、类别映射、图片要求和不符合规范的结构。

本文档只覆盖目标检测 detection，不覆盖实例分割 segmentation、姿态估计 pose 和语义分割 semantic segmentation。COCO segmentation 与 COCO pose 分别维护独立导入格式规范。

## 适用范围

当前 COCO 目标检测导入格式对应 DatasetImport 的：

- `task_type=detection`
- `format_type=coco`

可复用该 detection DatasetVersion 的模型：

- `YOLOX detection`
- `YOLOv8 detection`
- `YOLO11 detection`
- `YOLO26 detection`
- `RF-DETR detection`

COCO detection 是 YOLOX 和 RF-DETR detection 的默认训练导出格式。YOLOv8 / YOLO11 / YOLO26 detection 可以从同一份 DatasetVersion 导出为 `yolo-detection-v1` 后训练，也可以按后端能力使用 `coco-detection-v1`。

## 核心定义

COCO 目标检测数据集中，一张图像可以包含零个、一个或多个目标。图像、目标和类别统一记录在 JSON 文件中，通过 id 建立关联关系。

目标检测核心 JSON 字段为：

```text
images
annotations
categories
```

边界框格式固定为：

```text
[x_min, y_min, width, height]
```

坐标单位为像素，不使用归一化坐标。

## 标准目录结构

平台推荐使用 `images/{split}` 与 `annotations/instances_{split}.json` 的目录结构：

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
└─ annotations/
   ├─ instances_train.json
   ├─ instances_val.json
   └─ instances_test.json
```

目录含义：

- `images`：图像文件目录。
- `annotations`：COCO JSON 标注文件目录。
- `train`：训练集目录。
- `val`：验证集目录。
- `test`：测试集目录，可选。
- `instances_train.json`：训练集标注文件。
- `instances_val.json`：验证集标注文件。
- `instances_test.json`：测试集标注文件，可选。

## 最小标准目录结构

```text
dataset/
├─ images/
│  ├─ train/
│  └─ val/
└─ annotations/
   ├─ instances_train.json
   └─ instances_val.json
```

训练集和验证集是标准 detection 数据集的基本组成部分。测试集可选。

## 兼容目录结构

当前导入器也支持常见 COCO 导出目录。

### 年份后缀目录

```text
dataset/
├─ annotations/
│  ├─ instances_train2017.json
│  └─ instances_val2017.json
├─ train2017/
└─ val2017/
```

### split 内 manifest 目录

```text
dataset/
├─ train/
│  ├─ train-001.jpg
│  └─ _annotations.coco.json
├─ valid/
│  ├─ valid-001.jpg
│  └─ _annotations.coco.json
└─ test/
   ├─ test-001.jpg
   └─ _annotations.coco.json
```

`valid` 在导入后统一归一化为 `val`。

标准导入包推荐使用 `images/{split}` 与 `annotations/instances_{split}.json`，便于长期维护和人工检查。

## JSON 基本结构

COCO detection JSON 通常包含以下字段：

```json
{
  "info": {},
  "licenses": [],
  "images": [],
  "annotations": [],
  "categories": []
}
```

字段说明：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `info` | 否 | 数据集说明信息 |
| `licenses` | 否 | 图像许可证信息 |
| `images` | 是 | 图像信息列表 |
| `annotations` | 是 | 目标标注列表 |
| `categories` | 是 | 类别定义列表 |

普通目标检测导入只要求 `images / annotations / categories` 三个数组。`info` 和 `licenses` 会作为原始元数据保留。

## 图像信息定义

`images` 字段记录数据集中的图像。

示例：

```json
{
  "images": [
    {
      "id": 1,
      "file_name": "image_001.jpg",
      "width": 1000,
      "height": 800
    },
    {
      "id": 2,
      "file_name": "val/image_101.png",
      "width": 1280,
      "height": 720
    }
  ]
}
```

图像对象字段：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `id` | 是 | 图像唯一编号 |
| `file_name` | 是 | 图像文件名或相对路径 |
| `width` | 是 | 图像宽度，单位为像素 |
| `height` | 是 | 图像高度，单位为像素 |

规则：

- `images.id` 在当前 JSON 文件中必须唯一。
- `file_name` 可以是纯文件名，也可以是相对路径。
- `file_name` 不得是 zip 外部绝对路径。
- `width` 和 `height` 必须为正整数。
- JSON 中的 `width / height` 应与实际图像尺寸一致。

导入器解析图片路径时，优先按 `file_name` 自带相对路径定位；若无法定位，再按 manifest 所属 split 的图像目录定位。

## 类别定义

`categories` 字段记录目标类别。

示例：

```json
{
  "categories": [
    {
      "id": 1,
      "name": "type1",
      "supercategory": "object"
    },
    {
      "id": 2,
      "name": "type2",
      "supercategory": "object"
    }
  ]
}
```

类别对象字段：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `id` | 是 | 类别唯一编号 |
| `name` | 是 | 类别名称 |
| `supercategory` | 否 | 上级类别名称 |

规则：

- `categories.id` 在当前 JSON 文件中必须唯一。
- `categories.name` 应唯一、稳定，且不包含前导或尾随空格。
- COCO 常见类别编号从 1 开始，但本项目不要求必须从 1 开始。
- `annotations.category_id` 必须引用 `categories.id` 中已存在的编号。
- 不应根据 `categories` 数组位置推断类别编号。

导入后 DatasetVersion 会把类别重排为连续 0-based `category_id`，并在 metadata 中保留原始 `source_category_id`、`source_category_name` 和 `supercategory`。

## 目标标注定义

`annotations` 字段记录图像中的目标。每个目标对应一个 annotation 对象。

示例：

```json
{
  "annotations": [
    {
      "id": 1,
      "image_id": 1,
      "category_id": 1,
      "bbox": [200, 160, 400, 400],
      "area": 160000,
      "iscrowd": 0
    },
    {
      "id": 2,
      "image_id": 1,
      "category_id": 2,
      "bbox": [650, 300, 180, 220],
      "area": 39600,
      "iscrowd": 0
    }
  ]
}
```

标注对象字段：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `id` | 推荐 | 标注对象唯一编号 |
| `image_id` | 是 | 对应图像编号 |
| `category_id` | 是 | 对应类别编号 |
| `bbox` | 是 | 目标边界框 |
| `area` | 推荐 | 目标区域面积 |
| `iscrowd` | 推荐 | 是否为群体目标 |

规则：

- `annotations.image_id` 必须引用 `images.id` 中已存在的编号。
- `annotations.category_id` 必须引用 `categories.id` 中已存在的编号。
- `annotations.id` 若存在，在当前 JSON 文件中必须唯一。
- `area` 若缺失，导入器可按 `bbox` 的 `width * height` 计算。
- `iscrowd` 若缺失，导入器按 `0` 处理。
- `segmentation / keypoints / num_keypoints` 若存在，detection 导入只作为原始 metadata 保留，不写入 detection 通用字段。

## 边界框格式

COCO detection 边界框格式为：

```text
[x_min, y_min, width, height]
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `x_min` | 边界框左上角横坐标 |
| `y_min` | 边界框左上角纵坐标 |
| `width` | 边界框宽度 |
| `height` | 边界框高度 |

坐标单位为像素。

示例：

```json
"bbox": [200, 160, 400, 400]
```

表示：

```text
x_min = 200
y_min = 160
width = 400
height = 400
x_max = 200 + 400 = 600
y_max = 160 + 400 = 560
```

COCO detection 的 `bbox` 不是以下格式：

```text
[x_min, y_min, x_max, y_max]
```

也不是 YOLO 归一化中心点格式：

```text
[x_center, y_center, width, height]
```

导入后，平台会把 COCO `bbox` 写入 DatasetVersion 内部使用的像素 `bbox_xywh`。

## 坐标规则

假设图像尺寸为：

```text
W = 图像宽度
H = 图像高度
```

边界框应满足：

```text
0 <= x_min < W
0 <= y_min < H
width > 0
height > 0
x_min + width <= W
y_min + height <= H
```

平台导入校验会把越界、宽高无效和非数值 bbox 记录为 validation error。

## 面积规则

`area` 表示目标区域面积，单位为平方像素。

普通矩形框目标检测数据可按以下方式计算：

```text
area = width * height
```

若 JSON 中包含 `segmentation`，`area` 可以表示分割区域面积，不一定等于 bbox 面积。当前 detection 导入不依赖 `area` 反推 bbox。

## 群体目标规则

`iscrowd` 表示是否为群体目标：

```text
0 = 普通独立目标
1 = 群体目标
```

普通 detection 数据推荐设置为 `0`。当前 detection 导入会保留 `iscrowd` 到 annotation metadata，训练导出时按目标格式能力决定是否继续输出。

## 对象关联关系

COCO detection 通过编号建立关系：

```text
images.id
annotations.image_id
annotations.category_id
categories.id
```

示例：

```json
{
  "images": [
    {
      "id": 1,
      "file_name": "image_001.jpg",
      "width": 1000,
      "height": 800
    }
  ],
  "categories": [
    {
      "id": 2,
      "name": "type2"
    }
  ],
  "annotations": [
    {
      "id": 10,
      "image_id": 1,
      "category_id": 2,
      "bbox": [200, 160, 400, 400],
      "area": 160000,
      "iscrowd": 0
    }
  ]
}
```

该标注表示：

- 目标位于 `id=1` 的图像中。
- 目标类别为 `id=2` 的 `type2`。
- 目标框左上角为 `(200, 160)`。
- 目标框宽高为 `400 x 400`。

## 无目标图像

无目标图像仍应记录在 `images` 数组中，不需要创建 annotation。

示例：

```json
{
  "images": [
    {
      "id": 3,
      "file_name": "image_003.jpg",
      "width": 1000,
      "height": 800
    }
  ],
  "annotations": [],
  "categories": [
    {
      "id": 1,
      "name": "type1"
    }
  ]
}
```

COCO detection 不需要为空图像创建空标注文件。

## split 推断规则

平台按以下顺序推断 split：

- 若 manifest 位于 `train / val / valid / test` 目录下，优先使用父目录名。
- `valid` 统一归一化为 `val`。
- 若 manifest 位于 `annotations` 目录下，优先从文件名中的 `train / val / test` 推断。
- `instances_train2017.json` 归入 `train`。
- `instances_val2017.json` 归入 `val`。
- 若只有一个 manifest 且无法从路径或文件名推断 split，则按显式导入参数处理；未显式提供时默认归入 `train`。

同一图片不得同时出现在多个 split manifest 中。

## 图像文件要求

COCO detection 标准导入图片只支持以下扩展名：

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
- JSON 中记录的 `width / height` 与实际图像一致。
- `images.file_name` 能够定位 zip 内的图像文件。
- 图像文件不为空、不损坏。
- 训练集、验证集和测试集之间不存在重复样本。
- 同一来源的高度相似样本应放在同一个数据划分中。

`.webp / .tif / .tiff` 不属于当前 COCO detection 标准导入图片格式。

## 标注文件要求

COCO JSON 标注文件应满足：

- 文件为合法 JSON。
- 推荐使用 UTF-8 编码。
- 顶层 `images / annotations / categories` 必须为数组。
- `images.id` 在当前 JSON 文件中唯一。
- `categories.id` 在当前 JSON 文件中唯一。
- `annotations.id` 若存在，在当前 JSON 文件中唯一。
- 所有 `annotations.image_id` 必须能映射到 `images.id`。
- 所有 `annotations.category_id` 必须能映射到 `categories.id`。
- `bbox` 必须是长度为 4 的数值数组。
- `bbox` 的 `width / height` 必须大于 0。
- `bbox` 不应超出图像范围。
- 不应包含重复或无效标注。

## 数据划分要求

训练集、验证集和测试集应相互独立：

```text
train ∩ val = ∅
train ∩ test = ∅
val ∩ test = ∅
```

每个 split 的 JSON 文件只记录对应 split 的图像和标注。测试集可不包含公开标注；若用于平台内部评估，应提供对应的测试标注文件。

## zip 包要求

当前阶段默认通过 FastAPI 上传 zip 数据集压缩包。

zip 包应满足：

- zip 内允许存在一层额外包裹目录。
- 图片和标注文件必须位于 zip 内部。
- JSON 中的 `file_name` 不得指向 zip 外绝对路径。
- 不应包含同名但大小写不同的图片路径。
- 不应混入 classification、segmentation、pose、obb 等其他任务的独立标注格式。
- 不应混入不受支持的图片扩展名。

## DatasetVersion 结果

导入成功后生成的 DatasetVersion 满足：

- `task_type=detection`。
- `source_format=coco`。
- 图像按 `train / val / test` split 归档。
- 类别映射统一为连续 0-based 内部 category id。
- bbox 统一保存为像素 `bbox_xywh`。
- 原始 `images.id / annotations.id / categories.id` 保留在 metadata 中。
- `iscrowd / area / supercategory / segmentation / keypoints` 等非核心 detection 字段按原始 metadata 保留。

## 导出和训练关系

COCO detection DatasetVersion 当前可导出为：

```text
coco-detection-v1
yolo-detection-v1
voc-detection-v1
```

模型默认训练格式：

- `YOLOX detection`：默认使用 `coco-detection-v1`，可使用 `voc-detection-v1`。
- `RF-DETR detection`：使用 `coco-detection-v1`。
- `YOLOv8 / YOLO11 / YOLO26 detection`：默认使用 `yolo-detection-v1`，可使用 `coco-detection-v1`。

导入格式不等同于训练格式。同一份 COCO detection 导入数据先生成 DatasetVersion，再按训练任务需要导出为对应格式。

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
└─ annotations/
   ├─ instances_train.json
   └─ instances_val.json
```

`annotations/instances_train.json`：

```json
{
  "info": {
    "description": "Object detection dataset",
    "version": "1.0"
  },
  "licenses": [],
  "images": [
    {
      "id": 1,
      "file_name": "image_001.jpg",
      "width": 1000,
      "height": 800
    },
    {
      "id": 2,
      "file_name": "image_002.png",
      "width": 1280,
      "height": 720
    }
  ],
  "categories": [
    {
      "id": 1,
      "name": "type1",
      "supercategory": "object"
    },
    {
      "id": 2,
      "name": "type2",
      "supercategory": "object"
    }
  ],
  "annotations": [
    {
      "id": 1,
      "image_id": 1,
      "category_id": 1,
      "bbox": [200, 160, 400, 400],
      "area": 160000,
      "iscrowd": 0
    },
    {
      "id": 2,
      "image_id": 1,
      "category_id": 2,
      "bbox": [650, 300, 180, 220],
      "area": 39600,
      "iscrowd": 0
    }
  ]
}
```

`image_001.jpg` 中包含两个目标，`image_002.png` 是无目标图像。

## 不符合规范的结构

### 使用错误的边界框格式

```json
"bbox": [200, 160, 600, 560]
```

若最后两个值表示 `x_max / y_max`，则不符合 COCO detection 格式。

### 使用归一化坐标

```json
"bbox": [0.2, 0.2, 0.4, 0.5]
```

COCO detection bbox 使用像素坐标，不使用 0 到 1 的归一化坐标。

### 图像编号不存在

```json
{
  "id": 1,
  "image_id": 99,
  "category_id": 1,
  "bbox": [100, 100, 200, 200]
}
```

当 `images` 中不存在 `id=99` 的图像时，该标注无法关联到有效图像。

### 类别编号不存在

```json
{
  "id": 1,
  "image_id": 1,
  "category_id": 4,
  "bbox": [100, 100, 200, 200]
}
```

当 `categories` 中不存在 `id=4` 的类别时，该标注无法关联到有效类别。

### 图像尺寸记录错误

实际图像尺寸：

```text
1000 x 800
```

JSON 中记录：

```json
{
  "id": 1,
  "file_name": "image_001.jpg",
  "width": 800,
  "height": 600
}
```

JSON 尺寸与实际图像尺寸不一致。

### 边界框超出图像范围

图像宽度为 `1000`，标注为：

```json
"bbox": [900, 200, 200, 300]
```

由于 `900 + 200 > 1000`，该边界框超出图像范围。

### 标注编号重复

```json
{
  "annotations": [
    {
      "id": 1,
      "image_id": 1,
      "category_id": 1,
      "bbox": [100, 100, 200, 200]
    },
    {
      "id": 1,
      "image_id": 1,
      "category_id": 1,
      "bbox": [300, 300, 100, 100]
    }
  ]
}
```

同一 JSON 文件中的标注编号应唯一。

### 使用不支持的图片格式

```text
images/train/image_001.webp
images/train/image_002.tiff
```

当前 COCO detection 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。

### file_name 指向 zip 外路径

```json
{
  "id": 1,
  "file_name": "D:/datasets/images/image_001.jpg",
  "width": 1000,
  "height": 800
}
```

导入包中的 `file_name` 必须能在 zip 内定位图片，不接受 zip 外绝对路径。

## 标准定义总结

COCO 目标检测数据集推荐结构为：

```text
dataset/
├─ images/
│  ├─ train/图像文件
│  ├─ val/图像文件
│  └─ test/图像文件
└─ annotations/
   ├─ instances_train.json
   ├─ instances_val.json
   └─ instances_test.json
```

核心规则：

- 导入任务固定为 `task_type=detection`、`format_type=coco`。
- JSON 核心字段为 `images / annotations / categories`。
- `images.id / annotations.image_id` 建立图像与目标关系。
- `categories.id / annotations.category_id` 建立类别与目标关系。
- bbox 格式为 `[x_min, y_min, width, height]`。
- bbox 坐标使用像素单位，不使用归一化坐标。
- 无目标图像只需记录在 `images` 中。
- 导入图片只支持 `.jpg / .jpeg / .png / .bmp`。
- 导入后生成 DatasetVersion，再按训练任务导出为 `coco-detection-v1 / yolo-detection-v1 / voc-detection-v1`。

## 相关文档

- [classification-dataset-import-format.md](classification-dataset-import-format.md)
- [coco-segmentation-dataset-import-format.md](coco-segmentation-dataset-import-format.md)
- [coco-pose-dataset-import-format.md](coco-pose-dataset-import-format.md)
- [yolo-detection-dataset-import-format.md](yolo-detection-dataset-import-format.md)
- [model-dataset-format-contract.md](model-dataset-format-contract.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)
