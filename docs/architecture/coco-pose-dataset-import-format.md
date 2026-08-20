# COCO Keypoints 姿态估计数据集导入格式规范

## 文档目的

本文档定义平台当前 COCO Keypoints 姿态估计数据集的标准导入目录、JSON 结构、关键点字段、类别和骨架定义、图片要求和不符合规范的结构。

本文档只覆盖二维姿态估计 pose，不覆盖目标检测 detection、实例分割 segmentation、语义分割 semantic segmentation 和 OBB 旋转框检测。

## 适用范围

当前 COCO Keypoints 导入格式对应 DatasetImport 的：

- `task_type=pose`
- `format_type=coco`

可复用该 pose DatasetVersion 的模型：

- `YOLOv8 pose`
- `YOLO11 pose`
- `YOLO26 pose`

YOLOX 当前不作为平台公开 pose 训练能力。RF-DETR 当前不作为平台公开 pose 训练能力。

## 核心定义

COCO Keypoints 数据集中，一张图像可以包含零个、一个或多个目标实例。图像、实例、类别、bbox 和关键点统一记录在 JSON 文件中，通过 id 建立引用关系。

pose 任务的核心 annotation 字段为：

```text
image_id
category_id
bbox
keypoints
num_keypoints
```

`bbox` 使用像素 `xywh`：

```text
[x_min, y_min, width, height]
```

`keypoints` 使用像素坐标和可见性展平数组：

```text
x1 y1 visibility1 x2 y2 visibility2 ... xK yK visibilityK
```

导入后平台会把 bbox 和 keypoints 以像素坐标写入 DatasetVersion。

## 标准目录结构

平台推荐使用 `images/{split}` 与 `annotations/person_keypoints_{split}.json` 的目录结构：

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
   ├─ person_keypoints_train.json
   ├─ person_keypoints_val.json
   └─ person_keypoints_test.json
