# COCO 实例分割数据集导入格式规范

## 文档目的

本文档定义平台当前 COCO 实例分割数据集的标准导入目录、JSON 结构、segmentation 字段、类别映射、图片要求和不符合规范的结构。

本文档只覆盖实例分割 segmentation，不覆盖目标检测 detection、语义分割 semantic segmentation、姿态估计 pose 和 OBB 旋转框检测。

## 适用范围

当前 COCO 实例分割导入格式对应 DatasetImport 的：

- `task_type=segmentation`
- `format_type=coco`

可复用该 segmentation DatasetVersion 的模型：

- `YOLOv8 segmentation`
- `YOLO11 segmentation`
- `YOLO26 segmentation`
- `RF-DETR segmentation`

RF-DETR segmentation 默认使用 COCO instance segmentation 导出格式。YOLOv8 / YOLO11 / YOLO26 segmentation 默认使用 YOLO instance segmentation 导出格式，也可以按后端能力使用 COCO instance segmentation。

## 核心定义

COCO 实例分割数据集中，一张图像可以包含零个、一个或多个目标实例。每个实例对应一个 annotation 对象，必须包含类别、水平 bbox 和实例区域。

实例区域通过 `segmentation` 字段表示，支持两类结构：

- polygon：一个或多个多边形。
- RLE：压缩或未压缩的 run-length encoding mask。

实例分割 segmentation 与语义分割 semantic segmentation 不同。COCO instance segmentation 按实例记录对象区域；semantic segmentation 通常按样本 mask 记录每个像素的类别值。

## 标准目录结构

平台推荐使用 `images/{split}` 与 `annotations/instances_{split}.json` 的目录结构：

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

训练集和验证集是标准 segmentation 数据集的基本组成部分。测试集可选。

## 兼容目录结构

当前导入器也支持 split-local manifest 目录：

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

COCO segmentation JSON 通常包含以下字段：

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
| `annotations` | 是 | 实例标注列表 |
| `categories` | 是 | 类别定义列表 |

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

规则：

- `categories.id` 在当前 JSON 文件中必须唯一。
- `categories.name` 应唯一、稳定，且不包含前导或尾随空格。
- `annotations.category_id` 必须引用 `categories.id` 中已存在的编号。
- 不应根据 `categories` 数组位置推断类别编号。

导入后 DatasetVersion 会把类别重排为连续 0-based `category_id`，并在 metadata 中保留原始 `source_category_id`、`source_category_name` 和 `supercategory`。

## 实例标注定义

每个目标实例对应一个 annotation 对象。

示例：

```json
{
  "id": 1,
  "image_id": 1,
  "category_id": 1,
  "segmentation": [
    [
      200, 160,
      600, 180,
      650, 560,
      180, 520
    ]
  ],
  "bbox": [180, 160, 470, 400],
  "area": 172000,
  "iscrowd": 0
}
```

标注对象字段：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `id` | 推荐 | 实例标注唯一编号 |
| `image_id` | 是 | 对应图像编号 |
| `category_id` | 是 | 对应类别编号 |
| `segmentation` | 是 | 实例 polygon 或 RLE mask |
| `bbox` | 是 | 实例外接水平边界框 |
| `area` | 推荐 | 实例区域面积 |
| `iscrowd` | 推荐 | 是否为群体目标 |

规则：

- `annotations.image_id` 必须引用 `images.id` 中已存在的编号。
- `annotations.category_id` 必须引用 `categories.id` 中已存在的编号。
- `annotations.id` 若存在，在当前 JSON 文件中必须唯一。
- `bbox` 必须是 COCO `xywh` 像素框。
- `segmentation` 必须是合法 polygon 列表或 RLE 对象。
- `area` 若缺失，导入器可按 bbox 面积使用默认值；标准数据集推荐写入真实实例 mask 面积。
- `iscrowd` 若缺失，导入器按 `0` 处理。

## polygon segmentation

普通实例可以使用 polygon 表示：

```json
"segmentation": [
  [
    x1, y1,
    x2, y2,
    x3, y3,
    ...
  ]
]
```

polygon 规则：

- 坐标单位为像素，不使用归一化坐标。
- 每个 polygon 至少包含三个顶点。
- 坐标数量必须为偶数。
- 坐标必须为有限数值。
- 顶点应沿目标轮廓依次排列。
- polygon 不应自交或退化。
- polygon 不应超出图像有效范围。

