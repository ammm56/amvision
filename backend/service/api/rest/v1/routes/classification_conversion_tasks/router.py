"""classification conversion 路由组装。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.classification_conversion_tasks.services import (
    CLASSIFICATION_CONVERSION_SERVICE_ENTRIES,
)
from backend.service.api.rest.v1.routes.task_conversion.services import create_task_conversion_router


classification_conversion_tasks_router = create_task_conversion_router(
    route_segment="classification",
    task_type="classification",
    service_entries=CLASSIFICATION_CONVERSION_SERVICE_ENTRIES,
)
