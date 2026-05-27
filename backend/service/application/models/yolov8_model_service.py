"""YOLOv8 模型登记适配器。"""

from __future__ import annotations

from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXBuildRegistration as YoloV8BuildRegistration,
    YoloXPretrainedRegistrationRequest as YoloV8PretrainedRegistrationRequest,
    YoloXTrainingOutputRegistration as YoloV8TrainingOutputRegistration,
)
from backend.service.domain.files.detection_model_file_types import YOLOV8_DETECTION_FILE_TYPES
from backend.service.domain.models.yolov8_model_spec import (
    DEFAULT_YOLOV8_MODEL_SPEC,
    YoloV8ModelSpec,
)
from backend.service.infrastructure.db.session import SessionFactory


class SqlAlchemyYoloV8ModelService(SqlAlchemyYoloXModelService):
    """基于通用登记逻辑的 YOLOv8 模型服务。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        spec: YoloV8ModelSpec = DEFAULT_YOLOV8_MODEL_SPEC,
    ) -> None:
        """初始化 YOLOv8 模型登记服务。"""

        super().__init__(
            session_factory=session_factory,
            spec=spec,
            file_types=YOLOV8_DETECTION_FILE_TYPES,
        )
