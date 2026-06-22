"""detection conversion 路由组装。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.service.api.rest.v1.routes.detection_conversion_tasks.create import (
    detection_conversion_create_router,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.outputs import (
    detection_conversion_output_router,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.queries import (
    detection_conversion_query_router,
)


detection_conversion_tasks_router = APIRouter(prefix="/models", tags=["models"])
detection_conversion_tasks_router.include_router(detection_conversion_create_router)
detection_conversion_tasks_router.include_router(detection_conversion_query_router)
detection_conversion_tasks_router.include_router(detection_conversion_output_router)
