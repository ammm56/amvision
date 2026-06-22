"""detection 训练任务 API 服务选择与权限辅助。"""

from __future__ import annotations

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
    require_supported_platform_model_type,
)
from backend.service.application.models.training.rfdetr_detection_task_service import (
    RFDETR_TRAINING_TASK_KIND,
    RfdetrTrainingTaskRequest,
    SqlAlchemyRfdetrTrainingTaskService,
)
from backend.service.application.models.training.yolo11_training_service import (
    YOLO11_TRAINING_TASK_KIND,
    SqlAlchemyYolo11TrainingTaskService,
    Yolo11TrainingTaskRequest,
)
from backend.service.application.models.training.yolo26_training_service import (
    YOLO26_TRAINING_TASK_KIND,
    SqlAlchemyYolo26TrainingTaskService,
    Yolo26TrainingTaskRequest,
)
from backend.service.application.models.training.yolov8_training_service import (
    YOLOV8_TRAINING_TASK_KIND,
    SqlAlchemyYoloV8TrainingTaskService,
    YoloV8TrainingTaskRequest,
)
from backend.service.application.models.training.yolox_detection_task_service import (
    YOLOX_TRAINING_TASK_KIND,
    SqlAlchemyYoloXTrainingTaskService,
    YoloXTrainingTaskRequest,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE = {
    "yolox": (SqlAlchemyYoloXTrainingTaskService, YoloXTrainingTaskRequest),
    "yolov8": (SqlAlchemyYoloV8TrainingTaskService, YoloV8TrainingTaskRequest),
    "yolo11": (SqlAlchemyYolo11TrainingTaskService, Yolo11TrainingTaskRequest),
    "yolo26": (SqlAlchemyYolo26TrainingTaskService, Yolo26TrainingTaskRequest),
    "rfdetr": (SqlAlchemyRfdetrTrainingTaskService, RfdetrTrainingTaskRequest),
}
_DETECTION_TRAINING_TASK_KIND_BY_MODEL_TYPE = {
    "yolox": YOLOX_TRAINING_TASK_KIND,
    "yolov8": YOLOV8_TRAINING_TASK_KIND,
    "yolo11": YOLO11_TRAINING_TASK_KIND,
    "yolo26": YOLO26_TRAINING_TASK_KIND,
    "rfdetr": RFDETR_TRAINING_TASK_KIND,
}
_DETECTION_TRAINING_MODEL_TYPE_BY_TASK_KIND = {
    task_kind: model_type
    for model_type, task_kind in _DETECTION_TRAINING_TASK_KIND_BY_MODEL_TYPE.items()
}


def _normalize_detection_training_model_type(value: str) -> str:
    """把 detection 训练模型分类归一化为正式值。"""

    return require_supported_platform_model_type(
        task_type=DETECTION_TASK_TYPE,
        model_type=value,
        unsupported_message="当前 detection training 不支持指定模型分类",
    )


def _resolve_detection_training_task_kinds(model_type: str | None) -> tuple[str, ...]:
    """根据查询条件返回需要覆盖的 detection 训练任务种类。"""

    if model_type is None:
        return tuple(_DETECTION_TRAINING_TASK_KIND_BY_MODEL_TYPE.values())
    normalized_model_type = _normalize_detection_training_model_type(model_type)
    return (_DETECTION_TRAINING_TASK_KIND_BY_MODEL_TYPE[normalized_model_type],)


def _resolve_detection_training_model_type_from_task(task: object) -> str:
    """从任务记录中解析 detection 训练模型分类。"""

    metadata = dict(getattr(task, "metadata", {}))
    normalized_model_type = normalize_optional_platform_model_type(metadata.get("model_type"))
    if normalized_model_type is not None:
        return normalized_model_type
    task_kind = getattr(task, "task_kind", "")
    resolved_model_type = _DETECTION_TRAINING_MODEL_TYPE_BY_TASK_KIND.get(str(task_kind))
    if resolved_model_type is None:
        raise ResourceNotFoundError(
            "找不到指定的 detection 训练任务",
            details={"task_id": getattr(task, "task_id", None)},
        )
    return resolved_model_type



def _resolve_visible_project_ids(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str | None,
) -> tuple[str, ...]:
    """根据主体权限和查询条件解析可查询的 Project 范围。"""

    if project_id is not None:
        if principal.project_ids and project_id not in principal.project_ids:
            raise ResourceNotFoundError(
                "找不到指定的任务范围",
                details={"project_id": project_id},
            )
        return (project_id,)
    if principal.project_ids:
        return principal.project_ids
    raise InvalidRequestError("查询训练任务列表时必须提供 project_id")


def _ensure_detection_training_task_visible(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    task_project_id: str,
) -> None:
    """校验当前主体是否可以访问指定 detection 训练任务。"""

    if principal.project_ids and task_project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的训练任务",
            details={"task_id": task_id},
        )


def _require_visible_detection_training_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    include_events: bool,
):
    """读取并校验当前主体可见的 detection 训练任务。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    _ensure_detection_training_task_visible(
        principal=principal,
        task_id=task_id,
        task_project_id=task_detail.task.project_id,
    )
    if task_detail.task.task_kind not in _DETECTION_TRAINING_MODEL_TYPE_BY_TASK_KIND:
        raise ResourceNotFoundError(
            "找不到指定的 detection 训练任务",
            details={"task_id": task_id},
        )
    return task_detail


def _matches_detection_training_filters(
    *,
    task: object,
    dataset_export_id: str | None,
    dataset_export_manifest_key: str | None,
) -> bool:
    """判断 detection 训练任务是否满足额外筛选条件。"""

    task_spec = dict(getattr(task, "task_spec", {}))
    manifest_object_key = task_spec.get("manifest_object_key")
    if dataset_export_id is not None and task_spec.get("dataset_export_id") != dataset_export_id:
        return False
    if (
        dataset_export_manifest_key is not None
        and task_spec.get("dataset_export_manifest_key") != dataset_export_manifest_key
        and manifest_object_key != dataset_export_manifest_key
    ):
        return False
    return True


def _build_detection_training_service_for_task(
    *,
    task: object,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage | None = None,
    queue_backend: LocalFileQueueBackend | None = None,
):
    """按训练任务模型分类构造对应的 detection 训练服务。"""

    model_type = _resolve_detection_training_model_type_from_task(task)
    service_cls, _request_cls = _DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE[model_type]
    return service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
