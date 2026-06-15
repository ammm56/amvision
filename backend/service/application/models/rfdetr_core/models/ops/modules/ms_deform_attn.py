"""RF-DETR core 模型结构模块：`models.ops.modules.ms_deform_attn`。"""

from __future__ import absolute_import, division, print_function

import math
import warnings

import torch
import torch.nn.functional as F  # noqa: N812
from torch import nn
from torch.nn.init import constant_, xavier_uniform_

from backend.service.application.models.rfdetr_core.models.ops.functions import ms_deform_attn_core_pytorch


def _is_power_of_2(n):
    if (not isinstance(n, int)) or (n < 0):
        raise ValueError("invalid input for _is_power_of_2: {} (type: {})".format(n, type(n)))
    return (n & (n - 1) == 0) and n != 0


class MSDeformAttn(nn.Module):
    """RF-DETR core 类：`MSDeformAttn`。"""

    def __init__(self, d_model=256, n_levels=4, n_heads=8, n_points=4):
        """执行 `__init__`。
        
        参数：
        - `d_model`：传入的 `d_model` 参数。
        - `n_levels`：传入的 `n_levels` 参数。
        - `n_heads`：传入的 `n_heads` 参数。
        - `n_points`：传入的 `n_points` 参数。
        """
        super().__init__()
        if d_model % n_heads != 0:
            raise ValueError("d_model must be divisible by n_heads, but got {} and {}".format(d_model, n_heads))
        _d_per_head = d_model // n_heads
        if not _is_power_of_2(_d_per_head):
            warnings.warn(
                "You'd better set d_model in MSDeformAttn to make the"
                " dimension of each attention head a power of 2"
                " which is more efficient in our CUDA implementation."
            )

        self.im2col_step = 64

        self.d_model = d_model
        self.n_levels = n_levels
        self.n_heads = n_heads
        self.n_points = n_points

        self.sampling_offsets = nn.Linear(d_model, n_heads * n_levels * n_points * 2)
        self.attention_weights = nn.Linear(d_model, n_heads * n_levels * n_points)
        self.value_proj = nn.Linear(d_model, d_model)
        self.output_proj = nn.Linear(d_model, d_model)

        self._reset_parameters()

        self._export = False

    def export(self):
        """切换到导出模式。"""
        self._export = True

    def _reset_parameters(self):
        constant_(self.sampling_offsets.weight.data, 0.0)
        thetas = torch.arange(self.n_heads, dtype=torch.float32) * (2.0 * math.pi / self.n_heads)
        grid_init = torch.stack([thetas.cos(), thetas.sin()], -1)
        grid_init = (
            (grid_init / grid_init.abs().max(-1, keepdim=True)[0])
            .view(self.n_heads, 1, 1, 2)
            .repeat(1, self.n_levels, self.n_points, 1)
        )
        for i in range(self.n_points):
            grid_init[:, :, i, :] *= i + 1
        with torch.no_grad():
            self.sampling_offsets.bias = nn.Parameter(grid_init.view(-1))
        constant_(self.attention_weights.weight.data, 0.0)
        constant_(self.attention_weights.bias.data, 0.0)
        xavier_uniform_(self.value_proj.weight.data)
        constant_(self.value_proj.bias.data, 0.0)
        xavier_uniform_(self.output_proj.weight.data)
        constant_(self.output_proj.bias.data, 0.0)

    def forward(
        self,
        query,
        reference_points,
        input_flatten,
        input_spatial_shapes,
        input_level_start_index,
        input_padding_mask=None,
        input_spatial_shapes_hw: list[tuple[int, int]] | None = None,
    ):
        """执行 `forward`。
        
        参数：
        - `query`：传入的 `query` 参数。
        - `reference_points`：传入的 `reference_points` 参数。
        - `input_flatten`：传入的 `input_flatten` 参数。
        - `input_spatial_shapes`：传入的 `input_spatial_shapes` 参数。
        - `input_level_start_index`：传入的 `input_level_start_index` 参数。
        - `input_padding_mask`：传入的 `input_padding_mask` 参数。
        - `input_spatial_shapes_hw`：传入的 `input_spatial_shapes_hw` 参数。
        """
        batch_size, len_query, _ = query.shape
        batch_size, len_input, _ = input_flatten.shape
        error_msg = "input_spatial_shapes must match the flattened input length"
        if input_spatial_shapes_hw is not None:
            expected_len_in = sum(int(height) * int(width) for height, width in input_spatial_shapes_hw)
            if expected_len_in != len_input:
                raise ValueError(error_msg)
        else:
            expected_len_in = (input_spatial_shapes[:, 0] * input_spatial_shapes[:, 1]).sum()
            if self._export:
                torch._assert(expected_len_in == len_input, error_msg)
            else:
                assert expected_len_in == len_input, error_msg

        value = self.value_proj(input_flatten)
        if input_padding_mask is not None:
            value = value.masked_fill(input_padding_mask[..., None], float(0))

        sampling_offsets = self.sampling_offsets(query).view(
            batch_size, len_query, self.n_heads, self.n_levels, self.n_points, 2
        )
        attention_weights = self.attention_weights(query).view(
            batch_size, len_query, self.n_heads, self.n_levels * self.n_points
        )

        if reference_points.shape[-1] == 2:
            offset_normalizer = torch.stack([input_spatial_shapes[..., 1], input_spatial_shapes[..., 0]], -1)
            sampling_locations = (
                reference_points[:, :, None, :, None, :]
                + sampling_offsets / offset_normalizer[None, None, None, :, None, :]
            )
        elif reference_points.shape[-1] == 4:
            sampling_locations = (
                reference_points[:, :, None, :, None, :2]
                + sampling_offsets / self.n_points * reference_points[:, :, None, :, None, 2:] * 0.5
            )
        else:
            raise ValueError(
                "Last dim of reference_points must be 2 or 4, but get {} instead.".format(reference_points.shape[-1])
            )
        attention_weights = F.softmax(attention_weights, -1)

        value = (
            value.transpose(1, 2).contiguous().view(batch_size, self.n_heads, self.d_model // self.n_heads, len_input)
        )
        output = ms_deform_attn_core_pytorch(
            value,
            input_spatial_shapes,
            sampling_locations,
            attention_weights,
            value_spatial_shapes_hw=input_spatial_shapes_hw,
        )
        output = self.output_proj(output)
        return output
