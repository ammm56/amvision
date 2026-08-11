"""普通 YOLO 训练公共支撑能力。"""

from backend.service.application.models.yolo_core_common.training.ultralytics_schedule import (
    YoloUltralyticsTrainingSchedule,
    apply_yolo_ultralytics_warmup,
    build_yolo_ultralytics_optimizer,
    build_yolo_ultralytics_scheduler,
    compute_yolo_ultralytics_lr_factor,
    resolve_yolo_optimizer_base_learning_rate,
    resolve_yolo_ultralytics_accumulate,
)
from backend.service.application.models.yolo_core_common.training.ema import (
    YoloModelEMA,
)
from backend.service.application.models.yolo_core_common.training.optimizer_step import (
    YoloTrainingNumericalError,
    YoloUltralyticsOptimizerStep,
)
from backend.service.application.models.yolo_core_common.training.infinite_dataloader import (
    YoloInfiniteDataLoader,
    resolve_yolo_dataloader_batch_size,
    resolve_yolo_dataloader_worker_count,
)
from backend.service.application.models.yolo_core_common.training.metrics_history import (
    build_yolo_completed_epoch_history_item,
    build_yolo_epoch_history_item,
)
from backend.service.application.models.yolo_core_common.training.batch_progress import (
    YoloTaskTrainingBatchProgress,
)
from backend.service.application.models.yolo_core_common.training.worker_ipc import (
    serialize_yolo_worker_value,
)
from backend.service.application.models.yolo_core_common.training.classification_dataloader import (
    YoloClassificationDataLoaderPlan,
    build_yolo_classification_training_dataloader,
    load_yolo_classification_dataloader_imports,
    move_yolo_classification_batch_to_device,
    replace_yolo_classification_dataloader_plan_seed,
    resolve_yolo_classification_dataloader_plan,
)
from backend.service.application.models.yolo_core_common.training.task_dataloader import (
    YoloTaskDataLoaderPlan,
    YoloTaskTrainingDataLoaderLifecycle,
    build_yolo_task_evaluation_dataloader,
    build_yolo_task_training_dataloader,
    close_yolo_dataloader,
    iter_yolo_task_evaluation_items,
    load_yolo_task_dataloader_imports,
    managed_yolo_task_evaluation_dataloader,
    move_yolo_task_batch_to_device,
    pin_yolo_task_value,
    replace_yolo_task_dataloader_plan_seed,
    resolve_yolo_task_evaluation_dataloader_plan,
    resolve_yolo_task_dataloader_plan,
)
from backend.service.application.models.yolo_core_common.training.validation_schedule import (
    should_run_yolo_validation,
)
from backend.service.application.models.yolo_core_common.training.detection_metrics import (
    YOLO_DETECTION_LOSS_METRIC_NAMES,
    YoloDetectionLossAccumulator,
    normalize_yolo_detection_loss_metrics,
)

__all__ = [
    "YoloInfiniteDataLoader",
    "YOLO_DETECTION_LOSS_METRIC_NAMES",
    "YoloClassificationDataLoaderPlan",
    "YoloDetectionLossAccumulator",
    "YoloModelEMA",
    "YoloTrainingNumericalError",
    "YoloUltralyticsOptimizerStep",
    "YoloTaskDataLoaderPlan",
    "YoloTaskTrainingBatchProgress",
    "YoloTaskTrainingDataLoaderLifecycle",
    "YoloUltralyticsTrainingSchedule",
    "apply_yolo_ultralytics_warmup",
    "build_yolo_classification_training_dataloader",
    "build_yolo_completed_epoch_history_item",
    "build_yolo_epoch_history_item",
    "build_yolo_task_evaluation_dataloader",
    "build_yolo_task_training_dataloader",
    "close_yolo_dataloader",
    "build_yolo_ultralytics_optimizer",
    "build_yolo_ultralytics_scheduler",
    "compute_yolo_ultralytics_lr_factor",
    "load_yolo_classification_dataloader_imports",
    "load_yolo_task_dataloader_imports",
    "iter_yolo_task_evaluation_items",
    "managed_yolo_task_evaluation_dataloader",
    "move_yolo_classification_batch_to_device",
    "move_yolo_task_batch_to_device",
    "normalize_yolo_detection_loss_metrics",
    "pin_yolo_task_value",
    "replace_yolo_classification_dataloader_plan_seed",
    "replace_yolo_task_dataloader_plan_seed",
    "resolve_yolo_classification_dataloader_plan",
    "resolve_yolo_dataloader_batch_size",
    "resolve_yolo_dataloader_worker_count",
    "resolve_yolo_task_evaluation_dataloader_plan",
    "resolve_yolo_task_dataloader_plan",
    "should_run_yolo_validation",
    "serialize_yolo_worker_value",
    "resolve_yolo_optimizer_base_learning_rate",
    "resolve_yolo_ultralytics_accumulate",
]
