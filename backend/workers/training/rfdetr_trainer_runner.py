"""RF-DETR 训练执行器（TrainingBackend 实现）。"""

from __future__ import annotations

from backend.service.application.backends import (
    TrainingBackend,
    TrainingBackendRunRequest,
    TrainingBackendRunResult,
)
from backend.service.application.models.training.rfdetr_detection_task_service import (
    SqlAlchemyRfdetrTrainingTaskService,
)
from backend.service.application.support.resource_cleanup import (
    model_task_resource_cleanup,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.training.device_assignment import assigned_training_device


# 沿用统一训练执行规则的别名导出
RfdetrTrainingRunRequest = TrainingBackendRunRequest
RfdetrTrainingRunResult = TrainingBackendRunResult
RfdetrTrainerRunner = TrainingBackend


class SqlAlchemyRfdetrTrainerRunner:
    """基于 SQLAlchemy 与本地文件存储的 RF-DETR 训练执行器。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化 RF-DETR 训练执行器。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        """
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def run_training(self, request: TrainingBackendRunRequest) -> TrainingBackendRunResult:
        """执行 RF-DETR 训练处理链路并返回结果。

        参数：
        - request：训练执行请求。

        返回：
        - TrainingBackendRunResult：训练执行结果。
        """
        with model_task_resource_cleanup(), assigned_training_device(
            session_factory=self.session_factory,
            task_id=request.training_task_id,
        ):
            service = SqlAlchemyRfdetrTrainingTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
            )
            return service.process_training_task(request.training_task_id)
