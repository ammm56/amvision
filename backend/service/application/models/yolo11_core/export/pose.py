"""YOLO11 pose 导出边界。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError

YOLO11_POSE_EXPORT_OUTPUT_NAMES = ("predictions",)


def resolve_yolo11_pose_export_output_names() -> tuple[str]:
    """返回 YOLO11 pose 导出输出名。"""

    return YOLO11_POSE_EXPORT_OUTPUT_NAMES


def normalize_yolo11_pose_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any]:
    """校验并返回 YOLO11 pose 导出输出。"""

    if not outputs:
        raise InvalidRequestError("YOLO11 pose 导出输出为空")
    return (outputs[0],)


__all__ = [
    "normalize_yolo11_pose_export_outputs",
    "resolve_yolo11_pose_export_output_names",
]
