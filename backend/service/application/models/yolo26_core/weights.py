"""YOLO26 core 权重覆盖率和加载入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from torch import nn

from backend.service.application.models.model_core_validation import StateDictCoverageSummary
from backend.service.application.models.yolo_core_common.weights import (
    YoloStateDictLoadResult,
    analyze_yolo_state_dict_coverage,
    load_yolo_checkpoint_file,
    load_yolo_state_dict,
)


def analyze_yolo26_state_dict_coverage(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
) -> StateDictCoverageSummary:
    """分析 YOLO26 state_dict 对当前模型的覆盖率。"""

    return analyze_yolo_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
    )


def load_yolo26_state_dict(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
    minimum_loadable_ratio: float = 1.0,
) -> YoloStateDictLoadResult:
    """加载 YOLO26 state_dict，并返回覆盖率报告。"""

    return load_yolo_state_dict(
        model=model,
        source_state_dict=source_state_dict,
        minimum_loadable_ratio=minimum_loadable_ratio,
    )


def load_yolo26_checkpoint_file(
    *,
    torch_module: Any,
    model: nn.Module,
    checkpoint_path: Path,
    minimum_loadable_ratio: float = 1.0,
) -> YoloStateDictLoadResult:
    """读取并加载 YOLO26 checkpoint 文件，返回覆盖率报告。"""

    return load_yolo_checkpoint_file(
        torch_module=torch_module,
        model=model,
        checkpoint_path=checkpoint_path,
        minimum_loadable_ratio=minimum_loadable_ratio,
        pickle_class_binders=(_bind_yolo26_pickle_checkpoint_classes,),
    )


def _bind_yolo26_pickle_checkpoint_classes(
    *,
    block_module: Any,
    conv_module: Any,
    head_module: Any,
    tasks_module: Any,
) -> None:
    """把 YOLO26 专属旧 pickle 类名绑定到项目内 YOLO26 core。"""

    del conv_module, tasks_module
    from backend.service.application.models.yolo26_core.tasks import (
        OBB26,
        Pose26,
        Proto26,
        RealNVP,
        Segment26,
    )

    block_module.Proto26 = Proto26
    head_module.OBB26 = OBB26
    head_module.Pose26 = Pose26
    head_module.RealNVP = RealNVP
    head_module.Segment26 = Segment26
