"""YOLO11 classification 训练 service hook 工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.training.yolo11_classification_task_execution import (
    run_yolo11_classification_training_from_task_request,
)
from backend.service.application.models.training.yolo11_classification_task_payload import (
    build_yolo11_classification_create_task_metadata,
    build_yolo11_classification_queue_payload,
    build_yolo11_classification_task_spec,
    read_yolo11_classification_task_payload,
)
from backend.service.application.models.training.yolo11_classification_task_registration import (
    register_yolo11_classification_training_output_model_version,
    resolve_yolo11_classification_implementation_mode,
)
from backend.service.application.models.training.yolo11_task_service_support import (
    require_yolo11_model_type,
)
from backend.service.application.models.training.yolo11_classification_training import (
    Yolo11ClassificationTrainingPausedError,
    Yolo11ClassificationTrainingTerminatedError,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory


def build_yolo11_classification_service_task_spec(
    *,
    request: Any,
    dataset_export: DatasetExport,
    model_type: str,
) -> dict[str, object]:
    """构建 YOLO11 classification 训练任务规格快照。"""

    require_yolo11_model_type(model_type, task_type="classification")
    return build_yolo11_classification_task_spec(
        request=request,
        dataset_export=dataset_export,
        model_type=model_type,
    )


def build_yolo11_classification_service_create_task_metadata(
    *,
    request: Any,
    dataset_export: DatasetExport,
    model_type: str,
    task_spec: dict[str, object],
) -> dict[str, object]:
    """构建 YOLO11 classification TaskRecord metadata。"""

    require_yolo11_model_type(model_type, task_type="classification")
    return build_yolo11_classification_create_task_metadata(
        request=request,
        dataset_export=dataset_export,
        model_type=model_type,
        task_spec=task_spec,
    )


def build_yolo11_classification_service_queue_payload(
    *,
    task_id: str,
    task_kind: str,
    task_spec: dict[str, object],
) -> dict[str, object]:
    """构建 YOLO11 classification 队列负载。"""

    return build_yolo11_classification_queue_payload(
        task_id=task_id,
        task_kind=task_kind,
        task_spec=task_spec,
    )


def read_yolo11_classification_service_task_payload(
    task_record: TaskRecord,
) -> dict[str, object]:
    """从任务记录中解析 YOLO11 classification 训练负载。"""

    return read_yolo11_classification_task_payload(task_record)


def run_yolo11_classification_service_training_execution(request: object) -> object:
    """执行 YOLO11 classification 训练。"""

    return run_yolo11_classification_training_from_task_request(request)


def get_yolo11_classification_terminated_error_types() -> tuple[
    type[BaseException], ...
]:
    """返回 YOLO11 classification 应按取消处理的异常类型。"""

    return (Yolo11ClassificationTrainingTerminatedError,)


def get_yolo11_classification_paused_error_types() -> tuple[type[BaseException], ...]:
    """返回 YOLO11 classification 应按暂停处理的异常类型。"""

    return (Yolo11ClassificationTrainingPausedError,)


def register_yolo11_classification_service_training_output(
    *,
    session_factory: SessionFactory,
    task_record: TaskRecord,
    dataset_export: DatasetExport,
    payload: dict[str, object],
    model_type: str,
    execution_result: object,
    checkpoint_object_key: str,
    labels_object_key: str,
    train_metrics_object_key: str,
    summary: dict[str, object],
) -> str:
    """登记 YOLO11 classification 训练输出。"""

    require_yolo11_model_type(model_type, task_type="classification")
    return register_yolo11_classification_training_output_model_version(
        session_factory=session_factory,
        task_record=task_record,
        dataset_export=dataset_export,
        payload=payload,
        execution_result=execution_result,
        checkpoint_object_key=checkpoint_object_key,
        labels_object_key=labels_object_key,
        train_metrics_object_key=train_metrics_object_key,
        summary=summary,
    )


def resolve_yolo11_classification_service_implementation_mode(model_type: str) -> str:
    """返回 YOLO11 classification 训练实现标记。"""

    require_yolo11_model_type(model_type, task_type="classification")
    return resolve_yolo11_classification_implementation_mode()


__all__ = [
    "build_yolo11_classification_service_create_task_metadata",
    "build_yolo11_classification_service_queue_payload",
    "build_yolo11_classification_service_task_spec",
    "get_yolo11_classification_paused_error_types",
    "get_yolo11_classification_terminated_error_types",
    "read_yolo11_classification_service_task_payload",
    "register_yolo11_classification_service_training_output",
    "resolve_yolo11_classification_service_implementation_mode",
    "run_yolo11_classification_service_training_execution",
]
