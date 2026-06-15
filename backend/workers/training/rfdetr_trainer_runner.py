"""RF-DETR 训练执行器（TrainingBackend 实现）。"""

from __future__ import annotations

from backend.service.application.backends import (
    TrainingBackend,
    TrainingBackendRunRequest,
    TrainingBackendRunResult,
)
from backend.service.application.models.training.rfdetr_detection import (
    RfdetrTrainingExecutionRequest,
    run_rfdetr_training,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


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
        task_id = request.training_task_id
        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        task = task_service.get_task(task_id)
        payload = (task.metadata or {}).get("queue_payload", {})

        model_scale = payload.get("model_scale", "nano")
        output_prefix = f"task-runs/{task_id}"

        # 加载 manifest
        mk = payload.get("dataset_export_manifest_key", "")
        manifest = self.dataset_storage.read_json(mk) if mk else {}

        # 解析 input_size
        input_size = payload.get("input_size")
        if input_size and isinstance(input_size, (list, tuple)) and len(input_size) == 2:
            input_size = (int(input_size[0]), int(input_size[1]))
        else:
            input_size = (384, 384)

        result = run_rfdetr_training(RfdetrTrainingExecutionRequest(
            dataset_storage=self.dataset_storage,
            manifest_payload=manifest,
            model_scale=model_scale,
            batch_size=int(payload.get("batch_size", 2)),
            max_epochs=int(payload.get("max_epochs", 1)),
            input_size=input_size,
            precision=payload.get("precision", "fp32"),
            extra_options=payload.get("extra_options", {}),
        ))

        # 保存 checkpoint + metrics
        checkpoint_key = f"{output_prefix}/checkpoints/best.pt"
        self.dataset_storage.write_bytes(checkpoint_key, result.latest_checkpoint_bytes)
        metrics_key = f"{output_prefix}/metrics.json"
        self.dataset_storage.write_json(metrics_key, result.metrics_payload)

        # 解析数据集信息
        dataset_export_id = payload.get("dataset_export_id", "")
        dataset_export_manifest_key = payload.get("dataset_export_manifest_key", "")
        dataset_version_id = payload.get("dataset_version_id", "")
        format_id = payload.get("format_id", "coco-detection-v1")

        return TrainingBackendRunResult(
            training_task_id=task_id,
            status="succeeded",
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
            dataset_version_id=dataset_version_id,
            format_id=format_id,
            output_object_prefix=output_prefix,
            checkpoint_object_key=checkpoint_key,
            latest_checkpoint_object_key=checkpoint_key,
            labels_object_key=None,
            metrics_object_key=metrics_key,
            validation_metrics_object_key=None,
            summary_object_key=None,
            best_metric_name=result.best_metric_name,
            best_metric_value=result.best_metric_value,
            summary={
                "model_scale": model_scale,
                "labels": list(result.labels),
                "input_size": list(result.aligned_input_size),
                "training_config": {
                    "input_size": list(result.aligned_input_size),
                    "model_scale": model_scale,
                    "batch_size": int(payload.get("batch_size", 2)),
                    "max_epochs": int(payload.get("max_epochs", 1)),
                    "precision": payload.get("precision", "fp32"),
                },
            },
        )
