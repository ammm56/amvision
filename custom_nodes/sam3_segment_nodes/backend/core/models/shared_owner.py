"""SAM3.1 多能力共享模型所有者。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn

from backend.service.application.runtime.support.detection import (
    enable_pytorch_cuda_inference_fast_path,
    resolve_execution_device_name,
)

from ..checkpoint.loader import (
    Sam3CheckpointBranches,
    build_sam3_interactive_state_dict,
    build_sam3_semantic_state_dict,
)
from ..nn.vision_backbone import (
    build_sam3_vit_trunk,
    release_rotary_device_caches,
)
from .interactive import (
    Sam3InteractiveImageModel,
    _load_compatible_state_dict as _load_interactive_state_dict,
    _resolve_requested_device_name,
    _resolve_runtime_torch_dtype,
)
from .semantic import (
    Sam3SemanticImageModel,
    _load_compatible_state_dict as _load_semantic_state_dict,
)
from .multiplex_video import (
    Sam3MultiplexPropagationModel,
    load_sam3_multiplex_propagation_weights,
)


@dataclass(frozen=True)
class Sam3SharedOwnerBuildResult:
    """描述共享模型构建结果。"""

    owner: "Sam3SharedModelOwner"
    resolved_device_name: str
    runtime_torch_dtype: torch.dtype
    compatibility_summary: dict[str, object]


class Sam3SharedTrunkFeatureCache:
    """只保留共享 ViT 最近一张图片的输出。"""

    def __init__(self) -> None:
        self._image_identity: str | None = None
        self._trunk_feature: torch.Tensor | None = None
        self.hits = 0
        self.misses = 0

    @torch.inference_mode()
    def get_or_compute(
        self,
        *,
        image_identity: str,
        image_tensor: torch.Tensor,
        trunk: nn.Module,
    ) -> torch.Tensor:
        """命中时返回同一 tensor；新图片立即替换旧特征。"""

        if (
            self._image_identity == image_identity
            and self._trunk_feature is not None
        ):
            self.hits += 1
            return self._trunk_feature
        trunk_outputs = trunk(image_tensor)
        if not trunk_outputs:
            raise RuntimeError("SAM3 ViT trunk 没有返回视觉特征")
        self._image_identity = image_identity
        self._trunk_feature = trunk_outputs[-1]
        self.misses += 1
        return self._trunk_feature

    def clear(self) -> None:
        """释放最近图像特征引用。"""

        self._image_identity = None
        self._trunk_feature = None

    def diagnostics(self) -> dict[str, object]:
        """返回 cache 诊断信息。"""

        return {
            "scope": "shared-owner-latest-image",
            "has_value": self._trunk_feature is not None,
            "hits": self.hits,
            "misses": self.misses,
        }


class Sam3SharedModelOwner(nn.Module):
    """持有 SAM3 图片与视频能力共用的一份 ViT trunk。"""

    def __init__(
        self,
        *,
        interactive_model: Sam3InteractiveImageModel | None = None,
        semantic_model: Sam3SemanticImageModel | None = None,
        multiplex_model: Sam3MultiplexPropagationModel | None = None,
    ) -> None:
        super().__init__()
        models = tuple(
            model
            for model in (interactive_model, semantic_model, multiplex_model)
            if model is not None
        )
        if len(models) < 2:
            raise ValueError("SAM3 共享 owner 至少需要两个能力视图")
        trunks = tuple(
            model.image_encoder.vision_backbone.trunk for model in models
        )
        if any(trunk is not trunks[0] for trunk in trunks[1:]):
            raise ValueError("SAM3 共享 owner 必须引用同一个 ViT trunk")
        self.interactive_model = interactive_model
        self.semantic_model = semantic_model
        self.multiplex_model = multiplex_model
        self._shared_trunk = trunks[0]
        self.feature_cache = Sam3SharedTrunkFeatureCache()
        self._closed = False

    @property
    def shared_trunk(self) -> nn.Module:
        """返回唯一共享的视觉 trunk。"""

        return self._shared_trunk

    def diagnostics(self) -> dict[str, object]:
        """返回可用于 runtime 健康信息的资源摘要。"""

        unique_parameters = {
            id(parameter): parameter for parameter in self.parameters()
        }
        capability_views = [
            capability
            for capability, model in (
                ("interactive", self.interactive_model),
                ("semantic", self.semantic_model),
                ("multiplex-propagation", self.multiplex_model),
            )
            if model is not None
        ]
        trunk_views = [
            model.image_encoder.vision_backbone.trunk
            for model in (
                self.interactive_model,
                self.semantic_model,
                self.multiplex_model,
            )
            if model is not None
        ]
        return {
            "owner_kind": "shared-vit-trunk",
            "model_instance_count": 1,
            "capability_views": capability_views,
            "shared_trunk_identity": id(self.shared_trunk),
            "unique_parameter_count": sum(
                parameter.numel() for parameter in unique_parameters.values()
            ),
            "all_trunk_views_shared": all(
                trunk is self.shared_trunk for trunk in trunk_views
            ),
            "feature_cache": self.feature_cache.diagnostics(),
        }

    def close(self) -> None:
        """一次性把共享 owner 移回 CPU 并释放 CUDA allocator 缓存。"""

        if self._closed:
            return
        self.feature_cache.clear()
        release_rotary_device_caches(self)
        self.to(device=torch.device("cpu"))
        self._closed = True
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def build_sam3_shared_model_owner(
    *,
    checkpoint_path: Path,
    requested_device_name: str,
    precision: str,
    checkpoint_branches: Sam3CheckpointBranches,
    include_interactive: bool = True,
    include_semantic: bool = True,
    include_multiplex: bool = False,
) -> Sam3SharedOwnerBuildResult:
    """从一次 checkpoint 读取构造共享 ViT 的能力模型。"""

    resolved_device_name = resolve_execution_device_name(
        torch_module=torch,
        requested_device_name=_resolve_requested_device_name(requested_device_name),
    )
    enable_pytorch_cuda_inference_fast_path(
        torch_module=torch,
        device_name=resolved_device_name,
    )
    runtime_torch_dtype = _resolve_runtime_torch_dtype(
        device_name=resolved_device_name,
        precision=precision,
    )

    shared_trunk = build_sam3_vit_trunk()
    interactive_model = (
        Sam3InteractiveImageModel(shared_trunk=shared_trunk)
        if include_interactive
        else None
    )
    semantic_model = (
        Sam3SemanticImageModel(shared_trunk=shared_trunk)
        if include_semantic
        else None
    )
    multiplex_model = (
        Sam3MultiplexPropagationModel(shared_trunk=shared_trunk)
        if include_multiplex
        else None
    )
    compatibility_summary: dict[str, object] = {}
    if interactive_model is not None:
        compatibility_summary["interactive"] = _load_interactive_state_dict(
            interactive_model,
            build_sam3_interactive_state_dict(checkpoint_branches),
            checkpoint_path=checkpoint_path,
        )
    if semantic_model is not None:
        compatibility_summary["semantic"] = _load_semantic_state_dict(
            semantic_model,
            build_sam3_semantic_state_dict(checkpoint_branches),
            checkpoint_path=checkpoint_path,
        )
    if multiplex_model is not None:
        compatibility_summary["multiplex"] = (
            load_sam3_multiplex_propagation_weights(
                model=multiplex_model,
                checkpoint_path=checkpoint_path,
                checkpoint_branches=checkpoint_branches,
            )
        )

    owner = Sam3SharedModelOwner(
        interactive_model=interactive_model,
        semantic_model=semantic_model,
        multiplex_model=multiplex_model,
    )
    owner.eval()
    owner.to(
        device=torch.device(resolved_device_name),
        dtype=runtime_torch_dtype,
    )
    diagnostics = owner.diagnostics()
    if diagnostics["all_trunk_views_shared"] is not True:
        owner.close()
        raise RuntimeError("SAM3 共享 ViT trunk 验证失败")
    compatibility_summary["owner"] = diagnostics
    return Sam3SharedOwnerBuildResult(
        owner=owner,
        resolved_device_name=resolved_device_name,
        runtime_torch_dtype=runtime_torch_dtype,
        compatibility_summary=compatibility_summary,
    )


__all__ = [
    "Sam3SharedModelOwner",
    "Sam3SharedOwnerBuildResult",
    "build_sam3_shared_model_owner",
]
