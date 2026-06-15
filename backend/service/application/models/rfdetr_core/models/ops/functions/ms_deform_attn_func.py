"""RF-DETR core 模型结构模块：`models.ops.functions.ms_deform_attn_func`。"""

from __future__ import absolute_import, division, print_function

import torch

from backend.service.application.models.rfdetr_core.utilities.tensors import _bilinear_grid_sample


def ms_deform_attn_core_pytorch(
    value: torch.Tensor,
    value_spatial_shapes: torch.Tensor,
    sampling_locations: torch.Tensor,
    attention_weights: torch.Tensor,
    value_spatial_shapes_hw: list[tuple[int, int]] | None = None,
) -> torch.Tensor:
    """执行 `ms_deform_attn_core_pytorch`。
    
    参数：
    - `value`：传入的 `value` 参数。
    - `value_spatial_shapes`：传入的 `value_spatial_shapes` 参数。
    - `sampling_locations`：传入的 `sampling_locations` 参数。
    - `attention_weights`：传入的 `attention_weights` 参数。
    - `value_spatial_shapes_hw`：传入的 `value_spatial_shapes_hw` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    batch_size, n_heads, head_dim, _ = value.shape
    _, len_query, n_heads, num_levels, num_points, _ = sampling_locations.shape
    shapes = value_spatial_shapes_hw if value_spatial_shapes_hw is not None else value_spatial_shapes
    value_list = value.split([height * width for height, width in shapes], dim=3)
    sampling_grids = 2 * sampling_locations - 1
    sampling_value_list = []
    for level_index, (height, width) in enumerate(shapes):
        value_l_ = value_list[level_index].view(batch_size * n_heads, head_dim, height, width)
        sampling_grid_l_ = sampling_grids[:, :, :, level_index].transpose(1, 2).flatten(0, 1)
        sampling_value_l_ = _bilinear_grid_sample(value_l_, sampling_grid_l_, padding_mode="zeros", align_corners=False)
        sampling_value_list.append(sampling_value_l_)
    attention_weights = attention_weights.transpose(1, 2).reshape(
        batch_size * n_heads, 1, len_query, num_levels * num_points
    )
    sampling_value_list = torch.stack(sampling_value_list, dim=-2).flatten(-2)
    output = (sampling_value_list * attention_weights).sum(-1).view(batch_size, n_heads * head_dim, len_query)
    return output.transpose(1, 2).contiguous()
