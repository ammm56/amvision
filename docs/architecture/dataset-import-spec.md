# 数据集导入规范

## 文档目的

本文档用于定义平台中的 DatasetImport、DatasetVersion、通用数据格式、数据集导出和外部数据集格式兼容规则。

本文档解决的问题是“外部数据集如何被导入、校验、归档、标准化并供不同模型训练后端复用”，而不是描述具体训练代码实现。

## 适用范围

- 数据集导入对象链与生命周期
- 外部数据集格式识别、显式声明和导入校验规则
- 通用数据格式的字段定义和任务类型拆分
- detection、instance segmentation、semantic segmentation、pose 的导入格式与导出格式矩阵
- DatasetVersion 与数据集导出的关系

## 非目标

- 不定义具体训练框架内部的数据加载代码
- 不定义标注工具的交互流程
- 不承诺当前仓库已经完整实现本文档列出的所有格式支持
- 不把某个单一模型的文件结构上升为整个平台内部的唯一数据结构

## 核心术语

### Dataset

- 逻辑数据集容器，记录业务身份、用途、标签和长期归属关系

### DatasetImport

- 一次外部数据导入记录
- 记录 source format、task type、image root、annotation root、manifest file、split 信息、class map、导入时间、校验结果和导入日志

### DatasetVersion

- 导入并整理后的固定数据版本
- 是训练、验证、推理回放和流程执行的稳定输入对象

### 通用数据格式

- 平台内部统一使用的数据格式
- 用统一字段描述样本、类别、任务类型和任务特定标注内容

### DatasetExport

- 从 DatasetVersion 按 format id 派生出的格式化输出
- 可以临时生成，也可以保存到 exports 目录
- DatasetExport 不是正式数据版本

## 总体原则

- 外部格式兼容与内部通用格式分离
- 自动识别只作为导入便利能力，不作为最终判断
- DatasetVersion 生成后按不可修改的数据版本处理
- 原始导入内容、统一版本内容和训练导出内容分层存放，不混用目录
- 不同模型共享的是 task type 和通用数据格式，不是完全相同的原始标注文件结构
- 当前阶段默认通过 FastAPI 接收 zip 数据集压缩包，服务端负责解压、校验、转成通用数据格式并保存到本地磁盘
- 训练、验证和推理默认读取平台内部统一结构；只有在导出时才回到目标模型需要的目录和文件格式

## 当前第一阶段实现范围

- 第一阶段导入接口只实现 detection task type 的数据集导入
- 第一阶段只支持两种外部格式：COCO detection json 和 Pascal VOC detection xml
- COCO 第一阶段只接受 bbox 检测标注；segmentation、keypoints 等字段如存在，只保留原始值，不写入 detection 通用字段
- Pascal VOC 第一阶段只接受 object/bndbox 检测标注；segmented、part、action 等扩展信息不写入 detection 通用字段
- 输入统一为 zip 压缩包；zip 内允许存在一层额外包裹目录，导入器应先消除单层包裹目录后再识别结构
- zip 中所有图片和标注都必须位于压缩包内部；不接受 xml 或 json 指向 zip 外绝对路径的情况

## 对象链与生命周期

```text
Project
  -> Dataset
    -> DatasetImport
      -> DatasetVersion
      -> DatasetExport
```

### 生命周期阶段

1. discovered：接收 zip 数据集压缩包并形成待导入记录
2. detected：产生一个或多个候选格式判断
3. confirmed：确认 format type、task type、class map、split strategy
4. validated：完成结构与内容校验
5. normalized：转成通用数据格式
6. versioned：生成可复用的 DatasetVersion
7. exported：按需生成数据集导出结果

## 实现分层建议

- FastAPI 接口只接收两类输入：导入时上传 zip 数据集压缩包并提供或确认格式；导出时提供 DatasetVersion 和 format id
- application/datasets/imports 负责接上传、识别格式、解析内容、校验字段并转成通用数据格式
- 导入流程应先把 zip 包保存到本地磁盘的 imports 目录，再解压到 staging，校验通过后写入 DatasetVersion 的统一目录
- domain/datasets 只保留平台内部通用格式，不直接依赖 COCO、VOC、YOLO、SAM 的原始目录写法
- application/datasets/exports 负责把 DatasetVersion 按 format id 导出成训练、验证或评估要用的目录和 manifest
- workers/training 和 workers/validation 只消费数据集导出结果，不直接读取原始导入包
- contracts/datasets/imports 和 contracts/datasets/exports 分别定义导入格式和导出格式规则，避免把格式细节散落在训练代码里

