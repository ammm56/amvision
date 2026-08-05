# VOC 目标检测数据集导入格式规范

## 文档目的

本文档定义平台当前 Pascal VOC 矩形边界框目标检测数据集的标准导入目录、XML 结构、split 文件、类别映射、图片要求和不符合规范的结构。

本文档只覆盖目标检测 detection，不覆盖实例分割、姿态估计和 OBB 旋转框检测。

## 适用范围

当前 VOC 目标检测导入格式对应 DatasetImport 的：

- `task_type=detection`
- `format_type=voc`

可复用该 detection DatasetVersion 的模型：

- `YOLOX detection`
- `YOLOv8 detection`
- `YOLO11 detection`
- `YOLO26 detection`
- `RF-DETR detection`

VOC detection 可作为 YOLOX detection 的训练导出格式。RF-DETR detection 默认使用 COCO detection。YOLOv8 / YOLO11 / YOLO26 detection 默认使用 YOLO detection；同一份 VOC detection 导入数据可以先生成 DatasetVersion，再按训练任务导出为 `coco-detection-v1`、`yolo-detection-v1` 或 `voc-detection-v1`。

## 核心定义

VOC 目标检测数据集中，每张图像对应一个同名 XML 标注文件。XML 文件记录图像文件名、图像尺寸、目标类别、边界框和可选目标属性。

VOC 边界框格式固定为：

```text
xmin ymin xmax ymax
```

对应 XML 字段为：

```xml
<bndbox>
    <xmin>200</xmin>
    <ymin>160</ymin>
    <xmax>600</xmax>
    <ymax>560</ymax>
</bndbox>
```

坐标单位为像素，不使用归一化坐标。

## 标准目录结构

```text
dataset/
├─ JPEGImages/
│  ├─ image_001.jpg
│  ├─ image_002.png
│  └─ ...
├─ Annotations/
│  ├─ image_001.xml
│  ├─ image_002.xml
│  └─ ...
└─ ImageSets/
   └─ Main/
      ├─ train.txt
      ├─ val.txt
      ├─ trainval.txt
      └─ test.txt
```

目录含义：

- `JPEGImages`：图像文件目录。
- `Annotations`：XML 标注文件目录。
- `ImageSets/Main`：数据划分文件目录。
- `train.txt`：训练集样本列表，标准导入必需。
- `val.txt`：验证集样本列表，标准导入必需。
- `trainval.txt`：训练集与验证集样本合集，可选。
- `test.txt`：测试集样本列表，可选。

虽然标准目录名是 `JPEGImages`，当前标准导入图片仍只支持 `.jpg / .jpeg / .png / .bmp`。

## 最小标准目录结构

```text
dataset/
├─ JPEGImages/
│  ├─ image_001.jpg
│  └─ image_101.jpg
├─ Annotations/
│  ├─ image_001.xml
│  └─ image_101.xml
└─ ImageSets/
   └─ Main/
      ├─ train.txt
      └─ val.txt
```

标准 VOC detection 导入包必须包含 `train.txt` 和 `val.txt`。`trainval.txt` 与 `test.txt` 是可选文件，不作为标准导入的必需条件。

## 图像与标注对应关系

每张图像应对应一个同名 XML 标注文件。

示例：

```text
JPEGImages/image_001.jpg
Annotations/image_001.xml
```

对应关系要求：

- 基础文件名一致。
- XML 文件只描述一张图像。
- XML 中的 `filename` 能够定位 `JPEGImages` 下的实际图像。
- XML 中的 `size/width` 和 `size/height` 与实际图像尺寸一致。
- 图像样本应出现在 `train.txt`、`val.txt` 或可选的 `test.txt` 中。

若 XML 文件名与 `filename` 字段不一致，标准数据集应优先修正为一致。平台导入解析时会以 XML 中的 `filename` 定位图像，但这种情况会降低人工检查和外部工具兼容性。

## split 文件规则

`ImageSets/Main` 下的 split 文件为 UTF-8 文本文件，每行记录一个样本名。

标准写法只记录基础文件名，不包含目录和图片扩展名：

```text
image_001
image_002
image_003
```

对应文件为：

```text
JPEGImages/image_001.jpg
Annotations/image_001.xml
```

