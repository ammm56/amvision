"""YOLO11 训练 worker 接口与 SQLAlchemy 实现。"""

from __future__ import annotations

from backend.service.application.backends import (
    TrainingBackend,
    TrainingBackendRunRequest,
    TrainingBackendRunResult,
)
from backend.service.application.models.training.yolo11_training_service import (
    SqlAlchemyYolo11TrainingTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


Yolo11TrainingRunRequest = TrainingBackendRunRequest
Yolo11TrainingRunResult = TrainingBackendRunResult
Yolo11TrainerRunner = TrainingBackend


class SqlAlchemyYolo11TrainerRunner:
    """基于 SQLAlchemy 与本地文件存储的 YOLO11 训练 worker。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化 YOLO11 训练 worker。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def run_training(self, request: Yolo11TrainingRunRequest) -> Yolo11TrainingRunResult:
        """执行 YOLO11 训练处理链路并返回结果。"""

        service = SqlAlchemyYolo11TrainingTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )
        task_result = service.process_training_task(request.training_task_id)
        return Yolo11TrainingRunResult(
            training_task_id=task_result.task_id,
            status=task_result.status,
            dataset_export_id=task_result.dataset_export_id,
            dataset_export_manifest_key=task_result.dataset_export_manifest_key,
            dataset_version_id=task_result.dataset_version_id,
            format_id=task_result.format_id,
            output_object_prefix=task_result.output_object_prefix,
            checkpoint_object_key=task_result.checkpoint_object_key,
            latest_checkpoint_object_key=task_result.latest_checkpoint_object_key,
            labels_object_key=task_result.labels_object_key,
            metrics_object_key=task_result.metrics_object_key,
            validation_metrics_object_key=task_result.validation_metrics_object_key,
            summary_object_key=task_result.summary_object_key,
            best_metric_name=task_result.best_metric_name,
            best_metric_value=task_result.best_metric_value,
            summary=dict(task_result.summary),
        )
