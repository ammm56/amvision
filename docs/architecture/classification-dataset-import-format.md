# 图像分类数据集导入格式规范

## 文档目的

本文档定义平台当前单标签图像分类数据集的标准导入目录、标签来源、类别约束、图像约束和不符合规范的结构。

本文档只覆盖单标签图像分类。多标签分类、目标检测、实例分割、姿态估计和 OBB 旋转框不使用本文档格式。

## 适用范围

当前分类导入格式对应 DatasetImport 的：

- `task_type=classification`
- `format_type=imagenet`

当前适用模型：

- `YOLOv8 classification`
- `YOLO11 classification`
- `YOLO26 classification`

YOLOX 和 RF-DETR 当前不提供 classification 公开主链。

## 核心定义

单标签图像分类数据集要求每张图像只属于一个类别。类别由图像所在的类别目录确定，不需要为每张图像建立单独标签文件。

示例：

```text
train/type1/image_001.jpg
```

该图像类别为：

```text
type1
```

## 标准目录结构

```text
dataset/
├─ train/
│  ├─ type1/
│  │  ├─ image_001.jpg
│  │  └─ ...
│  ├─ type2/
│  │  ├─ image_001.jpg
│  │  └─ ...
│  └─ ...
├─ val/
│  ├─ type1/
│  ├─ type2/
│  └─ ...
└─ test/
   ├─ type1/
   ├─ type2/
   └─ ...
```

目录含义：

- `dataset`：数据集根目录。
- `train`：训练集目录。
- `val`：验证集目录。
- `test`：测试集目录，可选。
- `type1 / type2`：类别目录，目录名即类别名称。
- 类别目录中的文件为该类别的图像样本。

## 最小标准目录结构

```text
dataset/
├─ train/
│  ├─ type1/
│  └─ type2/
└─ val/
   ├─ type1/
   └─ type2/
```

训练集和验证集是标准分类数据集的基本组成部分。测试集可根据项目需求增加。

## 当前兼容结构

当前导入器还兼容无 split 的 ImageNet 风格根目录：

```text
dataset/
├─ type1/
└─ type2/
```

该结构会被导入器默认归入 `train`，除非请求中通过 `split_strategy=train / val / test` 显式强制指定。该结构只作为兼容输入，不作为标准推荐结构。

## 标签规则

- 图像类别由其所在的类别目录确定。
- 分类数据集不读取 YOLO detection 标签文件、COCO annotation json、VOC xml 或 DOTA txt 作为分类标签。
- 每张图像必须且只能对应一个类别目录。
- 导入后 DatasetVersion 中每个样本生成一条 `ClassificationAnnotation`。
- 类别编号由导入器按类别顺序生成连续的 0-based `category_id`，训练、验证、导出和部署必须使用同一份类别映射。

## 类别要求

各 split 中的类别目录名称应保持一致。

正确示例：

```text
train/type1/
val/type1/
test/type1/
```

类别名称要求：

- 名称唯一。
- 拼写和大小写一致。
- 不包含前导或尾随空格。
- 不包含路径分隔符。
- 不使用 `.` 或 `..`。
- 避免使用不兼容的特殊字符。
- 数据集确定后不随意修改类别名。

类别目录名称会进入 DatasetVersion 的 `categories`，也会用于 `imagenet-classification-v1` 导出目录。因此类别名必须可以作为安全的单层目录名。

## 图像要求

图像文件要求：

- 文件能够正常读取。
- 文件内容与扩展名一致。
- 图像具有有效宽度和高度。
- 图像存放在正确的类别目录中。
- 一张图像只属于一个类别。
- train、val、test 之间不存在重复样本。
- 同一来源的高度相似样本应放在同一个 split 中，避免数据泄漏。

当前导入器支持的图片扩展名：

```text
.jpg
.jpeg
.png
.bmp
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
classification-dataset.zip
└─ dataset/
   ├─ train/
   ├─ val/
   └─ test/
```

或：

```text
classification-dataset.zip
├─ train/
├─ val/
└─ test/
```

zip 内文件路径必须是安全相对路径，不允许绝对路径和 `..`。

## class_map_json 规则

导入请求可通过 `class_map_json` 覆盖类别名称。classification 数据集支持用原类别目录名作为 key：

```json
{
  "type1": "ok",
  "type2": "ng"
}
```

覆盖后的类别名仍必须满足安全单层目录名要求。

## 不符合规范的结构

### 图像未按类别分目录

```text
train/
├─ image_001.jpg
└─ image_002.jpg
```

该结构无法通过目录确定图像类别。

### 不同 split 中类别名称不一致

```text
train/type1/
val/Type1/
test/type_1/
```

上述目录名称会被视为不同类别，不符合标准单标签分类数据集要求。

### 同一图像属于多个类别

```text
train/type1/image_001.jpg
train/type2/image_001.jpg
```

该结构不符合单标签分类定义。

### 使用目标检测标签格式

```text
class_id x_center y_center width height
```

该格式用于目标检测任务，不属于图像分类数据集规范。

### 类别目录使用多层路径

```text
train/type/group1/image_001.jpg
```

classification 类别名称必须来自 split 下的第一层目录。多层目录会破坏类别名和文件归属边界，不作为标准结构。

## DatasetVersion 结果

导入成功后生成的 DatasetVersion 满足：

- `task_type=classification`
- `categories` 为导入后的类别列表
- 每张图片对应一个 `DatasetSample`
- 每个样本包含且只包含一条 `ClassificationAnnotation`
- 样本 `split` 为 `train / val / test`
- 原始类别目录名写入样本或 annotation metadata

## 导出和训练关系

classification DatasetVersion 当前只能导出为：

```text
imagenet-classification-v1
```

导出目录包含：

```text
export-root/
├─ manifest.json
├─ annotations/{split}.json
└─ {split}/{class_name}/
```

训练任务应消费 DatasetExport 的 `manifest_object_key` 或 `dataset_export_id`，不直接读取原始导入 zip。

## 标准定义总结

图像分类数据集标准结构：

```text
数据集根目录/
├─ train/
│  ├─ type1/图像文件
│  ├─ type2/图像文件
│  └─ ...
├─ val/
│  ├─ type1/图像文件
│  ├─ type2/图像文件
│  └─ ...
└─ test/
   ├─ type1/图像文件
   ├─ type2/图像文件
   └─ ...
```

核心规则：

- 按 train、val、test 划分数据。
- 每个 split 下按类别建立目录。
- 类别目录名称即类别标签。
- 每张图像仅对应一个类别。
- 各 split 中的类别名称保持一致。
- 分类数据集不需要边界框标注文件。
- test 可选，正式评估建议使用独立 test。

## 相关文档

- [dataset-import-spec.md](dataset-import-spec.md)
- [model-dataset-format-contract.md](model-dataset-format-contract.md)
- [dataset-export-formats.md](dataset-export-formats.md)