一个 annotation 的 `segmentation` 外层数组表示同一个实例的全部区域。多个内层 polygon 表示同一个实例的多个区域，不表示多个实例。

不同实例必须创建不同 annotation 对象。

## RLE segmentation

复杂 mask 可以使用 RLE 表示。

压缩 RLE 示例：

```json
"segmentation": {
  "size": [800, 1000],
  "counts": "encoded-rle-data"
}
```

未压缩 RLE 示例：

```json
"segmentation": {
  "size": [800, 1000],
  "counts": [1200, 30, 970, 35, 965]
}
```

RLE 规则：

- `size` 必须为 `[height, width]`。
- `size` 必须与对应图像的 `height / width` 一致。
- `counts` 可以是压缩字符串，也可以是未压缩整数数组。
- 未压缩 `counts` 的总和必须等于 `height * width`。
- `iscrowd=1` 的群体区域通常使用 RLE 表示。

## bbox 规则

COCO segmentation bbox 格式为：

```text
[x_min, y_min, width, height]
```

坐标单位为像素，不使用归一化坐标。

bbox 应覆盖对应实例的完整 segmentation 区域。

示例：

```json
"bbox": [180, 160, 470, 400]
```

表示：

```text
x_min = 180
y_min = 160
width = 470
height = 400
```

## area 规则

`area` 表示实例区域面积，单位为平方像素。

对于实例分割数据，`area` 推荐根据 segmentation mask 或 polygon 面积计算，而不是简单使用：

```text
area = bbox_width * bbox_height
```

只有当实例区域正好填满 bbox 时，两者才相等。

## 无目标图像

无目标图像仍应记录在 `images` 数组中，不需要创建 annotation。

示例：

```json
{
  "images": [
    {
      "id": 2,
      "file_name": "image_002.jpg",
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

COCO segmentation 不需要为空图像创建空标注文件。

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

COCO segmentation 标准导入图片只支持以下扩展名：

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

`.webp / .tif / .tiff` 不属于当前 COCO segmentation 标准导入图片格式。

## 标注文件要求

COCO segmentation JSON 标注文件应满足：

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
- `segmentation` 必须是合法 polygon 列表或 RLE 对象。
- polygon 坐标必须成对出现。
- 每个 polygon 至少包含三个顶点。
- RLE `size` 必须与图像尺寸一致。
- 不应包含重复实例或无效 mask。

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
- 不应混入 detection、pose、obb、semantic segmentation 等其他任务的独立标注格式。
- 不应混入不受支持的图片扩展名。

## DatasetVersion 结果

导入成功后生成的 DatasetVersion 满足：

- `task_type=segmentation`。
- `source_format=coco`。
- 图像按 `train / val / test` split 归档。
- 类别映射统一为连续 0-based 内部 category id。
- 每个实例保存 `segmentation`，保留 COCO polygon 或 RLE 结构。
- 每个实例保存 `bbox_xywh`、`area` 和 `iscrowd`。
- 原始 `images.id / annotations.id / categories.id` 保留在 metadata 中。
- `supercategory` 和额外 annotation 字段按原始 metadata 保留。

## 导出和训练关系

COCO segmentation DatasetVersion 当前可导出为：

```text
coco-instance-seg-v1
yolo-instance-seg-v1
```

模型默认训练格式：

- `RF-DETR segmentation`：使用 `coco-instance-seg-v1`。
- `YOLOv8 segmentation`：默认使用 `yolo-instance-seg-v1`，可使用 `coco-instance-seg-v1`。
- `YOLO11 segmentation`：默认使用 `yolo-instance-seg-v1`，可使用 `coco-instance-seg-v1`。
- `YOLO26 segmentation`：默认使用 `yolo-instance-seg-v1`，可使用 `coco-instance-seg-v1`。

导出为 `yolo-instance-seg-v1` 时，只支持可以转换为 YOLO 单 polygon 的实例。COCO RLE 和无法无损表达为单 polygon 的多区域实例应保留 COCO 导出格式。

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
    "description": "Instance segmentation dataset",
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
      "segmentation": [
        [
          200, 160,
          600, 180,
          650, 560,
          180, 520
        ]
      ],
      "bbox": [180, 160, 470, 400],
      "area": 172000,
      "iscrowd": 0
    },
    {
      "id": 2,
      "image_id": 1,
      "category_id": 2,
      "segmentation": {
        "size": [800, 1000],
        "counts": "encoded-rle-data"
      },
      "bbox": [100, 120, 300, 250],
      "area": 68000,
      "iscrowd": 1
    }
  ]
}
```

