# VOC 目标检测数据集格式规范

## 目标与范围

本文定义 `format_type=voc`、`task_type=detection` 的 v1 导入、统一化和导出规则。VOC 在平台中是外部交换格式，不是训练后端内部数据模型。数据导入后必须先形成统一 `DatasetVersion`，再根据模型能力导出为 COCO、YOLO 或 VOC。

本规范只覆盖矩形框 detection。分类、实例分割、pose 和 OBB 使用各自格式规范。

## 平台统一坐标语义

平台内部的像素框统一使用：

- 原点为图片左上角；
- 0-based；
- 左上边界 inclusive；
- 右下边界 exclusive；
- 合法范围为 `[0, image_width] × [0, image_height]`；
- 持久化字段为绝对像素 `bbox_xywh=(x, y, width, height)`。

例如宽 100、高 80 的图片中，覆盖 `x=10..29`、`y=20..49` 像素的框表示为：

```text
xyxy = (10, 20, 30, 50)
xywh = (10, 20, 20, 30)
```

所有导入器、导出器、训练读取器、评估器、预览和推理结果转换必须通过同一坐标边界规则，不能各自执行 `+1` 或 `-1`。

## VOC XML 坐标约定

### 项目默认约定

没有坐标声明的 VOC XML 按常用的 0-based、`xmax/ymax` exclusive 约定读取：

```xml
<bndbox>
  <xmin>10</xmin>
  <ymin>20</ymin>
  <xmax>30</xmax>
  <ymax>50</ymax>
</bndbox>
```

该框导入后的 `bbox_xywh` 为 `(10, 20, 20, 30)`。坐标可以从 0 开始，`xmax` 可以等于图片宽度，`ymax` 可以等于图片高度。

### 官方 PASCAL VOC 约定

官方 PASCAL VOC 1-based、右下 inclusive 坐标只有在 XML 明确声明时才启用。推荐声明：

```xml
<source>
  <coordinateConvention>pascal-voc-1-based-inclusive</coordinateConvention>
</source>
```

也接受以下声明位置：

- `annotation` 根节点属性 `coordinate_convention`；
- `/annotation/coordinate_convention`；
- `/annotation/coordinateConvention`；
- `/annotation/source/coordinate_convention`；
- `/annotation/source/coordinateConvention`。

规范值为：

```text
pascal-voc-1-based-inclusive
```

兼容输入别名为 `1-based-inclusive`、`one-based-inclusive` 和 `official-pascal-voc`。官方坐标 `(10, 20, 30, 50)` 会统一化为内部 `xyxy=(9, 19, 30, 50)` 和 `xywh=(9, 19, 21, 31)`。

同一个 XML 出现冲突声明、声明值未知，或者同一次导入混用两种坐标约定，均直接拒绝。平台不会根据坐标是否出现 0 猜测方言。

## 支持的目录布局

### 直接根目录

```text
dataset/
├─ Annotations/
├─ ImageSets/
│  └─ Main/
└─ JPEGImages/
```

### VOC 年份目录

```text
dataset/
└─ VOC2007/
   ├─ Annotations/
   ├─ ImageSets/Main/
   └─ JPEGImages/
```

`VOC2012` 和其他名称的包装目录按相同结构识别。

### 多 shard 目录

```text
dataset/
└─ VOCdevkit/
   ├─ VOC2007/
   │  ├─ Annotations/
   │  ├─ ImageSets/Main/
   │  └─ JPEGImages/
   └─ VOC2012/
      ├─ Annotations/
      ├─ ImageSets/Main/
      └─ JPEGImages/
```

导入器在受限目录深度内发现每个完整 shard，将 shard id 加入样本源标识，避免不同年份的同名 XML 冲突。目录发现不跟随符号链接。

一个 shard 必须同时具备 `Annotations`、`JPEGImages`、`ImageSets/Main`，并至少包含一个 XML。残缺目录不会被当作可导入 shard。

## split 规则

支持 `train.txt`、`val.txt`、`test.txt` 和 `trainval.txt`。文件使用 UTF-8 或 UTF-8 BOM，每行只能包含一个不带目录和扩展名的 XML stem。

规则如下：

- `train.txt` 和 `val.txt` 如果使用，必须同时存在；
- `trainval.txt` 与 `train.txt`、`val.txt` 同时存在时，必须严格等于二者合集；
- 只有 `trainval.txt` 时，将其明确导入为 `train`，记录 `VOC_VALIDATION_SPLIT_MISSING` warning，不静默制造验证集；
- `test.txt` 可以独立存在；
- `train`、`val`、`test` 必须互斥；
- split 中每个 stem 必须存在对应 XML；
- 每个 XML 必须属于一个有效 split，除非请求显式指定统一 split strategy；
- 空行被忽略，重复 stem、路径、同一行多个 token 均为错误。

多 shard 导入分别解析各自 split，最终合并为统一 `train/val/test`。

## XML 必需字段

最小有效 XML：

