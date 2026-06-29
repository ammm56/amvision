# training 目录职责

本目录放模型训练任务的应用层 helper，不放模型结构 core。

## 文件名前缀

- `yolo_*`：普通 YOLO 主线中仍可共享的训练任务 helper，当前只允许放跨 `yolov8 / yolo11 / yolo26` 共用的任务参数、DatasetExport 校验、状态事件、输出登记、warm start 解析和 task payload，不实现 backbone、head、loss、assigner、decode、postprocess、export 或 deployment session。
- `yolov8_*`、`yolo11_*`、`yolo26_*`：对应模型代际的专属训练任务入口。只要涉及某一代模型的训练执行、loss、target、augmentation、evaluation 或 checkpoint 语义，都应优先进入对应 `*_core` 或对应模型 service helper。
- `yolox_*`：YOLOX detection 训练任务 helper，只服务 `yolox`。
- `rfdetr_*`：RF-DETR 训练任务 helper，只服务 `rfdetr`。

## 与 core 的边界

- `backend/service/application/models/yolov8_core/`、`yolo11_core/`、`yolo26_core/`、`yolox_core/`、`rfdetr_core/` 放模型结构、训练 loss、target、postprocess、权重加载、导出 forward 和 core 验收工具。
- 本目录 helper 可以被应用层 service 调用，也可以调用对应 core 的正式入口。
- core 目录不得反向 import 本目录 helper，避免模型实现依赖任务服务、数据库、队列或对象存储。
- 纯 DDP 值对象、torchrun 启动配置和 rank0-only reporter 放在 `backend/service/application/models/support/distributed_training/`。该目录不得依赖本目录，也不得写数据库、队列或对象存储。

## 当前注意点

共享 detection 训练入口已删除。YOLOv8 detection 训练执行位于 `backend/service/application/models/yolov8_core/training/detection_execution.py`，本目录只保留 `yolov8_detection_training.py` 作为应用层入口包装。

YOLOX detection 多 GPU 训练已通过 `backend/workers/training/yolox_ddp_entry.py` 进入 torchrun 子进程；本目录中的 YOLOX service 只负责 rank0 任务事件、产物登记和非 rank0 的只读执行上下文。YOLOX 不再允许 `gpu_count > 1` 静默回退到 `DataParallel`。
