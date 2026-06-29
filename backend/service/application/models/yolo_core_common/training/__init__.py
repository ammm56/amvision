"""普通 YOLO 训练公共支撑能力。"""

from backend.service.application.models.yolo_core_common.training.ultralytics_schedule import (
    YoloUltralyticsTrainingSchedule,
    apply_yolo_ultralytics_warmup,
    build_yolo_ultralytics_optimizer,
    build_yolo_ultralytics_scheduler,
    compute_yolo_ultralytics_lr_factor,
    resolve_yolo_ultralytics_accumulate,
)
from backend.service.application.models.yolo_core_common.training.ema import (
    YoloModelEMA,
)
from backend.service.application.models.yolo_core_common.training.runtime_resources import (
    YoloTrainingRuntimeResources,
    build_yolo_data_parallel_model,
    resolve_yolo_training_runtime_resources,
)
from backend.service.application.models.yolo_core_common.training.ddp import (
    YOLO_DETECTION_DDP_ENTRY_MODULE,
    YOLO_DETECTION_DDP_MODEL_TYPES,
    YoloDetectionDdpTrainingLaunchRequest,
    prepare_yolo_detection_ddp_launch,
)

__all__ = [
    "YoloModelEMA",
    "YOLO_DETECTION_DDP_ENTRY_MODULE",
    "YOLO_DETECTION_DDP_MODEL_TYPES",
    "YoloDetectionDdpTrainingLaunchRequest",
    "YoloTrainingRuntimeResources",
    "YoloUltralyticsTrainingSchedule",
    "apply_yolo_ultralytics_warmup",
    "build_yolo_ultralytics_optimizer",
    "build_yolo_ultralytics_scheduler",
    "build_yolo_data_parallel_model",
    "compute_yolo_ultralytics_lr_factor",
    "prepare_yolo_detection_ddp_launch",
    "resolve_yolo_ultralytics_accumulate",
    "resolve_yolo_training_runtime_resources",
]