## 导入输入模型

### 最小导入声明

- format type：如 yolo, coco, voc, masks, custom-json
- task type：如 detection, instance-segmentation, semantic-segmentation, pose
- image root
- annotation root 或 manifest file
- split strategy：显式 train/val/test 或导入后切分
- class map：类别 id 与名称映射
- optional attributes：场景标签、采集来源、设备信息、难例标记等

### 自动识别策略

- 自动识别应根据目录签名、文件扩展名、manifest 内容和标注字段进行候选判断
- 若候选格式唯一且字段完整，可直接给出高置信度建议
- 若存在多个候选格式、目录结构不对齐、类别冲突或混合任务标注，则必须要求显式确认
- 最终写入数据库的应是确认后的 format type 与 task type，而不是某次推断结果

### 推荐支持的外部输入形态

- zip 压缩包，内部包含 YOLO、COCO、VOC、mask 目录或其他标准数据集结构
- 图像目录 + 标注目录
- 图像目录 + 单一 manifest 文件
- 图像目录 + mask 目录
- 已包含 split 的目录树
- 未包含 split，需要导入时切分的数据包

## 本地存储分层

- imports：保存原始 zip 包、导入日志和解压 staging
- versions：保存转成通用数据格式后的数据、索引和统计信息
- exports：保存按 format id 生成的数据集导出结果
- 训练、验证和推理默认读取 versions，不直接读取 imports 下的原始压缩包或解压目录

### 上传、解压、校验和生成版本后的目录层次

```text
projects/{project_id}/datasets/{dataset_id}/
├─ imports/
│  └─ {dataset_import_id}/
│     ├─ package.zip
│     ├─ manifests/
│     │  ├─ upload-request.json
│     │  └─ detected-profile.json
│     ├─ staging/
│     │  └─ extracted/
│     └─ logs/
│        ├─ validation-report.json
│        └─ import.log
└─ versions/
   └─ {dataset_version_id}/
      ├─ manifests/
      │  ├─ dataset-version.json
      │  └─ categories.json
      ├─ images/
      │  ├─ train/
      │  ├─ val/
      │  └─ test/
      ├─ samples/
      │  ├─ train/
      │  ├─ val/
      │  └─ test/
      └─ indexes/
         ├─ train.json
         ├─ val.json
         └─ test.json
```

- package.zip：保存原始上传压缩包，作为审计和问题复现依据
- manifests/upload-request.json：保存导入时显式传入的 format type、task type、split strategy 和 class map
- manifests/detected-profile.json：保存自动识别出的候选格式、目录签名和最终确认结果
- staging/extracted：保存安全解压后的原始目录，只作为校验和格式转换输入，不作为长期训练输入
- logs/validation-report.json：保存结构化校验结果、错误清单和警告清单
- versions/{dataset_version_id}：保存生成后的统一数据版本，是训练、验证和导出使用的正式输入

## 推荐的外部导入目录模式

### 模式 A：图像与标注平行目录

```text
dataset-root/
├─ images/
│  ├─ train/
│  ├─ val/
│  └─ test/
└─ labels/
   ├─ train/
   ├─ val/
   └─ test/
```

适用于 YOLO detection、YOLO instance segmentation、YOLO pose 等目录型格式。

### 模式 B：图像目录 + 单一注释文件

```text
dataset-root/
├─ images/
└─ annotations/
   ├─ instances_train.json
   ├─ instances_val.json
   └─ person_keypoints_train.json
```

适用于 COCO detection、COCO instance segmentation、COCO keypoints 等 manifest 型格式。

### 模式 C：图像目录 + mask 目录

```text
dataset-root/
├─ images/
│  ├─ train/
│  └─ val/
└─ masks/
   ├─ train/
   └─ val/
```

适用于 semantic segmentation 的图像与掩码配对导入。

### 模式 D：图像目录 + XML 标注目录

