"""项目内 YOLOX 兼容性辅助。"""

from __future__ import annotations

import torch


_TORCH_VER = [int(part) for part in torch.__version__.split(".")[:2]]


def meshgrid(*tensors):
    """兼容不同 torch 版本的 meshgrid 行为。"""

    if _TORCH_VER >= [1, 10]:
        return torch.meshgrid(*tensors, indexing="ij")
    return torch.meshgrid(*tensors)