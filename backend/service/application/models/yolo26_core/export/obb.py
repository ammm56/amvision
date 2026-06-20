"""YOLO26 OBB 导出边界。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError

YOLO26_OBB_EXPORT_OUTPUT_NAMES = ("predictions",)


def resolve_yolo26_obb_export_output_names() -> tuple[str]:
    """返回 YOLO26 OBB 导出输出名。"""

    return YOLO26_OBB_EXPORT_OUTPUT_NAMES


def normalize_yolo26_obb_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any]:
    """校验并返回 YOLO26 OBB 导出输出。"""

    if not outputs:
        raise InvalidRequestError("YOLO26 OBB 导出输出为空")
    return (outputs[0],)


__all__ = [
    "normalize_yolo26_obb_export_outputs",
    "resolve_yolo26_obb_export_output_names",
]
