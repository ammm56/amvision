"""YOLO11 模型登记适配器。"""

from __future__ import annotations

from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXBuildRegistration as Yolo11BuildRegistration,
    YoloXPretrainedRegistrationRequest as Yolo11PretrainedRegistrationRequest,
    YoloXTrainingOutputRegistration as Yolo11TrainingOutputRegistration,
)
from backend.service.domain.files.detection_model_file_types import YOLO11_DETECTION_FILE_TYPES
from backend.service.domain.models.yolo11_model_spec import (
    DEFAULT_YOLO11_MODEL_SPEC,
    Yolo11ModelSpec,
)
from backend.service.infrastructure.db.session import SessionFactory


class SqlAlchemyYolo11ModelService(SqlAlchemyYoloXModelService):
    """基于通用登记逻辑的 YOLO11 模型服务。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        spec: Yolo11ModelSpec = DEFAULT_YOLO11_MODEL_SPEC,
    ) -> None:
        """初始化 YOLO11 模型登记服务。"""

        super().__init__(
            session_factory=session_factory,
            spec=spec,
            file_types=YOLO11_DETECTION_FILE_TYPES,
        )
