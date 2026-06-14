"""YOLO11 core export 入口。"""

from __future__ import annotations

from typing import Any, Iterable

from backend.service.application.models.yolo_core_common.export import (
    YOLO_EXPORT_TARGET_FORMATS,
    YoloExportTaskPlan,
    build_yolo_export_task_plan,
    normalize_segmentation_export_outputs,
    resolve_segmentation_export_output_names,
)


def resolve_yolo11_segmentation_export_output_names() -> tuple[str, str]:
    """返回 YOLO11 segmentation 导出输出名。"""

    return resolve_segmentation_export_output_names()


def normalize_yolo11_segmentation_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any, Any]:
    """校验并返回 YOLO11 segmentation 导出双输出。"""

    return normalize_segmentation_export_outputs(outputs=outputs)


def build_yolo11_export_task_plan(
    *,
    task_type: str,
    target_formats: Iterable[str] = YOLO_EXPORT_TARGET_FORMATS,
) -> YoloExportTaskPlan:
    """返回 YOLO11 指定任务的导出构建计划。"""

    return build_yolo_export_task_plan(
        task_type=task_type,
        target_formats=target_formats,
    )
