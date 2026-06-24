"""YOLOE text prompt 特征聚合 helper。"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F

from backend.service.application.errors import InvalidRequestError


def build_grouped_text_features(
    *,
    text_features: torch.Tensor,
    prompt_text_offsets: tuple[tuple[int, int, int], ...],
    negative_prompt_weight: float,
) -> torch.Tensor:
    """按 prompt 组聚合文本特征，并把负文本作为抑制项并入类别原型。"""

    grouped_features: list[torch.Tensor] = []
    for positive_start, positive_count, negative_count in prompt_text_offsets:
        positive_end = positive_start + positive_count
        positive_features = text_features[positive_start:positive_end]
        if int(positive_features.shape[0]) <= 0:
            raise InvalidRequestError("YOLOE text-prompt 组内缺少 positive 文本特征")
        positive_feature = F.normalize(positive_features.mean(dim=0, keepdim=False), dim=0, p=2)
        if negative_count > 0:
            negative_start = positive_end
            negative_end = negative_start + negative_count
            negative_features = text_features[negative_start:negative_end]
            negative_feature = F.normalize(negative_features.mean(dim=0, keepdim=False), dim=0, p=2)
            positive_feature = F.normalize(
                positive_feature - float(negative_prompt_weight) * negative_feature,
                dim=0,
                p=2,
            )
        grouped_features.append(positive_feature)
    return torch.stack(grouped_features, dim=0)


def build_group_source_prompt_text(group: Any) -> str:
    """为检测结果和 region 结果构造可追溯的文本组合摘要。"""

    positive_segment = " | ".join(str(item) for item in group.positive_texts)
    if not group.negative_texts:
        return positive_segment
    negative_segment = " | ".join(f"!{item}" for item in group.negative_texts)
    return f"{positive_segment} || {negative_segment}"


__all__ = [
    "build_group_source_prompt_text",
    "build_grouped_text_features",
]
