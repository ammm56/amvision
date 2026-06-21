"""YOLO26 ONNX 导出入口。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.models.yolo26_core.export.plan import (
    Yolo26ExportTaskPlan,
)
from backend.service.application.models.yolo_core_common.export import (
    export_yolo_onnx,
    validate_yolo_onnx,
)
from backend.service.application.models.yolo26_core.export.validation import (
    summarize_yolo26_detection_processed_onnx_validation,
)


def export_yolo26_onnx(
    *,
    session: object,
    output_path: Path,
    output_object_key: str,
    export_plan: Yolo26ExportTaskPlan,
) -> dict[str, object]:
    """把 YOLO26 PyTorch session 导出为 ONNX。"""

    return export_yolo_onnx(
        session=session,
        output_path=output_path,
        output_object_key=output_object_key,
        export_plan=export_plan,
    )


def validate_yolo26_onnx(
    *,
    session: object,
    onnx_path: Path,
    onnx_module: object,
    onnxruntime_module: object,
    export_plan: Yolo26ExportTaskPlan,
) -> dict[str, object]:
    """校验 YOLO26 ONNX 文件和 PyTorch 输出是否一致。"""

    if export_plan.task_type == "detection":
        return validate_yolo_onnx(
            session=session,
            onnx_path=onnx_path,
            onnx_module=onnx_module,
            onnxruntime_module=onnxruntime_module,
            export_plan=export_plan,
            summary_builder=summarize_yolo26_detection_processed_onnx_validation,
            strict_numeric_validation=False,
        )
    return validate_yolo_onnx(
        session=session,
        onnx_path=onnx_path,
        onnx_module=onnx_module,
        onnxruntime_module=onnxruntime_module,
        export_plan=export_plan,
    )


__all__ = [
    "export_yolo26_onnx",
    "validate_yolo26_onnx",
]
