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
from backend.service.application.models.training.segmentation_training_service import (
    SqlAlchemySegmentationTrainingService,
)
from backend.service.application.support.resource_cleanup import (
    model_task_resource_cleanup,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.tasks.task_records import TaskRecord
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
            task_record = SqlAlchemyTaskService(
                session_factory=self.session_factory,
            ).get_task(request.training_task_id).task
            task_type = self._resolve_task_type(request=request, task_record=task_record)
            if task_type == "detection":
                service = SqlAlchemyRfdetrTrainingTaskService(
                    session_factory=self.session_factory,
                    dataset_storage=self.dataset_storage,
                )
                return service.process_training_task(request.training_task_id)
            if task_type == "segmentation":
                service = SqlAlchemySegmentationTrainingService(
                    session_factory=self.session_factory,
                    dataset_storage=self.dataset_storage,
                    queue_backend=None,
                )
                result = service.process_training_task(task_record, model_type="rfdetr")
                return self._build_segmentation_run_result(
                    training_task_id=request.training_task_id,
                    result=result,
                )
            raise InvalidRequestError(
                "RF-DETR 训练不支持指定 task_type",
                details={
                    "task_id": request.training_task_id,
                    "task_type": task_type,
                },
            )

    def _resolve_task_type(
        self,
        *,
        request: TrainingBackendRunRequest,
        task_record: TaskRecord,
    ) -> str:
        """按 request、task_spec 和 metadata 解析 RF-DETR 训练 task_type。"""

        candidates = (
            request.task_type,
            task_record.task_spec.get("task_type"),
            (task_record.metadata or {}).get("task_type"),
        )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip().lower()
        raise InvalidRequestError(
            "RF-DETR 训练任务缺少 task_type",
            details={"task_id": request.training_task_id},
        )

    def _build_segmentation_run_result(
        self,
        *,
        training_task_id: str,
        result: dict[str, object],
    ) -> TrainingBackendRunResult:
        """把 segmentation service 结果转换成统一 TrainingBackendRunResult。"""

        output_prefix = f"task-runs/{training_task_id}"
        return TrainingBackendRunResult(
            training_task_id=training_task_id,
            status=str(result.get("status") or "succeeded"),
            dataset_export_id=str(result.get("dataset_export_id") or ""),
            dataset_export_manifest_key=str(
                result.get("dataset_export_manifest_key") or ""
            ),
            dataset_version_id=str(result.get("dataset_version_id") or ""),
            format_id=str(result.get("format_id") or ""),
            output_object_prefix=str(
                result.get("output_object_prefix")
                or result.get("output_prefix")
                or output_prefix
            ),
            checkpoint_object_key=str(
                result.get("checkpoint_object_key")
                or f"{output_prefix}/output-files/best-checkpoint.pt"
            ),
            latest_checkpoint_object_key=_read_optional_string(
                result.get("latest_checkpoint_object_key")
            ),
            labels_object_key=_read_optional_string(result.get("labels_object_key")),
            metrics_object_key=_read_optional_string(result.get("metrics_object_key")),
            validation_metrics_object_key=_read_optional_string(
                result.get("validation_metrics_object_key")
            ),
            summary_object_key=_read_optional_string(result.get("summary_object_key")),
            best_metric_name=_read_optional_string(result.get("best_metric_name")),
            best_metric_value=_read_optional_float(result.get("best_metric_value")),
            summary=dict(result),
        )


def _read_optional_string(value: object) -> str | None:
    """读取可选字符串字段。"""

    if isinstance(value, str) and value:
        return value
    return None


def _read_optional_float(value: object) -> float | None:
    """读取可选浮点字段。"""

    if isinstance(value, int | float):
        return float(value)
    return None
