"""按 consumer kind 统一消费各任务推理队列的 worker。"""

from __future__ import annotations

from collections.abc import Callable

from backend.queue import QueueBackend, QueueMessage
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.models.inference.classification_inference_task_service import (
    CLASSIFICATION_INFERENCE_QUEUE_NAME,
    SqlAlchemyClassificationInferenceTaskService,
)
from backend.service.application.models.inference.inference_gateway import (
    QueueBackedAsyncInferenceClient,
)
from backend.service.application.models.inference.detection_inference_task_service import (
    DETECTION_INFERENCE_QUEUE_NAME,
    SqlAlchemyDetectionInferenceTaskService,
)
from backend.service.application.models.inference.obb_inference_task_service import (
    OBB_INFERENCE_QUEUE_NAME,
    SqlAlchemyObbInferenceTaskService,
)
from backend.service.application.models.inference.pose_inference_task_service import (
    POSE_INFERENCE_QUEUE_NAME,
    SqlAlchemyPoseInferenceTaskService,
)
from backend.service.application.models.inference.segmentation_inference_task_service import (
    SEGMENTATION_INFERENCE_QUEUE_NAME,
    SqlAlchemySegmentationInferenceTaskService,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.workers.queue_failure_metadata import build_queue_failure_metadata
from backend.workers.settings import (
    BACKEND_WORKER_CONSUMER_CLASSIFICATION_INFERENCE,
    BACKEND_WORKER_CONSUMER_DETECTION_INFERENCE,
    BACKEND_WORKER_CONSUMER_OBB_INFERENCE,
    BACKEND_WORKER_CONSUMER_POSE_INFERENCE,
    BACKEND_WORKER_CONSUMER_SEGMENTATION_INFERENCE,
)


_InferenceServiceFactory = Callable[..., object]

_INFERENCE_CONSUMER_CONFIGS: dict[str, tuple[str, _InferenceServiceFactory]] = {
    BACKEND_WORKER_CONSUMER_DETECTION_INFERENCE: (
        DETECTION_INFERENCE_QUEUE_NAME,
        SqlAlchemyDetectionInferenceTaskService,
    ),
    BACKEND_WORKER_CONSUMER_CLASSIFICATION_INFERENCE: (
        CLASSIFICATION_INFERENCE_QUEUE_NAME,
        SqlAlchemyClassificationInferenceTaskService,
    ),
    BACKEND_WORKER_CONSUMER_SEGMENTATION_INFERENCE: (
        SEGMENTATION_INFERENCE_QUEUE_NAME,
        SqlAlchemySegmentationInferenceTaskService,
    ),
    BACKEND_WORKER_CONSUMER_POSE_INFERENCE: (
        POSE_INFERENCE_QUEUE_NAME,
        SqlAlchemyPoseInferenceTaskService,
    ),
    BACKEND_WORKER_CONSUMER_OBB_INFERENCE: (
        OBB_INFERENCE_QUEUE_NAME,
        SqlAlchemyObbInferenceTaskService,
    ),
}


class InferenceQueueWorker:
    """消费指定推理任务队列的统一 worker。"""

    def __init__(
        self,
        *,
        consumer_kind: str,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        async_inference_request_timeout_seconds: float = 30.0,
        worker_id: str = "inference-worker",
    ) -> None:
        """初始化指定 consumer kind 的推理 worker。"""

        consumer_config = _INFERENCE_CONSUMER_CONFIGS.get(consumer_kind)
        if consumer_config is None:
            raise InvalidRequestError(
                "当前 inference worker 不支持指定 consumer kind",
                details={"consumer_kind": consumer_kind},
            )
        self.consumer_kind = consumer_kind
        self.queue_name, self.service_factory = consumer_config
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.async_inference_executor = QueueBackedAsyncInferenceClient(
            queue_backend=queue_backend,
            request_timeout_seconds=async_inference_request_timeout_seconds,
            client_id=worker_id,
        )
        self.worker_id = worker_id

    def run_once(self) -> bool:
        """消费并执行一条推理队列任务。"""

        queue_task = self.queue_backend.claim_next(
            queue_name=self.queue_name,
            worker_id=self.worker_id,
        )
        if queue_task is None:
            return False

        try:
            task_id = self._read_task_id(queue_task)
            service = self.service_factory(
                session_factory=self.session_factory,
                dataset_storage=self.dataset_storage,
                async_inference_executor=self.async_inference_executor,
            )
            run_result = service.process_inference_task(task_id)
        except ServiceError as error:
            self.queue_backend.fail(
                queue_task,
                error_message=error.message,
                metadata=build_queue_failure_metadata(queue_task, error),
            )
            return True
        except Exception as error:
            self.queue_backend.fail(
                queue_task,
                error_message=str(error),
                metadata=build_queue_failure_metadata(queue_task, error),
            )
            return True

        complete_metadata = {
            "task_id": run_result.task_id,
            "status": run_result.status,
            "deployment_instance_id": run_result.deployment_instance_id,
            "model_version_id": run_result.model_version_id,
            "model_build_id": run_result.model_build_id,
            "output_object_prefix": run_result.output_object_prefix,
            "result_object_key": run_result.result_object_key,
            "preview_image_object_key": run_result.preview_image_object_key,
            "latency_ms": run_result.latency_ms,
            "consumer_kind": self.consumer_kind,
        }
        detection_count = getattr(run_result, "detection_count", None)
        if isinstance(detection_count, int):
            complete_metadata["detection_count"] = detection_count
            complete_metadata["item_count"] = detection_count
        item_count = getattr(run_result, "item_count", None)
        if isinstance(item_count, int):
            complete_metadata["item_count"] = item_count

        self.queue_backend.complete(queue_task, metadata=complete_metadata)
        return True

    @staticmethod
    def _read_task_id(queue_task: QueueMessage) -> str:
        """从队列负载中读取推理任务 id。"""

        task_id = queue_task.payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidRequestError(
                "推理队列任务缺少 task_id",
                details={"queue_task_id": queue_task.task_id},
            )
        return task_id


__all__ = ["InferenceQueueWorker"]
