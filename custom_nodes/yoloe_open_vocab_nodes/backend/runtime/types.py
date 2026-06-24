"""YOLOE project-native runtime 数据类型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectNativeYoloePrediction:
    """描述一次 project-native YOLOE 节点推理结果。"""

    detections: tuple[dict[str, object], ...]
    regions: tuple[dict[str, object], ...]
    summary: dict[str, object]


__all__ = ["ProjectNativeYoloePrediction"]
