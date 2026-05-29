"""RF-DETR 模型服务。"""

from __future__ import annotations

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
    RFDETR_SUPPORTED_BUILD_FORMATS,
    RFDETR_SUPPORTED_TASKS,
)
from backend.service.infrastructure.db.session import SessionFactory


RFDETR_DETECTION_FILE_TYPES = YOLOV8_DETECTION_FILE_TYPES


class RfdetrModelSpec:
    """RF-DETR 模型规格。"""

    def __init__(self) -> None:
        self.model_name = "rfdetr"
        self.supported_tasks = RFDETR_SUPPORTED_TASKS
        self.supported_scales = RFDETR_DETECTION_SCALES
        self.supported_build_formats = RFDETR_SUPPORTED_BUILD_FORMATS
        self.default_dataset_format = RFDETR_DEFAULT_DATASET_FORMAT

    def supports_task_type(self, task_type: str) -> bool:
        return task_type in self.supported_tasks

    def supports_model_scale(self, model_scale: str) -> bool:
        return model_scale in self.supported_scales

    def supports_build_format(self, build_format: str) -> bool:
        return build_format in self.supported_build_formats

    def resolve_default_dataset_format(self, task_type: str) -> str | None:
        if task_type == "detection":
            return self.default_dataset_format
        return None


DEFAULT_RFDETR_MODEL_SPEC = RfdetrModelSpec()


class SqlAlchemyRfdetrModelService(SqlAlchemyYoloXModelService):
    """RF-DETR 模型服务。基于通用登记逻辑。"""

    def __init__(self, session_factory: SessionFactory, spec: RfdetrModelSpec | None = None) -> None:
        super().__init__(
            session_factory=session_factory,
            spec=spec or DEFAULT_RFDETR_MODEL_SPEC,
            file_types=RFDETR_DETECTION_FILE_TYPES,
        )