```text
dataset-root/
├─ JPEGImages/
├─ Annotations/
└─ ImageSets/
```

适用于 Pascal VOC detection 风格数据。

## 第一阶段支持的输入格式细则

### COCO detection zip

#### 推荐目录结构

```text
dataset-root/
├─ annotations/
│  ├─ instances_train.json
│  ├─ instances_val.json
│  └─ instances_test.json
├─ train/
├─ val/
└─ test/
```

或：

```text
dataset-root/
├─ annotations/
│  ├─ instances_train2017.json
│  └─ instances_val2017.json
├─ train2017/
└─ val2017/
```

或：

```text
dataset-root/
├─ train/
│  ├─ train-1.jpg
│  └─ _annotations.coco.json
├─ valid/
│  ├─ valid-1.jpg
│  └─ _annotations.coco.json
└─ test/
   ├─ test-1.jpg
   └─ _annotations.coco.json
```

上面这类 split 目录内各自携带 manifest 的布局常见于 Roboflow 导出的 COCO detection zip。

#### 图片与标注位置

- 标注文件默认位于 annotations 目录下，文件名优先识别 instances_train.json、instances_val.json、instances_test.json，以及带年份后缀的 instances_train2017.json、instances_val2017.json
- 也接受 train、val、valid、test 目录内各自携带的 COCO manifest，例如 _annotations.coco.json 这类 split-local manifest
- 图片目录默认位于 train、val、test、train2017、val2017、test2017，或 images/{split} 这类与 split 对应的目录中
- images[*].file_name 可以是纯文件名，也可以是相对路径；导入时应优先按 file_name 自带相对路径解析，其次按 manifest 对应 split 的图片目录解析

#### 标注 JSON 结构与字段

- 顶层必须至少包含 images、annotations、categories 三个数组；info 和 licenses 可选
- images 数组第一阶段必需字段：id、file_name、width、height
- categories 数组第一阶段必需字段：id、name；supercategory 可选
- annotations 数组第一阶段必需字段：image_id、category_id、bbox
- annotations.id、annotations.area、annotations.iscrowd 为推荐字段；若缺失，area 可由 bbox 自动计算，iscrowd 默认视为 0
- bbox 必须是长度为 4 的数组，语义固定为 [x, y, width, height]，单位为像素
- segmentation、keypoints、num_keypoints 等字段若存在，第一阶段 detection 导入链只记录原始值，不写入 detection 通用字段

#### split 推断规则

- 若 manifest 位于 train、val、valid、test 这类 split 目录下，则优先用父目录名推断 split；valid 应归一化为 val
- 若父目录不携带 split 语义，且 manifest 文件名包含 train、val、test 语义，则再用文件名推断 split
- 若只有一个 manifest 且文件名不带 split 语义，则优先使用显式导入参数中的 split strategy；未显式提供时默认整包视为 train
- 同一图片不得同时出现在多个 split manifest 中

### Pascal VOC detection zip

#### 推荐目录结构

```text
dataset-root/
├─ JPEGImages/
│  ├─ 000001.jpg
│  └─ 000002.jpg
├─ Annotations/
│  ├─ 000001.xml
│  └─ 000002.xml
└─ ImageSets/
    └─ Main/
         ├─ train.txt
         ├─ val.txt
         ├─ trainval.txt
         └─ test.txt
```

#### 图片与标注位置

- 图片默认位于 JPEGImages 目录
- XML 标注默认位于 Annotations 目录，通常与图片同名但扩展名为 xml
- split 文件默认位于 ImageSets/Main；若存在 train.txt、val.txt、test.txt，则按文件中的样本 stem 归入对应 split
- 若不存在 ImageSets/Main，导入流程应依赖显式 split strategy；未显式提供时默认全部归入 train

#### XML 结构与字段

- 根节点应为 annotation
- 第一阶段必需字段：filename、size/width、size/height、至少一个 object
- 每个 object 第一阶段必需字段：name、bndbox/xmin、bndbox/ymin、bndbox/xmax、bndbox/ymax
- size/depth、folder、path、segmented、object/pose、object/truncated、object/difficult 为可选字段
- bbox 在 Pascal VOC 中语义为左上和右下角坐标，导入时应转换为 detection 通用格式使用的 bbox_xywh_abs
- difficult、truncated、pose 等字段若存在，应保留到 annotation metadata 中，而不是丢失

