"""RF-DETR 模型服务。"""

from __future__ import annotations

from backend.service.application.models.rfdetr_model import build_rfdetr_model, RfdetrModel
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXBuildRegistration as RfdetrBuildRegistration,
    YoloXPretrainedRegistrationRequest as RfdetrPretrainedRegistrationRequest,
    YoloXTrainingOutputRegistration as RfdetrTrainingOutputRegistration,
)
from backend.service.domain.files.detection_model_file_types import YOLOV8_DETECTION_FILE_TYPES
from backend.service.domain.models.rfdetr_model_spec import (
    RFDETR_DEFAULT_DATASET_FORMAT,
    RFDETR_DETECTION_SCALES,
    RFDETR_SEGMENTATION_SCALES,
    RFDETR_SUPPORTED_BUILD_FORMATS,
    RFDETR_SUPPORTED_TASKS,
)
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory


RFDETR_DETECTION_FILE_TYPES = YOLOV8_DETECTION_FILE_TYPES


class RfdetrModelSpec:
    """RF-DETR 模型规格。实现 YOLO 通用服务 spec 接口。
    支持 detection（nano/small/medium/large）和 segmentation（nano/small/medium/large/xlarge）。"""

    def __init__(self) -> None:
        self._supported_tasks = RFDETR_SUPPORTED_TASKS
        self._detection_scales = RFDETR_DETECTION_SCALES
        self._seg_scales = RFDETR_SEGMENTATION_SCALES
        self._supported_build_formats = RFDETR_SUPPORTED_BUILD_FORMATS
        self._default_dataset_format = RFDETR_DEFAULT_DATASET_FORMAT

    def supports_task_type(self, task_type: str) -> bool:
        return task_type in self._supported_tasks

    def supports_model_scale(self, model_scale: str) -> bool:
        return model_scale in self._detection_scales or model_scale in self._seg_scales

    def supports_build_format(self, build_format: str) -> bool:
        return build_format in self._supported_build_formats

    def resolve_default_dataset_format(self, task_type: str) -> str | None:
        if task_type == "detection":
            return "coco-detection-v1"
        return None


DEFAULT_RFDETR_MODEL_SPEC = RfdetrModelSpec()


class SqlAlchemyRfdetrModelService(SqlAlchemyYoloXModelService):
    """RF-DETR 模型服务。基于通用登记逻辑。"""

    def __init__(self, session_factory: SessionFactory, spec: RfdetrModelSpec | None = None) -> None:
        super().__init__(
            session_factory=session_factory,
            spec=spec or DEFAULT_RFDETR_MODEL_SPEC,
            file_types=RFDETR_DETECTION_FILE_TYPES,
            default_task_type=DETECTION_TASK_TYPE,
        )
