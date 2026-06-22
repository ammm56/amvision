"""detection conversion 路由响应构造。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.detection_conversion_route_models import (
    DetectionConversionTaskDetailResponse,
    DetectionConversionTaskSummaryResponse,
    build_detection_conversion_task_detail_response,
    build_detection_conversion_task_summary_response,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.services import (
    resolve_detection_conversion_model_type_from_task,
)


def build_detection_conversion_task_summary(task: object) -> DetectionConversionTaskSummaryResponse:
    """把 detection conversion TaskRecord 转成摘要响应。"""

    return build_detection_conversion_task_summary_response(
        task,
        model_type=resolve_detection_conversion_model_type_from_task(task),
    )


def build_detection_conversion_task_detail(
    task: object,
    events: tuple[object, ...],
) -> DetectionConversionTaskDetailResponse:
    """把 detection conversion TaskRecord 转成详情响应。"""

    return build_detection_conversion_task_detail_response(
        task,
        events,
        model_type=resolve_detection_conversion_model_type_from_task(task),
    )
