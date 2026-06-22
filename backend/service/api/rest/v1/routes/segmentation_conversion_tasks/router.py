"""segmentation conversion 路由组装。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.segmentation_conversion_tasks.services import (
    SEGMENTATION_CONVERSION_SERVICE_ENTRIES,
)
from backend.service.api.rest.v1.routes.task_conversion.services import create_task_conversion_router


segmentation_conversion_tasks_router = create_task_conversion_router(
    route_segment="segmentation",
    task_type="segmentation",
    service_entries=SEGMENTATION_CONVERSION_SERVICE_ENTRIES,
)