`image_001.jpg` 中包含两个实例，`image_002.png` 是无目标图像。

## 不符合规范的结构

### 使用归一化 polygon 坐标

```json
"segmentation": [
  [0.2, 0.2, 0.6, 0.2, 0.6, 0.7]
]
```

COCO segmentation polygon 使用像素坐标，不使用 0 到 1 的归一化坐标。

### polygon 顶点不足

```json
"segmentation": [
  [200, 160, 600, 180]
]
```

该 polygon 只有两个点，无法形成有效区域。

### 坐标数量为奇数

```json
"segmentation": [
  [200, 160, 600, 180, 650]
]
```

最后一个横坐标缺少对应纵坐标。

### 把多个实例写入同一个 annotation

```json
"segmentation": [
  [100, 100, 200, 100, 200, 200, 100, 200],
  [300, 300, 380, 300, 380, 380, 300, 380]
]
```

如果这两个 polygon 表示两个独立目标，应拆成两个 annotation。只有同一个实例的多个区域才可以写在同一个 `segmentation` 外层数组中。

### bbox 格式错误

```json
"bbox": [180, 160, 650, 560]
```

若后两个字段表示右下角坐标，则不符合 COCO `xywh` 格式。

### RLE size 顺序错误

图像宽度为 `1000`、高度为 `800`，错误写法：

```json
"segmentation": {
  "size": [1000, 800],
  "counts": "encoded-rle-data"
}
```

正确顺序为 `[height, width]`：

```json
"size": [800, 1000]
```

### image_id 不存在

```json
{
  "image_id": 99
}
```

当 `images` 中不存在 `id=99` 的图像时，该标注无法关联到有效图像。

### category_id 不存在

```json
{
  "category_id": 3
}
```

当 `categories` 中不存在 `id=3` 的类别时，该标注无法关联到有效类别。

### 使用不支持的图片格式

```text
images/train/image_001.webp
images/train/image_002.tiff
```

当前 COCO segmentation 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。

## 与 COCO detection 的区别

COCO detection 核心字段：

```json
{
  "bbox": [x_min, y_min, width, height]
}
```

COCO segmentation 核心字段：

```json
{
  "segmentation": [],
  "bbox": [x_min, y_min, width, height]
}
```

主要区别：

| 项目 | detection | segmentation |
| --- | --- | --- |
| 目标位置 | 水平 bbox | 实例 mask 区域 |
| 核心字段 | `bbox` | `segmentation` 和 `bbox` |
| 分割表达 | 无 | polygon 或 RLE |
| 实例面积 | bbox 或目标面积 | mask 实际面积 |
| 复杂轮廓 | 不能精确表示 | 可以通过 polygon/RLE 表示 |

## 标准定义总结

COCO 实例分割数据集推荐结构为：

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

- 导入任务固定为 `task_type=segmentation`、`format_type=coco`。
- JSON 核心字段为 `images / annotations / categories`。
- 每个实例对应一个独立 annotation。
- `segmentation` 必须是 polygon 列表或 RLE 对象。
- polygon 坐标使用像素单位，不使用归一化坐标。
- RLE `size` 必须为 `[height, width]`。
- bbox 格式为 `[x_min, y_min, width, height]`。
- 无目标图像只需记录在 `images` 中。
- 导入图片只支持 `.jpg / .jpeg / .png / .bmp`。
- 导入后生成 DatasetVersion，再按训练任务导出为 `coco-instance-seg-v1 / yolo-instance-seg-v1`。

## 相关文档

- [classification-dataset-import-format.md](classification-dataset-import-format.md)
- [coco-detection-dataset-import-format.md](coco-detection-dataset-import-format.md)
- [coco-pose-dataset-import-format.md](coco-pose-dataset-import-format.md)
- [voc-detection-dataset-import-format.md](voc-detection-dataset-import-format.md)
- [yolo-detection-dataset-import-format.md](yolo-detection-dataset-import-format.md)
- [yolo-segmentation-dataset-import-format.md](yolo-segmentation-dataset-import-format.md)
- [dota-obb-dataset-import-format.md](dota-obb-dataset-import-format.md)
- [model-dataset-format-contract.md](model-dataset-format-contract.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)
