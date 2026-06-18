"""YOLOv8 ONNX 导出入口。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.models.yolov8_core.export.execution import (
    export_yolov8_onnx_model,
    validate_yolov8_onnx_model,
)
from backend.service.application.models.yolov8_core.export.plan import (
    YoloV8ExportTaskPlan,
)


def export_yolov8_onnx(
    *,
    session: object,
    output_path: Path,
    output_object_key: str,
    export_plan: YoloV8ExportTaskPlan,
) -> dict[str, object]:
    """把 YOLOv8 PyTorch session 导出为 ONNX。"""

    return export_yolov8_onnx_model(
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
    export_plan: YoloV8ExportTaskPlan,
) -> dict[str, object]:
    """校验 YOLOv8 ONNX 文件和 PyTorch 输出是否一致。"""

    return validate_yolov8_onnx_model(
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