#### 样本匹配规则

- 首选 XML 文件 stem 与图片文件 stem 一致的配对方式
- 若 XML 中 filename 与 stem 不一致，则以 XML.filename 为准，但必须能在 JPEGImages 或显式 image root 下定位到对应图片
- Annotations 中的每个 xml 都必须能匹配到一张图片；存在孤立 xml 或孤立图片时应给出结构化校验错误或警告

## 第一阶段 detection 通用格式

第一阶段内部统一格式只保存 detection 数据，但目录结构和字段命名继续为后续其他 task type 预留扩展空间。

### 统一规则

- 所有导入结果统一生成 DatasetVersion，task_type 固定为 detection
- categories 在生成版本时统一重排为连续的 0-based category_id，外部原始 id 或 name 通过 metadata 保留
- COCO detection 的 bbox 直接使用 [x, y, width, height] 像素坐标写入通用格式
- Pascal VOC detection 的 xmin、ymin、xmax、ymax 在生成版本时统一转换为 bbox_xywh_abs
- sample 的 image_ref 必须指向 versions/{dataset_version_id}/images/{split}/ 下的相对 object key，不保留绝对磁盘路径
- source_format、source_annotation_id、source_path、difficult、truncated、iscrowd 等外部格式字段应保留到 sample 或 annotation metadata 中，避免后续追溯丢失信息

### 生成版本后的统一目录结构

```text
versions/{dataset_version_id}/
├─ manifests/
│  ├─ dataset-version.json
│  └─ categories.json
├─ images/
│  ├─ train/
│  ├─ val/
│  └─ test/
├─ samples/
│  ├─ train/
│  ├─ val/
│  └─ test/
└─ indexes/
    ├─ train.json
    ├─ val.json
    └─ test.json
```

- manifests/dataset-version.json：保存 dataset_version_id、dataset_id、source_import_id、task_type、split_summary、sample_count、annotation_count 等版本元数据
- manifests/categories.json：保存当前版本的类别顺序、category_id、name 和来源映射信息
- images/{split}：保存当前版本实际使用的图片内容，文件名应稳定且可追溯
- samples/{split}/{sample_id}.json：保存单个样本记录，包括 image_ref、width、height、source_path、annotations 和 metadata
- indexes/{split}.json：保存 split 级索引、样本 id 列表和统计信息，供 exporter 和训练前检查快速读取

### 单样本记录示例

```json
{
   "sample_id": "sample-000001",
   "split": "train",
   "image_ref": {
      "object_key": "images/train/000001.jpg"
   },
   "file_name": "000001.jpg",
   "width": 1280,
   "height": 720,
   "source_path": "JPEGImages/000001.jpg",
   "annotations": [
      {
         "annotation_id": "annotation-000001",
         "task_type": "detection",
         "category_id": 0,
         "bbox_xywh_abs": [10, 20, 30, 40],
         "area": 1200,
         "iscrowd": 0,
         "source_format": "voc",
         "metadata": {
            "difficult": 0,
            "truncated": 0
         }
      }
   ]
}
```

## 通用数据格式

### 设计目标

- 统一平台内部对样本、类别和标注的管理方式
- 支撑多种外部格式导入和多种数据集导出格式
- 把 detection、instance segmentation、semantic segmentation、pose 区分为不同任务类型，但共享统一的样本与版本管理边界

### 公共结构

#### dataset manifest

- dataset_id
- dataset_version_id
- task_type
- source_import_id
- source_format
- created_at
- split_summary
- class_count
- sample_count
- annotation_count

#### categories

- category_id
- name
- supercategory
- color
- aliases
- attributes schema
- keypoint schema or skeleton definition when applicable

#### samples

- sample_id
- image_ref
- width
- height
- channels
- split
- source_path
- capture metadata
- tags

#### annotations 共通字段

- annotation_id
- sample_id
- task_type
- category_id
- source_annotation_id
- source_format
- attributes
- ignored
- iscrowd
- confidence when imported from machine generated labels

### detection 载荷

- bbox_xywh_abs
- area
- optional rotation

