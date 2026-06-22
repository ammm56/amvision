"""segmentation conversion 路由 service 映射。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.task_conversion.services import TaskConversionServiceEntry
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    RFDETR_CONVERSION_QUEUE_NAME,
    RFDETR_CONVERSION_TASK_KIND,
    RfdetrConversionTaskRequest,
    SqlAlchemyRfdetrConversionTaskService,
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


SEGMENTATION_CONVERSION_SERVICE_ENTRIES = {
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
    "rfdetr": TaskConversionServiceEntry(
        service_cls=SqlAlchemyRfdetrConversionTaskService,
        request_cls=RfdetrConversionTaskRequest,
        task_kind=RFDETR_CONVERSION_TASK_KIND,
        queue_name=RFDETR_CONVERSION_QUEUE_NAME,
        request_includes_task_type=True,
    ),
}
