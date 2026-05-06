"""后台任务消费者注册表。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.queue import LocalFileQueueBackend
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolox_conversion_queue_worker import YoloXConversionQueueWorker
from backend.workers.datasets.dataset_export_queue_worker import DatasetExportQueueWorker
from backend.workers.datasets.dataset_import_queue_worker import DatasetImportQueueWorker
from backend.workers.evaluation.yolox_evaluation_queue_worker import YoloXEvaluationQueueWorker
from backend.workers.inference.yolox_inference_queue_worker import YoloXInferenceQueueWorker
from backend.workers.settings import (
    BACKEND_WORKER_CONSUMER_DATASET_EXPORT,
    BACKEND_WORKER_CONSUMER_DATASET_IMPORT,
    BACKEND_WORKER_CONSUMER_YOLOX_CONVERSION,
    BACKEND_WORKER_CONSUMER_YOLOX_EVALUATION,
    BACKEND_WORKER_CONSUMER_YOLOX_INFERENCE,
    BACKEND_WORKER_CONSUMER_YOLOX_TRAINING,
)
from backend.workers.task_manager import BackgroundTaskConsumer
from backend.workers.training.yolox_training_queue_worker import YoloXTrainingQueueWorker


@dataclass(frozen=True)
class BackgroundTaskConsumerResources:
    """描述构造后台任务消费者需要的共享资源。

    字段：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储服务。
    - queue_backend：本地队列后端。
    - worker_id_prefix：worker id 前缀。
    - yolox_async_deployment_process_supervisor：异步 deployment 进程监督器；YOLOX inference 消费者依赖该对象。
    """

    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: LocalFileQueueBackend
    worker_id_prefix: str
    yolox_async_deployment_process_supervisor: YoloXDeploymentProcessSupervisor | None = None


def build_background_task_consumers(
    *,
    resources: BackgroundTaskConsumerResources,
    enabled_consumer_kinds: tuple[str, ...],
) -> tuple[BackgroundTaskConsumer, ...]:
    """根据当前配置构造后台任务消费者列表。

    参数：
    - resources：构造消费者需要的共享资源。
    - enabled_consumer_kinds：需要启用的消费者种类列表。

    返回：
    - tuple[BackgroundTaskConsumer, ...]：按稳定顺序排列的消费者元组。
    """

    consumers: list[BackgroundTaskConsumer] = []
    for consumer_kind in enabled_consumer_kinds:
        if consumer_kind == BACKEND_WORKER_CONSUMER_DATASET_IMPORT:
            consumers.append(
                DatasetImportQueueWorker(
                    session_factory=resources.session_factory,
                    dataset_storage=resources.dataset_storage,
                    queue_backend=resources.queue_backend,
                    worker_id=f"{resources.worker_id_prefix}-dataset-import",
                )
            )
            continue
        if consumer_kind == BACKEND_WORKER_CONSUMER_DATASET_EXPORT:
            consumers.append(
                DatasetExportQueueWorker(
                    session_factory=resources.session_factory,
                    dataset_storage=resources.dataset_storage,
                    queue_backend=resources.queue_backend,
                    worker_id=f"{resources.worker_id_prefix}-dataset-export",
                )
            )
            continue
        if consumer_kind == BACKEND_WORKER_CONSUMER_YOLOX_TRAINING:
            consumers.append(
                YoloXTrainingQueueWorker(
                    session_factory=resources.session_factory,
                    dataset_storage=resources.dataset_storage,
                    queue_backend=resources.queue_backend,
                    worker_id=f"{resources.worker_id_prefix}-yolox-training",
                )
            )
            continue
        if consumer_kind == BACKEND_WORKER_CONSUMER_YOLOX_CONVERSION:
            consumers.append(
                YoloXConversionQueueWorker(
                    session_factory=resources.session_factory,
                    dataset_storage=resources.dataset_storage,
                    queue_backend=resources.queue_backend,
                    worker_id=f"{resources.worker_id_prefix}-yolox-conversion",
                )
            )
            continue
        if consumer_kind == BACKEND_WORKER_CONSUMER_YOLOX_EVALUATION:
            consumers.append(
                YoloXEvaluationQueueWorker(
                    session_factory=resources.session_factory,
                    dataset_storage=resources.dataset_storage,
                    queue_backend=resources.queue_backend,
                    worker_id=f"{resources.worker_id_prefix}-yolox-evaluation",
                )
            )
            continue
        if consumer_kind == BACKEND_WORKER_CONSUMER_YOLOX_INFERENCE:
            if resources.yolox_async_deployment_process_supervisor is None:
                raise ServiceConfigurationError("YOLOX inference 消费者缺少异步 deployment supervisor")
            consumers.append(
                YoloXInferenceQueueWorker(
                    session_factory=resources.session_factory,
                    dataset_storage=resources.dataset_storage,
                    queue_backend=resources.queue_backend,
                    deployment_process_supervisor=resources.yolox_async_deployment_process_supervisor,
                    worker_id=f"{resources.worker_id_prefix}-yolox-inference",
                )
            )
            continue
        raise ServiceConfigurationError(
            "发现未支持的后台任务消费者类型",
            details={"consumer_kind": consumer_kind},
        )

    return tuple(consumers)