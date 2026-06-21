"""YOLO26 模型登记适配器。"""

from __future__ import annotations

from backend.service.application.models.registry.model_service import (
    ModelBuildRegistration as Yolo26BuildRegistration,
    PretrainedRegistrationRequest as Yolo26PretrainedRegistrationRequest,
    SqlAlchemyModelService,
    TrainingOutputRegistration as Yolo26TrainingOutputRegistration,
)
from backend.service.domain.files.detection_model_file_types import YOLO26_DETECTION_FILE_TYPES
from backend.service.domain.models.yolo26_model_spec import (
    DEFAULT_YOLO26_MODEL_SPEC,
    Yolo26ModelSpec,
)
from backend.service.infrastructure.db.session import SessionFactory


class SqlAlchemyYolo26ModelService(SqlAlchemyModelService):
    """基于通用登记逻辑的 YOLO26 模型服务。"""

    def __init__(
        self,
        session_factory: SessionFactory,
        spec: Yolo26ModelSpec = DEFAULT_YOLO26_MODEL_SPEC,
    ) -> None:
        """初始化 YOLO26 模型登记服务。"""

        super().__init__(
            session_factory=session_factory,
            spec=spec,
            file_types=YOLO26_DETECTION_FILE_TYPES,
        )


__all__ = [
    "SqlAlchemyYolo26ModelService",
    "Yolo26BuildRegistration",
    "Yolo26PretrainedRegistrationRequest",
    "Yolo26TrainingOutputRegistration",
]
