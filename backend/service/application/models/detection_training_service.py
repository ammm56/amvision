"""detection 公共训练任务服务。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.errors import InvalidRequestError
from backend.service.application.model_type_support import require_supported_platform_model_type
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.application.models.yolo11_training_service import (
    YOLO11_TRAINING_TASK_KIND,
    SqlAlchemyYolo11TrainingTaskService,
    Yolo11TrainingTaskRequest,
)
from backend.service.application.models.yolo26_training_service import (
    YOLO26_TRAINING_TASK_KIND,
    SqlAlchemyYolo26TrainingTaskService,
    Yolo26TrainingTaskRequest,
)
from backend.service.application.models.yolov8_training_service import (
    YOLOV8_TRAINING_TASK_KIND,
    SqlAlchemyYoloV8TrainingTaskService,
    YoloV8TrainingTaskRequest,
)
from backend.service.application.models.training.rfdetr_detection_task_service import (
    RFDETR_TRAINING_TASK_KIND,
    RfdetrTrainingTaskRequest,
    SqlAlchemyRfdetrTrainingTaskService,
)
from backend.service.application.models.training.yolox_detection_task_service import (
    YOLOX_TRAINING_TASK_KIND,
    SqlAlchemyYoloXTrainingTaskService,
    YoloXTrainingTaskRequest,
)

_TRAINING_SERVICE_BY_MODEL_TYPE: dict[str, tuple[type, type]] = {
    "yolox": (SqlAlchemyYoloXTrainingTaskService, YoloXTrainingTaskRequest),
    "yolov8": (SqlAlchemyYoloV8TrainingTaskService, YoloV8TrainingTaskRequest),
    "yolo11": (SqlAlchemyYolo11TrainingTaskService, Yolo11TrainingTaskRequest),
    "yolo26": (SqlAlchemyYolo26TrainingTaskService, Yolo26TrainingTaskRequest),
    "rfdetr": (SqlAlchemyRfdetrTrainingTaskService, RfdetrTrainingTaskRequest),
}


_TRAINING_TASK_KIND_BY_MODEL_TYPE: dict[str, str] = {
    "yolox": YOLOX_TRAINING_TASK_KIND,
    "yolov8": YOLOV8_TRAINING_TASK_KIND,
    "yolo11": YOLO11_TRAINING_TASK_KIND,
    "yolo26": YOLO26_TRAINING_TASK_KIND,
    "rfdetr": RFDETR_TRAINING_TASK_KIND,
}


@dataclass(frozen=True)
class DetectionTrainingTaskRequest:
    """描述一次 detection 训练任务创建请求。"""

    project_id: str
    model_type: str
    model_scale: str
    dataset_export_id: str
    recipe_id: str | None = None
    learning_rate: float | None = None
    weight_decay: float | None = None
    batch_size: int | None = None
    max_epochs: int | None = None
    evaluation_interval: int | None = None
    warm_start_model_id: str | None = None
    resume_training_task_id: str | None = None
    display_name: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    extra_options: dict[str, object] = field(default_factory=dict)


def resolve_detection_training_service(model_type: str):
    """按模型分类解析 detection training task service 的构造参数。"""

    normalized = require_supported_platform_model_type(
        task_type=DETECTION_TASK_TYPE,
        model_type=model_type,
        unsupported_message="当前 detection 训练尚未接通指定模型分类",
    )
    entry = _TRAINING_SERVICE_BY_MODEL_TYPE.get(normalized)
    if entry is None:
        raise InvalidRequestError(
            "当前 detection 训练服务映射缺失指定模型分类",
            details={"model_type": normalized},
        )
    service_cls, request_cls = entry
    task_kind = _TRAINING_TASK_KIND_BY_MODEL_TYPE.get(normalized, "yolox-detection")
    return service_cls, request_cls, task_kind
