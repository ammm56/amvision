"""YOLOE visual prompt embedding helper。"""

from __future__ import annotations

from typing import Any

import torch

from backend.service.application.errors import InvalidRequestError
from custom_nodes.yoloe_open_vocab_nodes.backend.core.nn.models import (
    YoloeTextPromptSegmentationHead,
    YoloeTextPromptSegmentationModel,
)


def forward_with_class_embeddings(
    *,
    model: YoloeTextPromptSegmentationModel,
    input_tensor: torch.Tensor,
    class_embeddings: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """执行一次带类别 embedding 的 YOLOE segmentation 前向。"""

    prediction = model(input_tensor, class_embeddings)
    if not isinstance(prediction, tuple) or len(prediction) != 2:
        raise InvalidRequestError("YOLOE segmentation 头输出格式不合法")
    prediction_tensor, proto_tensor = prediction
    if not torch.is_tensor(prediction_tensor) or not torch.is_tensor(proto_tensor):
        raise InvalidRequestError("YOLOE segmentation 头输出张量类型不合法")
    return prediction_tensor, proto_tensor


def extract_visual_prompt_embeddings(
    *,
    model: YoloeTextPromptSegmentationModel,
    prompt_input_tensor: torch.Tensor,
    visual_prompt_tensor: torch.Tensor,
) -> torch.Tensor:
    """从 prompt image 与视觉提示 mask 中提取 visual prompt embedding。"""

    outputs: list[Any] = []
    current: Any = prompt_input_tensor
    for layer in model.model:
        from_index = getattr(layer, "from_index", -1)
        if isinstance(from_index, tuple):
            layer_input = [current if index == -1 else outputs[index] for index in from_index]
        else:
            layer_input = current if from_index == -1 else outputs[from_index]
        if isinstance(layer, YoloeTextPromptSegmentationHead):
            return layer.get_vpe(layer_input, visual_prompt_tensor)
        current = layer(layer_input)
        outputs.append(current)
    raise InvalidRequestError("YOLOE visual-prompt 无法从模型中提取 visual embedding")


__all__ = [
    "extract_visual_prompt_embeddings",
    "forward_with_class_embeddings",
]
