"""YOLO 主线非 detection 训练执行器（TrainingBackend 实现）。

将 classification / segmentation / pose / obb 训练统一到 TrainingBackend
协议，与 YOLOX detection 训练保持一致的执行边界。
"""

from __future__ import annotations

from backend.service.application.backends import (
    TrainingBackendRunRequest,
    TrainingBackendRunResult,
)
from backend.service.application.models.training.yolov8_classification_training_service import (
    SqlAlchemyYoloV8ClassificationTrainingService,
    YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
    YOLO11_CLASSIFICATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo26_classification_training_service import (
    SqlAlchemyYolo26ClassificationTrainingTaskService,
    YOLO26_CLASSIFICATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.segmentation_training_service import (
    SqlAlchemySegmentationTrainingService,
    SEGMENTATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo11_segmentation_training_service import (
    SqlAlchemyYolo11SegmentationTrainingTaskService,
    YOLO11_SEGMENTATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo26_segmentation_training_service import (
    SqlAlchemyYolo26SegmentationTrainingTaskService,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolov8_pose_training_service import (
    SqlAlchemyYoloV8PoseTrainingService,
    YOLOV8_POSE_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo11_pose_training_service import (
    SqlAlchemyYolo11PoseTrainingTaskService,
    YOLO11_POSE_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo26_pose_training_service import (
    SqlAlchemyYolo26PoseTrainingTaskService,
    YOLO26_POSE_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolov8_obb_training_service import (
    SqlAlchemyYoloV8ObbTrainingService,
    YOLOV8_OBB_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo11_obb_training_service import (
    SqlAlchemyYolo11ObbTrainingTaskService,
    YOLO11_OBB_TRAINING_TASK_KIND,
)
from backend.service.application.models.training.yolo26_obb_training_service import (
    SqlAlchemyYolo26ObbTrainingTaskService,
    YOLO26_OBB_TRAINING_TASK_KIND,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


# 任务类型到训练服务的映射
_TASK_KIND_TO_SERVICE: dict[str, type] = {
    YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND: SqlAlchemyYoloV8ClassificationTrainingService,
    YOLO11_CLASSIFICATION_TRAINING_TASK_KIND: SqlAlchemyYolo11ClassificationTrainingTaskService,
    YOLO26_CLASSIFICATION_TRAINING_TASK_KIND: SqlAlchemyYolo26ClassificationTrainingTaskService,
    SEGMENTATION_TRAINING_TASK_KIND: SqlAlchemySegmentationTrainingService,
    YOLO11_SEGMENTATION_TRAINING_TASK_KIND: SqlAlchemyYolo11SegmentationTrainingTaskService,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND: SqlAlchemyYolo26SegmentationTrainingTaskService,
    YOLOV8_POSE_TRAINING_TASK_KIND: SqlAlchemyYoloV8PoseTrainingService,
    YOLO11_POSE_TRAINING_TASK_KIND: SqlAlchemyYolo11PoseTrainingTaskService,
    YOLO26_POSE_TRAINING_TASK_KIND: SqlAlchemyYolo26PoseTrainingTaskService,
    YOLOV8_OBB_TRAINING_TASK_KIND: SqlAlchemyYoloV8ObbTrainingService,
    YOLO11_OBB_TRAINING_TASK_KIND: SqlAlchemyYolo11ObbTrainingTaskService,
    YOLO26_OBB_TRAINING_TASK_KIND: SqlAlchemyYolo26ObbTrainingTaskService,
}

_MODEL_SPECIFIC_SERVICE_BY_TASK_KIND_AND_MODEL_TYPE: dict[tuple[str, str], type] = {
    (
        YOLO11_CLASSIFICATION_TRAINING_TASK_KIND,
        "yolo11",
    ): SqlAlchemyYolo11ClassificationTrainingTaskService,
    (
        YOLO26_CLASSIFICATION_TRAINING_TASK_KIND,
        "yolo26",
    ): SqlAlchemyYolo26ClassificationTrainingTaskService,
    (
        YOLO11_SEGMENTATION_TRAINING_TASK_KIND,
        "yolo11",
    ): SqlAlchemyYolo11SegmentationTrainingTaskService,
    (
        YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
        "yolo26",
    ): SqlAlchemyYolo26SegmentationTrainingTaskService,
    (
        YOLO11_POSE_TRAINING_TASK_KIND,
        "yolo11",
    ): SqlAlchemyYolo11PoseTrainingTaskService,
    (
        YOLO26_POSE_TRAINING_TASK_KIND,
        "yolo26",
    ): SqlAlchemyYolo26PoseTrainingTaskService,
    (
        YOLO11_OBB_TRAINING_TASK_KIND,
        "yolo11",
    ): SqlAlchemyYolo11ObbTrainingTaskService,
    (
        YOLO26_OBB_TRAINING_TASK_KIND,
        "yolo26",
    ): SqlAlchemyYolo26ObbTrainingTaskService,
}


class SqlAlchemyYoloTaskTrainerRunner:
    """基于 SQLAlchemy 的 YOLO 主线非 detection 训练执行器。

    实现 TrainingBackend 协议，统一 classification / segmentation /
    pose / obb 训练的执行边界。
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend=None,
    ) -> None:
        """初始化训练执行器。

        参数：
        - session_factory：数据库会话工厂。
        - dataset_storage：本地数据集文件存储服务。
        - queue_backend：队列后端（部分服务需要）。
        """
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend

    def run_training(
        self, request: TrainingBackendRunRequest
    ) -> TrainingBackendRunResult:
        """执行训练并返回结果。

        参数：
        - request：训练执行请求，metadata 中需包含 queue_payload。

        返回：
        - TrainingBackendRunResult：训练执行结果。
        """
        task_id = request.training_task_id
        task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
        task = task_service.get_task(task_id).task

        # 读取 model_type
        model_type = request.model_type
        if not model_type:
            payload = (task.metadata or {}).get("queue_payload", {})
            if isinstance(payload, dict):
                model_type = str(payload.get("model_type", "yolov8"))
            else:
                model_type = "yolov8"
            if not model_type or model_type in (
                "n",
                "nano",
                "tiny",
                "s",
                "m",
                "l",
                "x",
                "xx",
            ):
                model_type = "yolov8"

        # 获取对应的训练服务
        normalized_model_type = str(model_type or "").strip().lower()
        service_cls = _MODEL_SPECIFIC_SERVICE_BY_TASK_KIND_AND_MODEL_TYPE.get(
            (task.task_kind, normalized_model_type)
        )
        if service_cls is None:
            service_cls = _TASK_KIND_TO_SERVICE.get(task.task_kind)
        if service_cls is None:
            # 尝试通过 task_type 推断
            task_type = request.task_type or "classification"
            kind_map = {
                "classification": {
                    "yolo11": SqlAlchemyYolo11ClassificationTrainingTaskService,
                    "yolo26": SqlAlchemyYolo26ClassificationTrainingTaskService,
                }.get(
                    normalized_model_type,
                    SqlAlchemyYoloV8ClassificationTrainingService,
                ),
                "segmentation": {
                    "yolo11": SqlAlchemyYolo11SegmentationTrainingTaskService,
                    "yolo26": SqlAlchemyYolo26SegmentationTrainingTaskService,
                }.get(normalized_model_type, SqlAlchemySegmentationTrainingService),
                "pose": {
                    "yolo11": SqlAlchemyYolo11PoseTrainingTaskService,
                    "yolo26": SqlAlchemyYolo26PoseTrainingTaskService,
                }.get(normalized_model_type, SqlAlchemyYoloV8PoseTrainingService),
                "obb": {
                    "yolo11": SqlAlchemyYolo11ObbTrainingTaskService,
                    "yolo26": SqlAlchemyYolo26ObbTrainingTaskService,
                }.get(normalized_model_type, SqlAlchemyYoloV8ObbTrainingService),
            }
            service_cls = kind_map.get(task_type)
            if service_cls is None:
                raise ValueError(
                    f"无法确定训练服务: task_kind={task.task_kind}, task_type={request.task_type}"
                )

        # 构建服务实例
        service_kwargs = {
            "session_factory": self.session_factory,
            "dataset_storage": self.dataset_storage,
        }
        if self.queue_backend is not None:
            service_kwargs["queue_backend"] = self.queue_backend
        service = service_cls(**service_kwargs)

        # 执行训练
        result = service.process_training_task(task, model_type=model_type)

        # 构建统一结果
        output_prefix = f"task-runs/{task_id}"
        return TrainingBackendRunResult(
            training_task_id=task_id,
            status=result.get("status", "succeeded"),
            dataset_export_id=result.get("dataset_export_id", ""),
            dataset_export_manifest_key=result.get("dataset_export_manifest_key", ""),
            dataset_version_id=result.get("dataset_version_id", ""),
            format_id=result.get("format_id", ""),
            output_object_prefix=output_prefix,
            checkpoint_object_key=result.get(
                "checkpoint_object_key", f"{output_prefix}/latest.pt"
            ),
            latest_checkpoint_object_key=result.get("latest_checkpoint_object_key"),
            labels_object_key=result.get("labels_object_key"),
            metrics_object_key=result.get("metrics_object_key"),
            validation_metrics_object_key=result.get("validation_metrics_object_key"),
            summary_object_key=result.get("summary_object_key"),
            best_metric_name=result.get("best_metric_name", "loss"),
            best_metric_value=result.get("best_metric_value"),
            summary=result,
        )


