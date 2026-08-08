# 数据集导出格式

## 文档目的

本文档用于定义平台支持的数据集导出格式、格式命名规则、目录结构和模型默认格式映射。

本文档主要回答两个问题：一个 DatasetVersion 可以导出成哪些格式；不同模型训练前默认应该拿哪一种格式。

## 核心原则

- DatasetVersion 是平台里的正式输入，数据集导出是为训练、验证和评估生成的派生结果
- 数据集导出按 format id 管理，不按某个模型内部脚本命名
- 同一个 DatasetVersion 可以导出成多种格式，但每个导出结果都必须追到同一个固定版本
- 导出格式要先把目录、annotation 文件、类别顺序和最小字段定清楚，再接具体训练代码
- 模型和任务类型的完整导入、导出和默认格式矩阵以 [model-dataset-format-contract.md](model-dataset-format-contract.md) 为准

## 格式命名规则

- 命名格式：{format}-{task}-{version}
- format id 一旦公开，应按版本维护，例如 yolo-detection-v1、coco-detection-v1
- 格式定义至少包括目录布局、annotation 文件、类别顺序约束、split 表达方式和最小字段要求

## 当前已实现格式

### yolo-detection-v1

- task type：detection
- 目录布局：manifest.json、images/{split}/、labels/{split}/
- 主要内容：YOLO detection 标签文件
- 适用模型：YOLOv8/11/26 detection

### yolo-instance-seg-v1

- task type：segmentation
- 目录布局：manifest.json、images/{split}/、labels/{split}/
- 主要内容：YOLO segmentation 标签文件
- 适用模型：YOLOv8/11/26 segmentation

### yolo-pose-v1

- task type：pose
- 目录布局：manifest.json、images/{split}/、labels/{split}/
- 主要内容：YOLO pose 标签文件
- 适用模型：YOLOv8/11/26 pose

### yolo-obb-v1

- task type：obb
- 目录布局：manifest.json、images/{split}/、labels/{split}/、annotations/{split}.json
- 主要内容：YOLO 归一化四角点标签；annotations 是平台训练、验证和评估共用索引
- 适用模型：YOLOv8/11/26 obb

### coco-detection-v1

- task type：detection
- 目录布局：images/{split}/、annotations/instances_{split}.json
- 主要内容：COCO detection json
- 适用模型：YOLOX、RT-DETR

### coco-instance-seg-v1

- task type：segmentation
- 目录布局：images/{split}/、annotations/instances_{split}.json
- 主要内容：COCO instance segmentation json
- 适用模型：实例分割训练后端

### coco-keypoints-v1

- task type：pose
- 目录布局：images/{split}/、annotations/person_keypoints_{split}.json
- 主要内容：COCO keypoints json
- 适用模型：keypoint 训练后端

### imagenet-classification-v1

- task type：classification
- 目录布局：{split}/{class_name}/、annotations/{split}.json、manifest.json
- 主要内容：ImageNet 风格目录，加每个 split 的标准 annotation json
- 适用模型：YOLOv8/11/26 classification

### dota-obb-v1

- task type：obb
- 目录布局：manifest.json、images/{split}/、annotations/{split}.json、labels/{split}/
- 主要内容：DOTA 四角点 polygon 风格 OBB annotation json
- 适用模型：YOLOv8/11/26 obb

## 模型默认格式映射

| 模型 | 主要任务 | 默认数据集导出格式 | 备选格式 | 说明 |
| --- | --- | --- | --- | --- |
| YOLOX | detection | coco-detection-v1 | voc-detection-v1 | 默认优先 COCO detection；VOC detection 也已接入训练与评估 |
| YOLOv8/11/26 | detection | yolo-detection-v1 | coco-detection-v1 | 默认优先原生 YOLO 目录格式 |
| YOLOv8/11/26 | segmentation | yolo-instance-seg-v1 | coco-instance-seg-v1 | 默认优先原生 YOLO segmentation 格式 |
| YOLOv8/11/26 | pose | yolo-pose-v1 | coco-keypoints-v1 | 默认优先原生 YOLO pose 格式 |
| YOLOv8/11/26 | classification | imagenet-classification-v1 | backend-specific classification manifest | 当前导出为 ImageNet 风格目录，同时保留 split annotation json |
| YOLOv8/11/26 | obb | yolo-obb-v1 | dota-obb-v1 | 默认使用 YOLO 归一化四角点标签，DOTA 用于外部 DOTA 工具链 |
| RT-DETR | detection | coco-detection-v1 | backend-specific detection manifest | 默认优先 COCO detection |

## 选择规则

- 默认优先目标模型或训练后端最直接支持的格式
- 只有在现有训练资产、历史兼容性或外部工具限制下，才回退到备选格式
- 需要 prompt、skeleton、palette 或额外 sidecar 的格式必须显式声明，不能藏在训练脚本里

## 当前实现状态

- 当前已经正式实现并公开：
  - coco-detection-v1
  - voc-detection-v1
  - yolo-detection-v1
  - coco-instance-seg-v1
  - yolo-instance-seg-v1
  - coco-keypoints-v1
  - yolo-pose-v1
  - yolo-obb-v1
  - imagenet-classification-v1
  - dota-obb-v1
- `YOLOv8 / YOLO11 / YOLO26` 的 detection 训练与评估当前已经同时接通 `yolo-detection-v1` 和 `coco-detection-v1`，其中 `yolo-detection-v1` 仍是首选默认格式。
- `YOLOX` detection 当前已经接通 `coco-detection-v1` 和 `voc-detection-v1` 的训练与评估入口，其中 `coco-detection-v1` 仍是默认格式。
- `RF-DETR` detection 当前仍只接 `coco-detection-v1`。上游参考仓库虽然还存在更多数据集变体入口，但本项目没有把这些变体全部接成正式训练输入。
- `imagenet-classification-v1` 当前导出为 ImageNet 风格目录，同时保留 `annotations/{split}.json` 和 `manifest.json`，便于项目内训练与评估链直接消费。
- `dota-obb-v1` 当前导出为 split 级图片目录和 DOTA polygon 风格 annotation json，不再把 OBB 数据继续塞进 detection 语义。
- `yolo-detection-v1 / yolo-instance-seg-v1 / yolo-pose-v1 / yolo-obb-v1` 当前写出 `manifest.json`、`images/{split}/` 和 `labels/{split}/`，不写 `data.yaml`。如后续需要面向外部工具直接下载的 YAML，应新增明确字段或独立生成规则，不能在文档中假设当前已存在。
- `dota-obb-v1` 当前同时写出 `annotations/{split}.json` 和 `labels/{split}/{image_stem}.txt`，训练侧可按 manifest 或 DOTA txt 标签消费。
- 公开格式注册表只包含导入和导出均已实现的格式，不暴露未来格式占位项。
- 后续新增格式时，继续沿用“DatasetVersion -> format id -> 导出目录和 annotation payload”这条主线扩展，不回退到模型私有脚本入口。

## 推荐后续文档

- [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)
- [docs/architecture/data-and-files.md](data-and-files.md)
- [docs/architecture/project-structure.md](project-structure.md)
