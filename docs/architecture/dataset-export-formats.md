# 数据集导出格式

## 文档目的

本文档用于定义平台支持的数据集导出格式、格式命名规则、目录结构和模型默认格式映射。

本文档主要回答两个问题：一个 DatasetVersion 可以导出成哪些格式；不同模型训练前默认应该拿哪一种格式。

## 核心原则

- DatasetVersion 是平台里的权威输入，数据集导出是为训练、验证和评估生成的派生结果
- 数据集导出按 format id 管理，不按某个模型内部脚本命名
- 同一个 DatasetVersion 可以导出成多种格式，但每个导出结果都必须追到同一个冻结版本
- 导出格式要先把目录、annotation 文件、类别顺序和最小字段定清楚，再接具体训练代码

## 格式命名规则

- 命名格式：{format}-{task}-{version}
- format id 一旦公开，应按版本维护，例如 yolo-detection-v1、coco-detection-v1
- 格式定义至少包括目录布局、annotation 文件、类别顺序约束、split 表达方式和最小字段要求

## 当前规划支持的格式

### yolo-detection-v1

- task family：detection
- 目录布局：images/{split}/、labels/{split}/、data.yaml
- 主要内容：YOLO detection 标签文件
- 适用模型：YOLOv8/11 detection

### yolo-instance-seg-v1

- task family：instance-segmentation
- 目录布局：images/{split}/、labels/{split}/、data.yaml
- 主要内容：YOLO segmentation 标签文件
- 适用模型：YOLOv8/11 segmentation

### yolo-pose-v1

- task family：pose
- 目录布局：images/{split}/、labels/{split}/、data.yaml
- 主要内容：YOLO pose 标签文件
- 适用模型：YOLOv8/11 pose

### coco-detection-v1

- task family：detection
- 目录布局：images/{split}/、annotations/instances_{split}.json
- 主要内容：COCO detection json
- 适用模型：YOLOX、RT-DETR

### coco-instance-seg-v1

- task family：instance-segmentation
- 目录布局：images/{split}/、annotations/instances_{split}.json
- 主要内容：COCO instance segmentation json
- 适用模型：实例分割训练后端

### coco-keypoints-v1

- task family：pose
- 目录布局：images/{split}/、annotations/person_keypoints_{split}.json
- 主要内容：COCO keypoints json
- 适用模型：keypoint 训练后端

### semantic-mask-dir-v1

- task family：semantic-segmentation
- 目录布局：images/{split}/、masks/{split}/、classes.json
- 主要内容：图像和 mask 目录
- 适用模型：U-Net、DeepLab、MMSeg 风格训练后端

### sam-promptable-seg-v1

- task family：instance-segmentation 或 prompt-driven segmentation
- 目录布局：images/{split}/、masks/{split}/、prompts/{split}.jsonl、classes.json
- 主要内容：mask 加 prompt sidecar
- 适用模型：SAM 相关微调和提示驱动分割流程

## 模型默认格式映射

| 模型 | 主要任务 | 默认数据集导出格式 | 备选格式 | 说明 |
| --- | --- | --- | --- | --- |
| YOLOX | detection | coco-detection-v1 | yolo-detection-v1 | 默认优先 COCO detection，因为 YOLOX 训练接口更接近 COCO |
| YOLOv8/11 | detection | yolo-detection-v1 | coco-detection-v1 | 默认优先原生 YOLO 目录格式 |
| YOLOv8/11 | instance-segmentation | yolo-instance-seg-v1 | coco-instance-seg-v1 | 默认优先原生 YOLO segmentation 格式 |
| YOLOv8/11 | pose | yolo-pose-v1 | coco-keypoints-v1 | 默认优先原生 YOLO pose 格式 |
| RT-DETR | detection | coco-detection-v1 | backend-specific detection manifest | 默认优先 COCO detection |
| SAM | instance-segmentation | sam-promptable-seg-v1 | coco-instance-seg-v1 | 需要保留 prompt 信息时优先 sam-promptable-seg-v1 |
| SAM | semantic-segmentation | semantic-mask-dir-v1 | sam-promptable-seg-v1 | 语义分割链路优先 image+mask 目录格式 |

## 选择规则

- 默认优先目标模型或训练后端最直接支持的格式
- 只有在现有训练资产、历史兼容性或外部工具限制下，才回退到备选格式
- 需要 prompt、skeleton、palette 或额外 sidecar 的格式必须显式声明，不能藏在训练脚本里

## 当前实现状态

- 架构层面已经把 detection、instance-segmentation、semantic-segmentation、pose 这几类格式都纳入支持范围
- 当前代码层最小实现只先落了 coco-detection-v1
- 后续新增格式时，应继续沿用“DatasetVersion -> format id -> 导出目录和 annotation payload”这条主线扩展

## 推荐后续文档

- [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)
- [docs/architecture/data-and-files.md](data-and-files.md)
- [docs/architecture/project-structure.md](project-structure.md)