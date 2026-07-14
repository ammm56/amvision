"""classification / segmentation / detection / pose / obb 评估队列 worker。"""

from __future__ import annotations

from backend.queue import QueueBackend
from backend.service.application.models.evaluation.yolov8_classification_evaluation_service import (
    CLASSIFICATION_EVALUATION_QUEUE_NAME,
    SqlAlchemyYoloV8ClassificationEvaluationService,
)
from backend.service.application.models.evaluation.segmentation_evaluation_service import (
    SEGMENTATION_EVALUATION_QUEUE_NAME,
    SqlAlchemySegmentationEvaluationService,
)
from backend.service.application.models.evaluation.detection_evaluation_task_service import (
    DETECTION_EVALUATION_QUEUE_NAME,
    SqlAlchemyDetectionEvaluationTaskService,
)
from backend.service.application.models.evaluation.pose_evaluation_task_service import (
    POSE_EVALUATION_QUEUE_NAME,
    SqlAlchemyPoseEvaluationTaskService,
)
from backend.service.application.models.evaluation.obb_evaluation_task_service import (
    OBB_EVALUATION_QUEUE_NAME,
    SqlAlchemyObbEvaluationTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.queue_failure_metadata import build_queue_failure_metadata


class ClassificationEvaluationQueueWorker:
    """消费 classification-evaluations 队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        worker_id: str = "classification-evaluation",
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        queue_task = self.queue_backend.claim_next(
            queue_name=CLASSIFICATION_EVALUATION_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False
        try:
            task_id = queue_task.payload["task_id"]
            service = SqlAlchemyYoloV8ClassificationEvaluationService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
            )
            result = service.process_evaluation_task(task_id)
            self.queue_backend.complete(queue_task, metadata={
                "task_id": task_id, "status": "succeeded",
                "top1_accuracy": result.top1_accuracy,
                "top5_accuracy": result.top5_accuracy,
                "sample_count": result.sample_count,
                "report_object_key": result.report_object_key,
            })
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata=build_queue_failure_metadata(queue_task, error),
            )
        return True


class SegmentationEvaluationQueueWorker:
    """消费 segmentation-evaluations 队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        worker_id: str = "segmentation-evaluation",
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        queue_task = self.queue_backend.claim_next(
            queue_name=SEGMENTATION_EVALUATION_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False
        try:
            task_id = queue_task.payload["task_id"]
            service = SqlAlchemySegmentationEvaluationService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
            )
            result = service.process_evaluation_task(task_id)
            self.queue_backend.complete(queue_task, metadata={
                "task_id": task_id, "status": "succeeded",
                "map50": result.map50, "map50_95": result.map50_95,
                "mask_map50": result.mask_map50, "mask_map50_95": result.mask_map50_95,
                "sample_count": result.sample_count,
                "report_object_key": result.report_object_key,
            })
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata=build_queue_failure_metadata(queue_task, error),
            )
        return True


class DetectionEvaluationQueueWorker:
    """消费 detection-evaluations 队列（统一 detection 评估）。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        worker_id: str = "detection-evaluation",
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        queue_task = self.queue_backend.claim_next(
            queue_name=DETECTION_EVALUATION_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False
        try:
            task_id = queue_task.payload["task_id"]
            service = SqlAlchemyDetectionEvaluationTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
            )
            result = service.process_evaluation_task(task_id)
            self.queue_backend.complete(
                queue_task,
                metadata={
                    "task_id": task_id,
                    "status": "succeeded",
                    "map50": result.map50,
                    "map50_95": result.map50_95,
                    "sample_count": result.sample_count,
                    "report_object_key": result.report_object_key,
                },
            )
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata=build_queue_failure_metadata(queue_task, error),
            )
        return True


class PoseEvaluationQueueWorker:
    """消费 pose-evaluations 队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        worker_id: str = "pose-evaluation",
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        queue_task = self.queue_backend.claim_next(
            queue_name=POSE_EVALUATION_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False
        try:
            task_id = queue_task.payload["task_id"]
            service = SqlAlchemyPoseEvaluationTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
            )
            result = service.process_evaluation_task(task_id)
            self.queue_backend.complete(
                queue_task,
                metadata={
                    "task_id": task_id,
                    "status": "succeeded",
                    "oks_ap50": result.oks_ap50,
                    "oks_ap50_95": result.oks_ap50_95,
                    "sample_count": result.sample_count,
                    "report_object_key": result.report_object_key,
                },
            )
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata=build_queue_failure_metadata(queue_task, error),
            )
        return True


class ObbEvaluationQueueWorker:
    """消费 obb-evaluations 队列。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        worker_id: str = "obb-evaluation",
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.worker_id = worker_id

    def run_once(self) -> bool:
        queue_task = self.queue_backend.claim_next(
            queue_name=OBB_EVALUATION_QUEUE_NAME,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False
        try:
            task_id = queue_task.payload["task_id"]
            service = SqlAlchemyObbEvaluationTaskService(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                queue_backend=self.queue_backend,
            )
            result = service.process_evaluation_task(task_id)
            self.queue_backend.complete(
                queue_task,
                metadata={
                    "task_id": task_id,
                    "status": "succeeded",
                    "map50": result.map50,
                    "map50_95": result.map50_95,
                    "sample_count": result.sample_count,
                    "report_object_key": result.report_object_key,
                },
            )
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata=build_queue_failure_metadata(queue_task, error),
            )
        return True
