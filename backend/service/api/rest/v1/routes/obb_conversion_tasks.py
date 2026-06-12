"""OBB conversion task REST 路由。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.task_conversion_routes_common import (
    TaskConversionServiceEntry,
    create_task_conversion_router,
)
from backend.service.application.conversions.yolo11_conversion_task_service import (
    YOLO11_CONVERSION_QUEUE_NAME,
    YOLO11_CONVERSION_TASK_KIND,
    SqlAlchemyYolo11ConversionTaskService,
    Yolo11ConversionTaskRequest,
)
from backend.service.application.conversions.yolo26_conversion_task_service import (
    YOLO26_CONVERSION_QUEUE_NAME,
    YOLO26_CONVERSION_TASK_KIND,
    SqlAlchemyYolo26ConversionTaskService,
    Yolo26ConversionTaskRequest,
)
from backend.service.application.conversions.yolov8_conversion_task_service import (
    YOLOV8_CONVERSION_QUEUE_NAME,
    YOLOV8_CONVERSION_TASK_KIND,
    SqlAlchemyYoloV8ConversionTaskService,
    YoloV8ConversionTaskRequest,
)


obb_conversion_tasks_router = create_task_conversion_router(
    route_segment="obb",
    task_type="obb",
    service_entries={
        "yolov8": TaskConversionServiceEntry(
            service_cls=SqlAlchemyYoloV8ConversionTaskService,
            request_cls=YoloV8ConversionTaskRequest,
            task_kind=YOLOV8_CONVERSION_TASK_KIND,
            queue_name=YOLOV8_CONVERSION_QUEUE_NAME,
        ),
        "yolo11": TaskConversionServiceEntry(
            service_cls=SqlAlchemyYolo11ConversionTaskService,
            request_cls=Yolo11ConversionTaskRequest,
            task_kind=YOLO11_CONVERSION_TASK_KIND,
            queue_name=YOLO11_CONVERSION_QUEUE_NAME,
        ),
        "yolo26": TaskConversionServiceEntry(
            service_cls=SqlAlchemyYolo26ConversionTaskService,
            request_cls=Yolo26ConversionTaskRequest,
            task_kind=YOLO26_CONVERSION_TASK_KIND,
            queue_name=YOLO26_CONVERSION_QUEUE_NAME,
        ),
    },
)