split 文件要求：

- `train.txt` 必须存在。
- `val.txt` 必须存在。
- `trainval.txt` 可选。
- `test.txt` 可选。
- `train.txt` 与 `val.txt` 互斥，不应包含相同样本名。
- `test.txt` 若存在，应与 `train.txt`、`val.txt` 互斥。
- `trainval.txt` 若存在，应等于 `train.txt` 与 `val.txt` 的合集。
- split 文件中的样本名必须能匹配 `Annotations/{sample}.xml`。
- split 文件中的样本名应能定位对应图像。

`trainval.txt` 是辅助合集，不是独立数据划分。平台标准导入以 `train.txt / val.txt / test.txt` 作为互斥 split 来源。

## XML 基本结构

单个 XML 标注文件的推荐结构：

```xml
<annotation>
    <folder>JPEGImages</folder>
    <filename>image_001.jpg</filename>
    <size>
        <width>1000</width>
        <height>800</height>
        <depth>3</depth>
    </size>
    <segmented>0</segmented>
    <object>
        <name>type1</name>
        <pose>Unspecified</pose>
        <truncated>0</truncated>
        <difficult>0</difficult>
        <bndbox>
            <xmin>200</xmin>
            <ymin>160</ymin>
            <xmax>600</xmax>
            <ymax>560</ymax>
        </bndbox>
    </object>
</annotation>
```

核心字段：

```text
filename
size
object
name
bndbox
```

无目标图像可以不包含 `object` 元素，但仍应包含 `filename` 和 `size`。

## 图像信息定义

图像文件名通过 `filename` 字段定义：

```xml
<filename>image_001.jpg</filename>
```

图像尺寸通过 `size` 字段定义：

```xml
<size>
    <width>1000</width>
    <height>800</height>
    <depth>3</depth>
</size>
```

字段说明：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `filename` | 是 | 图像文件名或相对路径 |
| `size/width` | 是 | 图像宽度，单位为像素 |
| `size/height` | 是 | 图像高度，单位为像素 |
| `size/depth` | 否 | 图像通道数 |
| `folder` | 否 | 图像目录名称 |
| `path` | 否 | 原始路径信息 |

规则：

- `filename` 不得是 zip 外部绝对路径。
- `filename` 不得包含 `..`。
- `width` 和 `height` 必须为正整数。
- XML 中的 `width / height` 应与实际图像尺寸一致。
- `path` 若存在，只作为原始 metadata，不作为 zip 外图片定位依据。

## 目标标注定义

每个目标使用一个 `object` 元素表示。

示例：

```xml
<object>
    <name>type1</name>
    <pose>Unspecified</pose>
    <truncated>0</truncated>
    <difficult>0</difficult>
    <bndbox>
        <xmin>200</xmin>
        <ymin>160</ymin>
        <xmax>600</xmax>
        <ymax>560</ymax>
    </bndbox>
</object>
```

字段说明：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `name` | 是 | 目标类别名称 |
| `bndbox/xmin` | 是 | 左边界横坐标 |
| `bndbox/ymin` | 是 | 上边界纵坐标 |
| `bndbox/xmax` | 是 | 右边界横坐标 |
| `bndbox/ymax` | 是 | 下边界纵坐标 |
| `pose` | 否 | 目标姿态 |
| `truncated` | 否 | 是否被图像边界截断 |
| `difficult` | 否 | 是否为困难目标 |

`truncated / difficult / pose` 导入后保留到 annotation metadata。未提供 `truncated` 或 `difficult` 时按 `0` 处理。

## 边界框格式

VOC detection 边界框格式为：

