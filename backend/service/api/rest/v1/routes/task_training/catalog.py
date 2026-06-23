"""非 detection 训练任务类型、队列和服务选择。"""

from __future__ import annotations

from typing import Protocol

from backend.queue import LocalFileQueueBackend
from backend.service.application.errors import InvalidRequestError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
)
from backend.service.application.models.training.yolov8_classification_training_service import (
    YOLOV8_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
    YOLOV8_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND,
    SqlAlchemyYoloV8ClassificationTrainingService,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    YOLO11_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO11_CLASSIFICATION_TRAINING_TASK_KIND,
    SqlAlchemyYolo11ClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolo11_classification_task_control import (
    YOLO11_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.training.yolo26_classification_training_service import (
    YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO26_CLASSIFICATION_TRAINING_TASK_KIND,
    SqlAlchemyYolo26ClassificationTrainingTaskService,
)
from backend.service.application.models.training.yolo26_classification_task_control import (
    YOLO26_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.training.yolov8_obb_training_service import (
    YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
    YOLOV8_OBB_TRAINING_QUEUE_NAME,
    YOLOV8_OBB_TRAINING_TASK_KIND,
    SqlAlchemyYoloV8ObbTrainingService,
)
from backend.service.application.models.training.yolo11_obb_training_service import (
    YOLO11_OBB_TRAINING_QUEUE_NAME,
    YOLO11_OBB_TRAINING_TASK_KIND,
    SqlAlchemyYolo11ObbTrainingTaskService,
)
from backend.service.application.models.training.yolo11_obb_task_control import (
    YOLO11_OBB_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.training.yolo26_obb_task_control import (
    YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.training.yolo26_obb_training_service import (
    YOLO26_OBB_TRAINING_QUEUE_NAME,
    YOLO26_OBB_TRAINING_TASK_KIND,
    SqlAlchemyYolo26ObbTrainingTaskService,
)
from backend.service.application.models.training.yolov8_pose_training_service import (
    YOLOV8_POSE_TRAINING_CONTROL_METADATA_KEY,
    YOLOV8_POSE_TRAINING_QUEUE_NAME,
    YOLOV8_POSE_TRAINING_TASK_KIND,
    SqlAlchemyYoloV8PoseTrainingService,
)
from backend.service.application.models.training.yolo11_pose_training_service import (
    YOLO11_POSE_TRAINING_QUEUE_NAME,
    YOLO11_POSE_TRAINING_TASK_KIND,
    SqlAlchemyYolo11PoseTrainingTaskService,
)
from backend.service.application.models.training.yolo11_pose_task_control import (
    YOLO11_POSE_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.training.yolo26_pose_task_control import (
    YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.training.yolo26_pose_training_service import (
    YOLO26_POSE_TRAINING_QUEUE_NAME,
    YOLO26_POSE_TRAINING_TASK_KIND,
    SqlAlchemyYolo26PoseTrainingTaskService,
)
from backend.service.application.models.training.segmentation_training_service import (
    SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    SEGMENTATION_TRAINING_QUEUE_NAME,
    SEGMENTATION_TRAINING_TASK_KIND,
    SqlAlchemySegmentationTrainingService,
)
from backend.service.application.models.training.yolo11_segmentation_training_service import (
    YOLO11_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO11_SEGMENTATION_TRAINING_TASK_KIND,
    SqlAlchemyYolo11SegmentationTrainingTaskService,
)
from backend.service.application.models.training.yolo11_segmentation_task_control import (
    YOLO11_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.training.yolo26_segmentation_task_control import (
    YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.models.training.yolo26_segmentation_training_service import (
    YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
    SqlAlchemyYolo26SegmentationTrainingTaskService,
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
    YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND: "classification",
    YOLO11_CLASSIFICATION_TRAINING_TASK_KIND: "classification",
    YOLO26_CLASSIFICATION_TRAINING_TASK_KIND: "classification",
    SEGMENTATION_TRAINING_TASK_KIND: "segmentation",
    YOLO11_SEGMENTATION_TRAINING_TASK_KIND: "segmentation",
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND: "segmentation",
    YOLOV8_POSE_TRAINING_TASK_KIND: "pose",
    YOLO11_POSE_TRAINING_TASK_KIND: "pose",
    YOLO26_POSE_TRAINING_TASK_KIND: "pose",
    YOLOV8_OBB_TRAINING_TASK_KIND: "obb",
    YOLO11_OBB_TRAINING_TASK_KIND: "obb",
    YOLO26_OBB_TRAINING_TASK_KIND: "obb",
}

TASK_TYPE_TO_TASK_KINDS: dict[str, tuple[str, ...]] = {
    "classification": (
        YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND,
        YOLO11_CLASSIFICATION_TRAINING_TASK_KIND,
        YOLO26_CLASSIFICATION_TRAINING_TASK_KIND,
    ),
    "segmentation": (
        SEGMENTATION_TRAINING_TASK_KIND,
        YOLO11_SEGMENTATION_TRAINING_TASK_KIND,
        YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
    ),
    "pose": (
        YOLOV8_POSE_TRAINING_TASK_KIND,
        YOLO11_POSE_TRAINING_TASK_KIND,
        YOLO26_POSE_TRAINING_TASK_KIND,
    ),
    "obb": (
        YOLOV8_OBB_TRAINING_TASK_KIND,
        YOLO11_OBB_TRAINING_TASK_KIND,
        YOLO26_OBB_TRAINING_TASK_KIND,
    ),
}
TASK_TYPE_TO_TASK_KIND: dict[str, str] = {
    task_type: task_kinds[0]
    for task_type, task_kinds in TASK_TYPE_TO_TASK_KINDS.items()
}

ALL_NON_DETECTION_TRAINING_TASK_KINDS: tuple[str, ...] = tuple(
    TASK_KIND_TO_TASK_TYPE.keys()
)

TASK_KIND_TO_QUEUE_NAME: dict[str, str] = {
    YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND: YOLOV8_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO11_CLASSIFICATION_TRAINING_TASK_KIND: YOLO11_CLASSIFICATION_TRAINING_QUEUE_NAME,
    YOLO26_CLASSIFICATION_TRAINING_TASK_KIND: YOLO26_CLASSIFICATION_TRAINING_QUEUE_NAME,
    SEGMENTATION_TRAINING_TASK_KIND: SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO11_SEGMENTATION_TRAINING_TASK_KIND: YOLO11_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND: YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLOV8_POSE_TRAINING_TASK_KIND: YOLOV8_POSE_TRAINING_QUEUE_NAME,
    YOLO11_POSE_TRAINING_TASK_KIND: YOLO11_POSE_TRAINING_QUEUE_NAME,
    YOLO26_POSE_TRAINING_TASK_KIND: YOLO26_POSE_TRAINING_QUEUE_NAME,
    YOLOV8_OBB_TRAINING_TASK_KIND: YOLOV8_OBB_TRAINING_QUEUE_NAME,
    YOLO11_OBB_TRAINING_TASK_KIND: YOLO11_OBB_TRAINING_QUEUE_NAME,
    YOLO26_OBB_TRAINING_TASK_KIND: YOLO26_OBB_TRAINING_QUEUE_NAME,
}

TASK_KIND_TO_CONTROL_METADATA_KEY: dict[str, str] = {
    YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND: YOLOV8_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO11_CLASSIFICATION_TRAINING_TASK_KIND: YOLO11_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_CLASSIFICATION_TRAINING_TASK_KIND: YOLO26_CLASSIFICATION_TRAINING_CONTROL_METADATA_KEY,
    SEGMENTATION_TRAINING_TASK_KIND: SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO11_SEGMENTATION_TRAINING_TASK_KIND: YOLO11_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_SEGMENTATION_TRAINING_TASK_KIND: YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
    YOLOV8_POSE_TRAINING_TASK_KIND: YOLOV8_POSE_TRAINING_CONTROL_METADATA_KEY,
    YOLO11_POSE_TRAINING_TASK_KIND: YOLO11_POSE_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_POSE_TRAINING_TASK_KIND: YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY,
    YOLOV8_OBB_TRAINING_TASK_KIND: YOLOV8_OBB_TRAINING_CONTROL_METADATA_KEY,
    YOLO11_OBB_TRAINING_TASK_KIND: YOLO11_OBB_TRAINING_CONTROL_METADATA_KEY,
    YOLO26_OBB_TRAINING_TASK_KIND: YOLO26_OBB_TRAINING_CONTROL_METADATA_KEY,
}


def build_service_for_task(
    task: TaskRecord,
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
) -> TrainingServiceWithControl:
    """按 task_kind 构造对应的训练服务实例。"""

    kind = task.task_kind
    if kind == YOLOV8_CLASSIFICATION_TRAINING_TASK_KIND:
        return SqlAlchemyYoloV8ClassificationTrainingService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO11_CLASSIFICATION_TRAINING_TASK_KIND:
        return SqlAlchemyYolo11ClassificationTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO26_CLASSIFICATION_TRAINING_TASK_KIND:
        return SqlAlchemyYolo26ClassificationTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == SEGMENTATION_TRAINING_TASK_KIND:
        return SqlAlchemySegmentationTrainingService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO11_SEGMENTATION_TRAINING_TASK_KIND:
        return SqlAlchemyYolo11SegmentationTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO26_SEGMENTATION_TRAINING_TASK_KIND:
        return SqlAlchemyYolo26SegmentationTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLOV8_POSE_TRAINING_TASK_KIND:
        return SqlAlchemyYoloV8PoseTrainingService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO11_POSE_TRAINING_TASK_KIND:
        return SqlAlchemyYolo11PoseTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO26_POSE_TRAINING_TASK_KIND:
        return SqlAlchemyYolo26PoseTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLOV8_OBB_TRAINING_TASK_KIND:
        return SqlAlchemyYoloV8ObbTrainingService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO11_OBB_TRAINING_TASK_KIND:
        return SqlAlchemyYolo11ObbTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    if kind == YOLO26_OBB_TRAINING_TASK_KIND:
        return SqlAlchemyYolo26ObbTrainingTaskService(
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )
    raise InvalidRequestError("不支持的训练任务类型", details={"task_kind": kind})


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

