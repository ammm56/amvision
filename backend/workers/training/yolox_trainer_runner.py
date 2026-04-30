"""YOLOX 训练 worker 接口与 SQLAlchemy 实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.service.application.models.yolox_training_service import (
    SqlAlchemyYoloXTrainingTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloXTrainingRunRequest:
    """描述一次 YOLOX 训练执行请求。

    字段：
    - training_task_id：训练任务 id。
    - metadata：附加元数据。
    """

    training_task_id: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXTrainingRunResult:
    """描述一次 YOLOX 训练执行结果。

    字段：
    - training_task_id：训练任务 id。
    - status：训练任务最终状态。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
    - dataset_version_id：训练使用的 DatasetVersion id。
    - format_id：训练输入导出格式 id。
    - output_object_prefix：训练输出目录前缀。
    - checkpoint_object_key：checkpoint 的 object key。
    - latest_checkpoint_object_key：最新 checkpoint 的 object key。
    - labels_object_key：标签文件的 object key。
    - metrics_object_key：指标文件的 object key。
    - validation_metrics_object_key：验证指标文件的 object key。
    - summary_object_key：训练摘要文件 object key。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - summary：训练摘要。
    """

    training_task_id: str
    status: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    output_object_prefix: str
    checkpoint_object_key: str
    latest_checkpoint_object_key: str | None = None
    labels_object_key: str | None = None
    metrics_object_key: str | None = None
    validation_metrics_object_key: str | None = None
    summary_object_key: str | None = None
    best_metric_name: str | None = None
    best_metric_value: float | None = None
    summary: dict[str, object] = field(default_factory=dict)


class YoloXTrainerRunner(Protocol):
    """执行 YOLOX 训练任务的 worker 接口。"""

    def run_training(self, request: YoloXTrainingRunRequest) -> YoloXTrainingRunResult:
        """执行训练并返回结果。

        参数：
        - request：训练执行请求。

        返回：
        - 训练执行结果。
        """

        ...


class SqlAlchemyYoloXTrainerRunner:
    """基于 SQLAlchemy 与本地文件存储的 YOLOX 训练 worker。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化 YOLOX 训练 worker。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        """

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def run_training(self, request: YoloXTrainingRunRequest) -> YoloXTrainingRunResult:
        """执行 YOLOX 训练处理链路并返回结果。

        参数：
        - request：训练执行请求。

        返回：
        - 训练执行结果。
        """

        service = SqlAlchemyYoloXTrainingTaskService(
            session_factory=self.session_factory,
            dataset_storage=self.dataset_storage,
        )
        task_result = service.process_training_task(request.training_task_id)
        return YoloXTrainingRunResult(
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