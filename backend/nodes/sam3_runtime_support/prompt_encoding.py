"""SAM3 interactive prompt 编码。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import torch


class Sam3InteractivePromptLike(Protocol):
    """描述 SAM3 interactive prompt 最小字段协议。"""

    prompt_id: str
    prompt_kind: str
    display_name: str
    bbox_xyxy: tuple[float, float, float, float] | None
    point_xy: tuple[float, float] | None
    point_label: str | None


SAM3_POSITIVE_POINT_LABEL = 1
SAM3_NEGATIVE_POINT_LABEL = 0
SAM3_BOX_TOP_LEFT_LABEL = 2
SAM3_BOX_BOTTOM_RIGHT_LABEL = 3
SAM3_PADDING_LABEL = -1


@dataclass(frozen=True)
class PreparedSam3InteractivePrompts:
    """描述已编码完成的 SAM3 interactive prompt 张量。"""

    point_coords: torch.Tensor
    point_labels: torch.Tensor
    prompt_ids: tuple[str, ...]
    prompt_kinds: tuple[str, ...]


def build_sam3_interactive_prompt_tensors(
    prompt_items: tuple[Sam3InteractivePromptLike, ...],
    *,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    device: torch.device | str = "cpu",
) -> PreparedSam3InteractivePrompts:
    """把第一阶段 box/point prompt 转换为 tracker 需要的 points/labels。"""

    scale_x = target_width / float(source_width)
    scale_y = target_height / float(source_height)

    point_coord_items: list[list[list[float]]] = []
    point_label_items: list[list[int]] = []
    prompt_ids: list[str] = []
    prompt_kinds: list[str] = []
    max_prompt_length = 0

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
            max_prompt_length = max(max_prompt_length, 2)
            continue

        assert item.point_xy is not None
        assert item.point_label is not None
        point_x, point_y = item.point_xy
        point_coord_items.append([[float(point_x) * scale_x, float(point_y) * scale_y]])
        point_label_items.append(
            [SAM3_POSITIVE_POINT_LABEL if item.point_label == "positive" else SAM3_NEGATIVE_POINT_LABEL]
        )
        max_prompt_length = max(max_prompt_length, 1)

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
    return PreparedSam3InteractivePrompts(
        point_coords=point_coords,
        point_labels=point_labels,
        prompt_ids=tuple(prompt_ids),
        prompt_kinds=tuple(prompt_kinds),
    )
