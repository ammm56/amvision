"""RF-DETR 运行时目标解析适配器。"""

from __future__ import annotations

from backend.service.application.models.catalog.rfdetr import (
    DEFAULT_RFDETR_MODEL_SPEC,
    RFDETR_MODEL_FILE_TYPES,
    SqlAlchemyRfdetrModelService,
)
from backend.service.application.runtime.runtime_target import (
    SqlAlchemyRuntimeTargetResolver,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class SqlAlchemyRfdetrRuntimeTargetResolver(SqlAlchemyRuntimeTargetResolver):
    """复用共用解析链的 RF-DETR 运行时快照解析器。"""

    model_type = "rfdetr"

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化 RF-DETR 运行时快照解析器。"""

        super().__init__(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            file_types=RFDETR_MODEL_FILE_TYPES,
            supported_task_types=DEFAULT_RFDETR_MODEL_SPEC.supported_tasks,
            model_service_factory=lambda current_session_factory: SqlAlchemyRfdetrModelService(
                session_factory=current_session_factory
            ),
        )
