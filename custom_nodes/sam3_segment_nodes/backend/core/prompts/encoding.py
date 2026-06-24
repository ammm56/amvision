"""SAM3 interactive prompt 编码。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import torch
import torch.nn.functional as F


class Sam3InteractivePromptLike(Protocol):
    """描述 SAM3 interactive prompt 最小字段协议。"""

    prompt_id: str
    prompt_kind: str
    display_name: str
    bbox_xyxy: tuple[float, float, float, float] | None
    point_xy: tuple[float, float] | None
    point_label: str | None
    prompt_mask: object | None


SAM3_POSITIVE_POINT_LABEL = 1
SAM3_NEGATIVE_POINT_LABEL = 0
SAM3_BOX_TOP_LEFT_LABEL = 2
SAM3_BOX_BOTTOM_RIGHT_LABEL = 3
SAM3_PADDING_LABEL = -1


@dataclass(frozen=True)
class PreparedSam3InteractivePrompts:
    """描述已编码完成的 SAM3 interactive prompt 张量。"""

    point_coords: torch.Tensor | None
    point_labels: torch.Tensor | None
    prompt_masks: torch.Tensor | None
    prompt_ids: tuple[str, ...]
    prompt_kinds: tuple[str, ...]


def build_sam3_interactive_prompt_tensors(
    prompt_items: tuple[Sam3InteractivePromptLike, ...],
    *,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    mask_prompt_width: int | None = None,
    mask_prompt_height: int | None = None,
    device: torch.device | str = "cpu",
    prompt_mask_dtype: torch.dtype = torch.float32,
) -> PreparedSam3InteractivePrompts:
    """把当前阶段交互 prompt 转换为 tracker 需要的张量。"""

    scale_x = target_width / float(source_width)
    scale_y = target_height / float(source_height)

    point_coord_items: list[list[list[float]]] = []
    point_label_items: list[list[int]] = []
    prompt_mask_items: list[torch.Tensor | None] = []
    prompt_ids: list[str] = []
    prompt_kinds: list[str] = []
    max_prompt_length = 0
    contains_dense_mask_prompt = False

    for item in prompt_items:
        prompt_ids.append(item.prompt_id)
        prompt_kinds.append(item.prompt_kind)
        if item.prompt_kind == "box":
            assert item.bbox_xyxy is not None
            x1_value, y1_value, x2_value, y2_value = item.bbox_xyxy
            point_coord_items.append(
                [
                    [float(x1_value) * scale_x, float(y1_value) * scale_y],
                    [float(x2_value) * scale_x, float(y2_value) * scale_y],
                ]
            )
            point_label_items.append(
                [
                    SAM3_BOX_TOP_LEFT_LABEL,
                    SAM3_BOX_BOTTOM_RIGHT_LABEL,
                ]
            )
            prompt_mask_items.append(None)
            max_prompt_length = max(max_prompt_length, 2)
            continue

        if item.prompt_kind == "point":
            assert item.point_xy is not None
            assert item.point_label is not None
            point_x, point_y = item.point_xy
            point_coord_items.append([[float(point_x) * scale_x, float(point_y) * scale_y]])
            point_label_items.append(
                [SAM3_POSITIVE_POINT_LABEL if item.point_label == "positive" else SAM3_NEGATIVE_POINT_LABEL]
            )
            prompt_mask_items.append(None)
            max_prompt_length = max(max_prompt_length, 1)
            continue

        if item.prompt_kind in {"polygon", "mask"}:
            if mask_prompt_width is None or mask_prompt_height is None:
                raise ValueError("mask 类 prompt 编码要求显式提供 mask_prompt_width 与 mask_prompt_height")
            prompt_mask = getattr(item, "prompt_mask", None)
            if prompt_mask is None:
                raise ValueError(f"{item.prompt_kind} prompt 缺少 prompt_mask")
            point_coord_items.append([])
            point_label_items.append([])
            prompt_mask_items.append(
                _build_resized_prompt_mask_tensor(
                    prompt_mask,
                    width=mask_prompt_width,
                    height=mask_prompt_height,
                    device=device,
                    dtype=prompt_mask_dtype,
                )
            )
            contains_dense_mask_prompt = True
            continue

        raise ValueError(f"暂不支持的 SAM3 interactive prompt_kind: {item.prompt_kind}")

    point_coords: torch.Tensor | None = None
    point_labels: torch.Tensor | None = None
    if max_prompt_length > 0:
        padded_coord_items: list[list[list[float]]] = []
        padded_label_items: list[list[int]] = []
        for coords, labels in zip(point_coord_items, point_label_items, strict=False):
            padded_coords = list(coords)
            padded_labels = list(labels)
            while len(padded_coords) < max_prompt_length:
                padded_coords.append([0.0, 0.0])
                padded_labels.append(SAM3_PADDING_LABEL)
            padded_coord_items.append(padded_coords)
            padded_label_items.append(padded_labels)

        point_coords = torch.tensor(padded_coord_items, dtype=torch.float32, device=device)
        point_labels = torch.tensor(padded_label_items, dtype=torch.int32, device=device)

    prompt_masks: torch.Tensor | None = None
    if contains_dense_mask_prompt:
        if len(prompt_items) != 1:
            raise ValueError("当前阶段的 polygon/mask prompt 编码要求逐条处理，不支持在同一次编码中混合多条 prompt")
        prompt_mask_tensor = prompt_mask_items[0]
        if prompt_mask_tensor is None:
            raise ValueError("mask 类 prompt 编码缺少有效 prompt_mask 张量")
        prompt_masks = prompt_mask_tensor

    return PreparedSam3InteractivePrompts(
        point_coords=point_coords,
        point_labels=point_labels,
        prompt_masks=prompt_masks,
        prompt_ids=tuple(prompt_ids),
        prompt_kinds=tuple(prompt_kinds),
    )


def _build_resized_prompt_mask_tensor(
    prompt_mask: object,
    *,
    width: int,
    height: int,
    device: torch.device | str,
    dtype: torch.dtype,
) -> torch.Tensor:
    """把源图分辨率 prompt mask 规整为 PromptEncoder 所需大小。"""

    mask_tensor = torch.as_tensor(prompt_mask, dtype=torch.float32, device=device)
    if mask_tensor.ndim != 2:
        raise ValueError(f"prompt_mask 期望二维数组，实际得到 {tuple(mask_tensor.shape)}")
    mask_tensor = (mask_tensor > 0).to(dtype=torch.float32).unsqueeze(0).unsqueeze(0)
    resized_mask = F.interpolate(mask_tensor, size=(height, width), mode="nearest")
    return resized_mask.to(dtype=dtype)
