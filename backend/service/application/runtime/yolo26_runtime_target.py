"""YOLO26 运行时目标解析适配器。"""

from __future__ import annotations

from backend.service.application.models.yolo26_model_service import SqlAlchemyYolo26ModelService
from backend.service.application.runtime.yolox_runtime_target import (
    RuntimeTargetResolveRequest,
    RuntimeTargetSnapshot,
    SqlAlchemyYoloXRuntimeTargetResolver,
    describe_runtime_execution_mode,
    deserialize_runtime_target_snapshot,
    find_model_file,
    normalize_device_name,
    normalize_runtime_backend,
    normalize_runtime_precision,
    require_model_file,
    resolve_input_size,
    resolve_labels,
    resolve_local_file_path,
    resolve_model_build_file_type,
    resolve_model_build_runtime_backend,
    resolve_runtime_backend,
    resolve_runtime_precision,
    serialize_runtime_target_snapshot,
)
from backend.service.domain.files.detection_model_file_types import YOLO26_DETECTION_FILE_TYPES
from backend.service.domain.models.yolo26_model_spec import DEFAULT_YOLO26_MODEL_SPEC
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class SqlAlchemyYolo26RuntimeTargetResolver(SqlAlchemyYoloXRuntimeTargetResolver):
    """复用共用解析链的 YOLO26 运行时快照解析器。"""

    def __init__(self, *, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 YOLO26 运行时快照解析器。"""

        super().__init__(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            file_types=YOLO26_DETECTION_FILE_TYPES,
            supported_task_types=DEFAULT_YOLO26_MODEL_SPEC.supported_tasks,
            model_service_factory=lambda current_session_factory: SqlAlchemyYolo26ModelService(
                session_factory=current_session_factory
            ),
        )
