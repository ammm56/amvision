"""detection conversion task REST 路由。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.yolox_conversion_tasks import (
    OPENVINO_IR_PRECISION_OPTION_KEY,
    TENSORRT_ENGINE_PRECISION_OPTION_KEY,
    YoloXConversionResultResponse,
    YoloXConversionTaskDetailResponse,
    YoloXConversionTaskSummaryResponse,
    _build_yolox_conversion_result_response,
    _build_yolox_conversion_task_detail_response,
    _build_yolox_conversion_task_summary_response,
)
from backend.service.application.conversions.yolo11_conversion_task_service import (
    YOLO11_CONVERSION_TASK_KIND,
    SqlAlchemyYolo11ConversionTaskService,
    Yolo11ConversionTaskRequest,
)
from backend.service.application.conversions.yolo26_conversion_task_service import (
    YOLO26_CONVERSION_TASK_KIND,
    SqlAlchemyYolo26ConversionTaskService,
    Yolo26ConversionTaskRequest,
)
from backend.service.application.conversions.yolov8_conversion_task_service import (
    YOLOV8_CONVERSION_TASK_KIND,
    SqlAlchemyYoloV8ConversionTaskService,
    YoloV8ConversionTaskRequest,
)
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    RFDETR_CONVERSION_TASK_KIND,
    RfdetrConversionTaskRequest,
    SqlAlchemyRfdetrConversionTaskService,
)
from backend.service.application.conversions.yolox_conversion_task_service import (
    YOLOX_CONVERSION_TASK_KIND,
    SqlAlchemyYoloXConversionTaskService,
    YoloXConversionTaskRequest,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_conversion_tasks_router = APIRouter(prefix="/models", tags=["models"])

DetectionConversionTargetLiteral = Literal[
    "onnx",
    "onnx-optimized",
    "openvino-ir",
    "tensorrt-engine",
    "rknn",
]

_DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE = {
    "yolox": (SqlAlchemyYoloXConversionTaskService, YoloXConversionTaskRequest),
    "yolov8": (SqlAlchemyYoloV8ConversionTaskService, YoloV8ConversionTaskRequest),
    "yolo11": (SqlAlchemyYolo11ConversionTaskService, Yolo11ConversionTaskRequest),
    "yolo26": (SqlAlchemyYolo26ConversionTaskService, Yolo26ConversionTaskRequest),
    "rfdetr": (SqlAlchemyRfdetrConversionTaskService, RfdetrConversionTaskRequest),
}
_DETECTION_CONVERSION_TASK_KIND_BY_MODEL_TYPE = {
    "yolox": YOLOX_CONVERSION_TASK_KIND,
    "yolov8": YOLOV8_CONVERSION_TASK_KIND,
    "yolo11": YOLO11_CONVERSION_TASK_KIND,
    "yolo26": YOLO26_CONVERSION_TASK_KIND,
    "rfdetr": RFDETR_CONVERSION_TASK_KIND,
}
_DETECTION_CONVERSION_MODEL_TYPE_BY_TASK_KIND = {
    task_kind: model_type
    for model_type, task_kind in _DETECTION_CONVERSION_TASK_KIND_BY_MODEL_TYPE.items()
}


class DetectionConversionTaskCreateRequestBody(BaseModel):
    """描述 detection conversion 任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类；当前支持 yolox、yolov8、yolo11、yolo26、rfdetr")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    runtime_profile_id: str | None = Field(default=None, description="可选 RuntimeProfile id")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加转换选项")
    display_name: str = Field(default="", description="可选任务展示名称")


