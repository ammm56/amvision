"""detection training task REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_output_files import (
    DetectionTrainingMetricsFileResponse,
    DetectionTrainingOutputFileDetailResponse,
    DetectionTrainingOutputFileSummaryResponse,
    _DETECTION_TRAINING_OUTPUT_FILE_ORDER,
    _build_detection_training_metrics_file_response,
    _build_detection_training_output_file_summary_response,
    _parse_detection_training_output_file_name,
    _read_detection_training_output_file,
)
from backend.service.api.rest.v1.routes.yolox_training_tasks import (
    YoloXTrainingTaskActionName,
    YoloXTrainingTaskControlStatusResponse,
    YoloXTrainingTaskEventResponse,
    YoloXTrainingTaskSubmissionResponse,
    YoloXTrainingTaskSummaryResponse,
    _build_yolox_training_task_available_actions,
    _build_yolox_training_task_control_status,
    _build_yolox_training_task_event_response,
    _build_yolox_training_task_summary_response,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.models.yolo11_training_service import (
    YOLO11_TRAINING_TASK_KIND,
    SqlAlchemyYolo11TrainingTaskService,
    Yolo11TrainingTaskRequest,
)
from backend.service.application.models.yolo26_training_service import (
    YOLO26_TRAINING_TASK_KIND,
    SqlAlchemyYolo26TrainingTaskService,
    Yolo26TrainingTaskRequest,
)
from backend.service.application.models.yolov8_training_service import (
    YOLOV8_TRAINING_TASK_KIND,
    SqlAlchemyYoloV8TrainingTaskService,
    YoloV8TrainingTaskRequest,
)
from backend.service.application.models.yolox_training_service import (
    YOLOX_TRAINING_TASK_KIND,
    SqlAlchemyYoloXTrainingTaskService,
    YoloXTrainingTaskRequest,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_training_tasks_router = APIRouter(prefix="/models", tags=["models"])

_SUPPORTED_DETECTION_TRAINING_MODEL_TYPES = ("yolox", "yolov8", "yolo11", "yolo26")
_DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE = {
    "yolox": (SqlAlchemyYoloXTrainingTaskService, YoloXTrainingTaskRequest),
    "yolov8": (SqlAlchemyYoloV8TrainingTaskService, YoloV8TrainingTaskRequest),
    "yolo11": (SqlAlchemyYolo11TrainingTaskService, Yolo11TrainingTaskRequest),
    "yolo26": (SqlAlchemyYolo26TrainingTaskService, Yolo26TrainingTaskRequest),
}
_DETECTION_TRAINING_TASK_KIND_BY_MODEL_TYPE = {
    "yolox": YOLOX_TRAINING_TASK_KIND,
    "yolov8": YOLOV8_TRAINING_TASK_KIND,
    "yolo11": YOLO11_TRAINING_TASK_KIND,
    "yolo26": YOLO26_TRAINING_TASK_KIND,
}
_DETECTION_TRAINING_MODEL_TYPE_BY_TASK_KIND = {
    task_kind: model_type
    for model_type, task_kind in _DETECTION_TRAINING_TASK_KIND_BY_MODEL_TYPE.items()
}


class DetectionTrainingTaskCreateRequestBody(BaseModel):
    """描述 detection 训练任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类；当前支持 yolox、yolov8、yolo11、yolo26")
    dataset_export_id: str | None = Field(default=None, description="训练输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="训练输入使用的导出 manifest object key")
    recipe_id: str = Field(description="训练 recipe id")
    model_scale: str = Field(description="训练目标的模型 scale")
    output_model_name: str = Field(description="训练后登记的模型名")
    warm_start_model_version_id: str | None = Field(default=None, description="warm start 使用的 ModelVersion id")
    evaluation_interval: int | None = Field(default=None, ge=1, description="每隔多少轮执行一次真实验证评估")
    max_epochs: int | None = Field(default=None, description="最大训练轮数")
    batch_size: int | None = Field(default=None, description="batch size")
    gpu_count: int | None = Field(default=None, ge=1, description="请求参与训练的 GPU 数量")
    precision: str | None = Field(default=None, description="请求使用的训练 precision")
    input_size: tuple[int, int] | None = Field(default=None, description="训练输入尺寸")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加训练选项")
    display_name: str = Field(default="", description="可选任务展示名称")


class DetectionTrainingTaskSubmissionResponse(BaseModel):
    """描述 detection 训练任务创建响应。"""

    task_id: str = Field(description="训练任务 id")
    status: str = Field(description="训练任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    model_type: str = Field(description="模型分类")
    dataset_export_id: str = Field(description="解析后的 DatasetExport id")
    dataset_export_manifest_key: str = Field(description="解析后的导出 manifest object key")
    dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
    format_id: str = Field(description="训练使用的数据集导出格式 id")


class DetectionTrainingTaskControlStatusResponse(YoloXTrainingTaskControlStatusResponse):
    """描述 detection 训练任务正式控制状态。"""


class DetectionTrainingTaskEventResponse(YoloXTrainingTaskEventResponse):
    """描述 detection 训练任务事件响应。"""


class DetectionTrainingTaskSummaryResponse(YoloXTrainingTaskSummaryResponse):
    """描述 detection 训练任务摘要响应。"""

    model_type: str = Field(description="模型分类")


class DetectionTrainingTaskDetailResponse(DetectionTrainingTaskSummaryResponse):
    """描述 detection 训练任务详情响应。"""

    available_actions: list[YoloXTrainingTaskActionName] = Field(description="当前建议展示的训练控制动作列表")
    control_status: DetectionTrainingTaskControlStatusResponse = Field(description="正式训练控制状态")
    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[DetectionTrainingTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


@detection_training_tasks_router.post(
    "/detection/training-tasks",
    response_model=DetectionTrainingTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_training_task(
    body: DetectionTrainingTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> DetectionTrainingTaskSubmissionResponse:
    """创建一个 detection 训练任务。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的 Project",
            details={"project_id": body.project_id},
        )
    model_type = _normalize_detection_training_model_type(body.model_type)
    service_cls, request_cls = _DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE[model_type]
    service = service_cls(
        session_factory=session_factory,
        queue_backend=queue_backend,
    )
    submission = service.submit_training_task(
        request_cls(
            project_id=body.project_id,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            recipe_id=body.recipe_id,
            model_scale=body.model_scale,
            output_model_name=body.output_model_name,
            warm_start_model_version_id=body.warm_start_model_version_id,
            evaluation_interval=body.evaluation_interval,
            max_epochs=body.max_epochs,
            batch_size=body.batch_size,
            gpu_count=body.gpu_count,
            precision=body.precision,
            input_size=body.input_size,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return DetectionTrainingTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        model_type=model_type,
        dataset_export_id=submission.dataset_export_id,
        dataset_export_manifest_key=submission.dataset_export_manifest_key,
        dataset_version_id=submission.dataset_version_id,
        format_id=submission.format_id,
    )


@detection_training_tasks_router.get(
    "/detection/training-tasks",
    response_model=list[DetectionTrainingTaskSummaryResponse],
)
def list_detection_training_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    model_type: Annotated[str | None, Query(description="模型分类")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    dataset_export_id: Annotated[str | None, Query(description="训练输入使用的 DatasetExport id")] = None,
    dataset_export_manifest_key: Annotated[str | None, Query(description="训练输入使用的导出 manifest object key")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[DetectionTrainingTaskSummaryResponse]:
    """按公开筛选条件列出 detection 训练任务。"""

    visible_project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
    task_kinds = _resolve_detection_training_task_kinds(model_type)
    service = SqlAlchemyTaskService(session_factory)
    matched_tasks = []
    for current_project_id in visible_project_ids:
        for task_kind in task_kinds:
            matched_tasks.extend(
                service.list_tasks(
                    TaskQueryFilters(
                        project_id=current_project_id,
                        task_kind=task_kind,
                        state=state,
                        created_by=created_by,
                        limit=limit,
                    )
                )
            )
    visible_tasks = [
        task
        for task in matched_tasks
        if _matches_detection_training_filters(
            task=task,
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
        )
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [_build_detection_training_task_summary_response(task) for task in visible_tasks[:limit]]


@detection_training_tasks_router.get(
    "/detection/training-tasks/{task_id}",
    response_model=DetectionTrainingTaskDetailResponse,
)
def get_detection_training_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
) -> DetectionTrainingTaskDetailResponse:
    """按任务 id 返回 detection 训练任务详情。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=include_events,
    )
    return _build_detection_training_task_detail_response(task_detail.task, tuple(task_detail.events))


@detection_training_tasks_router.post(
    "/detection/training-tasks/{task_id}/save",
    response_model=DetectionTrainingTaskDetailResponse,
)
def request_detection_training_save(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> DetectionTrainingTaskDetailResponse:
    """为运行中的 detection 训练任务请求一次手动保存。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
    )
    updated_task_detail = service.request_training_save(task_id, requested_by=principal.principal_id)
    return _build_detection_training_task_detail_response(
        updated_task_detail.task,
        tuple(updated_task_detail.events),
    )


@detection_training_tasks_router.post(
    "/detection/training-tasks/{task_id}/pause",
    response_model=DetectionTrainingTaskDetailResponse,
)
def request_detection_training_pause(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> DetectionTrainingTaskDetailResponse:
    """为运行中的 detection 训练任务请求暂停。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
    )
    updated_task_detail = service.request_training_pause(task_id, requested_by=principal.principal_id)
    return _build_detection_training_task_detail_response(
        updated_task_detail.task,
        tuple(updated_task_detail.events),
    )


@detection_training_tasks_router.post(
    "/detection/training-tasks/{task_id}/resume",
    response_model=YoloXTrainingTaskSubmissionResponse,
)
def resume_detection_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> YoloXTrainingTaskSubmissionResponse:
    """把一个 paused 的 detection 训练任务重新入队执行。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.resume_training_task(task_id, resumed_by=principal.principal_id)
    return YoloXTrainingTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        dataset_export_id=submission.dataset_export_id,
        dataset_export_manifest_key=submission.dataset_export_manifest_key,
        dataset_version_id=submission.dataset_version_id,
        format_id=submission.format_id,
    )


@detection_training_tasks_router.post(
    "/detection/training-tasks/{task_id}/terminate",
    response_model=DetectionTrainingTaskDetailResponse,
)
def terminate_detection_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> DetectionTrainingTaskDetailResponse:
    """请求终止一个 queued、running 或 paused 的 detection 训练任务。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
    )
    updated_task_detail = service.request_training_terminate(task_id, requested_by=principal.principal_id)
    return _build_detection_training_task_detail_response(
        updated_task_detail.task,
        tuple(updated_task_detail.events),
    )


@detection_training_tasks_router.delete(
    "/detection/training-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_detection_training_task(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> Response:
    """删除一个已经停止且可安全删除的 detection 训练任务。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    service = _build_detection_training_service_for_task(
        task=task_detail.task,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    service.delete_training_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@detection_training_tasks_router.get(
    "/detection/training-tasks/{task_id}/validation-metrics",
    response_model=DetectionTrainingMetricsFileResponse,
)
def get_detection_training_validation_metrics(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionTrainingMetricsFileResponse:
    """按任务 id 返回当前 detection 训练的验证快照。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    output_file = _read_detection_training_output_file(
        task=task_detail.task,
        file_name="validation-metrics",
        dataset_storage=dataset_storage,
        strict_missing=True,
    )
    return _build_detection_training_metrics_file_response(output_file)


@detection_training_tasks_router.get(
    "/detection/training-tasks/{task_id}/train-metrics",
    response_model=DetectionTrainingMetricsFileResponse,
)
def get_detection_training_train_metrics(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionTrainingMetricsFileResponse:
    """按任务 id 返回当前 detection 训练的训练指标快照。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    output_file = _read_detection_training_output_file(
        task=task_detail.task,
        file_name="train-metrics",
        dataset_storage=dataset_storage,
        strict_missing=True,
    )
    return _build_detection_training_metrics_file_response(output_file)


@detection_training_tasks_router.get(
    "/detection/training-tasks/{task_id}/output-files",
    response_model=list[DetectionTrainingOutputFileSummaryResponse],
)
def list_detection_training_output_files(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> list[DetectionTrainingOutputFileSummaryResponse]:
    """按任务 id 列出当前 detection 训练输出文件状态。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return [
        _build_detection_training_output_file_summary_response(
            _read_detection_training_output_file(
                task=task_detail.task,
                file_name=file_name,
                dataset_storage=dataset_storage,
                strict_missing=False,
            )
        )
        for file_name in _DETECTION_TRAINING_OUTPUT_FILE_ORDER
    ]


@detection_training_tasks_router.get(
    "/detection/training-tasks/{task_id}/output-files/{file_name}",
    response_model=DetectionTrainingOutputFileDetailResponse,
)
def get_detection_training_output_file_detail(
    task_id: str,
    file_name: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionTrainingOutputFileDetailResponse:
    """按任务 id 和文件名返回单个 detection 训练输出文件的状态与内容。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return DetectionTrainingOutputFileDetailResponse.model_validate(
        _read_detection_training_output_file(
            task=task_detail.task,
            file_name=_parse_detection_training_output_file_name(file_name),
            dataset_storage=dataset_storage,
            strict_missing=False,
        ).model_dump()
    )


def _normalize_detection_training_model_type(value: str) -> str:
    """把 detection 训练模型分类归一化为正式值。"""

    normalized_value = value.strip().lower()
    if normalized_value not in _DETECTION_TRAINING_SERVICE_BY_MODEL_TYPE:
        raise InvalidRequestError(
            "当前 detection training 仅支持 yolox、yolov8、yolo11、yolo26",
            details={"model_type": value},
        )
    return normalized_value


def _resolve_detection_training_task_kinds(model_type: str | None) -> tuple[str, ...]:
    """根据查询条件返回需要覆盖的 detection 训练任务种类。"""

    if model_type is None:
        return tuple(_DETECTION_TRAINING_TASK_KIND_BY_MODEL_TYPE.values())
    normalized_model_type = _normalize_detection_training_model_type(model_type)
    return (_DETECTION_TRAINING_TASK_KIND_BY_MODEL_TYPE[normalized_model_type],)


def _resolve_detection_training_model_type_from_task(task: object) -> str:
    """从任务记录中解析 detection 训练模型分类。"""

    metadata = dict(getattr(task, "metadata", {}))
    model_type = metadata.get("model_type")
    if isinstance(model_type, str) and model_type.strip():
        return model_type.strip().lower()
    task_kind = getattr(task, "task_kind", "")
    resolved_model_type = _DETECTION_TRAINING_MODEL_TYPE_BY_TASK_KIND.get(str(task_kind))
    if resolved_model_type is None:
        raise ResourceNotFoundError(
            "找不到指定的 detection 训练任务",
            details={"task_id": getattr(task, "task_id", None)},
        )
    return resolved_model_type


def _build_detection_training_task_summary_response(
    task: object,
) -> DetectionTrainingTaskSummaryResponse:
    """把 detection 训练 TaskRecord 转成摘要响应。"""

    summary = _build_yolox_training_task_summary_response(task)
    return DetectionTrainingTaskSummaryResponse.model_validate(
        {
            **summary.model_dump(),
            "model_type": _resolve_detection_training_model_type_from_task(task),
        }
    )


def _build_detection_training_task_control_status(
    task: object,
) -> DetectionTrainingTaskControlStatusResponse:
    """把训练控制元数据归一成 detection 正式控制状态响应。"""

    return DetectionTrainingTaskControlStatusResponse.model_validate(
        _build_yolox_training_task_control_status(task).model_dump()
    )


def _build_detection_training_task_available_actions(
    task: object,
) -> list[YoloXTrainingTaskActionName]:
    """根据当前任务状态构建 detection 建议展示的控制动作列表。"""

    return _build_yolox_training_task_available_actions(task)


def _build_detection_training_task_event_response(
    event: object,
) -> DetectionTrainingTaskEventResponse:
    """把训练任务事件转换为 detection 事件响应。"""

    response = _build_yolox_training_task_event_response(event)
    return DetectionTrainingTaskEventResponse.model_validate(response.model_dump())


def _build_detection_training_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> DetectionTrainingTaskDetailResponse:
    """把 detection 训练任务和事件转换为详情响应。"""

    summary = _build_detection_training_task_summary_response(task)
    return DetectionTrainingTaskDetailResponse(
        **summary.model_dump(),
        available_actions=_build_detection_training_task_available_actions(task),
        control_status=_build_detection_training_task_control_status(task),
        task_spec=dict(task.task_spec),
        events=[_build_detection_training_task_event_response(event) for event in events],
    )


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
