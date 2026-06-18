"""YOLOv8 ONNX 导出入口。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.models.yolo_core_common.export import (
    YoloExportTaskPlan,
    export_yolo_onnx,
    validate_yolo_onnx,
)


def export_yolov8_onnx(
    *,
    session: object,
    output_path: Path,
    output_object_key: str,
    export_plan: YoloExportTaskPlan,
) -> dict[str, object]:
    """把 YOLOv8 PyTorch session 导出为 ONNX。"""

    return export_yolo_onnx(
        session=session,
        output_path=output_path,
        output_object_key=output_object_key,
        export_plan=export_plan,
    )


def validate_yolov8_onnx(
    *,
    session: object,
    onnx_path: Path,
    onnx_module: object,
    onnxruntime_module: object,
    export_plan: YoloExportTaskPlan,
) -> dict[str, object]:
    """校验 YOLOv8 ONNX 文件和 PyTorch 输出是否一致。"""

    return validate_yolo_onnx(
        session=session,
        onnx_path=onnx_path,
        onnx_module=onnx_module,
        onnxruntime_module=onnxruntime_module,
        export_plan=export_plan,
    )


__all__ = [
    "export_yolov8_onnx",
    "validate_yolov8_onnx",
]
