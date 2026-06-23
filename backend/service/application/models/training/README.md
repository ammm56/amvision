# training 目录职责

本目录放模型训练任务的应用层 helper，不放模型结构 core。

## 文件名前缀

- `yolo_task_*`：普通 YOLO 主线中仍可共享的训练任务 helper，当前只允许放跨 `yolov8 / yolo11 / yolo26` 共用的任务参数、DatasetExport 校验、状态事件、输出登记、warm start 解析和 task payload，不实现 backbone、head、loss、assigner、decode、postprocess、export 或 deployment session。
- `yolov8_*`、`yolo11_*`、`yolo26_*`：对应模型代际的专属训练任务入口。只要涉及某一代模型的训练执行、loss、target、augmentation、evaluation 或 checkpoint 语义，都应优先进入对应 `*_core` 或对应模型 service helper。
- `yolox_*`：YOLOX detection 训练任务 helper，只服务 `yolox`。
- `rfdetr_*`：RF-DETR 训练任务 helper，只服务 `rfdetr`。

## 与 core 的边界

- `backend/service/application/models/yolov8_core/`、`yolo11_core/`、`yolo26_core/`、`yolox_core/`、`rfdetr_core/` 放模型结构、训练 loss、target、postprocess、权重加载、导出 forward 和 core 验收工具。
- 本目录 helper 可以被应用层 service 调用，也可以调用对应 core 的正式入口。
- core 目录不得反向 import 本目录 helper，避免模型实现依赖任务服务、数据库、队列或对象存储。

## 当前注意点

共享 detection 训练入口已删除。YOLOv8 detection 训练执行位于 `backend/service/application/models/yolov8_core/training/detection_execution.py`，本目录只保留 `yolov8_detection_training.py` 作为应用层入口包装。