### instance segmentation 载荷

- polygon list 或 mask_ref
- optional bbox_xywh_abs
- area

### semantic segmentation 载荷

- mask_ref
- label_encoding
- palette or class_value_map
- optional tile metadata

### pose 载荷

- keypoints list
- visibility flags
- skeleton_ref
- optional bbox_xywh_abs

### 字段级 JSON Schema 草案

以下草案继续把通用数据格式整理成字段级规则，后续可以放到 contracts 或独立 schema 文件中。当前目标是先把稳定字段定清楚，而不是一次列完所有扩展属性。

```json
{
   "$schema": "https://json-schema.org/draft/2020-12/schema",
   "$id": "amvision.dataset.schema.v1.json",
   "title": "AmVision DatasetVersion Schema",
   "type": "object",
   "additionalProperties": false,
   "required": [
      "dataset_id",
      "dataset_version_id",
      "task_type",
      "source_import_id",
      "source_format",
      "created_at",
      "categories",
      "samples",
      "annotations"
   ],
   "properties": {
      "dataset_id": {
         "type": "string",
         "minLength": 1
      },
      "dataset_version_id": {
         "type": "string",
         "minLength": 1
      },
      "task_type": {
         "type": "string",
         "enum": [
            "detection",
            "instance-segmentation",
            "semantic-segmentation",
            "pose"
         ]
      },
      "source_import_id": {
         "type": "string",
         "minLength": 1
      },
      "source_format": {
         "type": "string",
         "minLength": 1
      },
      "created_at": {
         "type": "string",
         "format": "date-time"
      },
      "split_summary": {
         "$ref": "#/$defs/split_summary"
      },
      "categories": {
         "type": "array",
         "items": {
            "$ref": "#/$defs/category"
         }
      },
      "samples": {
         "type": "array",
         "items": {
            "$ref": "#/$defs/sample"
         }
      },
      "annotations": {
         "type": "array",
         "items": {
            "anyOf": [
               {
                  "$ref": "#/$defs/detection_annotation"
               },
               {
                  "$ref": "#/$defs/instance_segmentation_annotation"
               },
               {
                  "$ref": "#/$defs/semantic_segmentation_annotation"
               },
               {
                  "$ref": "#/$defs/pose_annotation"
               }
            ]
         }
      }
   },
   "$defs": {
      "object_ref": {
         "type": "object",
         "additionalProperties": false,
         "required": [
            "object_key"
         ],
         "properties": {
            "object_key": {
               "type": "string",
               "minLength": 1
            },
            "media_type": {
               "type": "string"
            },
            "checksum": {
               "type": "string"
            },
            "size_bytes": {
               "type": "integer",
               "minimum": 0
            }
         }
      },
      "split_summary": {
         "type": "object",
         "additionalProperties": false,
         "properties": {
            "train": {
               "type": "integer",
               "minimum": 0
            },
            "val": {
               "type": "integer",
               "minimum": 0
            },
            "test": {
               "type": "integer",
               "minimum": 0
            },
            "unassigned": {
               "type": "integer",
               "minimum": 0
            }
         }
      },
      "category": {
         "type": "object",
         "additionalProperties": false,
         "required": [
            "category_id",
            "name"
         ],
         "properties": {
            "category_id": {
               "type": "integer",
               "minimum": 0
            },
            "name": {
               "type": "string",
               "minLength": 1
            },
            "supercategory": {
               "type": "string"
            },
            "color": {
               "type": "string"
            },
            "aliases": {
               "type": "array",
               "items": {
                  "type": "string"
               }
            },
            "attributes_schema": {
               "type": "object",
               "additionalProperties": true
            },
            "keypoint_schema": {
               "type": "array",
               "items": {
                  "type": "string"
               }
            },
            "skeleton_definition": {
               "type": "array",
               "items": {
                  "type": "array",
                  "items": {
                     "type": "integer",
                     "minimum": 0
                  },
                  "minItems": 2,
                  "maxItems": 2
               }
            }
         }
      },
      "sample": {
         "type": "object",
         "additionalProperties": false,
         "required": [
            "sample_id",
            "image_ref",
            "width",
            "height",
            "split"
         ],
         "properties": {
            "sample_id": {
               "type": "string",
               "minLength": 1
            },
            "image_ref": {
               "$ref": "#/$defs/object_ref"
            },
            "width": {
               "type": "integer",
               "minimum": 1
            },
            "height": {
               "type": "integer",
               "minimum": 1
            },
            "channels": {
               "type": "integer",
               "minimum": 1
            },
            "split": {
               "type": "string",
               "enum": [
                  "train",
                  "val",
                  "test",
                  "unassigned"
               ]
            },
            "source_path": {
               "type": "string"
            },
            "capture_metadata": {
               "type": "object",
               "additionalProperties": true
            },
            "tags": {
               "type": "array",
               "items": {
                  "type": "string"
               }
            }
         }
      },
      "base_annotation": {
         "type": "object",
         "additionalProperties": false,
         "required": [
            "annotation_id",
            "sample_id",
            "task_type"
         ],
         "properties": {
            "annotation_id": {
               "type": "string",
               "minLength": 1
            },
            "sample_id": {
               "type": "string",
               "minLength": 1
            },
            "task_type": {
               "type": "string"
            },
            "category_id": {
               "type": [
                  "integer",
                  "null"
               ],
               "minimum": 0
            },
            "source_annotation_id": {
               "type": "string"
            },
            "source_format": {
               "type": "string"
            },
            "attributes": {
               "type": "object",
               "additionalProperties": true
            },
            "ignored": {
               "type": "boolean"
            },
            "iscrowd": {
               "type": "boolean"
            },
            "confidence": {
               "type": "number",
               "minimum": 0,
               "maximum": 1
            }
         }
      },
      "detection_payload": {
         "type": "object",
         "additionalProperties": false,
         "required": [
            "bbox_xywh_abs",
            "area"
         ],
         "properties": {
            "bbox_xywh_abs": {
               "type": "array",
               "items": {
                  "type": "number",
                  "minimum": 0
               },
               "minItems": 4,
               "maxItems": 4
            },
            "area": {
               "type": "number",
               "minimum": 0
            },
            "rotation_deg": {
               "type": "number"
            }
         }
      },
      "instance_segmentation_payload": {
         "type": "object",
         "additionalProperties": false,
         "required": [
            "area"
         ],
         "properties": {
            "polygons": {
               "type": "array",
               "items": {
                  "type": "array",
                  "items": {
                     "type": "number",
                     "minimum": 0
                  },
                  "minItems": 6
               }
            },
            "mask_ref": {
               "$ref": "#/$defs/object_ref"
            },
            "bbox_xywh_abs": {
               "type": "array",
               "items": {
                  "type": "number",
                  "minimum": 0
               },
               "minItems": 4,
               "maxItems": 4
            },
            "area": {
               "type": "number",
               "minimum": 0
            }
         },
         "anyOf": [
            {
               "required": [
                  "polygons"
               ]
            },
            {
               "required": [
                  "mask_ref"
               ]
            }
         ]
      },
      "semantic_segmentation_payload": {
         "type": "object",
         "additionalProperties": false,
         "required": [
            "mask_ref",
            "label_encoding"
         ],
         "properties": {
            "mask_ref": {
               "$ref": "#/$defs/object_ref"
            },
            "label_encoding": {
               "type": "string",
               "enum": [
                  "class-index-mask",
                  "palette-mask",
                  "rle-manifest"
               ]
            },
            "class_value_map": {
               "type": "object",
               "additionalProperties": {
                  "type": "integer",
                  "minimum": 0
               }
            },
            "palette": {
               "type": "array",
               "items": {
                  "type": "string"
               }
            },
            "tile_metadata": {
               "type": "object",
               "additionalProperties": false,
               "properties": {
                  "row_index": {
                     "type": "integer",
                     "minimum": 0
                  },
                  "col_index": {
                     "type": "integer",
                     "minimum": 0
                  },
                  "total_rows": {
                     "type": "integer",
                     "minimum": 1
                  },
                  "total_cols": {
                     "type": "integer",
                     "minimum": 1
                  }
               }
            }
         }
      },
      "pose_keypoint": {
         "type": "object",
         "additionalProperties": false,
         "required": [
            "x",
            "y",
            "visibility"
         ],
         "properties": {
            "x": {
               "type": "number",
               "minimum": 0
            },
            "y": {
               "type": "number",
               "minimum": 0
            },
            "visibility": {
               "type": "integer",
               "enum": [
                  0,
                  1,
                  2
               ]
            },
            "label": {
               "type": "string"
            }
         }
      },
      "pose_payload": {
         "type": "object",
         "additionalProperties": false,
         "required": [
            "keypoints"
         ],
         "properties": {
            "keypoints": {
               "type": "array",
               "items": {
                  "$ref": "#/$defs/pose_keypoint"
               }
            },
            "skeleton_ref": {
               "type": "string"
            },
            "bbox_xywh_abs": {
               "type": "array",
               "items": {
                  "type": "number",
                  "minimum": 0
               },
               "minItems": 4,
               "maxItems": 4
            }
         }
      },
      "detection_annotation": {
         "allOf": [
            {
               "$ref": "#/$defs/base_annotation"
            },
            {
               "type": "object",
               "required": [
                  "task_type",
                  "category_id",
                  "payload"
               ],
               "properties": {
                  "task_type": {
                     "const": "detection"
                  },
                  "payload": {
                     "$ref": "#/$defs/detection_payload"
                  }
               }
            }
         ]
      },
      "instance_segmentation_annotation": {
         "allOf": [
            {
               "$ref": "#/$defs/base_annotation"
            },
            {
               "type": "object",
               "required": [
                  "task_type",
                  "category_id",
                  "payload"
               ],
               "properties": {
                  "task_type": {
                     "const": "instance-segmentation"
                  },
                  "payload": {
                     "$ref": "#/$defs/instance_segmentation_payload"
                  }
               }
            }
         ]
      },
      "semantic_segmentation_annotation": {
         "allOf": [
            {
               "$ref": "#/$defs/base_annotation"
            },
            {
               "type": "object",
               "required": [
                  "task_type",
                  "payload"
               ],
               "properties": {
                  "task_type": {
                     "const": "semantic-segmentation"
                  },
                  "payload": {
                     "$ref": "#/$defs/semantic_segmentation_payload"
                  }
               }
            }
         ]
      },
      "pose_annotation": {
         "allOf": [
            {
               "$ref": "#/$defs/base_annotation"
            },
            {
               "type": "object",
               "required": [
                  "task_type",
                  "category_id",
                  "payload"
               ],
               "properties": {
                  "task_type": {
                     "const": "pose"
                  },
                  "payload": {
                     "$ref": "#/$defs/pose_payload"
                  }
               }
            }
         ]
      }
   }
}
```

