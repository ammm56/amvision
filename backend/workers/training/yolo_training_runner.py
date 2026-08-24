"""YOLO 主线非 detection 训练执行器（TrainingBackend 实现）。

将 classification / segmentation / pose / obb 训练统一到 TrainingBackend
协议，与 YOLOX detection 训练保持一致的执行边界。
"""

from __future__ import annotations

from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    read_task_execution_fence,
)
from backend.service.application.backends import (
    TrainingBackendRunRequest,
    TrainingBackendRunResult,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.model_type_support import (
    require_supported_platform_model_type,
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
from backend.service.application.support.resource_cleanup import (
    model_task_resource_cleanup,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.workers.training.device_assignment import assigned_training_device


_SERVICE_BY_TASK_KIND_AND_MODEL_TYPE: dict[tuple[str, str], type] = {
    (
        YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND,
        "yolov8",
    ): SqlAlchemyYoloV8ClassificationTrainingService,
    (
        YOLO11_CLASSIFICATION_TRAINING_TASK_KIND,
        "yolo11",
    ): SqlAlchemyYolo11ClassificationTrainingTaskService,
    (
        YOLO26_CLASSIFICATION_TRAINING_TASK_KIND,
        "yolo26",
    ): SqlAlchemyYolo26ClassificationTrainingTaskService,
    (
        SEGMENTATION_TRAINING_TASK_KIND,
        "yolov8",
    ): SqlAlchemySegmentationTrainingService,
    (
        SEGMENTATION_TRAINING_TASK_KIND,
        "rfdetr",
    ): SqlAlchemySegmentationTrainingService,
    (
        YOLO11_SEGMENTATION_TRAINING_TASK_KIND,
        "yolo11",
    ): SqlAlchemyYolo11SegmentationTrainingTaskService,
    (
        YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
        "yolo26",
    ): SqlAlchemyYolo26SegmentationTrainingTaskService,
    (
        YOLOV8_POSE_TRAINING_TASK_KIND,
        "yolov8",
    ): SqlAlchemyYoloV8PoseTrainingService,
    (
        YOLO11_POSE_TRAINING_TASK_KIND,
        "yolo11",
    ): SqlAlchemyYolo11PoseTrainingTaskService,
    (
        YOLO26_POSE_TRAINING_TASK_KIND,
        "yolo26",
    ): SqlAlchemyYolo26PoseTrainingTaskService,
    (
        YOLOV8_OBB_TRAINING_TASK_KIND,
        "yolov8",
    ): SqlAlchemyYoloV8ObbTrainingService,
    (
        YOLO11_OBB_TRAINING_TASK_KIND,
        "yolo11",
    ): SqlAlchemyYolo11ObbTrainingTaskService,
    (
        YOLO26_OBB_TRAINING_TASK_KIND,
        "yolo26",
    ): SqlAlchemyYolo26ObbTrainingTaskService,
}


class SqlAlchemyYoloTrainingRunner:
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
        execution_fence = read_task_execution_fence(request.metadata)
        with (
            model_task_resource_cleanup(),
            assigned_training_device(
                session_factory=self.session_factory,
                task_id=task_id,
                execution_fence=execution_fence,
            ),
        ):
            task_service = SqlAlchemyTaskService(session_factory=self.session_factory)
            task = task_service.get_task(task_id).task
            task = self._restore_recovered_running_task(
                task=task,
                task_service=task_service,
                request=request,
                execution_fence=execution_fence,
            )

            task_type = str(request.task_type or "").strip().lower()
            if not task_type:
                raise InvalidRequestError(
                    "训练执行请求缺少 task_type",
                    details={"task_kind": task.task_kind},
                )
            normalized_model_type = require_supported_platform_model_type(
                task_type=task_type,
                model_type=request.model_type,
                empty_message="训练执行请求缺少 model_type",
                unsupported_message="训练执行请求的模型分类与任务类型不匹配",
            )
            service_cls = _SERVICE_BY_TASK_KIND_AND_MODEL_TYPE.get(
                (task.task_kind, normalized_model_type)
            )
            if service_cls is None:
                raise InvalidRequestError(
                    "训练任务记录与请求的模型分类不匹配",
                    details={
                        "task_kind": task.task_kind,
                        "task_type": task_type,
                        "model_type": normalized_model_type,
                    },
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
            result = service.process_training_task(
                task,
                model_type=normalized_model_type,
                execution_fence=execution_fence,
            )

            # 构建统一结果
            output_prefix = f"task-runs/{task_id}"
            return TrainingBackendRunResult(
                training_task_id=task_id,
                status=result.get("status", "succeeded"),
                dataset_export_id=result.get("dataset_export_id", ""),
                dataset_export_manifest_key=result.get(
                    "dataset_export_manifest_key", ""
                ),
                dataset_version_id=result.get("dataset_version_id", ""),
                format_id=result.get("format_id", ""),
                output_object_prefix=output_prefix,
                checkpoint_object_key=result.get(
                    "checkpoint_object_key", f"{output_prefix}/latest.pt"
                ),
                latest_checkpoint_object_key=result.get("latest_checkpoint_object_key"),
                labels_object_key=result.get("labels_object_key"),
                metrics_object_key=result.get("metrics_object_key"),
                validation_metrics_object_key=result.get(
                    "validation_metrics_object_key"
                ),
                summary_object_key=result.get("summary_object_key"),
                best_metric_name=result.get("best_metric_name", "loss"),
                best_metric_value=result.get("best_metric_value"),
                summary=result,
            )

    def _restore_recovered_running_task(
        self,
        *,
        task: TaskRecord,
        task_service: SqlAlchemyTaskService,
        request: TrainingBackendRunRequest,
        execution_fence,
    ) -> TaskRecord:
        """队列 lease 回收后，从已落盘的 latest checkpoint 恢复任务快照。"""

        if request.metadata.get("queue_lease_recovered") is not True:
            return task
        if task.state != "running":
            return task

        output_prefix = f"task-runs/{task.task_id}/output-files"
        latest_checkpoint_object_key = f"{output_prefix}/latest-checkpoint.pt"
        latest_checkpoint_path = self.dataset_storage.resolve(
            latest_checkpoint_object_key
        )
        if not latest_checkpoint_path.is_file():
            raise InvalidRequestError(
                "训练 queue lease 已恢复，但 latest checkpoint 不存在",
                details={
                    "task_id": task.task_id,
                    "latest_checkpoint_object_key": latest_checkpoint_object_key,
                },
            )

        best_checkpoint_object_key = f"{output_prefix}/best-checkpoint.pt"
        result_patch: dict[str, object] = {
            "latest_checkpoint_object_key": latest_checkpoint_object_key,
        }
        if self.dataset_storage.resolve(best_checkpoint_object_key).is_file():
            result_patch["checkpoint_object_key"] = best_checkpoint_object_key

        recovery_count = request.metadata.get("queue_lease_recovery_count")
        task_service.execute_task_state_event_command(
            AppendTaskEventRequest(
                task_id=task.task_id,
                event_type="status",
                message="training queue lease recovered",
                payload={
                    "state": "running",
                    "attempt_no": task.current_attempt_no,
                    "finished_at": None,
                    "error_message": None,
                    "progress": {"stage": "running"},
                    "result": result_patch,
                    "metadata": {
                        "training_queue_recovery": {
                            "queue_task_id": request.metadata.get("queue_task_id"),
                            "queue_attempt_count": request.metadata.get(
                                "queue_attempt_count"
                            ),
                            "lease_recovery_count": (
                                recovery_count
                                if isinstance(recovery_count, int)
                                else 1
                            ),
                        }
                    },
                },
            ),
            fence=execution_fence,
        )
        return task_service.get_task(task.task_id).task
