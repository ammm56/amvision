"""YOLOv8 core 权重覆盖率和加载入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from torch import nn

from backend.service.application.models.validation.model_core_validation import StateDictCoverageSummary
from backend.service.application.models.yolo_core_common.weights import (
    YoloStateDictLoadResult,
    analyze_yolo_state_dict_coverage,
    load_yolo_checkpoint_file,
    load_yolo_state_dict,
)


def analyze_yolov8_state_dict_coverage(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
) -> StateDictCoverageSummary:
    """分析 YOLOv8 state_dict 对当前模型的覆盖率。"""

    return analyze_yolo_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
    )


def load_yolov8_state_dict(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
    minimum_loadable_ratio: float = 1.0,
    strict_shape: bool = True,
) -> YoloStateDictLoadResult:
    """加载 YOLOv8 state_dict，并返回覆盖率报告。"""

    return load_yolo_state_dict(
        model=model,
        source_state_dict=source_state_dict,
        minimum_loadable_ratio=minimum_loadable_ratio,
        strict_shape=strict_shape,
    )


def load_yolov8_checkpoint_file(
    *,
    torch_module: Any,
    model: nn.Module,
    checkpoint_path: Path,
    minimum_loadable_ratio: float = 1.0,
    strict_shape: bool = True,
) -> YoloStateDictLoadResult:
    """读取并加载 YOLOv8 checkpoint 文件，返回覆盖率报告。"""

    return load_yolo_checkpoint_file(
        torch_module=torch_module,
        model=model,
        checkpoint_path=checkpoint_path,
        minimum_loadable_ratio=minimum_loadable_ratio,
        strict_shape=strict_shape,
    )
