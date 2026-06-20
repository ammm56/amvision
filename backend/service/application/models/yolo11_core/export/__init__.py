"""YOLO11 core export 入口。"""

from __future__ import annotations

from typing import Any, Iterable

from backend.service.application.models.yolo11_core.export.classification import (
    normalize_yolo11_classification_export_outputs as _normalize_classification_export_outputs,
    resolve_yolo11_classification_export_output_names as _resolve_classification_export_output_names,
)
from backend.service.application.models.yolo11_core.export.obb import (
    normalize_yolo11_obb_export_outputs as _normalize_obb_export_outputs,
    resolve_yolo11_obb_export_output_names as _resolve_obb_export_output_names,
)
from backend.service.application.models.yolo11_core.export.onnx import (
    export_yolo11_onnx,
    validate_yolo11_onnx,
)
from backend.service.application.models.yolo11_core.export.openvino import (
    build_yolo11_openvino_ir,
)
from backend.service.application.models.yolo11_core.export.plan import (
    YOLO11_EXPORT_TARGET_FORMATS,
    Yolo11ExportTaskPlan,
    build_yolo11_export_task_plan as _build_yolo11_export_task_plan,
)
from backend.service.application.models.yolo11_core.export.pose import (
    normalize_yolo11_pose_export_outputs as _normalize_pose_export_outputs,
    resolve_yolo11_pose_export_output_names as _resolve_pose_export_output_names,
)
from backend.service.application.models.yolo11_core.export.segmentation import (
    normalize_yolo11_segmentation_export_outputs as _normalize_segmentation_export_outputs,
    resolve_yolo11_segmentation_export_output_names as _resolve_segmentation_export_output_names,
)
from backend.service.application.models.yolo11_core.export.source import (
    Yolo11ExportImports,
    Yolo11ExportSourceSession,
    enable_yolo11_export_cuda_fast_path,
    require_yolo11_export_imports,
    resolve_yolo11_export_torch_device_name,
)
from backend.service.application.models.yolo11_core.export.tensorrt import (
    build_yolo11_tensorrt_engine,
)


def resolve_yolo11_segmentation_export_output_names() -> tuple[str, str]:
    """返回 YOLO11 segmentation 导出输出名。"""

    return _resolve_segmentation_export_output_names()


def resolve_yolo11_classification_export_output_names() -> tuple[str]:
    """返回 YOLO11 classification 导出输出名。"""

    return _resolve_classification_export_output_names()


def resolve_yolo11_pose_export_output_names() -> tuple[str]:
    """返回 YOLO11 pose 导出输出名。"""

    return _resolve_pose_export_output_names()


def resolve_yolo11_obb_export_output_names() -> tuple[str]:
    """返回 YOLO11 OBB 导出输出名。"""

    return _resolve_obb_export_output_names()


def normalize_yolo11_segmentation_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any, Any]:
    """校验并返回 YOLO11 segmentation 导出双输出。"""

    return _normalize_segmentation_export_outputs(outputs=outputs)


def normalize_yolo11_classification_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any]:
    """校验并返回 YOLO11 classification 导出输出。"""

    return _normalize_classification_export_outputs(outputs=outputs)


def normalize_yolo11_pose_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any]:
    """校验并返回 YOLO11 pose 导出输出。"""

    return _normalize_pose_export_outputs(outputs=outputs)


def normalize_yolo11_obb_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any]:
    """校验并返回 YOLO11 OBB 导出输出。"""

    return _normalize_obb_export_outputs(outputs=outputs)


def build_yolo11_export_task_plan(
    *,
    task_type: str,
    target_formats: Iterable[str] = YOLO11_EXPORT_TARGET_FORMATS,
) -> Yolo11ExportTaskPlan:
    """返回 YOLO11 指定任务的导出构建计划。"""

    return _build_yolo11_export_task_plan(
        task_type=task_type,
        target_formats=target_formats,
    )


__all__ = [
    "Yolo11ExportImports",
    "Yolo11ExportSourceSession",
    "Yolo11ExportTaskPlan",
    "build_yolo11_export_task_plan",
    "build_yolo11_openvino_ir",
    "build_yolo11_tensorrt_engine",
    "enable_yolo11_export_cuda_fast_path",
    "export_yolo11_onnx",
    "normalize_yolo11_classification_export_outputs",
    "normalize_yolo11_obb_export_outputs",
    "normalize_yolo11_pose_export_outputs",
    "normalize_yolo11_segmentation_export_outputs",
    "require_yolo11_export_imports",
    "resolve_yolo11_classification_export_output_names",
    "resolve_yolo11_export_torch_device_name",
    "resolve_yolo11_obb_export_output_names",
    "resolve_yolo11_pose_export_output_names",
    "resolve_yolo11_segmentation_export_output_names",
    "validate_yolo11_onnx",
]
