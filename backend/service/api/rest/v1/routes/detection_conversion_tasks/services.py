"""detection conversion 路由 service 装配和提交 helper。"""

from __future__ import annotations

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.detection_conversion_tasks.schemas import (
    DetectionConversionTaskCreateRequestBody,
    DetectionConversionTaskSubmissionResponse,
    DetectionConversionTargetLiteral,
)
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    RFDETR_CONVERSION_TASK_KIND,
    RfdetrConversionTaskRequest,
    SqlAlchemyRfdetrConversionTaskService,
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
from backend.service.application.conversions.yolox_conversion_task_service import (
    YOLOX_CONVERSION_TASK_KIND,
    SqlAlchemyYoloXConversionTaskService,
    YoloXConversionTaskRequest,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.model_type_support import require_supported_platform_model_type
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.platform_model_support import normalize_platform_model_type
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE = {
    "yolox": (SqlAlchemyYoloXConversionTaskService, YoloXConversionTaskRequest),
    "yolov8": (SqlAlchemyYoloV8ConversionTaskService, YoloV8ConversionTaskRequest),
    "yolo11": (SqlAlchemyYolo11ConversionTaskService, Yolo11ConversionTaskRequest),
    "yolo26": (SqlAlchemyYolo26ConversionTaskService, Yolo26ConversionTaskRequest),
    "rfdetr": (SqlAlchemyRfdetrConversionTaskService, RfdetrConversionTaskRequest),
}

DETECTION_CONVERSION_TASK_KIND_BY_MODEL_TYPE = {
    "yolox": YOLOX_CONVERSION_TASK_KIND,
    "yolov8": YOLOV8_CONVERSION_TASK_KIND,
    "yolo11": YOLO11_CONVERSION_TASK_KIND,
    "yolo26": YOLO26_CONVERSION_TASK_KIND,
    "rfdetr": RFDETR_CONVERSION_TASK_KIND,
}

DETECTION_CONVERSION_MODEL_TYPE_BY_TASK_KIND = {
    task_kind: model_type
    for model_type, task_kind in DETECTION_CONVERSION_TASK_KIND_BY_MODEL_TYPE.items()
}


def submit_detection_conversion_task(
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
    model_type = normalize_detection_conversion_model_type(body.model_type)
    service_cls, request_cls = DETECTION_CONVERSION_SERVICE_BY_MODEL_TYPE[model_type]
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


def merge_fixed_detection_conversion_extra_options(
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


def normalize_detection_conversion_model_type(value: str) -> str:
    """把 detection conversion 模型分类归一化为正式值。"""

    return require_supported_platform_model_type(
        task_type=DETECTION_TASK_TYPE,
        model_type=value,
        unsupported_message="当前 detection conversion 不支持指定模型分类",
    )


def resolve_detection_conversion_task_kinds(model_type: str | None) -> tuple[str, ...]:
    """根据查询条件返回需要覆盖的 detection conversion 任务种类。"""

    if model_type is None:
        return tuple(DETECTION_CONVERSION_TASK_KIND_BY_MODEL_TYPE.values())
    normalized_model_type = normalize_detection_conversion_model_type(model_type)
    return (DETECTION_CONVERSION_TASK_KIND_BY_MODEL_TYPE[normalized_model_type],)


def resolve_detection_conversion_model_type_from_task(task: object) -> str:
    """从任务记录中解析 detection conversion 模型分类。"""

    metadata = dict(getattr(task, "metadata", {}))
    model_type = metadata.get("model_type")
    normalized_model_type = normalize_platform_model_type(model_type)
    if normalized_model_type is not None:
        return normalized_model_type
    task_kind = getattr(task, "task_kind", "")
    resolved_model_type = DETECTION_CONVERSION_MODEL_TYPE_BY_TASK_KIND.get(str(task_kind))
    if resolved_model_type is None:
        raise ResourceNotFoundError(
            "找不到指定的 detection conversion 任务",
            details={"task_id": getattr(task, "task_id", None)},
        )
    return resolved_model_type
