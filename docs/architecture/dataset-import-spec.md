# 数据集导入规范

## 文档目的

本文档用于正式定义平台中 DatasetImport、DatasetVersion、canonical annotation schema、数据集导出和外部数据集格式兼容规则。

本文档解决的问题是“外部数据集如何被导入、校验、归档、标准化并供不同模型训练后端复用”，而不是描述具体训练代码实现。

## 适用范围

- 数据集导入对象链与生命周期
- 外部数据集格式识别、显式声明和导入校验规则
- canonical annotation schema 的统一字段与任务族拆分
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
- 记录 source format、task family、image root、annotation root、manifest file、split 信息、class map、导入时间、校验结果和导入日志

### DatasetVersion

- 导入并标准化后的冻结数据快照
- 是训练、验证、推理回放和流程执行的稳定输入对象

### canonical annotation schema

- 平台内部统一的数据与标注逻辑表示
- 用统一字段描述样本、类别、任务类型和任务特定标注载荷

### DatasetExport

- 从 DatasetVersion 按 format id 派生出的格式化输出
- 可以是临时生成，也可以缓存到 ObjectStore 的 exports 路径
- DatasetExport 不替代 DatasetVersion 的权威地位

## 总体原则

- 外部格式兼容与内部统一表示分离
- 自动识别只作为导入便利能力，不作为最终权威判断
- DatasetVersion 一旦冻结，应优先视为不可变快照
- 原始导入内容、统一版本内容和训练导出内容分层存放，不混用目录
- 不同模型共享的是 task family 和 canonical schema，不是完全相同的原始标注文件结构
- 当前阶段默认通过 FastAPI 接收 zip 数据集压缩包，服务端负责解压、校验、canonical 化和本地磁盘落盘
- 训练、验证和推理默认读取平台内部统一结构；只有在导出时才回到目标模型需要的目录和文件格式

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
3. confirmed：确认 format type、task family、class map、split strategy
4. validated：完成结构与内容校验
5. canonicalized：转成 canonical annotation schema
6. frozen：形成可复用的 DatasetVersion
7. exported：按需生成数据集导出结果

## 实现分层建议

- FastAPI 接口只接收两类输入：导入时上传 zip 数据集压缩包并提供或确认格式；导出时提供 DatasetVersion 和 format id
- application/datasets/imports 负责接上传、识别格式、解析内容、校验字段并转成 canonical annotation schema
- 导入流程应先把 zip 包落到本地磁盘的 imports 路径，再解压到 staging，校验通过后写入 DatasetVersion 的统一目录
- domain/datasets 只保留平台内部通用格式，不直接依赖 COCO、VOC、YOLO、SAM 的原始目录写法
- application/datasets/exports 负责把 DatasetVersion 按 format id 导出成训练、验证或评估要用的目录和 manifest
- workers/training 和 workers/validation 只消费数据集导出结果，不直接读取原始导入包
- contracts/datasets/imports 和 contracts/datasets/exports 分别定义导入格式和导出格式规则，避免把格式细节散落在训练代码里

## 导入输入模型

### 最小导入声明

- format type：如 yolo, coco, voc, masks, custom-json
- task family：如 detection, instance-segmentation, semantic-segmentation, pose
- image root
- annotation root 或 manifest file
- split strategy：显式 train/val/test 或导入后切分
- class map：类别 id 与名称映射
- optional attributes：场景标签、采集来源、设备信息、难例标记等

### 自动识别策略

- 自动识别应根据目录签名、文件扩展名、manifest 内容和标注字段进行候选判断
- 若候选格式唯一且字段完整，可直接给出高置信度建议
- 若存在多个候选格式、目录结构不对齐、类别冲突或混合任务标注，则必须要求显式确认
- 最终写入数据库的应是确认后的 format type 与 task family，而不是某次推断结果

### 推荐支持的外部输入形态

- zip 压缩包，内部包含 YOLO、COCO、VOC、mask 目录或其他标准数据集结构
- 图像目录 + 标注目录
- 图像目录 + 单一 manifest 文件
- 图像目录 + mask 目录
- 已包含 split 的目录树
- 未包含 split，需要导入时切分的数据包

## 本地存储分层

- imports：保存原始 zip 包、导入日志和解压 staging
- versions：保存 canonical 化后的统一数据结构、索引和统计信息
- exports：保存按 format id 生成的数据集导出结果
- 训练、验证和推理默认读取 versions，不直接读取 imports 下的原始压缩包或解压目录

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

## canonical annotation schema

### 设计目标

- 统一平台内部对样本、类别和标注的管理方式
- 支撑多种外部格式导入和多种数据集导出格式
- 把 detection、instance segmentation、semantic segmentation、pose 区分为不同任务族，但共享统一的样本与版本管理边界

### 公共结构

#### dataset manifest

- dataset_id
- dataset_version_id
- task_family
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
- task_family
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

以下草案继续把 canonical annotation schema 收成字段级规则，后续可以放到 contracts 或独立 schema 文件中。当前目标是先把稳定字段定清楚，而不是一次列完所有扩展属性。