```xml
<annotation>
  <filename>image_001.jpg</filename>
  <size>
    <width>1000</width>
    <height>800</height>
    <depth>3</depth>
  </size>
  <object>
    <name>defect</name>
    <pose>Unspecified</pose>
    <truncated>0</truncated>
    <difficult>0</difficult>
    <bndbox>
      <xmin>100</xmin>
      <ymin>80</ymin>
      <xmax>300</xmax>
      <ymax>240</ymax>
    </bndbox>
  </object>
</annotation>
```

要求：

- 根节点必须是 `annotation`；
- `filename` 必须是 `JPEGImages` 下的安全相对路径，不能是绝对路径或包含 `..`；
- 图片扩展名支持 `.jpg`、`.jpeg`、`.png`、`.bmp`；
- `width` 和 `height` 必须是正整数，并与实际解码图片尺寸相同；
- `object/name` 不能为空；
- `bndbox` 四个字段必须是有限数字；
- 转换后的框必须具有正面积且完整位于图片边界内；
- `difficult` 和 `truncated` 只接受 `0`、`1`、空值或 `Unspecified`；
- `pose` 作为可选 metadata 保存；
- 无目标图片允许没有 `object`，但整个 detection 数据集至少要有一个有效类别标注。

同一图片不能在一个 shard 中被多个 XML 重复引用。请求提供 `class_map` 时，类别映射后仍按首次稳定出现顺序生成连续 0-based `category_id`。

## 结构化校验结果

校验问题使用稳定结构返回：

```json
{
  "code": "VOC_BBOX_INVALID",
  "severity": "error",
  "message": "VOC bbox 超出图片范围或没有正面积",
  "file": "VOC2007/Annotations/image_001.xml",
  "location": "/annotation/object[1]/bndbox",
  "sample": "image_001",
  "actual": [100, 80, 1200, 240],
  "expected": "0 <= xmin < xmax <= image_width; 0 <= ymin < ymax <= image_height"
}
```

主要错误码包括：

- `VOC_XML_INVALID`、`VOC_XML_ROOT_INVALID`；
- `VOC_FILENAME_MISSING`、`VOC_FILENAME_INVALID`、`VOC_IMAGE_MISSING`；
- `VOC_SIZE_MISSING`、`VOC_IMAGE_DIMENSION_INVALID`、`VOC_IMAGE_SIZE_MISMATCH`；
- `VOC_SPLIT_FILE_MISSING`、`VOC_SPLIT_OVERLAP`、`VOC_TRAINVAL_MISMATCH`；
- `VOC_COORDINATE_DECLARATION_UNKNOWN`、`VOC_COORDINATE_DECLARATION_CONFLICT`、`VOC_COORDINATE_CONVENTION_MIXED`；
- `VOC_OBJECT_NAME_MISSING`、`VOC_BBOX_MISSING`、`VOC_BBOX_VALUE_INVALID`、`VOC_BBOX_INVALID`。

问题集合有保留数量上限，同时记录总数、error 数、warning 数和是否截断，避免恶意或大规模损坏数据集造成无界内存增长。

## DatasetVersion 统一化结果

成功导入后：

- 坐标统一为 0-based exclusive `bbox_xywh`；
- 类别统一为连续 0-based id；
- 原始坐标约定写入 DatasetVersion、sample 和 annotation metadata；
- shard 根、图片根、标注根、split 文件、split 统计和 warning 写入 detected profile 与 validation report；
- 图片、sample manifest、类别表和索引由 ObjectStore 管理；
- 导入失败时不保留半成品 DatasetVersion。

## `voc-detection-v1` 导出

平台 v1 VOC 导出固定生成：

```text
export/
├─ manifest.json
├─ Annotations/*.xml
├─ ImageSets/Main/{split}.txt
└─ JPEGImages/*
```

`voc-detection-v1` 固定使用项目默认 `zero-based-exclusive` 坐标。`manifest.json` 包含 `coordinate_convention`，每个 XML 也包含：

```xml
<source>
  <database>amvision</database>
  <coordinateConvention>zero-based-exclusive</coordinateConvention>
</source>
```

浮点内部框导出到整数 XML 时使用外包围量化：左上取 floor，右下 exclusive 取 ceil，保证导出不会缩小目标。导出的 VOC 可再次导入并保持相同整数边界语义。

## 训练链路

- YOLOX 可以消费 `voc-detection-v1` 或 `coco-detection-v1`；
- YOLOv8、YOLO11、YOLO26 detection 使用 `yolo-detection-v1`；
- RF-DETR detection 使用 `coco-detection-v1`；
- 导入来源不限制后续训练模型，格式转换统一经过 DatasetVersion 与 DatasetExport；
- YOLOX VOC 读取器使用同一坐标声明解析和边界转换，不再自行假定官方坐标。

## 安全和资源边界

- zip 导入先执行成员数、展开总大小、单成员压缩比、路径穿越和符号链接检查；
- VOC 根发现有最大深度且不跟随符号链接；
- 问题列表有保留上限；
- 图片必须实际解码并核对尺寸；
- 本地 ObjectStore 在 Windows 使用 extended-length path，系统首次启动同时检查 `LongPathsEnabled`；
- 文件写入使用同目录原子替换，失败时清理临时文件和未完成版本。
