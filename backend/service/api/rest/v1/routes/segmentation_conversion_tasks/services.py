"""segmentation conversion 路由 service 映射。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.task_conversion.services import TaskConversionServiceEntry


_CONVERSION_MODULE_BY_MODEL_TYPE = {
    "yolov8": "backend.service.application.conversions.yolov8_conversion_task_service",
    "yolo11": "backend.service.application.conversions.yolo11_conversion_task_service",
    "yolo26": "backend.service.application.conversions.yolo26_conversion_task_service",
    "rfdetr": "backend.service.application.conversions.rfdetr_conversion_task_service",
}


SEGMENTATION_CONVERSION_SERVICE_ENTRIES = {
    "yolov8": TaskConversionServiceEntry(
        module_name=_CONVERSION_MODULE_BY_MODEL_TYPE["yolov8"],
        service_class_name="SqlAlchemyYoloV8ConversionTaskService",
        request_class_name="YoloV8ConversionTaskRequest",
        task_kind="yolov8-conversion",
        queue_name="yolov8-conversions",
    ),
    "yolo11": TaskConversionServiceEntry(
        module_name=_CONVERSION_MODULE_BY_MODEL_TYPE["yolo11"],
        service_class_name="SqlAlchemyYolo11ConversionTaskService",
        request_class_name="Yolo11ConversionTaskRequest",
        task_kind="yolo11-conversion",
        queue_name="yolo11-conversions",
    ),
    "yolo26": TaskConversionServiceEntry(
        module_name=_CONVERSION_MODULE_BY_MODEL_TYPE["yolo26"],
        service_class_name="SqlAlchemyYolo26ConversionTaskService",
        request_class_name="Yolo26ConversionTaskRequest",
        task_kind="yolo26-conversion",
        queue_name="yolo26-conversions",
    ),
    "rfdetr": TaskConversionServiceEntry(
        module_name=_CONVERSION_MODULE_BY_MODEL_TYPE["rfdetr"],
        service_class_name="SqlAlchemyRfdetrConversionTaskService",
        request_class_name="RfdetrConversionTaskRequest",
        task_kind="rfdetr-conversion",
        queue_name="rfdetr-conversions",
        request_includes_task_type=True,
    ),
}
