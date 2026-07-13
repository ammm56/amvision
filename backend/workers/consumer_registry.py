"""后台任务消费者注册表。

采用声明式工厂模式：每种消费者类型只需在 ``_CONSUMER_FACTORIES`` 中
注册一个工厂函数，不再使用长 if-else 链。
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass

from backend.queue import LocalFileQueueBackend
from backend.service.application.errors import ServiceConfigurationError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.settings import (
    BACKEND_WORKER_CONSUMER_CLASSIFICATION_EVALUATION,
    BACKEND_WORKER_CONSUMER_CLASSIFICATION_INFERENCE,
    BACKEND_WORKER_CONSUMER_CLASSIFICATION_TRAINING,
    BACKEND_WORKER_CONSUMER_DATASET_EXPORT,
    BACKEND_WORKER_CONSUMER_DATASET_IMPORT,
    BACKEND_WORKER_CONSUMER_DETECTION_EVALUATION,
    BACKEND_WORKER_CONSUMER_OBB_EVALUATION,
    BACKEND_WORKER_CONSUMER_OBB_INFERENCE,
    BACKEND_WORKER_CONSUMER_OBB_TRAINING,
    BACKEND_WORKER_CONSUMER_POSE_EVALUATION,
    BACKEND_WORKER_CONSUMER_POSE_INFERENCE,
    BACKEND_WORKER_CONSUMER_POSE_TRAINING,
    BACKEND_WORKER_CONSUMER_RFDETR_CONVERSION,
    BACKEND_WORKER_CONSUMER_RFDETR_TRAINING,
    BACKEND_WORKER_CONSUMER_SEGMENTATION_EVALUATION,
    BACKEND_WORKER_CONSUMER_SEGMENTATION_INFERENCE,
    BACKEND_WORKER_CONSUMER_SEGMENTATION_TRAINING,
    BACKEND_WORKER_CONSUMER_YOLO11_TRAINING,
    BACKEND_WORKER_CONSUMER_YOLO11_CONVERSION,
    BACKEND_WORKER_CONSUMER_YOLO26_TRAINING,
    BACKEND_WORKER_CONSUMER_YOLO26_CONVERSION,
    BACKEND_WORKER_CONSUMER_YOLOV8_TRAINING,
    BACKEND_WORKER_CONSUMER_YOLOV8_CONVERSION,
    BACKEND_WORKER_CONSUMER_YOLOX_CONVERSION,
    BACKEND_WORKER_CONSUMER_DETECTION_INFERENCE,
    BACKEND_WORKER_CONSUMER_YOLOX_TRAINING,
)
from backend.workers.task_manager import BackgroundTaskConsumer


@dataclass(frozen=True)
class BackgroundTaskConsumerResources:
    """描述构造后台任务消费者需要的共享资源。

    字段：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储服务。
    - queue_backend：本地队列后端。
    - worker_id_prefix：worker id 前缀。
    - async_inference_request_timeout_seconds：等待 backend-service async inference 响应的最长秒数。
    """

    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: LocalFileQueueBackend
    worker_id_prefix: str
    async_inference_request_timeout_seconds: float = 30.0


# ── 工厂函数类型 ──

_ConsumerFactory = Callable[[BackgroundTaskConsumerResources], BackgroundTaskConsumer]


def _load_worker_class(module_name: str, class_name: str) -> type:
    """按需导入后台 worker 类。

    参数：
    - module_name：worker 类所在模块。
    - class_name：worker 类名。

    返回：
    - type：已导入的 worker 类。

    说明：
    - worker 注册表不能在模块加载时导入全部模型 worker，否则 CPU-only 发布目录启动
      dataset worker 时也会触碰训练、转换和 TensorRT 相关依赖。
    """

    worker_module = importlib.import_module(module_name)
    worker_cls = getattr(worker_module, class_name)
    if not isinstance(worker_cls, type):
        raise ServiceConfigurationError(
            "后台任务消费者类导入结果无效",
            details={"module_name": module_name, "class_name": class_name},
        )
    return worker_cls


def _std_factory(module_name: str, class_name: str, suffix: str) -> _ConsumerFactory:
    """构建标准 worker 工厂：session_factory + dataset_storage + queue_backend + worker_id。"""

    def _factory(resources: BackgroundTaskConsumerResources) -> BackgroundTaskConsumer:
        worker_cls = _load_worker_class(module_name, class_name)
        return worker_cls(
            session_factory=resources.session_factory,
            dataset_storage=resources.dataset_storage,
            queue_backend=resources.queue_backend,
            worker_id=f"{resources.worker_id_prefix}-{suffix}",
        )

    return _factory


def _inference_factory(suffix: str) -> _ConsumerFactory:
    """构建推理 worker 工厂：额外传递 async_inference_request_timeout_seconds。"""

    def _factory(resources: BackgroundTaskConsumerResources) -> BackgroundTaskConsumer:
        inference_worker_cls = _load_worker_class(
            "backend.workers.inference.inference_queue_worker",
            "InferenceQueueWorker",
        )
        return inference_worker_cls(
            consumer_kind=BACKEND_WORKER_CONSUMER_DETECTION_INFERENCE,
            session_factory=resources.session_factory,
            dataset_storage=resources.dataset_storage,
            queue_backend=resources.queue_backend,
            async_inference_request_timeout_seconds=resources.async_inference_request_timeout_seconds,
            worker_id=f"{resources.worker_id_prefix}-{suffix}",
        )

    return _factory


def _dynamic_inference_factory(resources: BackgroundTaskConsumerResources, consumer_kind: str) -> BackgroundTaskConsumer:
    """构建动态推理 worker 工厂：worker_id 使用 consumer_kind。"""
    inference_worker_cls = _load_worker_class(
        "backend.workers.inference.inference_queue_worker",
        "InferenceQueueWorker",
    )
    return inference_worker_cls(
        consumer_kind=consumer_kind,
        session_factory=resources.session_factory,
        dataset_storage=resources.dataset_storage,
        queue_backend=resources.queue_backend,
        async_inference_request_timeout_seconds=resources.async_inference_request_timeout_seconds,
        worker_id=f"{resources.worker_id_prefix}-{consumer_kind}",
    )


# ── 声明式注册表 ──

_CONSUMER_FACTORIES: dict[str, _ConsumerFactory] = {
    # 数据集
    BACKEND_WORKER_CONSUMER_DATASET_IMPORT: _std_factory(
        "backend.workers.datasets.dataset_import_queue_worker",
        "DatasetImportQueueWorker",
        "dataset-import",
    ),
    BACKEND_WORKER_CONSUMER_DATASET_EXPORT: _std_factory(
        "backend.workers.datasets.dataset_export_queue_worker",
        "DatasetExportQueueWorker",
        "dataset-export",
    ),
    # YOLOX
    BACKEND_WORKER_CONSUMER_YOLOX_TRAINING: _std_factory(
        "backend.workers.training.yolox_training_queue_worker",
        "YoloXTrainingQueueWorker",
        "yolox-training",
    ),
    BACKEND_WORKER_CONSUMER_YOLOX_CONVERSION: _std_factory(
        "backend.workers.conversion.yolox_conversion_queue_worker",
        "YoloXConversionQueueWorker",
        "yolox-conversion",
    ),
    BACKEND_WORKER_CONSUMER_DETECTION_INFERENCE: _inference_factory("detection-inference"),
    # YOLOv8
    BACKEND_WORKER_CONSUMER_YOLOV8_TRAINING: _std_factory(
        "backend.workers.training.yolov8_training_queue_worker",
        "YoloV8TrainingQueueWorker",
        "yolov8-training",
    ),
    BACKEND_WORKER_CONSUMER_YOLOV8_CONVERSION: _std_factory(
        "backend.workers.conversion.yolov8_conversion_queue_worker",
        "YoloV8ConversionQueueWorker",
        "yolov8-conversion",
    ),
    # YOLO11
    BACKEND_WORKER_CONSUMER_YOLO11_TRAINING: _std_factory(
        "backend.workers.training.yolo11_training_queue_worker",
        "Yolo11TrainingQueueWorker",
        "yolo11-training",
    ),
    BACKEND_WORKER_CONSUMER_YOLO11_CONVERSION: _std_factory(
        "backend.workers.conversion.yolo11_conversion_queue_worker",
        "Yolo11ConversionQueueWorker",
        "yolo11-conversion",
    ),
    # YOLO26
    BACKEND_WORKER_CONSUMER_YOLO26_TRAINING: _std_factory(
        "backend.workers.training.yolo26_training_queue_worker",
        "Yolo26TrainingQueueWorker",
        "yolo26-training",
    ),
    BACKEND_WORKER_CONSUMER_YOLO26_CONVERSION: _std_factory(
        "backend.workers.conversion.yolo26_conversion_queue_worker",
        "Yolo26ConversionQueueWorker",
        "yolo26-conversion",
    ),
    # RF-DETR
    BACKEND_WORKER_CONSUMER_RFDETR_TRAINING: _std_factory(
        "backend.workers.training.rfdetr_training_queue_worker",
        "RfdetrTrainingQueueWorker",
        "rfdetr-training",
    ),
    BACKEND_WORKER_CONSUMER_RFDETR_CONVERSION: _std_factory(
        "backend.workers.conversion.rfdetr_conversion_queue_worker",
        "RfdetrConversionQueueWorker",
        "rfdetr-conversion",
    ),
    # 非 Detection 训练
    BACKEND_WORKER_CONSUMER_CLASSIFICATION_TRAINING: _std_factory(
        "backend.workers.training.yolo_training_queue_worker",
        "ClassificationTrainingQueueWorker",
        "classification-training",
    ),
    BACKEND_WORKER_CONSUMER_SEGMENTATION_TRAINING: _std_factory(
        "backend.workers.training.yolo_training_queue_worker",
        "SegmentationTrainingQueueWorker",
        "segmentation-training",
    ),
    BACKEND_WORKER_CONSUMER_POSE_TRAINING: _std_factory(
        "backend.workers.training.yolo_training_queue_worker",
        "PoseTrainingQueueWorker",
        "pose-training",
    ),
    BACKEND_WORKER_CONSUMER_OBB_TRAINING: _std_factory(
        "backend.workers.training.yolo_training_queue_worker",
        "ObbTrainingQueueWorker",
        "obb-training",
    ),
    # 非 Detection 评估
    BACKEND_WORKER_CONSUMER_CLASSIFICATION_EVALUATION: _std_factory(
        "backend.workers.evaluation.model_evaluation_queue_worker",
        "ClassificationEvaluationQueueWorker",
        "classification-evaluation",
    ),
    BACKEND_WORKER_CONSUMER_SEGMENTATION_EVALUATION: _std_factory(
        "backend.workers.evaluation.model_evaluation_queue_worker",
        "SegmentationEvaluationQueueWorker",
        "segmentation-evaluation",
    ),
    BACKEND_WORKER_CONSUMER_DETECTION_EVALUATION: _std_factory(
        "backend.workers.evaluation.model_evaluation_queue_worker",
        "DetectionEvaluationQueueWorker",
        "detection-evaluation",
    ),
    BACKEND_WORKER_CONSUMER_POSE_EVALUATION: _std_factory(
        "backend.workers.evaluation.model_evaluation_queue_worker",
        "PoseEvaluationQueueWorker",
        "pose-evaluation",
    ),
    BACKEND_WORKER_CONSUMER_OBB_EVALUATION: _std_factory(
        "backend.workers.evaluation.model_evaluation_queue_worker",
        "ObbEvaluationQueueWorker",
        "obb-evaluation",
    ),
}

# 动态推理 worker（多个 consumer_kind 共享同一 worker 类，但 worker_id 不同）
_DYNAMIC_INFERENCE_KINDS: frozenset[str] = frozenset({
    BACKEND_WORKER_CONSUMER_CLASSIFICATION_INFERENCE,
    BACKEND_WORKER_CONSUMER_SEGMENTATION_INFERENCE,
    BACKEND_WORKER_CONSUMER_POSE_INFERENCE,
    BACKEND_WORKER_CONSUMER_OBB_INFERENCE,
})


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
        factory = _CONSUMER_FACTORIES.get(consumer_kind)
        if factory is not None:
            consumers.append(factory(resources))
            continue
        if consumer_kind in _DYNAMIC_INFERENCE_KINDS:
            consumers.append(_dynamic_inference_factory(resources, consumer_kind))
            continue
        raise ServiceConfigurationError(
            "发现未支持的后台任务消费者类型",
            details={"consumer_kind": consumer_kind},
        )

    return tuple(consumers)