```text
xmin ymin xmax ymax
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `xmin` | 边界框左边界横坐标 |
| `ymin` | 边界框上边界纵坐标 |
| `xmax` | 边界框右边界横坐标 |
| `ymax` | 边界框下边界纵坐标 |

坐标单位为像素。

VOC detection 的 bbox 不是以下格式：

```text
x_center y_center width height
```

也不是 COCO `xywh` 格式：

```text
xmin ymin width height
```

## 坐标规则

平台按 Pascal VOC 常见的 1-based inclusive `xyxy` 规则读取 XML 坐标。

假设图像尺寸为：

```text
W = 图像宽度
H = 图像高度
```

边界框应满足：

```text
1 <= xmin <= xmax <= W
1 <= ymin <= ymax <= H
```

导入后转换为平台内部 0-based `bbox_xywh`：

```text
x = xmin - 1
y = ymin - 1
width = xmax - xmin + 1
height = ymax - ymin + 1
```

示例：

```xml
<bndbox>
    <xmin>200</xmin>
    <ymin>160</ymin>
    <xmax>600</xmax>
    <ymax>560</ymax>
</bndbox>
```

导入后的平台内部 bbox 为：

```text
x = 199
y = 159
width = 401
height = 401
```

同一数据集不得混用 0-based 与 1-based 坐标约定。

## 类别定义

VOC XML 使用类别名称表示目标类别：

```xml
<name>type1</name>
```

类别名称要求：

- 名称唯一。
- 拼写和大小写一致。
- 不包含前导或尾随空格。
- 不包含空字符串。
- 训练、验证、测试和部署阶段保持一致。

导入后 DatasetVersion 会生成连续 0-based `category_id`。原始类别名称会作为 `source_class_name` 保留。若导入请求提供 `class_map_json`，平台可按请求映射把外部类别名称转换为项目类别名称。

## 目标属性规则

### truncated

`truncated` 表示目标是否被图像边界截断：

```text
0 = 未截断
1 = 被截断
```

### difficult

`difficult` 表示目标是否为困难样本：

```text
0 = 普通目标
1 = 困难目标
```

### pose

`pose` 表示目标姿态。常见值包括：

```text
Unspecified
Left
Right
Frontal
Rear
```

这些字段不参与平台 detection bbox 的核心几何计算，但会保留到 metadata 中。

## 无目标图像

无目标图像可以保留不包含 `object` 元素的 XML 文件。

示例：

```xml
<annotation>
    <folder>JPEGImages</folder>
    <filename>image_002.jpg</filename>
    <size>
        <width>1000</width>
        <height>800</height>
        <depth>3</depth>
    </size>
    <segmented>0</segmented>
