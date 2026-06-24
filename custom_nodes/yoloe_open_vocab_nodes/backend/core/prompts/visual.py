"""YOLOE visual prompt 张量构建。"""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from backend.service.application.errors import InvalidRequestError


def build_visual_prompt_tensor(
    *,
    torch_module: Any,
    np_module: Any,
    prompts: tuple[Any, ...],
    input_size: tuple[int, int],
    resize_ratio: float,
    prompt_image_width: int,
    prompt_image_height: int,
    device_name: str,
    dtype: torch.dtype,
) -> torch.Tensor:
    """把多种视觉提示统一转成 SAVPE 可消费的视觉提示张量。"""

    input_height, input_width = (int(input_size[0]), int(input_size[1]))
    visual_height = max(1, input_height // 8)
    visual_width = max(1, input_width // 8)
    full_resolution_tensor = torch_module.zeros(
        (1, len(prompts), input_height, input_width),
        device=device_name,
        dtype=dtype,
    )
    for index, item in enumerate(prompts):
        prompt_mask = _build_visual_prompt_mask(
            np_module=np_module,
            item=item,
            prompt_image_width=prompt_image_width,
            prompt_image_height=prompt_image_height,
        )
        if prompt_mask is None or int(np_module.count_nonzero(prompt_mask)) <= 0:
            continue
        prompt_tensor = torch_module.from_numpy(
            np_module.asarray(prompt_mask, dtype=np_module.float32),
        ).to(device=device_name, dtype=dtype)
        resized_width = max(1, min(input_width, int(round(prompt_image_width * float(resize_ratio)))))
        resized_height = max(1, min(input_height, int(round(prompt_image_height * float(resize_ratio)))))
        prompt_tensor = F.interpolate(
            prompt_tensor.unsqueeze(0).unsqueeze(0),
            size=(resized_height, resized_width),
            mode="nearest",
        )[0, 0]
        full_resolution_tensor[0, index, :resized_height, :resized_width] = prompt_tensor
    visual_tensor = F.max_pool2d(full_resolution_tensor, kernel_size=8, stride=8)
    if int(visual_tensor.shape[-2]) != visual_height or int(visual_tensor.shape[-1]) != visual_width:
        visual_tensor = F.interpolate(
            visual_tensor,
            size=(visual_height, visual_width),
            mode="nearest",
        )
    return visual_tensor


def _build_visual_prompt_mask(
    *,
    np_module: Any,
    item: Any,
    prompt_image_width: int,
    prompt_image_height: int,
) -> Any:
    """把单条视觉提示转换成参考图尺寸的二值 mask。"""

    prompt_mask = np_module.zeros((int(prompt_image_height), int(prompt_image_width)), dtype=np_module.uint8)
    if getattr(item, "prompt_mask", None) is not None:
        normalized_prompt_mask = np_module.asarray(item.prompt_mask, dtype=np_module.uint8)
        if normalized_prompt_mask.ndim != 2:
            return prompt_mask
        if (
            int(normalized_prompt_mask.shape[0]) != int(prompt_image_height)
            or int(normalized_prompt_mask.shape[1]) != int(prompt_image_width)
        ):
            raise InvalidRequestError(
                "YOLOE visual prompt mask 尺寸与 prompt_image 不一致",
                details={
                    "prompt_kind": getattr(item, "prompt_kind", None),
                    "prompt_mask_shape": [
                        int(normalized_prompt_mask.shape[0]),
                        int(normalized_prompt_mask.shape[1]),
                    ],
                    "prompt_image_size": [int(prompt_image_width), int(prompt_image_height)],
                },
            )
        return (normalized_prompt_mask > 0).astype(np_module.uint8)
    if getattr(item, "prompt_kind", "") == "box" and getattr(item, "bbox_xyxy", None) is not None:
        x1_value, y1_value, x2_value, y2_value = item.bbox_xyxy
        x1_index = max(0, min(int(prompt_image_width), int(np.floor(float(x1_value)))))
        y1_index = max(0, min(int(prompt_image_height), int(np.floor(float(y1_value)))))
        x2_index = max(x1_index + 1, min(int(prompt_image_width), int(np.ceil(float(x2_value)))))
        y2_index = max(y1_index + 1, min(int(prompt_image_height), int(np.ceil(float(y2_value)))))
        if x2_index <= x1_index or y2_index <= y1_index:
            return prompt_mask
        prompt_mask[y1_index:y2_index, x1_index:x2_index] = 1
        return prompt_mask
    if getattr(item, "prompt_kind", "") == "point" and getattr(item, "point_xy", None) is not None:
        point_x_value, point_y_value = item.point_xy
        point_x_index = max(0, min(int(prompt_image_width) - 1, int(round(float(point_x_value)))))
        point_y_index = max(0, min(int(prompt_image_height) - 1, int(round(float(point_y_value)))))
        radius = max(1, int(round(min(prompt_image_width, prompt_image_height) / 64.0)))
        x1_index = max(0, point_x_index - radius)
        y1_index = max(0, point_y_index - radius)
        x2_index = min(int(prompt_image_width), point_x_index + radius + 1)
        y2_index = min(int(prompt_image_height), point_y_index + radius + 1)
        prompt_mask[y1_index:y2_index, x1_index:x2_index] = 1
        return prompt_mask
    return prompt_mask


__all__ = [
    "build_visual_prompt_tensor",
]