```json
{
   "$schema": "https://json-schema.org/draft/2020-12/schema",
   "$id": "amvision.dataset.canonical.v1.schema.json",
   "title": "AmVision Canonical DatasetVersion Schema",
   "type": "object",
   "additionalProperties": false,
   "required": [
      "dataset_id",
      "dataset_version_id",
      "task_family",
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
      "task_family": {
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
            "task_family"
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
            "task_family": {
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
                  "task_family",
                  "category_id",
                  "payload"
               ],
               "properties": {
                  "task_family": {
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
                  "task_family",
                  "category_id",
                  "payload"
               ],
               "properties": {
                  "task_family": {
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
                  "task_family",
                  "payload"
               ],
               "properties": {
                  "task_family": {
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
                  "task_family",
                  "category_id",
                  "payload"
               ],
               "properties": {
                  "task_family": {
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

- 该草案定义的是冻结后的 DatasetVersion canonical payload，而不是原始导入包结构
- capture_metadata、attributes 和 attributes_schema 暂时保留开放扩展，避免过早把现场场景字段写死
- semantic segmentation 允许 category_id 为空，因为单个 mask 可能表示多类像素映射
- 数据集导出应从这个 canonical payload 派生，而不是反向把某个导出格式当成权威源

## 导入校验规则

- image root 和 annotation root 必须可解析且可枚举
- 图片与标注之间必须存在稳定匹配关系
- 类别 id、名称和类别数量必须自洽
- bbox、polygon、mask 和 keypoints 必须满足几何合法性校验
- split 信息若缺失，应明确记录为导入后切分
- 不同任务族的标签不得在同一 DatasetVersion 中无约束混放
- 导入失败应产出结构化错误清单，而不是只给笼统异常提示

## 数据集导出规则

- 训练、验证或评估前应从 DatasetVersion 生成指定格式的数据集导出结果
- 数据集导出可以写入 ObjectStore 的 exports 路径，也可以作为任务级临时产物
- 数据集导出应记录 source dataset version、target format、class map 和导出时间
- 导出失败不应影响既有 DatasetVersion 的稳定性
- 数据集导出默认不作为新的权威数据版本，除非显式发起新的导入或回写流程

## 任务族格式矩阵

下表中的“首批支持”表示推荐优先实现和优先保证兼容的格式，“扩展支持”表示后续可逐步补充。

### detection

| 项目 | 内容 |
| --- | --- |
| canonical task family | detection |
| 首批导入格式 | YOLO detection, COCO detection, Pascal VOC xml |
| 扩展导入格式 | LabelMe rectangle json, CVAT detection export, custom csv/json manifest |
| 首批导出格式 | YOLO detection, COCO detection |
| 扩展导出格式 | Pascal VOC xml, backend-specific detection manifest |
| 典型模型/后端 | YOLOX, YOLOv8 detection, YOLOv11 detection, RT-DETR |
| 说明 | RT-DETR 与 YOLO 可以共享 detection canonical schema，但数据集导出格式通常不同 |

### instance segmentation

| 项目 | 内容 |
| --- | --- |
| canonical task family | instance-segmentation |
| 首批导入格式 | COCO instance segmentation, YOLO segmentation |
| 扩展导入格式 | LabelMe polygon json, CVAT polygon export, Supervisely instance export |
| 首批导出格式 | COCO instance segmentation, YOLO segmentation |
| 扩展导出格式 | polygon manifest, mask package manifest |
| 典型模型/后端 | YOLOv8 seg, YOLOv11 seg, Mask-oriented pipelines |
| 说明 | polygon 与 mask 可在 canonical schema 中共存，但导出时需按目标训练后端选择一种主表示 |

### semantic segmentation

| 项目 | 内容 |
| --- | --- |
| canonical task family | semantic-segmentation |
| 首批导入格式 | image+mask directory, custom mask manifest |
| 扩展导入格式 | COCO semantic-like export, CVAT mask export, grayscale label maps |
| 首批导出格式 | image+mask directory, semantic segmentation manifest |
| 扩展导出格式 | backend-specific dataset manifest |
| 典型模型/后端 | U-Net family, DeepLab family, MMSeg-style pipelines |
| 说明 | semantic segmentation 的核心是样本级 mask_ref 与类值映射，不应与 instance segmentation 混成同一导出格式 |

### pose

| 项目 | 内容 |
| --- | --- |
| canonical task family | pose |
| 首批导入格式 | COCO keypoints, YOLO pose |
| 扩展导入格式 | CVAT keypoints export, custom keypoints manifest |
| 首批导出格式 | COCO keypoints, YOLO pose |
| 扩展导出格式 | backend-specific pose manifest |
| 典型模型/后端 | YOLO pose, keypoint estimation pipelines |
| 说明 | pose 除类别外还需要 keypoint schema 与 skeleton 定义，不能只靠 bbox 或类别表描述 |

## 模型与数据集导出格式的关系

- YOLO 系列通常直接消费 YOLO detection、YOLO segmentation、YOLO pose 数据集导出格式
- RT-DETR 更适合消费 COCO detection 风格数据集导出格式
- SAM 相关流程更适合消费 instance segmentation 或 semantic segmentation 的 canonical 数据，再按具体训练或微调工具导出成对应格式
- 同一 DatasetVersion 可以对应多个数据集导出结果，但这些结果都应追溯到同一个冻结版本

更细的格式命名、目录结构和模型默认格式映射见 [docs/architecture/dataset-export-formats.md](dataset-export-formats.md)。

## 建议目录位置

- contracts/datasets/canonical：放 canonical annotation schema 定义
- contracts/datasets/imports：放外部格式 profile 与导入声明结构
- contracts/datasets/exports：放数据集导出格式规则
- adapters/object-store/datasets/source：放原始导入包或原始目录归档
- adapters/object-store/datasets/canonical：放冻结后的统一版本内容
- adapters/object-store/datasets/exports：放按需生成的数据集导出结果

## 推荐后续文档

- [docs/architecture/data-and-files.md](data-and-files.md)
- [docs/architecture/dataset-export-formats.md](dataset-export-formats.md)
- [docs/architecture/project-structure.md](project-structure.md)
- [docs/architecture/backend-service.md](backend-service.md)