</annotation>
```

该 XML 表示图像有效，但其中不存在目标。无目标图像仍应出现在 `train.txt` 或 `val.txt` 中，不能只放在 `JPEGImages` 目录中。

## 图像文件要求

VOC detection 标准导入图片只支持以下扩展名：

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
- 图像文件名与 XML 中的 `filename` 一致。
- XML 中记录的 `width / height` 与实际图像一致。
- 图像样本正确出现在 `train.txt / val.txt` 或可选的 `test.txt` 中。
- train、val、test 之间不存在重复样本。
- 同一来源的高度相似样本应放在同一个 split 中，避免数据泄漏。

`.webp / .tif / .tiff` 不属于当前 VOC detection 标准导入图片格式。

## XML 标注文件要求

XML 标注文件应满足：

- 文件为合法 XML。
- 推荐使用 UTF-8 编码。
- 根节点应为 `annotation`。
- 每个 XML 文件只对应一张图像。
- XML 文件与图像使用相同基础文件名。
- `filename` 能够定位 `JPEGImages` 下的实际图像。
- `size/width` 和 `size/height` 必须为正整数。
- 每个 `object` 必须包含有效 `name`。
- 每个 `object` 必须包含 `bndbox/xmin/ymin/xmax/ymax`。
- bbox 坐标必须为有限数值。
- bbox 必须满足 `xmin <= xmax`、`ymin <= ymax`。
- bbox 不得超出图像范围。
- 不应包含重复、无效或面积为零的边界框。

## 数据划分要求

训练集、验证集和测试集应相互独立：

```text
train ∩ val = ∅
train ∩ test = ∅
val ∩ test = ∅
```

标准 VOC detection 导入包要求：

- `ImageSets/Main/train.txt` 必须存在。
- `ImageSets/Main/val.txt` 必须存在。
- `ImageSets/Main/trainval.txt` 可选。
- `ImageSets/Main/test.txt` 可选。

`trainval.txt` 是 `train.txt` 与 `val.txt` 的合集，不参与互斥性检查。正式评估建议提供独立 `test.txt`，但测试集不是标准导入的必需部分。

## zip 包要求

当前阶段默认通过 FastAPI 上传 zip 数据集压缩包。

zip 包应满足：

- zip 内允许存在一层额外包裹目录。
- `JPEGImages`、`Annotations` 和 `ImageSets/Main` 必须位于同一个数据集根目录下。
- `train.txt` 和 `val.txt` 必须位于 `ImageSets/Main`。
- 图片和 XML 标注文件必须位于 zip 内部。
- XML 中的 `filename` 不得指向 zip 外绝对路径。
- XML 中的 `path` 不作为 zip 外图片定位依据。
- 不应包含同名但大小写不同的图片或 XML 路径。
- 不应混入 classification、segmentation、pose、obb 等其他任务的独立标注格式。
- 不应混入不受支持的图片扩展名。

## DatasetVersion 结果

导入成功后生成的 DatasetVersion 满足：

- `task_type=detection`。
- `source_format=voc`。
- 图像按 `train / val / test` split 归档。
- 类别映射统一为连续 0-based 内部 category id。
- VOC 1-based inclusive `xyxy` bbox 统一转换为平台内部 0-based `bbox_xywh`。
- 原始 `filename`、XML 路径和 split 文件来源保留在 metadata 中。
- `difficult / truncated / pose / segmented` 等非核心 detection 字段按 metadata 保留。

## 导出和训练关系

VOC detection DatasetVersion 当前可导出为：

```text
voc-detection-v1
coco-detection-v1
yolo-detection-v1
```

模型默认训练格式：

- `YOLOX detection`：默认使用 `coco-detection-v1`，可使用 `voc-detection-v1`。
- `RF-DETR detection`：使用 `coco-detection-v1`。
- `YOLOv8 / YOLO11 / YOLO26 detection`：默认使用 `yolo-detection-v1`，可使用 `coco-detection-v1`。

导入格式不等同于训练格式。同一份 VOC detection 导入数据先生成 DatasetVersion，再按训练任务需要导出为对应格式。

## 完整示例

目录：

```text
dataset/
├─ JPEGImages/
│  ├─ image_001.jpg
│  ├─ image_002.png
│  └─ image_101.bmp
├─ Annotations/
│  ├─ image_001.xml
│  ├─ image_002.xml
│  └─ image_101.xml
└─ ImageSets/
   └─ Main/
      ├─ train.txt
      ├─ val.txt
      └─ trainval.txt
```

`ImageSets/Main/train.txt`：

```text
image_001
image_002
```

`ImageSets/Main/val.txt`：

```text
image_101
```

`ImageSets/Main/trainval.txt`：

```text
image_001
image_002
image_101
```

`Annotations/image_001.xml`：

```xml
<annotation>
    <folder>JPEGImages</folder>
    <filename>image_001.jpg</filename>
    <size>
        <width>1000</width>
        <height>800</height>
        <depth>3</depth>
    </size>
    <segmented>0</segmented>
    <object>
        <name>type1</name>
        <pose>Unspecified</pose>
        <truncated>0</truncated>
        <difficult>0</difficult>
        <bndbox>
            <xmin>200</xmin>
            <ymin>160</ymin>
            <xmax>600</xmax>
            <ymax>560</ymax>
        </bndbox>
    </object>
    <object>
        <name>type2</name>
        <pose>Unspecified</pose>
        <truncated>0</truncated>
        <difficult>1</difficult>
        <bndbox>
            <xmin>650</xmin>
            <ymin>300</ymin>
            <xmax>830</xmax>
            <ymax>520</ymax>
        </bndbox>
    </object>
</annotation>
```

## 不符合规范的结构

### 缺少 train.txt 或 val.txt

```text
ImageSets/Main/
└─ trainval.txt
```

标准 VOC detection 导入必须包含 `train.txt` 和 `val.txt`。`trainval.txt` 不能替代这两个文件。

### 把 trainval.txt 或 test.txt 当作必需文件

```text
ImageSets/Main/
├─ train.txt
└─ val.txt
```

该结构符合最小标准。`trainval.txt` 和 `test.txt` 可选，不应作为导入必需条件。

### 图像与 XML 文件名不一致

```text
JPEGImages/image_001.jpg
Annotations/label_001.xml
```

图像与标注无法通过基础文件名正确对应。

### XML 中的 filename 错误

实际图像为：

```text
image_001.jpg
```

XML 中记录为：

```xml
<filename>image_002.jpg</filename>
```

XML 文件信息与实际图像不一致。

### 使用错误的边界框格式

```xml
<bndbox>
    <xmin>200</xmin>
    <ymin>160</ymin>
    <width>400</width>
    <height>400</height>
