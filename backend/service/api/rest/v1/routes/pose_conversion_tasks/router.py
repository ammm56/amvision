"""pose conversion 路由组装。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.pose_conversion_tasks.services import POSE_CONVERSION_SERVICE_ENTRIES
from backend.service.api.rest.v1.routes.task_conversion.services import create_task_conversion_router


pose_conversion_tasks_router = create_task_conversion_router(
    route_segment="pose",
    task_type="pose",
    service_entries=POSE_CONVERSION_SERVICE_ENTRIES,
)
