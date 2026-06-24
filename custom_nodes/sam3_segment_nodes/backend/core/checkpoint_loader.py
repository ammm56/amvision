"""SAM3 checkpoint 解析与 interactive state_dict 映射。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import torch

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class Sam3CheckpointBranches:
    """描述一份 SAM3 checkpoint 中拆分出来的分支。"""

    full_state_dict: dict[str, torch.Tensor]
    detector_state_dict: dict[str, torch.Tensor]
    tracker_state_dict: dict[str, torch.Tensor]


def load_sam3_checkpoint_state_dict(checkpoint_path: Path) -> dict[str, torch.Tensor]:
    """读取本地 SAM3 checkpoint 并返回纯 state_dict。"""

    try:
        checkpoint_object = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    except Exception as exc:  # pragma: no cover - 真实损坏 checkpoint 属于集成层错误
        raise InvalidRequestError(
            "SAM3 checkpoint 无法读取",
            details={"checkpoint_path": str(checkpoint_path)},
        ) from exc

    if isinstance(checkpoint_object, dict) and isinstance(checkpoint_object.get("model"), dict):
        checkpoint_object = checkpoint_object["model"]
    if not isinstance(checkpoint_object, dict):
        raise InvalidRequestError(
            "SAM3 checkpoint 不是可识别的 state_dict",
            details={"checkpoint_path": str(checkpoint_path), "payload_type": type(checkpoint_object).__name__},
        )

    normalized_state_dict: dict[str, torch.Tensor] = {}
    for key, value in checkpoint_object.items():
        if isinstance(key, str) and torch.is_tensor(value):
            normalized_state_dict[key] = value
    if not normalized_state_dict:
        raise InvalidRequestError(
            "SAM3 checkpoint 中没有可用的 tensor 参数",
            details={"checkpoint_path": str(checkpoint_path)},
        )
    return normalized_state_dict


def load_sam3_checkpoint_branches(checkpoint_path: Path) -> Sam3CheckpointBranches:
    """拆分 SAM3 checkpoint 中的 detector 与 tracker 分支。"""

    full_state_dict = load_sam3_checkpoint_state_dict(checkpoint_path)
    detector_state_dict = {key: value for key, value in full_state_dict.items() if key.startswith("detector.")}
    tracker_state_dict = {key: value for key, value in full_state_dict.items() if key.startswith("tracker.")}
    if not detector_state_dict:
        raise InvalidRequestError(
            "SAM3 checkpoint 缺少 detector 分支",
            details={"checkpoint_path": str(checkpoint_path)},
        )
    if not tracker_state_dict:
        raise InvalidRequestError(
            "SAM3 checkpoint 缺少 tracker 分支",
            details={"checkpoint_path": str(checkpoint_path)},
        )
    return Sam3CheckpointBranches(
        full_state_dict=full_state_dict,
        detector_state_dict=detector_state_dict,
        tracker_state_dict=tracker_state_dict,
    )


def build_sam3_interactive_state_dict(branches: Sam3CheckpointBranches) -> dict[str, torch.Tensor]:
    """按 upstream interactive 加载规则构造 project-native interactive state_dict。"""

    detector_trimmed = {
        key.removeprefix("detector."): value
        for key, value in branches.detector_state_dict.items()
    }
    interactive_state_dict = dict(detector_trimmed)
    interactive_state_dict.update(
        {
            key.replace("backbone.vision_backbone", "image_encoder.vision_backbone"): value
            for key, value in detector_trimmed.items()
            if "backbone.vision_backbone" in key
        }
    )
    interactive_state_dict.update(
        {
            key.replace("tracker.transformer.encoder", "memory_attention"): value
            for key, value in branches.tracker_state_dict.items()
            if "tracker.transformer" in key
        }
    )
    interactive_state_dict.update(
        {
            key.replace("tracker.maskmem_backbone", "memory_encoder"): value
            for key, value in branches.tracker_state_dict.items()
            if "tracker.maskmem_backbone" in key
        }
    )
    interactive_state_dict.update(
        {
            key.removeprefix("tracker."): value
            for key, value in branches.tracker_state_dict.items()
        }
    )
    return interactive_state_dict


def build_sam3_semantic_state_dict(branches: Sam3CheckpointBranches) -> dict[str, torch.Tensor]:
    """构造 project-native semantic runtime 使用的 detector 分支 state_dict。"""

    return {
        key.removeprefix("detector."): value
        for key, value in branches.detector_state_dict.items()
    }


def summarize_sam3_checkpoint_prefixes(state_dict: dict[str, torch.Tensor]) -> list[tuple[str, int]]:
    """汇总 checkpoint 一级前缀数量，便于调试和审计。"""

    prefix_counter = Counter(key.split(".", 1)[0] for key in state_dict)
    return prefix_counter.most_common()