```

目录含义：

- `images`：图像文件目录。
- `annotations`：COCO JSON 标注文件目录。
- `train`：训练集目录。
- `val`：验证集目录。
- `test`：测试集目录，可选。
- `person_keypoints_train.json`：训练集关键点标注文件。
- `person_keypoints_val.json`：验证集关键点标注文件。
- `person_keypoints_test.json`：测试集关键点标注文件，可选。

当前导入器会扫描 `annotations/*.json`，不强制 JSON 文件名必须使用 `person_keypoints_*.json`。为减少歧义，标准导入包推荐使用 COCO 常见命名。

## 最小标准目录结构

```text
dataset/
├─ images/
│  ├─ train/
│  └─ val/
└─ annotations/
   ├─ person_keypoints_train.json
   └─ person_keypoints_val.json
```

训练集和验证集是标准 pose 数据集的基本组成部分。测试集可选。

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

`valid` 在导入后统一归一化为 `val`。标准导入包推荐使用 `images/{split}` 与 `annotations/person_keypoints_{split}.json`，便于长期维护和人工检查。

## JSON 基本结构

COCO Keypoints JSON 通常包含以下字段：

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
| `images` | 是 | 图像信息列表 |
| `annotations` | 是 | 实例 bbox 和关键点标注列表 |
| `categories` | 是 | 类别、关键点名称和骨架定义 |
| `info` | 否 | 数据集说明 |
| `licenses` | 否 | 许可证信息 |

当前导入器只会处理同时包含 `images / annotations / categories` 的 JSON 文件。

## images 字段

`images` 数组中的每个对象表示一张图像：

```json
{
  "id": 1,
  "file_name": "image_001.jpg",
  "width": 1000,
  "height": 800
}
```

字段说明：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `id` | 是 | 当前 JSON 内唯一图像 id |
| `file_name` | 是 | 图像文件名或相对路径 |
| `width` | 是 | 图像宽度，单位为像素 |
| `height` | 是 | 图像高度，单位为像素 |

`file_name` 可以是纯文件名：

```json
"file_name": "image_001.jpg"
```

也可以是相对路径：

```json
"file_name": "train/image_001.jpg"
```

导入器会按以下顺序解析图片路径：

- 按 `file_name` 相对于数据集根目录查找。
- 按 `{split}/{file_name}` 查找。
- 按 `images/{split}/{file_name}` 查找。
- 若仍未找到，会按文件名在数据集根目录下递归查找；只有唯一匹配时才使用。

## categories 字段

`categories` 数组用于定义类别、关键点名称和骨架连接：

```json
{
  "id": 1,
  "name": "type1",
  "supercategory": "object",
  "keypoints": [
    "point1",
    "point2",
    "point3",
    "point4",
    "point5"
  ],
  "skeleton": [
    [1, 2],
    [2, 3],
    [3, 4],
    [3, 5]
  ]
}
```

字段说明：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `id` | 是 | 类别 id |
| `name` | 是 | 类别名称 |
| `supercategory` | 否 | 上级类别 |
| `keypoints` | 推荐 | 关键点名称列表 |
| `skeleton` | 推荐 | 关键点连接关系 |

当前导入器硬校验 `id` 和 `name`，并按类别 id 生成平台内部连续 0-based `category_id`。`keypoints` 和 `skeleton` 是标准 pose 数据集应提供的语义字段，用于可视化、训练增强和后续导出一致性。

类别名称要求：

- 名称唯一。
- 拼写和大小写一致。
- 不包含前导或尾随空格。
- 避免使用不兼容的特殊字符。
- 不同 split 的类别 id、类别名称和关键点定义应保持一致。

## keypoints 和 skeleton

`categories.keypoints` 的顺序决定关键点索引和语义。

示例：

```text
0: point1
1: point2
2: point3
3: point4
4: point5
```

所有实例必须按该顺序保存关键点，不得在不同图像或不同实例中改变顺序。

`categories.skeleton` 通常使用 1-based keypoint 索引：

```json
"skeleton": [
  [1, 2],
  [2, 3]
]
```

标准数据集要求 skeleton 中的索引必须能在 `keypoints` 列表中找到。没有明确骨架关系时可以使用空数组：

```json
"skeleton": []
```

## annotations 字段

`annotations` 数组中的每个对象表示一个目标实例：

```json
{
  "id": 1,
  "image_id": 1,
  "category_id": 1,
  "bbox": [200, 120, 500, 560],
  "area": 280000,
  "iscrowd": 0,
  "num_keypoints": 4,
  "keypoints": [
    300, 200, 2,
    450, 300, 2,
    500, 450, 1,
    600, 600, 2,
    0, 0, 0
  ]
}
```

字段说明：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `id` | 否 | annotation id；缺失时导入器会生成内部 id |
| `image_id` | 是 | 关联的图像 id |
| `category_id` | 是 | 关联的类别 id |
| `bbox` | 是 | 实例水平 bbox，像素 `xywh` |
| `area` | 否 | 实例面积；缺失时按 bbox 面积计算 |
| `iscrowd` | 否 | 是否群体区域；缺失时按 `0` 处理 |
| `num_keypoints` | 是 | visibility 大于 0 的关键点数量 |
| `keypoints` | 是 | 关键点像素坐标和 visibility |

每个 annotation 必须引用已存在的 `images.id` 和 `categories.id`。

## bbox 规则

COCO bbox 固定为像素 `xywh`：

```text
[x_min, y_min, width, height]
```

字段要求：

- bbox 必须是长度为 4 的数组。
- bbox 必须只包含有限数字。
- `width` 必须大于 0。
- `height` 必须大于 0。
- bbox 坐标使用像素值，不使用归一化坐标。

`area` 若未提供，导入器会按 `width * height` 计算。若提供，必须是非负有限数字。

## keypoints 规则

`keypoints` 必须是一维数组：

```text
x1 y1 visibility1 x2 y2 visibility2 ... xK yK visibilityK
```

字段要求：

- `keypoints` 必须是非空数组。
- 数组长度必须是 3 的倍数。
- 所有值必须是有限数字。
- 每个关键点包含 `x / y / visibility` 三个字段。
- `x / y` 使用像素坐标，不使用归一化坐标。
- `visibility` 只能是 `0 / 1 / 2`。
- `num_keypoints` 必须等于 visibility 大于 0 的关键点数量。
- 未标注关键点不得删除字段位置，应保留 `x y visibility` 三个字段。

visibility 规则：

| 值 | 含义 |
| --- | --- |
| `0` | 关键点未标注或不存在 |
| `1` | 关键点已标注但不可见或被遮挡 |
| `2` | 关键点已标注且可见 |

当 `visibility=0` 时，常见写法是：

```text
0 0 0
```

标准数据集要求所有实例使用固定的关键点数量和顺序。若 `categories.keypoints` 定义了 `K` 个关键点，则每个实例的 `keypoints` 长度应为 `3 * K`。

## 无目标图像

无目标图像应保留在 `images` 数组中，不需要创建空 annotation：

```json
{
  "id": 2,
  "file_name": "image_002.jpg",
  "width": 1000,
  "height": 800
}
```

COCO Keypoints 不需要为空图像创建单独的空标注文件。

## 图像文件要求

COCO pose 标准导入图片只支持以下扩展名：

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
- JSON 中的 `width / height` 应与实际图像一致。
- `file_name` 能够定位到 zip 内图片。
- 图像文件不为空、不损坏。
- train、val、test 之间不存在重复样本。
- 同一来源的高度相似样本应放在同一个 split 中，避免数据泄漏。

`.webp / .tif / .tiff` 不属于当前 COCO pose 标准导入图片格式。

## 数据划分要求

训练集、验证集和测试集应相互独立：

```text
train ∩ val = ∅
train ∩ test = ∅
val ∩ test = ∅
```

不同 split 通常使用独立 JSON 文件：

```text
person_keypoints_train.json
person_keypoints_val.json
person_keypoints_test.json
```

若 manifest 位于 `train / val / valid / test` 目录下，导入器优先按父目录推断 split；否则按 manifest 文件名推断 split。无法识别时默认归入 `train`。请求中的 `split_strategy` 可以强制覆盖 split。

## zip 包要求

数据集通过 FastAPI 上传 zip 压缩包并异步导入。

zip 包应满足：

- zip 内允许存在一层额外包裹目录。
- 图片和 JSON 标注文件必须位于 zip 内部。
- JSON 中的 `file_name` 不应指向 zip 外绝对路径。
- `train` 和 `val` 应能解析到有效图像。
- 不应包含同名但大小写不同的图片路径。
- 不应混入 detection、segmentation、obb、semantic segmentation 等其他任务的独立标注格式。
- 不应混入不受支持的图片扩展名。

## DatasetVersion 结果

导入成功后生成的 DatasetVersion 满足：

- `task_type=pose`。
- `source_format=coco`。
- 图像按 `train / val / test` split 归档。
- 类别映射统一为连续 0-based 内部 category id。
- 每个实例保存像素 `bbox_xywh`。
- 每个实例保存像素 keypoints，格式为 `[x, y, visibility]` 展平数组。
- `num_keypoints` 等于 visibility 大于 0 的关键点数量。
- `area` 使用 COCO `area` 或 bbox 面积。
- `iscrowd` 保留到 annotation。
- COCO annotation 中非核心字段保留到 metadata。

## 导出和训练关系

COCO pose DatasetVersion 当前可导出为：

```text
yolo-pose-v1
coco-keypoints-v1
```

模型默认训练格式：

- `YOLOv8 pose`：默认使用 `yolo-pose-v1`，可使用 `coco-keypoints-v1`。
- `YOLO11 pose`：默认使用 `yolo-pose-v1`，可使用 `coco-keypoints-v1`。
- `YOLO26 pose`：默认使用 `yolo-pose-v1`，可使用 `coco-keypoints-v1`。

导入格式不等同于训练格式。同一份 COCO pose 导入数据先生成 DatasetVersion，再按训练任务需要导出为对应格式。

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
   ├─ person_keypoints_train.json
   └─ person_keypoints_val.json
```

`annotations/person_keypoints_train.json`：

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
      "file_name": "image_002.png",
      "width": 1280,
      "height": 720
    }
  ],
  "categories": [
    {
      "id": 1,
      "name": "type1",
      "keypoints": ["point1", "point2", "point3"],
      "skeleton": [[1, 2], [2, 3]]
    }
  ],
  "annotations": [
    {
      "id": 1,
      "image_id": 1,
      "category_id": 1,
      "bbox": [200, 120, 500, 560],
      "area": 280000,
      "iscrowd": 0,
      "num_keypoints": 3,
      "keypoints": [
        300, 200, 2,
        450, 300, 2,
        600, 600, 1
      ]
    }
  ]
}
```

`image_002.png` 没有对应 annotation，表示无目标图像。

## 不符合规范的结构

### 使用归一化关键点坐标

```json
"keypoints": [
  0.3, 0.2, 2,
  0.5, 0.4, 2
]
```

COCO Keypoints 使用像素坐标，不使用归一化坐标。

### 使用错误 bbox 格式

```json
"bbox": [200, 120, 700, 680]
```

如果后两个值表示右下角坐标，则不符合 COCO bbox。正确格式为：

```json
"bbox": [200, 120, 500, 560]
```

### keypoints 字段缺失

```json
{
  "image_id": 1,
  "category_id": 1,
  "bbox": [200, 120, 500, 560]
}
```

pose annotation 必须提供非空 `keypoints`。

### keypoints 字段数量不合法

```json
"keypoints": [
  300, 200, 2,
  450
]
```

`keypoints` 长度必须是 3 的倍数。

### 删除未标注关键点

类别定义 5 个关键点时，即使部分关键点未标注，也必须保留对应字段位置：

```json
"keypoints": [
  300, 200, 2,
  450, 300, 2,
  0, 0, 0,
  0, 0, 0,
  0, 0, 0
]
```

### num_keypoints 计算错误

```json
"num_keypoints": 5,
"keypoints": [
  300, 200, 2,
  450, 300, 2,
  500, 450, 1,
  0, 0, 0,
  0, 0, 0
]
```

实际只有 3 个关键点满足 `visibility > 0`，因此 `num_keypoints` 应为 `3`。

### visibility 值无效

```json
"keypoints": [
  300, 200, 3
]
```

visibility 只能是 `0 / 1 / 2`。

### image_id 不存在

```json
"image_id": 99
```

如果 `images` 中不存在 `id=99` 的图像，则 annotation 无法关联到有效图片。

### category_id 不存在

```json
"category_id": 3
```

如果 `categories` 中不存在 `id=3` 的类别，则 annotation 无法关联到有效类别。

### skeleton 索引不存在

```json
"keypoints": ["point1", "point2", "point3"],
"skeleton": [[1, 4]]
```

关键点编号 `4` 不存在。

### 使用不支持的图片格式

```text
images/train/image_001.webp
images/train/image_002.tiff
```

当前 COCO pose 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。

## 与 COCO detection 格式的区别

COCO detection annotation 核心字段：

```json
{
  "bbox": [x_min, y_min, width, height]
}
```

COCO pose annotation 在 bbox 之外还必须提供：

```json
{
  "num_keypoints": 3,
  "keypoints": [
    300, 200, 2,
    450, 300, 2,
    600, 600, 1
  ]
}
```

主要区别：

| 项目 | detection | pose |
| --- | --- | --- |
| 目标位置 | bbox | bbox 和 keypoints |
| 关键点坐标 | 无 | 像素坐标 |
| 可见性 | 无 | `0 / 1 / 2` |
| 骨架结构 | 无 | `categories.skeleton` |
| 关键点名称 | 无 | `categories.keypoints` |
| 已标注点数 | 无 | `num_keypoints` |

## 标准定义总结

COCO pose 数据集推荐结构为：

```text
dataset/
├─ images/
│  ├─ train/图像文件
│  ├─ val/图像文件
│  └─ test/图像文件
└─ annotations/
   ├─ person_keypoints_train.json
   ├─ person_keypoints_val.json
   └─ person_keypoints_test.json
```

核心规则：

- 导入任务固定为 `task_type=pose`、`format_type=coco`。
- JSON 必须包含 `images / annotations / categories`。
- 每张图像在 `images` 中记录一次。
- 每个目标实例在 `annotations` 中记录一次。
- annotation 必须引用有效 `image_id` 和 `category_id`。
- bbox 使用像素 `[x_min, y_min, width, height]`。
- keypoints 使用像素 `[x, y, visibility]` 展平数组。
- keypoints 数组长度必须是 3 的倍数。
- visibility 只能是 `0 / 1 / 2`。
- `num_keypoints` 必须等于 visibility 大于 0 的关键点数量。
- 标准数据集推荐在 `categories.keypoints` 中定义关键点名称。
- 标准数据集推荐在 `categories.skeleton` 中定义骨架连接。
- 无目标图像只需记录在 `images` 中。
- 导入图片只支持 `.jpg / .jpeg / .png / .bmp`。
- 导入后生成 DatasetVersion，再按训练任务导出为 `yolo-pose-v1 / coco-keypoints-v1`。

## 相关文档

- [classification-dataset-import-format.md](classification-dataset-import-format.md)
- [coco-detection-dataset-import-format.md](coco-detection-dataset-import-format.md)
- [coco-segmentation-dataset-import-format.md](coco-segmentation-dataset-import-format.md)
- [voc-detection-dataset-import-format.md](voc-detection-dataset-import-format.md)
- [yolo-detection-dataset-import-format.md](yolo-detection-dataset-import-format.md)
- [yolo-segmentation-dataset-import-format.md](yolo-segmentation-dataset-import-format.md)
- [yolo-pose-dataset-import-format.md](yolo-pose-dataset-import-format.md)
- [dota-obb-dataset-import-format.md](dota-obb-dataset-import-format.md)
- [model-dataset-format-contract.md](model-dataset-format-contract.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)
