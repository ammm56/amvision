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
        checkpoint_object = torch.load(
            checkpoint_path, map_location="cpu", weights_only=True
        )
    except Exception as exc:  # pragma: no cover - 真实损坏 checkpoint 属于集成层错误
        raise InvalidRequestError(
            "SAM3 checkpoint 无法读取",
            details={"checkpoint_path": str(checkpoint_path)},
        ) from exc

    if isinstance(checkpoint_object, dict) and isinstance(
        checkpoint_object.get("model"), dict
    ):
        checkpoint_object = checkpoint_object["model"]
    if not isinstance(checkpoint_object, dict):
        raise InvalidRequestError(
            "SAM3 checkpoint 不是可识别的 state_dict",
            details={
                "checkpoint_path": str(checkpoint_path),
                "payload_type": type(checkpoint_object).__name__,
            },
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
    detector_state_dict = {
        key: value
        for key, value in full_state_dict.items()
        if key.startswith("detector.")
    }
    tracker_state_dict = {
        key: value
        for key, value in full_state_dict.items()
        if key.startswith("tracker.")
    }
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


def build_sam3_interactive_state_dict(
    branches: Sam3CheckpointBranches,
) -> dict[str, torch.Tensor]:
    """构造 SAM3.1 multiplex 的单图 interactive state_dict。

    这里只选择 interactive neck、interactive prompt encoder 和 interactive
    mask decoder。Multiplex 的 propagation 分支和 bucketized 通用 decoder
    不属于当前单图能力，不能混载。
    """

    interactive_state_dict: dict[str, torch.Tensor] = {}
    for key, value in branches.detector_state_dict.items():
        normalized_key = key.removeprefix("detector.")
        if normalized_key.startswith("backbone.vision_backbone.trunk."):
            normalized_key = normalized_key.replace(
                "backbone.vision_backbone.",
                "image_encoder.vision_backbone.",
                1,
            )
        elif normalized_key.startswith(
            "backbone.vision_backbone.interactive_convs."
        ):
            normalized_key = normalized_key.replace(
                "backbone.vision_backbone.",
                "image_encoder.vision_backbone.",
                1,
            )
        else:
            continue
        interactive_state_dict[normalized_key] = value

    tracker_prefix_mappings = (
        (
            "tracker.model.interactive_sam_prompt_encoder.",
            "sam_prompt_encoder.",
        ),
        (
            "tracker.model.interactive_sam_mask_decoder.",
            "sam_mask_decoder.",
        ),
    )
    for key, value in branches.tracker_state_dict.items():
        if key == "tracker.model.interactivity_no_mem_embed":
            interactive_state_dict["no_mem_embed"] = value
            continue
        for source_prefix, target_prefix in tracker_prefix_mappings:
            if key.startswith(source_prefix):
                interactive_state_dict[
                    target_prefix + key.removeprefix(source_prefix)
                ] = value
                break

    interactive_state_dict.update(
        {
            key.replace(".mlp.lin1.", ".mlp.layers.0.").replace(
                ".mlp.lin2.",
                ".mlp.layers.1.",
            ): value
            for key, value in tuple(interactive_state_dict.items())
            if ".mlp.lin1." in key or ".mlp.lin2." in key
        }
    )
    return interactive_state_dict


def build_sam3_semantic_state_dict(
    branches: Sam3CheckpointBranches,
) -> dict[str, torch.Tensor]:
    """构造 project-native semantic runtime 使用的 detector 分支 state_dict。"""

    semantic_state_dict: dict[str, torch.Tensor] = {}
    for key, value in branches.detector_state_dict.items():
        normalized_key = key.removeprefix("detector.")
        if normalized_key.startswith("backbone.vision_backbone."):
            normalized_key = normalized_key.replace(
                "backbone.vision_backbone.",
                "image_encoder.vision_backbone.",
                1,
            )
        elif normalized_key.startswith("backbone.language_backbone."):
            normalized_key = normalized_key.replace(
                "backbone.language_backbone.",
                "language_backbone.",
                1,
            )
        elif normalized_key.startswith("transformer.encoder."):
            normalized_key = normalized_key.replace(
                "transformer.encoder.",
                "encoder.",
                1,
            )
        semantic_state_dict[normalized_key] = value
    return semantic_state_dict


def build_sam3_multiplex_propagation_state_dict(
    branches: Sam3CheckpointBranches,
) -> dict[str, torch.Tensor]:
    """构造 SAM3.1 视频 propagation 与 bucket decoder state_dict。"""

    propagation_state_dict: dict[str, torch.Tensor] = {}
    for key, value in branches.detector_state_dict.items():
        normalized_key = key.removeprefix("detector.")
        if normalized_key.startswith("backbone.vision_backbone.trunk."):
            normalized_key = normalized_key.replace(
                "backbone.vision_backbone.",
                "image_encoder.vision_backbone.",
                1,
            )
        elif normalized_key.startswith(
            "backbone.vision_backbone.propagation_convs."
        ):
            normalized_key = normalized_key.replace(
                "backbone.vision_backbone.",
                "image_encoder.vision_backbone.",
                1,
            )
        else:
            continue
        propagation_state_dict[normalized_key] = value

    tracker_prefixes = (
        "tracker.model.transformer.",
        "tracker.model.maskmem_backbone.",
        "tracker.model.sam_mask_decoder.",
        "tracker.model.obj_ptr_proj.",
        "tracker.model.interactive_obj_ptr_proj.",
        "tracker.model.no_obj_ptr_linear.",
        "tracker.model.obj_ptr_tpos_proj.",
        "tracker.model.image_pe_layer.",
    )
    tracker_parameter_keys = {
        "tracker.model.maskmem_tpos_enc",
        "tracker.model.no_obj_embed_spatial",
        "tracker.model.output_valid_embed",
        "tracker.model.output_invalid_embed",
    }
    for key, value in branches.tracker_state_dict.items():
        if key in tracker_parameter_keys:
            propagation_state_dict[
                key.removeprefix("tracker.model.")
            ] = value
            continue
        if key.startswith(tracker_prefixes):
            propagation_state_dict[
                key.removeprefix("tracker.model.")
            ] = value

    normalized_items = tuple(propagation_state_dict.items())
    for key, value in normalized_items:
        normalized_key = key.replace(".mlp.lin1.", ".mlp.layers.0.").replace(
            ".mlp.lin2.",
            ".mlp.layers.1.",
        )
        if normalized_key != key:
            propagation_state_dict[normalized_key] = value
            del propagation_state_dict[key]
    return propagation_state_dict


def summarize_sam3_checkpoint_prefixes(
    state_dict: dict[str, torch.Tensor],
) -> list[tuple[str, int]]:
    """汇总 checkpoint 一级前缀数量，便于调试和审计。"""

    prefix_counter = Counter(key.split(".", 1)[0] for key in state_dict)
    return prefix_counter.most_common()
