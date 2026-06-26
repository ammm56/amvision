"""YOLO11 core 权重覆盖率和加载入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from torch import nn

from backend.service.application.models.validation.model_core_validation import (
    StateDictCoverageSummary,
)
from backend.service.application.models.yolo_core_common.weights import (
    YoloStateDictLoadResult,
    analyze_yolo_state_dict_coverage,
    load_yolo_checkpoint_file,
    load_yolo_state_dict,
)


def analyze_yolo11_state_dict_coverage(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
) -> StateDictCoverageSummary:
    """分析 YOLO11 state_dict 对当前模型的覆盖率。"""

    return analyze_yolo_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
    )


def load_yolo11_state_dict(
    *,
    model: nn.Module,
    source_state_dict: dict[str, Any],
    minimum_loadable_ratio: float = 1.0,
    strict_shape: bool = True,
) -> YoloStateDictLoadResult:
    """加载 YOLO11 state_dict，并返回覆盖率报告。"""

    return load_yolo_state_dict(
        model=model,
        source_state_dict=source_state_dict,
        minimum_loadable_ratio=minimum_loadable_ratio,
        strict_shape=strict_shape,
    )


def load_yolo11_checkpoint_file(
    *,
    torch_module: Any,
    model: nn.Module,
    checkpoint_path: Path,
    minimum_loadable_ratio: float = 1.0,
    strict_shape: bool = True,
) -> YoloStateDictLoadResult:
    """读取并加载 YOLO11 checkpoint 文件，返回覆盖率报告。"""

    return load_yolo_checkpoint_file(
        torch_module=torch_module,
        model=model,
        checkpoint_path=checkpoint_path,
        minimum_loadable_ratio=minimum_loadable_ratio,
        strict_shape=strict_shape,
        pickle_class_binders=(_bind_yolo11_pickle_checkpoint_classes,),
    )


def _bind_yolo11_pickle_checkpoint_classes(
    *,
    block_module: Any,
    conv_module: Any,
    head_module: Any,
    tasks_module: Any,
) -> None:
    """把 YOLO11 旧 pickle 类名绑定到项目内 YOLO11 core。"""

    from backend.service.application.models.yolo11_core.nn.model import Yolo11Model
    from backend.service.application.models.yolo11_core.nn.modules import (
        Attention,
        Bottleneck,
        C2PSA,
        C2f,
        C3,
        C3k,
        C3k2,
        Concat,
        PSABlock,
        SPPF,
    )
    from backend.service.application.models.yolo11_core.nn.tasks import (
        Classify,
        Detect,
        OBB,
        Pose,
        Proto,
        Segment,
    )

    del conv_module
    block_module.Attention = Attention
    block_module.Bottleneck = Bottleneck
    block_module.C2PSA = C2PSA
    block_module.C2f = C2f
    block_module.C3 = C3
    block_module.C3k = C3k
    block_module.C3k2 = C3k2
    block_module.Concat = Concat
    block_module.PSABlock = PSABlock
    block_module.Proto = Proto
    block_module.SPPF = SPPF
    head_module.Classify = Classify
    head_module.Detect = Detect
    head_module.OBB = OBB
    head_module.Pose = Pose
    head_module.Segment = Segment
    tasks_module.ClassificationModel = Yolo11Model
    tasks_module.DetectionModel = Yolo11Model
    tasks_module.OBBModel = Yolo11Model
    tasks_module.PoseModel = Yolo11Model
    tasks_module.SegmentationModel = Yolo11Model
