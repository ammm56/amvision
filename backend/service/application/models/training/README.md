# training 目录职责

本目录放模型训练任务的应用层 helper，不放模型结构 core。

## 文件名前缀

- `yolo_primary_*`：YOLO 主线训练任务 helper，当前覆盖 `yolov8 / yolo11 / yolo26`。这些文件只处理任务参数、DatasetExport 校验、状态事件、输出登记、warm start 解析和 task payload，不实现 backbone、head、loss、assigner、decode、postprocess、export 或 deployment session。
- `yolox_*`：YOLOX detection 训练任务 helper，只服务 `yolox`。
- `rfdetr_*`：RF-DETR 训练任务 helper，只服务 `rfdetr`。

## 与 core 的边界

- `backend/service/application/models/yolov8_core/`、`yolo11_core/`、`yolo26_core/`、`yolox_core/`、`rfdetr_core/` 放模型结构、训练 loss、target、postprocess、权重加载、导出 forward 和 core 验收工具。
- 本目录 helper 可以被应用层 service 调用，也可以调用对应 core 的正式入口。
- core 目录不得反向 import 本目录 helper，避免模型实现依赖任务服务、数据库、队列或对象存储。

## 当前注意点

`yolo_primary_segmentation_*` 当前仍承接 `rfdetr` segmentation 的服务分发，这是历史过渡边界。后续继续收口时，应把 RF-DETR segmentation 训练任务服务拆到 `rfdetr_*` 或更中性的 segmentation service helper，避免 `yolo_primary` 名称继续覆盖非 YOLO 模型。