### Schema 草案说明

- 该草案定义的是 DatasetVersion 的通用数据格式，不是原始导入包结构
- capture_metadata、attributes 和 attributes_schema 暂时保留开放扩展，避免过早把现场场景字段写死
- semantic segmentation 允许 category_id 为空，因为单个 mask 可能表示多类像素映射
- 数据集导出应从这个通用数据格式派生，而不是反向把某个导出格式当成正式来源

## 导入校验规则

- zip 解压必须先做路径规范化校验，拒绝绝对路径、.. 穿越路径和非法符号链接
- image root 和 annotation root 必须可解析且可枚举
- 图片与标注之间必须存在稳定匹配关系
- 类别 id、名称和类别数量必须自洽
- bbox、polygon、mask 和 keypoints 必须满足几何合法性校验
- split 信息若缺失，应明确记录为导入后切分
- 不同任务类型的标签不得在同一 DatasetVersion 中无约束混放
- 导入失败应产出结构化错误清单，而不是只给笼统异常提示
- COCO detection 中每个 annotation.image_id 都必须能映射到一个 images.id，且 bbox 宽高必须大于 0
- Pascal VOC detection 中每个 object 都必须包含合法的 xmin < xmax、ymin < ymax，且 xml 必须能定位到实际图片文件

## 数据集导出规则

