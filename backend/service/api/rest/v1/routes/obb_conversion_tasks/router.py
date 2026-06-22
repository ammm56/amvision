"""OBB conversion 路由组装。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.obb_conversion_tasks.services import OBB_CONVERSION_SERVICE_ENTRIES
from backend.service.api.rest.v1.routes.task_conversion.services import create_task_conversion_router


obb_conversion_tasks_router = create_task_conversion_router(
    route_segment="obb",
    task_type="obb",
    service_entries=OBB_CONVERSION_SERVICE_ENTRIES,
)
