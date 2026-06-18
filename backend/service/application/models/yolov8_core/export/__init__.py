"""YOLOv8 core export 入口。"""

from __future__ import annotations

from typing import Any, Iterable

from backend.service.application.models.yolo_core_common.export import (
    YOLO_EXPORT_TARGET_FORMATS,
    YoloExportTaskPlan,
    build_yolo_export_task_plan,
)
from backend.service.application.models.yolov8_core.export.classification import (
    normalize_yolov8_classification_export_outputs as _normalize_classification_export_outputs,
    resolve_yolov8_classification_export_output_names as _resolve_classification_export_output_names,
)
from backend.service.application.models.yolov8_core.export.obb import (
    normalize_yolov8_obb_export_outputs as _normalize_obb_export_outputs,
    resolve_yolov8_obb_export_output_names as _resolve_obb_export_output_names,
)
from backend.service.application.models.yolov8_core.export.onnx import (
    export_yolov8_onnx,
    validate_yolov8_onnx,
)
from backend.service.application.models.yolov8_core.export.openvino import (
    build_yolov8_openvino_ir,
)
from backend.service.application.models.yolov8_core.export.pose import (
    normalize_yolov8_pose_export_outputs as _normalize_pose_export_outputs,
    resolve_yolov8_pose_export_output_names as _resolve_pose_export_output_names,
)
from backend.service.application.models.yolov8_core.export.segmentation import (
    normalize_yolov8_segmentation_export_outputs as _normalize_segmentation_export_outputs,
    resolve_yolov8_segmentation_export_output_names as _resolve_segmentation_export_output_names,
)
from backend.service.application.models.yolov8_core.export.source import (
    YoloV8ExportImports,
    YoloV8ExportSourceSession,
    enable_yolov8_export_cuda_fast_path,
    require_yolov8_export_imports,
    resolve_yolov8_export_torch_device_name,
)
from backend.service.application.models.yolov8_core.export.tensorrt import (
    build_yolov8_tensorrt_engine,
)


def resolve_yolov8_segmentation_export_output_names() -> tuple[str, str]:
    """返回 YOLOv8 segmentation 导出输出名。"""

    return _resolve_segmentation_export_output_names()


def resolve_yolov8_classification_export_output_names() -> tuple[str]:
    """返回 YOLOv8 classification 导出输出名。"""

    return _resolve_classification_export_output_names()


def resolve_yolov8_pose_export_output_names() -> tuple[str]:
    """返回 YOLOv8 pose 导出输出名。"""

    return _resolve_pose_export_output_names()


def resolve_yolov8_obb_export_output_names() -> tuple[str]:
    """返回 YOLOv8 OBB 导出输出名。"""

    return _resolve_obb_export_output_names()


def normalize_yolov8_segmentation_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any, Any]:
    """校验并返回 YOLOv8 segmentation 导出双输出。"""

    return _normalize_segmentation_export_outputs(outputs=outputs)


def normalize_yolov8_classification_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any]:
    """校验并返回 YOLOv8 classification 导出输出。"""

    return _normalize_classification_export_outputs(outputs=outputs)


def normalize_yolov8_pose_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any]:
    """校验并返回 YOLOv8 pose 导出输出。"""

    return _normalize_pose_export_outputs(outputs=outputs)


def normalize_yolov8_obb_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any]:
    """校验并返回 YOLOv8 OBB 导出输出。"""

    return _normalize_obb_export_outputs(outputs=outputs)


def build_yolov8_export_task_plan(
    *,
    task_type: str,
    target_formats: Iterable[str] = YOLO_EXPORT_TARGET_FORMATS,
) -> YoloExportTaskPlan:
    """返回 YOLOv8 指定任务的导出构建计划。"""

    plan = build_yolo_export_task_plan(
        task_type=task_type,
        target_formats=target_formats,
    )
    output_names = _resolve_yolov8_export_output_names(task_type=task_type)
    if output_names == plan.output_names:
        return plan
    return YoloExportTaskPlan(
        task_type=plan.task_type,
        input_names=plan.input_names,
        output_names=output_names,
        onnx_opset_version=plan.onnx_opset_version,
        exporter_mode=plan.exporter_mode,
        export_mode_enabled=plan.export_mode_enabled,
        target_specs=plan.target_specs,
    )


def _resolve_yolov8_export_output_names(*, task_type: str) -> tuple[str, ...]:
    """返回 YOLOv8 各 task 的导出输出名。"""

    if task_type == "classification":
        return resolve_yolov8_classification_export_output_names()
    if task_type == "segmentation":
        return resolve_yolov8_segmentation_export_output_names()
    if task_type == "pose":
        return resolve_yolov8_pose_export_output_names()
    if task_type == "obb":
        return resolve_yolov8_obb_export_output_names()
    return ("predictions",)


__all__ = [
    "build_yolov8_export_task_plan",
    "build_yolov8_openvino_ir",
    "build_yolov8_tensorrt_engine",
    "enable_yolov8_export_cuda_fast_path",
    "export_yolov8_onnx",
    "normalize_yolov8_classification_export_outputs",
    "normalize_yolov8_obb_export_outputs",
    "normalize_yolov8_pose_export_outputs",
    "normalize_yolov8_segmentation_export_outputs",
    "require_yolov8_export_imports",
    "resolve_yolov8_classification_export_output_names",
    "resolve_yolov8_export_torch_device_name",
    "resolve_yolov8_obb_export_output_names",
    "resolve_yolov8_pose_export_output_names",
    "resolve_yolov8_segmentation_export_output_names",
    "validate_yolov8_onnx",
    "YoloV8ExportImports",
    "YoloV8ExportSourceSession",
]
