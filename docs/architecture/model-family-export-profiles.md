# 模型家族到导出视图映射

## 文档目的

本文档用于定义模型家族与训练导出视图之间的稳定映射关系，明确每个模型家族默认消费哪一种 export profile、可接受哪些备选 profile，以及这些 profile 需要的数据特征。

本文档解决的问题是“同一个 DatasetVersion 在面对不同模型家族时应导出成什么结构”，而不是描述某个训练框架内部的数据读取代码。

## 适用范围

- export profile 的命名规则与职责边界
- YOLOX、YOLOv8/11、RT-DETR、SAM 对应的默认 export profile
- detection、instance segmentation、semantic segmentation、pose 相关 profile 的目录结构与字段要求
- 默认 profile、备选 profile 和不推荐组合的说明

## 核心原则

- DatasetVersion 是权威输入，export profile 是派生训练视图
- export profile 以“任务族 + 训练后端适配”为核心，不以单个模型文件名为核心
- 同一模型家族在不同任务族下可对应不同 export profile
- 一个 DatasetVersion 可以派生多个 export profile，但每个 profile 都必须可追溯到同一冻结版本

## export profile 命名规则

- 命名格式：{family-or-format}-{task}-{version}
- profile id 一旦公开，应按版本维护，例如 yolo-detection-v1、coco-detection-v1
- profile 定义至少包括目录布局、核心 manifest、类别顺序约束、任务字段要求和 split 表达方式

## 标准 export profile 列表

### yolo-detection-v1

- task family：detection
- 目录布局：images/{split}/、labels/{split}/、data.yaml
- 标签载荷：每行一条目标，使用 YOLO detection 风格 bbox
- 适用对象：YOLOv8/11 detection 等直接消费 YOLO 目录格式的训练后端

### yolo-instance-seg-v1

- task family：instance-segmentation
- 目录布局：images/{split}/、labels/{split}/、data.yaml
- 标签载荷：每行一条实例，包含类别和 polygon 点序列
- 适用对象：YOLOv8/11 segmentation

### yolo-pose-v1

- task family：pose
- 目录布局：images/{split}/、labels/{split}/、data.yaml
- 标签载荷：每行包含 bbox、类别和 keypoints 序列
- 适用对象：YOLOv8/11 pose

### coco-detection-v1

- task family：detection
- 目录布局：images/{split}/、annotations/instances_{split}.json
- 标签载荷：COCO detection json
- 适用对象：YOLOX、RT-DETR 等更偏向 COCO 数据接口的训练后端

### coco-instance-seg-v1

- task family：instance-segmentation
- 目录布局：images/{split}/、annotations/instances_{split}.json
- 标签载荷：COCO instance segmentation，包含 segmentation、bbox、area 等字段
- 适用对象：实例分割训练后端、部分 mask-oriented pipeline

### coco-keypoints-v1

- task family：pose
- 目录布局：images/{split}/、annotations/person_keypoints_{split}.json
- 标签载荷：COCO keypoints json
- 适用对象：keypoint estimation pipeline、需要 COCO keypoints 接口的训练后端

### semantic-mask-dir-v1

- task family：semantic-segmentation
- 目录布局：images/{split}/、masks/{split}/、classes.json
- 标签载荷：图像与 mask 一一配对，mask 使用 class-index 或 palette 表达
- 适用对象：semantic segmentation 训练后端，如 U-Net、DeepLab、MMSeg 风格管线

### sam-promptable-seg-v1

- task family：instance-segmentation 或 prompt-driven segmentation
- 目录布局：images/{split}/、masks/{split}/、prompts/{split}.jsonl、classes.json
- 标签载荷：除 mask 外，还包含 box prompt、point prompt 或其他提示侧车信息
- 适用对象：SAM 相关微调、提示驱动分割流程或以 SAM 为核心的交互式分割数据准备

## 模型家族到 export profile 映射表

| 模型家族 | 主要任务族 | 默认 export profile | 备选 profile | 说明 |
| --- | --- | --- | --- | --- |
| YOLOX | detection | coco-detection-v1 | yolo-detection-v1 | 默认优先 COCO detection，因为 YOLOX 训练生态普遍直接对接 COCO 风格数据接口 |
| YOLOv8/11 | detection | yolo-detection-v1 | coco-detection-v1 | 默认优先原生 YOLO 目录视图，便于直接复用 Ultralytics 训练入口 |
| YOLOv8/11 | instance-segmentation | yolo-instance-seg-v1 | coco-instance-seg-v1 | 默认使用 YOLO segmentation 标签行格式，备选 COCO instance segmentation |
| YOLOv8/11 | pose | yolo-pose-v1 | coco-keypoints-v1 | 默认使用 YOLO pose 格式，备选 COCO keypoints |
| RT-DETR | detection | coco-detection-v1 | backend-specific detection manifest | 默认优先 COCO detection，通常不建议直接消费 YOLO txt 目录 |
| SAM | instance-segmentation | sam-promptable-seg-v1 | coco-instance-seg-v1 | 若需要保留 prompt 信息，应使用 sam-promptable-seg-v1；只有 mask 导向训练时才退化为 COCO instance segmentation |
| SAM | semantic-segmentation | semantic-mask-dir-v1 | sam-promptable-seg-v1 | 用于把 SAM 作为 mask 生成器或分割组件接入语义分割流程时，优先 image+mask 目录视图 |

## 模型家族说明

### YOLOX

- 推荐 profile：coco-detection-v1
- 原因：YOLOX 的公开训练流程通常围绕 COCO detection 数据接口组织
- 风险：若强行走 yolo-detection-v1，通常仍需要中间转换层，不适合作为默认主 profile

### YOLOv8/11

- detection：默认 yolo-detection-v1
- instance segmentation：默认 yolo-instance-seg-v1
- pose：默认 yolo-pose-v1
- 原因：这一家族对原生 YOLO 目录和 data.yaml 组织更直接，减少额外导出转换步骤

### RT-DETR

- detection：默认 coco-detection-v1
- 原因：RT-DETR 训练配置与数据接口通常围绕 COCO 样式组织
- 说明：即使内部 canonical schema 统一，导出时也应优先维持 COCO 风格 manifest，而不是回退到 YOLO txt

### SAM

- instance-segmentation：默认 sam-promptable-seg-v1
- semantic-segmentation：默认 semantic-mask-dir-v1
- 原因：SAM 不只是消费 mask，还可能需要 prompt sidecar；若场景只需要语义掩码，可导出为 image+mask 目录视图
- 说明：SAM 不应被简单视为 detection 训练后端，也不应复用 YOLO detection 或 COCO detection profile

## profile 选择规则

- 同一模型家族若存在“原生 profile”和“兼容 profile”，默认优先原生 profile
- 只有在目标训练框架明确要求或现有训练资产只能兼容某种格式时，才选备选 profile
- 若某模型家族需要 prompt、skeleton、palette 或额外 sidecar，export profile 必须显式声明，不得隐含在训练脚本里

## 推荐后续文档

- [docs/architecture/dataset-import-spec.md](dataset-import-spec.md)
- [docs/architecture/data-and-artifacts.md](data-and-artifacts.md)
- [docs/architecture/project-structure.md](project-structure.md)