"""非 detection 训练任务类型、队列和服务选择。"""

from __future__ import annotations

from importlib import import_module
from typing import Protocol

from backend.service.application.errors import InvalidRequestError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
)
from backend.service.application.models.training.task_catalog import (  # noqa: F401
    NON_DETECTION_TRAINING_TASK_CATALOG,
    SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    SEGMENTATION_TRAINING_QUEUE_NAME,
    SEGMENTATION_TRAINING_TASK_KIND,
    YOLO11_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO11_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO11_CLASSIFICATION_TRAINING_TASK_KIND,
    YOLO11_OBB_TRAINING_CONTROL_METADATA_KEY,
    YOLO11_OBB_TRAINING_QUEUE_NAME,
    YOLO11_OBB_TRAINING_TASK_KIND,
    YOLO11_POSE_TRAINING_CONTROL_METADATA_KEY,
    YOLO11_POSE_TRAINING_QUEUE_NAME,
    YOLO11_POSE_TRAINING_TASK_KIND,
    YOLO11_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO11_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO11_SEGMENTATION_TRAINING_TASK_KIND,
    YOLO26_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO26_CLASSIFICATION_TRAINING_TASK_KIND,
    YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_OBB_TRAINING_QUEUE_NAME,
    YOLO26_OBB_TRAINING_TASK_KIND,
    YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_POSE_TRAINING_QUEUE_NAME,
    YOLO26_POSE_TRAINING_TASK_KIND,
    YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
    YOLOV8_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
    YOLOV8_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND,
    YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
    YOLOV8_OBB_TRAINING_QUEUE_NAME,
    YOLOV8_OBB_TRAINING_TASK_KIND,
    YOLOV8_POSE_TRAINING_CONTROL_METADATA_KEY,
    YOLOV8_POSE_TRAINING_QUEUE_NAME,
    YOLOV8_POSE_TRAINING_TASK_KIND,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


class TrainingServiceWithControl(Protocol):
    """描述支持控制操作的训练服务最小接口。"""

    def request_training_save(self, task_record: TaskRecord) -> None: ...
    def request_training_pause(self, task_record: TaskRecord) -> None: ...
    def request_training_terminate(self, task_record: TaskRecord) -> None: ...


TASK_KIND_TO_TASK_TYPE: dict[str, str] = {
    task_kind: entry.task_type
    for task_kind, entry in NON_DETECTION_TRAINING_TASK_CATALOG.items()
}

TASK_TYPE_TO_TASK_KINDS: dict[str, tuple[str, ...]] = {
    task_type: tuple(
        kind
        for kind, value in TASK_KIND_TO_TASK_TYPE.items()
        if value == task_type
    )
    for task_type in ("classification", "segmentation", "pose", "obb")
}
TASK_TYPE_TO_TASK_KIND: dict[str, str] = {
    task_type: task_kinds[0]
    for task_type, task_kinds in TASK_TYPE_TO_TASK_KINDS.items()
}

ALL_NON_DETECTION_TRAINING_TASK_KINDS: tuple[str, ...] = tuple(
    TASK_KIND_TO_TASK_TYPE.keys()
)

TASK_KIND_TO_QUEUE_NAME: dict[str, str] = {
    task_kind: entry.queue_name
    for task_kind, entry in NON_DETECTION_TRAINING_TASK_CATALOG.items()
}

TASK_KIND_TO_CONTROL_METADATA_KEY: dict[str, str] = {
    task_kind: entry.control_metadata_key
    for task_kind, entry in NON_DETECTION_TRAINING_TASK_CATALOG.items()
}


def build_service_for_task(
    task: TaskRecord,
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> TrainingServiceWithControl:
    """按 task_kind 构造对应的训练服务实例。"""

    kind = task.task_kind
    entry = NON_DETECTION_TRAINING_TASK_CATALOG.get(kind)
    if entry is None:
        raise InvalidRequestError("不支持的训练任务类型", details={"task_kind": kind})
    module = import_module(entry.service_module)
    service_class = getattr(module, entry.service_class, None)
    if not isinstance(service_class, type):
        raise InvalidRequestError(
            "训练任务服务入口无效",
            details={"task_kind": kind, "service_class": entry.service_class},
        )
    return service_class(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


def resolve_model_type_from_metadata(task: TaskRecord) -> str:
    """从任务元数据中解析 model_type。"""

    resolved_model_type = resolve_model_type(task)
    if resolved_model_type is not None:
        return resolved_model_type
    return "yolov8"


def resolve_task_type(task: TaskRecord) -> str:
    """从任务记录中解析公开 task_type。"""

    metadata = dict(task.metadata) if task.metadata else {}
    explicit_task_type = read_optional_str(metadata.get("task_type"))
    if explicit_task_type is not None:
        return explicit_task_type
    return TASK_KIND_TO_TASK_TYPE.get(task.task_kind, task.task_kind)


def resolve_model_type(
    task: TaskRecord,
    *,
    metadata: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
    task_spec: dict[str, object] | None = None,
) -> str | None:
    """从任务记录中解析公开 model_type。"""

    normalized_result = (
        result if result is not None else (dict(task.result) if task.result else {})
    )
    normalized_metadata = (
        metadata
        if metadata is not None
        else (dict(task.metadata) if task.metadata else {})
    )
    normalized_task_spec = (
        task_spec
        if task_spec is not None
        else (dict(task.task_spec) if task.task_spec else {})
    )
    payload = normalized_metadata.get("queue_payload", {})
    if isinstance(payload, dict):
        normalized_payload_model_type = normalize_optional_platform_model_type(
            payload.get("model_type")
        )
        if normalized_payload_model_type is not None:
            return normalized_payload_model_type
    normalized_task_spec_model_type = normalize_optional_platform_model_type(
        normalized_task_spec.get("model_type")
    )
    if normalized_task_spec_model_type is not None:
        return normalized_task_spec_model_type
    normalized_result_model_type = normalize_optional_platform_model_type(
        normalized_result.get("model_type")
    )
    if normalized_result_model_type is not None:
        return normalized_result_model_type
    normalized_metadata_model_type = normalize_optional_platform_model_type(
        normalized_metadata.get("model_type")
    )
    if normalized_metadata_model_type is not None:
        return normalized_metadata_model_type
    return None


def resolve_resume_checkpoint_object_key(task: TaskRecord) -> str | None:
    """读取 paused 训练任务可用于 resume 的 checkpoint object key。"""

    result = dict(task.result) if task.result else {}
    return read_optional_str(result.get("latest_checkpoint_object_key"))


def read_training_control_payload(task: TaskRecord) -> dict[str, object]:
    """从任务 metadata 中读取统一控制负载。"""

    metadata = dict(task.metadata) if task.metadata else {}
    control_metadata_key = TASK_KIND_TO_CONTROL_METADATA_KEY.get(task.task_kind)
    if control_metadata_key is None:
        return {}
    raw_control = metadata.get(control_metadata_key)
    if not isinstance(raw_control, dict):
        return {}
    return {str(key): value for key, value in raw_control.items()}


def read_optional_str(value: object) -> str | None:
    """读取可选字符串字段。"""

    if isinstance(value, str) and value.strip():
        return value
    return None