class DetectionConversionTaskSubmissionResponse(BaseModel):
    """描述 detection conversion 任务创建响应。"""

    task_id: str = Field(description="转换任务 id")
    status: str = Field(description="转换任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    model_type: str = Field(description="模型分类")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[DetectionConversionTargetLiteral] = Field(description="固化后的目标格式列表")


class DetectionConversionTaskSummaryResponse(YoloXConversionTaskSummaryResponse):
    """描述 detection conversion 任务摘要响应。"""

    model_type: str = Field(description="模型分类")


class DetectionConversionTaskDetailResponse(DetectionConversionTaskSummaryResponse):
    """描述 detection conversion 任务详情响应。"""

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[dict[str, object]] = Field(default_factory=list, description="任务事件列表")


class DetectionConversionResultResponse(YoloXConversionResultResponse):
    """描述 detection conversion 结果读取响应。"""


@detection_conversion_tasks_router.post(
    "/detection/conversion-tasks/onnx",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_onnx_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个只输出 ONNX 的 detection conversion task。"""

    return _submit_detection_conversion_task(
        body=body,
        target_format="onnx",
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_tasks_router.post(
    "/detection/conversion-tasks/onnx-optimized",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_optimized_onnx_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 optimized ONNX 的 detection conversion task。"""

    return _submit_detection_conversion_task(
        body=body,
        target_format="onnx-optimized",
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_tasks_router.post(
    "/detection/conversion-tasks/openvino-ir-fp32",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_openvino_ir_fp32_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 FP32 OpenVINO IR 的 detection conversion task。"""

    return _submit_detection_conversion_task(
        body=body,
        target_format="openvino-ir",
        extra_options_override=_merge_fixed_detection_conversion_extra_options(
            body_extra_options=body.extra_options,
            fixed_extra_options={OPENVINO_IR_PRECISION_OPTION_KEY: "fp32"},
        ),
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_tasks_router.post(
    "/detection/conversion-tasks/openvino-ir-fp16",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_openvino_ir_fp16_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 FP16 OpenVINO IR 的 detection conversion task。"""

    return _submit_detection_conversion_task(
        body=body,
        target_format="openvino-ir",
        extra_options_override=_merge_fixed_detection_conversion_extra_options(
            body_extra_options=body.extra_options,
            fixed_extra_options={OPENVINO_IR_PRECISION_OPTION_KEY: "fp16"},
        ),
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_tasks_router.post(
    "/detection/conversion-tasks/tensorrt-engine-fp32",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_tensorrt_engine_fp32_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 FP32 TensorRT engine 的 detection conversion task。"""

    return _submit_detection_conversion_task(
        body=body,
        target_format="tensorrt-engine",
        extra_options_override=_merge_fixed_detection_conversion_extra_options(
            body_extra_options=body.extra_options,
            fixed_extra_options={TENSORRT_ENGINE_PRECISION_OPTION_KEY: "fp32"},
        ),
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_tasks_router.post(
    "/detection/conversion-tasks/tensorrt-engine-fp16",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_tensorrt_engine_fp16_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 FP16 TensorRT engine 的 detection conversion task。"""

    return _submit_detection_conversion_task(
        body=body,
        target_format="tensorrt-engine",
        extra_options_override=_merge_fixed_detection_conversion_extra_options(
            body_extra_options=body.extra_options,
            fixed_extra_options={TENSORRT_ENGINE_PRECISION_OPTION_KEY: "fp16"},
        ),
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_tasks_router.get(
    "/detection/conversion-tasks",
    response_model=list[DetectionConversionTaskSummaryResponse],
)
def list_detection_conversion_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    model_type: Annotated[str | None, Query(description="模型分类")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    source_model_version_id: Annotated[str | None, Query(description="来源 ModelVersion id")] = None,
    target_format: Annotated[str | None, Query(description="目标 build 格式")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[DetectionConversionTaskSummaryResponse]:
    """按公开筛选条件列出 detection conversion 任务。"""

    visible_project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
    task_kinds = _resolve_detection_conversion_task_kinds(model_type)
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
        if _matches_detection_conversion_filters(
            task=task,
            source_model_version_id=source_model_version_id,
            target_format=target_format,
        )
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [_build_detection_conversion_task_summary_response(task) for task in visible_tasks[:limit]]


@detection_conversion_tasks_router.get(
    "/detection/conversion-tasks/{task_id}",
    response_model=DetectionConversionTaskDetailResponse,
)
def get_detection_conversion_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
) -> DetectionConversionTaskDetailResponse:
    """按任务 id 返回 detection conversion 任务详情。"""

    task_detail = _require_visible_detection_conversion_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=include_events,
    )
    return _build_detection_conversion_task_detail_response(task_detail.task, tuple(task_detail.events))


@detection_conversion_tasks_router.get(
    "/detection/conversion-tasks/{task_id}/result",
    response_model=DetectionConversionResultResponse,
)
def get_detection_conversion_task_result(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionResultResponse:
    """按任务 id 返回当前 detection conversion 结果。"""

    task_detail = _require_visible_detection_conversion_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    model_type = _resolve_detection_conversion_model_type_from_task(task_detail.task)
    service_cls, _ = _DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE[model_type]
    result_snapshot = service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).read_conversion_result(task_id)
    response = _build_yolox_conversion_result_response(task_id, result_snapshot)
    return DetectionConversionResultResponse.model_validate(response.model_dump())


def _submit_detection_conversion_task(
    *,
    body: DetectionConversionTaskCreateRequestBody,
    target_format: DetectionConversionTargetLiteral,
    extra_options_override: dict[str, object] | None = None,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    queue_backend: LocalFileQueueBackend,
    dataset_storage: LocalDatasetStorage,
) -> DetectionConversionTaskSubmissionResponse:
    """按固定 target_format 提交一条 detection conversion task。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的 Project",
            details={"project_id": body.project_id},
        )
    model_type = _normalize_detection_conversion_model_type(body.model_type)
    service_cls, request_cls = _DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE[model_type]
    service = service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.submit_conversion_task(
        request_cls(
            project_id=body.project_id,
            source_model_version_id=body.source_model_version_id,
            target_formats=(target_format,),
            runtime_profile_id=body.runtime_profile_id,
            extra_options=dict(extra_options_override or body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return DetectionConversionTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        model_type=model_type,
        source_model_version_id=submission.source_model_version_id,
        target_formats=list(submission.target_formats),
    )


def _merge_fixed_detection_conversion_extra_options(
    *,
    body_extra_options: dict[str, object],
    fixed_extra_options: dict[str, object],
) -> dict[str, object]:
    """把固定策略接口要求的 extra_options 合并到 detection 请求体中。"""

    merged_extra_options = dict(body_extra_options)
    for option_key, option_value in fixed_extra_options.items():
        existing_value = merged_extra_options.get(option_key)
        if existing_value is not None and existing_value != option_value:
            raise InvalidRequestError(
                "固定策略转换接口不允许覆盖内建 extra_options",
                details={
                    "option_key": option_key,
                    "existing_value": existing_value,
                    "required_value": option_value,
                },
            )
        merged_extra_options[option_key] = option_value
    return merged_extra_options


def _normalize_detection_conversion_model_type(value: str) -> str:
    """把 detection conversion 模型分类归一化为正式值。"""

    normalized_value = value.strip().lower()
    if normalized_value not in _DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE:
        raise InvalidRequestError(
            "当前 detection conversion 仅支持 yolox、yolov8、yolo11、yolo26、rfdetr",
            details={"model_type": value},
        )
    return normalized_value


def _resolve_detection_conversion_task_kinds(model_type: str | None) -> tuple[str, ...]:
    """根据查询条件返回需要覆盖的 detection conversion 任务种类。"""

    if model_type is None:
        return tuple(_DETECTION_CONVERSION_TASK_KIND_BY_MODEL_TYPE.values())
    normalized_model_type = _normalize_detection_conversion_model_type(model_type)
    return (_DETECTION_CONVERSION_TASK_KIND_BY_MODEL_TYPE[normalized_model_type],)


def _resolve_detection_conversion_model_type_from_task(task: object) -> str:
    """从任务记录中解析 detection conversion 模型分类。"""

    metadata = dict(getattr(task, "metadata", {}))
    model_type = metadata.get("model_type")
    if isinstance(model_type, str) and model_type.strip():
        return model_type.strip().lower()
    task_kind = getattr(task, "task_kind", "")
    resolved_model_type = _DETECTION_CONVERSION_MODEL_TYPE_BY_TASK_KIND.get(str(task_kind))
    if resolved_model_type is None:
        raise ResourceNotFoundError(
            "找不到指定的 detection conversion 任务",
            details={"task_id": getattr(task, "task_id", None)},
        )
    return resolved_model_type


def _build_detection_conversion_task_summary_response(
    task: object,
) -> DetectionConversionTaskSummaryResponse:
    """把 detection conversion TaskRecord 转成摘要响应。"""

    summary = _build_yolox_conversion_task_summary_response(task)
    return DetectionConversionTaskSummaryResponse.model_validate(
        {
            **summary.model_dump(),
            "model_type": _resolve_detection_conversion_model_type_from_task(task),
        }
    )


def _build_detection_conversion_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> DetectionConversionTaskDetailResponse:
    """把 detection conversion TaskRecord 转成详情响应。"""

    detail = _build_yolox_conversion_task_detail_response(task, events)
    return DetectionConversionTaskDetailResponse.model_validate(
        {
            **detail.model_dump(),
            "model_type": _resolve_detection_conversion_model_type_from_task(task),
        }
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
    raise InvalidRequestError("查询转换任务列表时必须提供 project_id")


def _require_visible_detection_conversion_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    include_events: bool,
):
    """读取并校验当前主体可见的 detection conversion 任务。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    if principal.project_ids and task_detail.task.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的转换任务",
            details={"task_id": task_id},
        )
    if task_detail.task.task_kind not in _DETECTION_CONVERSION_MODEL_TYPE_BY_TASK_KIND:
        raise ResourceNotFoundError(
            "找不到指定的 detection conversion 任务",
            details={"task_id": task_id},
        )
    return task_detail


def _matches_detection_conversion_filters(
    *,
    task: object,
    source_model_version_id: str | None,
    target_format: str | None,
) -> bool:
    """判断 detection conversion 任务是否满足额外筛选条件。"""

    task_spec = dict(getattr(task, "task_spec", {}))
    task_result = dict(getattr(task, "result", {}))
    if (
        source_model_version_id is not None
        and task_spec.get("source_model_version_id") != source_model_version_id
        and task_result.get("source_model_version_id") != source_model_version_id
    ):
        return False
    if target_format is not None:
        requested_target_formats = task_spec.get("target_formats")
        produced_formats = task_result.get("produced_formats")
        requested_matches = isinstance(requested_target_formats, list) and target_format in requested_target_formats
        produced_matches = isinstance(produced_formats, list) and target_format in produced_formats
        if not requested_matches and not produced_matches:
            return False
    return True