- 训练、验证或评估前应从 DatasetVersion 生成指定格式的数据集导出结果
- 数据集导出可以写入 ObjectStore 的 exports 路径，也可以作为任务级临时产物
- 数据集导出应记录 source dataset version、target format、class map 和导出时间
- 导出失败不应影响既有 DatasetVersion 的稳定性
- 数据集导出默认不作为新的正式数据版本，除非显式发起新的导入或回写流程

## 任务类型格式矩阵

下表中的“第一阶段支持”表示优先实现的格式，“扩展支持”表示后续可逐步补充。

### detection

| 项目 | 内容 |
| --- | --- |
| 任务类型 | detection |
| 第一阶段导入格式 | COCO detection json, Pascal VOC xml |
| 扩展导入格式 | YOLO detection, LabelMe rectangle json, CVAT detection export, custom csv/json manifest |
| 第一阶段导出格式 | COCO detection |
| 扩展导出格式 | YOLO detection, Pascal VOC xml, backend-specific detection manifest |
| 常见模型/后端 | YOLOX, YOLOv8 detection, YOLOv11 detection, RT-DETR |
| 说明 | RT-DETR 与 YOLO 可以共用 detection 通用格式，但导出格式通常不同 |

### instance segmentation

| 项目 | 内容 |
| --- | --- |
| 任务类型 | instance-segmentation |
| 第一阶段导入格式 | COCO instance segmentation, YOLO segmentation |
| 扩展导入格式 | LabelMe polygon json, CVAT polygon export, Supervisely instance export |
| 第一阶段导出格式 | COCO instance segmentation, YOLO segmentation |
| 扩展导出格式 | polygon manifest, mask package manifest |
| 常见模型/后端 | YOLOv8 seg, YOLOv11 seg, Mask-oriented pipelines |
| 说明 | polygon 与 mask 可以放在同一套通用格式里，但导出时要按目标训练后端选择一种主表示 |

