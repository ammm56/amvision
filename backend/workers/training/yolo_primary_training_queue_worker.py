"""YOLO 主线非 detection 训练队列 worker。"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.backends import TrainingBackend, TrainingBackendRunRequest
from backend.service.application.errors import InvalidRequestError, OperationCancelledError, ServiceError
from backend.service.application.tasks.task_service import AppendTaskEventRequest, SqlAlchemyTaskService
from backend.service.application.models.yolo_primary_classification_training_service import (
    YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME,
)
from backend.service.application.models.yolo26_classification_training_service import (
    YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME,
)
from backend.service.application.models.yolo_primary_segmentation_training_service import (
    YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME,
)
from backend.service.application.models.yolo26_segmentation_training_service import (
    YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
)
from backend.service.application.models.yolo_primary_pose_training_service import (
    POSE_TRAINING_QUEUE_NAME,
)
from backend.service.application.models.yolo26_pose_training_service import (
    YOLO26_POSE_TRAINING_QUEUE_NAME,
)
from backend.service.application.models.yolo26_obb_training_service import (
    YOLO26_OBB_TRAINING_QUEUE_NAME,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.training.yolo_primary_trainer_runner import SqlAlchemyYoloPrimaryTrainerRunner


OBB_TRAINING_QUEUE_NAME = "obb-trainings"


class ClassificationTrainingQueueWorker:
    """消费 classification 训练队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        training_backend: TrainingBackend | None = None,
        worker_id: str = "classification-training-worker",
    ) -> None:
        """初始化 classification 训练队列 worker。"""
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.training_backend = training_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 classification 训练任务。"""
        qt = _claim_next_training_queue(
            self.queue_backend,
            queue_names=(
                YOLO_PRIMARY_CLASSIFICATION_TRAINING_QUEUE_NAME,
                YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME,
            ),
            worker_id=self.worker_id,
        )
        if qt is None:
            return False

        try:
            task_id = _read_task_id(qt)
            training_backend = self.training_backend or SqlAlchemyYoloPrimaryTrainerRunner(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
            )
            run_result = training_backend.run_training(TrainingBackendRunRequest(
                training_task_id=task_id,
                model_type=_read_model_type(qt.payload),
                task_type="classification",
                metadata={"queue_task_id": qt.task_id},
            ))
        except OperationCancelledError as error:
            self.queue_backend.complete(qt, metadata={"task_id": qt.payload.get("task_id"), "status": "cancelled", "cancel_message": error.message})
            return True
        except ServiceError as error:
            _mark_training_task_failed(
                session_factory=self.session_factory,
                payload=qt.payload,
                error_message=error.message,
            )
            self.queue_backend.fail(qt, error_message=error.message, metadata={"task_id": qt.payload.get("task_id")})
            return True
        except Exception as error:
            _mark_training_task_failed(
                session_factory=self.session_factory,
                payload=qt.payload,
                error_message=str(error),
            )
            self.queue_backend.fail(qt, error_message=str(error), metadata={"task_id": qt.payload.get("task_id"), "error_type": error.__class__.__name__})
            return True

        self.queue_backend.complete(qt, metadata={
            "task_id": run_result.training_task_id, "status": run_result.status,
            "dataset_export_id": run_result.dataset_export_id,
            "output_object_prefix": run_result.output_object_prefix,
            "checkpoint_object_key": run_result.checkpoint_object_key,
        })
        return True


def _claim_next_training_queue(
    queue_backend: QueueBackend,
    *,
    queue_names: tuple[str, ...],
    worker_id: str,
) -> QueueMessage | None:
    """按顺序从多个训练队列中领取一条任务。"""

    for queue_name in queue_names:
        queue_task = queue_backend.claim_next(
            queue_name=queue_name,
            worker_id=worker_id,
        )
        if queue_task is not None:
            return queue_task
    return None


class SegmentationTrainingQueueWorker:
    """消费 segmentation 训练队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        training_backend: TrainingBackend | None = None,
        worker_id: str = "segmentation-training-worker",
    ) -> None:
        """初始化 segmentation 训练队列 worker。"""
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.training_backend = training_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 segmentation 训练任务。"""
        qt = _claim_next_training_queue(
            self.queue_backend,
            queue_names=(
                YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME,
                YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
            ),
            worker_id=self.worker_id,
        )
        if qt is None:
            return False

        try:
            task_id = _read_task_id(qt)
            training_backend = self.training_backend or SqlAlchemyYoloPrimaryTrainerRunner(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
            )
            run_result = training_backend.run_training(TrainingBackendRunRequest(
                training_task_id=task_id,
                model_type=_read_model_type(qt.payload),
                task_type="segmentation",
                metadata={"queue_task_id": qt.task_id},
            ))
        except OperationCancelledError as error:
            self.queue_backend.complete(qt, metadata={"task_id": qt.payload.get("task_id"), "status": "cancelled", "cancel_message": error.message})
            return True
        except ServiceError as error:
            _mark_training_task_failed(
                session_factory=self.session_factory,
                payload=qt.payload,
                error_message=error.message,
            )
            self.queue_backend.fail(qt, error_message=error.message, metadata={"task_id": qt.payload.get("task_id")})
            return True
        except Exception as error:
            _mark_training_task_failed(
                session_factory=self.session_factory,
                payload=qt.payload,
                error_message=str(error),
            )
            self.queue_backend.fail(qt, error_message=str(error), metadata={"task_id": qt.payload.get("task_id"), "error_type": error.__class__.__name__})
            return True

        self.queue_backend.complete(qt, metadata={
            "task_id": run_result.training_task_id, "status": run_result.status,
            "dataset_export_id": run_result.dataset_export_id,
            "output_object_prefix": run_result.output_object_prefix,
            "checkpoint_object_key": run_result.checkpoint_object_key,
        })
        return True


class PoseTrainingQueueWorker:
    """消费 pose 训练队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        training_backend: TrainingBackend | None = None,
        worker_id: str = "pose-training-worker",
    ) -> None:
        """初始化 pose 训练队列 worker。"""
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.training_backend = training_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 pose 训练任务。"""
        qt = _claim_next_training_queue(
            self.queue_backend,
            queue_names=(
                POSE_TRAINING_QUEUE_NAME,
                YOLO26_POSE_TRAINING_QUEUE_NAME,
            ),
            worker_id=self.worker_id,
        )
        if qt is None:
            return False

        try:
            task_id = _read_task_id(qt)
            training_backend = self.training_backend or SqlAlchemyYoloPrimaryTrainerRunner(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
            )
            run_result = training_backend.run_training(TrainingBackendRunRequest(
                training_task_id=task_id,
                model_type=_read_model_type(qt.payload),
                task_type="pose",
                metadata={"queue_task_id": qt.task_id},
            ))
        except OperationCancelledError as error:
            self.queue_backend.complete(qt, metadata={"task_id": qt.payload.get("task_id"), "status": "cancelled", "cancel_message": error.message})
            return True
        except ServiceError as error:
            _mark_training_task_failed(
                session_factory=self.session_factory,
                payload=qt.payload,
                error_message=error.message,
            )
            self.queue_backend.fail(qt, error_message=error.message, metadata={"task_id": qt.payload.get("task_id")})
            return True
        except Exception as error:
            _mark_training_task_failed(
                session_factory=self.session_factory,
                payload=qt.payload,
                error_message=str(error),
            )
            self.queue_backend.fail(qt, error_message=str(error), metadata={"task_id": qt.payload.get("task_id"), "error_type": error.__class__.__name__})
            return True

        self.queue_backend.complete(qt, metadata={
            "task_id": run_result.training_task_id, "status": run_result.status,
            "dataset_export_id": run_result.dataset_export_id,
            "output_object_prefix": run_result.output_object_prefix,
            "checkpoint_object_key": run_result.checkpoint_object_key,
        })
        return True


class ObbTrainingQueueWorker:
    """消费 obb 训练队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        training_backend: TrainingBackend | None = None,
        worker_id: str = "obb-training-worker",
    ) -> None:
        """初始化 obb 训练队列 worker。"""
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.training_backend = training_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条 obb 训练任务。"""
        qt = _claim_next_training_queue(
            self.queue_backend,
            queue_names=(
                OBB_TRAINING_QUEUE_NAME,
                YOLO26_OBB_TRAINING_QUEUE_NAME,
            ),
            worker_id=self.worker_id,
        )
        if qt is None:
            return False

        try:
            task_id = _read_task_id(qt)
            training_backend = self.training_backend or SqlAlchemyYoloPrimaryTrainerRunner(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
            )
            run_result = training_backend.run_training(TrainingBackendRunRequest(
                training_task_id=task_id,
                model_type=_read_model_type(qt.payload),
                task_type="obb",
                metadata={"queue_task_id": qt.task_id},
            ))
        except OperationCancelledError as error:
            self.queue_backend.complete(qt, metadata={"task_id": qt.payload.get("task_id"), "status": "cancelled", "cancel_message": error.message})
            return True
        except ServiceError as error:
            _mark_training_task_failed(
                session_factory=self.session_factory,
                payload=qt.payload,
                error_message=error.message,
            )
            self.queue_backend.fail(qt, error_message=error.message, metadata={"task_id": qt.payload.get("task_id")})
            return True
        except Exception as error:
            _mark_training_task_failed(
                session_factory=self.session_factory,
                payload=qt.payload,
                error_message=str(error),
            )
            self.queue_backend.fail(qt, error_message=str(error), metadata={"task_id": qt.payload.get("task_id"), "error_type": error.__class__.__name__})
            return True

        self.queue_backend.complete(qt, metadata={
            "task_id": run_result.training_task_id, "status": run_result.status,
            "dataset_export_id": run_result.dataset_export_id,
            "output_object_prefix": run_result.output_object_prefix,
            "checkpoint_object_key": run_result.checkpoint_object_key,
        })
        return True


def _read_task_id(qt: QueueMessage) -> str:
    """从队列负载中读取训练任务 id。"""
    import json
    payload = qt.payload
    if isinstance(payload, dict):
        return str(payload.get("task_id", ""))
    if isinstance(payload, str):
        return str(json.loads(payload).get("task_id", ""))
    raise InvalidRequestError("训练队列任务缺少 task_id")


def _read_model_type(payload: dict | str) -> str:
    """从负载中读取模型类型。"""
    import json
    if isinstance(payload, str):
        payload = json.loads(payload)
    model_type = str(payload.get("model_type", payload.get("model_scale", "yolov8")))
    if not model_type or model_type in ("s", "m", "l", "x", "nano"):
        return "yolov8"
    return model_type


def _mark_training_task_failed(
    *,
    session_factory: SessionFactory,
    payload: dict | str,
    error_message: str,
) -> None:
    """在 worker 早期异常时把平台 TaskRecord 同步为 failed。

    训练服务内部异常通常会自行写入失败事件；该兜底只处理 runner 或
    worker 边界提前失败的情况，避免队列失败但页面任务仍停在 queued。
    """

    task_id = _read_optional_task_id(payload)
    if task_id is None:
        return
    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    try:
        task_record = task_service.get_task(task_id).task
        if task_record.state in {"succeeded", "failed", "cancelled"}:
            return
        task_service.append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="result",
                message="training failed",
                payload={
                    "state": "failed",
                    "error_message": error_message,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
    except Exception:
        return


def _read_optional_task_id(payload: dict | str) -> str | None:
    """从队列负载中读取可选 task_id。"""

    import json

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("task_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