</bndbox>
```

VOC detection 标准边界框应使用 `xmin / ymin / xmax / ymax`。

### 使用归一化坐标

```xml
<bndbox>
    <xmin>0.2</xmin>
    <ymin>0.2</ymin>
    <xmax>0.6</xmax>
    <ymax>0.7</ymax>
</bndbox>
```

VOC detection bbox 使用像素坐标，不使用 0 到 1 的归一化坐标。

### 边界框顺序错误

```xml
<bndbox>
    <xmin>600</xmin>
    <ymin>560</ymin>
    <xmax>200</xmax>
    <ymax>160</ymax>
</bndbox>
```

该边界框不满足 `xmin <= xmax`、`ymin <= ymax`。

### 边界框超出图像范围

图像尺寸为：

```text
1000 x 800
```

标注为：

```xml
<bndbox>
    <xmin>900</xmin>
    <ymin>600</ymin>
    <xmax>1100</xmax>
    <ymax>900</ymax>
</bndbox>
```

`xmax` 和 `ymax` 超出图像尺寸。

### 类别名称为空或不一致

```xml
<name> type1 </name>
```

类别名称不应包含前导或尾随空格。大小写和拼写应在整个数据集中保持一致。

### 图像尺寸记录错误

实际图像尺寸为：

```text
1000 x 800
```

XML 中记录为：

```xml
<size>
    <width>800</width>
    <height>600</height>
    <depth>3</depth>
</size>
```

XML 中的图像尺寸与实际文件不一致。

### split 样本不存在

`train.txt` 中记录：

```text
image_999
```

但不存在：

```text
JPEGImages/image_999.jpg
Annotations/image_999.xml
```

该 split 记录无效。

### 使用不支持的图片格式

```text
JPEGImages/image_001.webp
JPEGImages/image_002.tiff
```

当前 VOC detection 标准导入图片只支持 `.jpg / .jpeg / .png / .bmp`。

## 标准定义总结

VOC 目标检测数据集推荐结构为：

```text
dataset/
├─ JPEGImages/图像文件
├─ Annotations/XML 标注文件
└─ ImageSets/
   └─ Main/
      ├─ train.txt
      ├─ val.txt
      ├─ trainval.txt
      └─ test.txt
```

核心规则：

- 导入任务固定为 `task_type=detection`、`format_type=voc`。
- `train.txt` 和 `val.txt` 必须存在。
- `trainval.txt` 和 `test.txt` 可选。
- 每张图像对应一个同名 XML 文件。
- XML 必须包含 `filename` 和 `size/width / size/height`。
- 有目标图像的每个目标使用一个 `object` 元素。
- 无目标图像可以使用不含 `object` 的 XML。
- 类别通过 `object/name` 定义。
- bbox 格式为 `xmin / ymin / xmax / ymax`。
- bbox 坐标使用像素单位，不使用归一化坐标。
- 平台按 1-based inclusive VOC 坐标读取，导入后转为 0-based `bbox_xywh`。
- 导入图片只支持 `.jpg / .jpeg / .png / .bmp`。
- 导入后生成 DatasetVersion，再按训练任务导出为 `voc-detection-v1 / coco-detection-v1 / yolo-detection-v1`。

## 相关文档

- [classification-dataset-import-format.md](classification-dataset-import-format.md)
- [coco-detection-dataset-import-format.md](coco-detection-dataset-import-format.md)
- [yolo-detection-dataset-import-format.md](yolo-detection-dataset-import-format.md)
- [model-dataset-format-contract.md](model-dataset-format-contract.md)
- [dataset-import-spec.md](dataset-import-spec.md)
- [dataset-export-formats.md](dataset-export-formats.md)