### semantic segmentation

| 项目 | 内容 |
| --- | --- |
| 任务类型 | semantic-segmentation |
| 第一阶段导入格式 | image+mask directory, custom mask manifest |
| 扩展导入格式 | COCO semantic-like export, CVAT mask export, grayscale label maps |
| 第一阶段导出格式 | image+mask directory, semantic segmentation manifest |
| 扩展导出格式 | backend-specific dataset manifest |
| 常见模型/后端 | U-Net 系列, DeepLab 系列, MMSeg-style pipelines |
| 说明 | semantic segmentation 的核心是样本级 mask_ref 与类值映射，不应与 instance segmentation 混成同一导出格式 |

### pose

| 项目 | 内容 |
| --- | --- |
| 任务类型 | pose |
| 第一阶段导入格式 | COCO keypoints, YOLO pose |
| 扩展导入格式 | CVAT keypoints export, custom keypoints manifest |
| 第一阶段导出格式 | COCO keypoints, YOLO pose |
| 扩展导出格式 | backend-specific pose manifest |
| 常见模型/后端 | YOLO pose, keypoint estimation pipelines |
| 说明 | pose 除类别外还需要 keypoint schema 与 skeleton 定义，不能只靠 bbox 或类别表描述 |

## 模型与数据集导出格式的关系

- YOLO 系列通常直接消费 YOLO detection、YOLO segmentation、YOLO pose 数据集导出格式
- RT-DETR 更适合消费 COCO detection 风格数据集导出格式
- SAM 相关流程更适合消费 instance segmentation 或 semantic segmentation 的通用数据格式，再按具体训练或微调工具导出成对应格式
- 同一 DatasetVersion 可以对应多个数据集导出结果，但这些结果都应追溯到同一个固定版本

更细的格式命名、目录结构和模型默认格式映射见 [docs/architecture/dataset-export-formats.md](dataset-export-formats.md)。

## 建议目录位置

- contracts/datasets/schema：放通用数据格式定义
- contracts/datasets/imports：放外部格式 profile 与导入声明结构
- contracts/datasets/exports：放数据集导出格式规则
- adapters/object-store/datasets/imports：放原始导入包、staging 和导入日志
- adapters/object-store/datasets/versions：放生成后的统一版本内容
- adapters/object-store/datasets/exports：放按需生成的数据集导出结果

## 推荐后续文档

- [docs/architecture/data-and-files.md](data-and-files.md)
- [docs/architecture/dataset-export-formats.md](dataset-export-formats.md)
- [docs/architecture/project-structure.md](project-structure.md)
- [docs/architecture/backend-service.md](backend-service.md)