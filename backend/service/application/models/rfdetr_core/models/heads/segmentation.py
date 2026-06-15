from typing import Any, Callable

import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812

from backend.service.application.models.rfdetr_core.utilities.tensors import _bilinear_grid_sample


class _DepthwiseConvWithoutCuDNN(torch.autograd.Function):
    """RF-DETR core 类：`_DepthwiseConvWithoutCuDNN`。"""

    @staticmethod
    def forward(
        ctx: torch.autograd.function.FunctionCtx,
        x: torch.Tensor,
        weight: torch.Tensor,
        bias: torch.Tensor | None,
        stride: tuple[int, ...],
        padding: tuple[int, ...],
        dilation: tuple[int, ...],
        groups: int,
    ) -> torch.Tensor:
        """执行 `forward`。
        
        参数：
        - `ctx`：传入的 `ctx` 参数。
        - `x`：传入的 `x` 参数。
        - `weight`：传入的 `weight` 参数。
        - `bias`：传入的 `bias` 参数。
        - `stride`：传入的 `stride` 参数。
        - `padding`：传入的 `padding` 参数。
        - `dilation`：传入的 `dilation` 参数。
        - `groups`：传入的 `groups` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        ctx.save_for_backward(x, weight)
        ctx.has_bias = bias is not None
        ctx.stride = stride
        ctx.padding = padding
        ctx.dilation = dilation
        ctx.groups = groups
        with torch.backends.cudnn.flags(enabled=False):
            return F.conv2d(x, weight, bias, stride=stride, padding=padding, dilation=dilation, groups=groups)

    @staticmethod
    def backward(
        ctx: torch.autograd.function.FunctionCtx,
        grad_output: torch.Tensor,
    ) -> tuple[torch.Tensor | None, torch.Tensor | None, torch.Tensor | None, None, None, None, None]:
        """执行 `backward`。
        
        参数：
        - `ctx`：传入的 `ctx` 参数。
        - `grad_output`：传入的 `grad_output` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        x, weight = ctx.saved_tensors
        input_dtype = x.dtype

        needs_x_grad = ctx.needs_input_grad[0]
        needs_w_grad = ctx.needs_input_grad[1]
        needs_b_grad = ctx.has_bias and ctx.needs_input_grad[2]

        grad_input = None
        grad_weight = None
        grad_bias = None

        if needs_x_grad or needs_w_grad:
            grad_output_cast = grad_output.to(dtype=weight.dtype)
            with torch.backends.cudnn.flags(enabled=False):
                if needs_x_grad:
                    grad_input = torch.nn.grad.conv2d_input(
                        x.shape,
                        weight,
                        grad_output_cast,
                        stride=ctx.stride,
                        padding=ctx.padding,
                        dilation=ctx.dilation,
                        groups=ctx.groups,
                    ).to(dtype=input_dtype)
                if needs_w_grad:
                    grad_weight = torch.nn.grad.conv2d_weight(
                        x.to(dtype=weight.dtype),
                        weight.shape,
                        grad_output_cast,
                        stride=ctx.stride,
                        padding=ctx.padding,
                        dilation=ctx.dilation,
                        groups=ctx.groups,
                    )

        if needs_b_grad:
            grad_bias = grad_output.to(dtype=weight.dtype).sum(dim=(0, 2, 3))

        return grad_input, grad_weight, grad_bias, None, None, None, None


class DepthwiseConvBlock(nn.Module):
    """RF-DETR core 类：`DepthwiseConvBlock`。"""

    def __init__(self, dim, layer_scale_init_value=0):
        super().__init__()
        self.dwconv = nn.Conv2d(dim, dim, kernel_size=3, padding=1, groups=dim)
        self.norm = nn.LayerNorm(dim, eps=1e-6)
        self.pwconv1 = nn.Linear(dim, dim)
        self.act = nn.GELU()
        self.gamma = (
            nn.Parameter(layer_scale_init_value * torch.ones((dim)), requires_grad=True)
            if layer_scale_init_value > 0
            else None
        )

    def _depthwise_conv(self, x: torch.Tensor) -> torch.Tensor:
        return _DepthwiseConvWithoutCuDNN.apply(
            x,
            self.dwconv.weight,
            self.dwconv.bias,
            self.dwconv.stride,
            self.dwconv.padding,
            self.dwconv.dilation,
            self.dwconv.groups,
        )

    def forward(self, x):
        input = x
        x = self._depthwise_conv(x)
        x = x.permute(0, 2, 3, 1)
        x = self.norm(x)
        x = self.pwconv1(x)
        x = self.act(x)
        if self.gamma is not None:
            x = self.gamma * x
        x = x.permute(0, 3, 1, 2)

        return x + input


class MLPBlock(nn.Module):
    def __init__(self, dim, layer_scale_init_value=0):
        super().__init__()
        self.norm_in = nn.LayerNorm(dim)
        self.layers = nn.ModuleList(
            [
                nn.Linear(dim, dim * 4),
                nn.GELU(),
                nn.Linear(dim * 4, dim),
            ]
        )
        self.gamma = (
            nn.Parameter(layer_scale_init_value * torch.ones((dim)), requires_grad=True)
            if layer_scale_init_value > 0
            else None
        )

    def forward(self, x):
        input = x
        x = self.norm_in(x)
        for layer in self.layers:
            x = layer(x)
        if self.gamma is not None:
            x = self.gamma * x
        return x + input


class SegmentationHead(nn.Module):
    def __init__(self, in_dim, num_blocks: int, bottleneck_ratio: int = 1, downsample_ratio: int = 4):
        super().__init__()

        self.downsample_ratio = downsample_ratio
        self.interaction_dim = in_dim // bottleneck_ratio if bottleneck_ratio is not None else in_dim
        self.blocks = nn.ModuleList([DepthwiseConvBlock(in_dim) for _ in range(num_blocks)])
        self.spatial_features_proj = (
            nn.Identity() if bottleneck_ratio is None else nn.Conv2d(in_dim, self.interaction_dim, kernel_size=1)
        )

        self.query_features_block = MLPBlock(in_dim)
        self.query_features_proj = (
            nn.Identity() if bottleneck_ratio is None else nn.Linear(in_dim, self.interaction_dim)
        )

        self.bias = nn.Parameter(torch.zeros(1), requires_grad=True)

        self._export = False

    def export(self):
        self._export = True
        self._forward_origin = self.forward
        self.forward = self.forward_export
        for name, m in self.named_modules():
            if hasattr(m, "export") and isinstance(m.export, Callable) and hasattr(m, "_export") and not m._export:
                m.export()

    def forward(
        self,
        spatial_features: torch.Tensor,
        query_features: list[torch.Tensor],
        image_size: tuple[int, int],
        skip_blocks: bool = False,
    ) -> list[torch.Tensor]:
        target_size = (image_size[0] // self.downsample_ratio, image_size[1] // self.downsample_ratio)
        spatial_features = F.interpolate(spatial_features, size=target_size, mode="bilinear", align_corners=False)

        mask_logits = []
        if not skip_blocks:
            for block, qf in zip(self.blocks, query_features):
                spatial_features = block(spatial_features)
                spatial_features_proj = self.spatial_features_proj(spatial_features)
                qf = self.query_features_proj(self.query_features_block(qf))
                mask_logits.append(torch.einsum("bchw,bnc->bnhw", spatial_features_proj, qf) + self.bias)
        else:
            assert len(query_features) == 1, "skip_blocks is only supported for length 1 query features"
            qf = self.query_features_proj(self.query_features_block(query_features[0]))
            mask_logits.append(torch.einsum("bchw,bnc->bnhw", spatial_features, qf) + self.bias)

        return mask_logits

    def sparse_forward(
        self,
        spatial_features: torch.Tensor,
        query_features: list[torch.Tensor],
        image_size: tuple[int, int],
        skip_blocks: bool = False,
    ) -> list[torch.Tensor]:
        target_size = (image_size[0] // self.downsample_ratio, image_size[1] // self.downsample_ratio)
        spatial_features = F.interpolate(spatial_features, size=target_size, mode="bilinear", align_corners=False)


        output_dicts = []

        if not skip_blocks:
            for block, qf in zip(self.blocks, query_features):
                spatial_features = block(spatial_features)
                spatial_features_proj = self.spatial_features_proj(spatial_features)
                qf = self.query_features_proj(self.query_features_block(qf))

                output_dicts.append(
                    {
                        "spatial_features": spatial_features_proj,
                        "query_features": qf,
                        "bias": self.bias,
                    }
                )
        else:
            assert len(query_features) == 1, "skip_blocks is only supported for length 1 query features"

            qf = self.query_features_proj(self.query_features_block(query_features[0]))

            output_dicts.append(
                {
                    "spatial_features": spatial_features,
                    "query_features": qf,
                    "bias": self.bias,
                }
            )

        return output_dicts

    def forward_export(
        self,
        spatial_features: torch.Tensor,
        query_features: list[torch.Tensor],
        image_size: tuple[int, int],
        skip_blocks: bool = False,
    ) -> list[torch.Tensor]:
        assert len(query_features) == 1, "at export time, segmentation head expects exactly one query feature"

        target_size = (image_size[0] // self.downsample_ratio, image_size[1] // self.downsample_ratio)
        spatial_features = F.interpolate(spatial_features, size=target_size, mode="bilinear", align_corners=False)

        if not skip_blocks:
            for block in self.blocks:
                spatial_features = block(spatial_features)

        spatial_features_proj = self.spatial_features_proj(spatial_features)

        qf = self.query_features_proj(self.query_features_block(query_features[0]))
        return [torch.einsum("bchw,bnc->bnhw", spatial_features_proj, qf) + self.bias]


def point_sample(input: torch.Tensor, point_coords: torch.Tensor, **kwargs: Any) -> torch.Tensor:
    """执行 `point_sample`。
    
    参数：
    - `input`：传入的 `input` 参数。
    - `point_coords`：传入的 `point_coords` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    add_dim = False
    if point_coords.dim() == 3:
        add_dim = True
        point_coords = point_coords.unsqueeze(2)

    grid = 2.0 * point_coords - 1.0

    mode = kwargs.pop("mode", "bilinear")
    align_corners = kwargs.pop("align_corners", False)
    padding_mode = kwargs.pop("padding_mode", "border")

    if mode == "bilinear":
        if kwargs:
            unexpected = ", ".join(sorted(kwargs.keys()))
            raise TypeError(f"Unexpected keyword argument(s) for bilinear mode: {unexpected}")
        if padding_mode not in ("zeros", "border"):
            output = F.grid_sample(
                input,
                grid,
                mode=mode,
                padding_mode=padding_mode,
                align_corners=align_corners,
            )
        else:
            output = _bilinear_grid_sample(
                input,
                grid,
                padding_mode=padding_mode,
                align_corners=align_corners,
            )
    else:
        output = F.grid_sample(
            input,
            grid,
            mode=mode,
            padding_mode=padding_mode,
            align_corners=align_corners,
            **kwargs,
        )

    if add_dim:
        output = output.squeeze(3)
    return output


def get_uncertain_point_coords_with_randomness(
    coarse_logits: torch.Tensor,
    uncertainty_func: Callable[[torch.Tensor], torch.Tensor],
    num_points: int,
    oversample_ratio: int = 3,
    importance_sample_ratio: float = 0.75,
) -> torch.Tensor:
    """执行 `get_uncertain_point_coords_with_randomness`。
    
    参数：
    - `coarse_logits`：传入的 `coarse_logits` 参数。
    - `uncertainty_func`：传入的 `uncertainty_func` 参数。
    - `num_points`：传入的 `num_points` 参数。
    - `oversample_ratio`：传入的 `oversample_ratio` 参数。
    - `importance_sample_ratio`：传入的 `importance_sample_ratio` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    assert oversample_ratio >= 1
    assert importance_sample_ratio <= 1 and importance_sample_ratio >= 0
    num_boxes = coarse_logits.shape[0]
    num_sampled = int(num_points * oversample_ratio)
    point_coords = torch.rand(num_boxes, num_sampled, 2, device=coarse_logits.device)
    point_logits = point_sample(coarse_logits, point_coords, align_corners=False)
    point_uncertainties = uncertainty_func(point_logits)
    num_uncertain_points = int(importance_sample_ratio * num_points)
    num_random_points = num_points - num_uncertain_points
    idx = torch.topk(point_uncertainties[:, 0, :], k=num_uncertain_points, dim=1)[1]
    shift = num_sampled * torch.arange(num_boxes, dtype=torch.long, device=coarse_logits.device)
    idx += shift[:, None]
    point_coords = point_coords.view(-1, 2)[idx.view(-1), :].view(num_boxes, num_uncertain_points, 2)
    if num_random_points > 0:
        point_coords = torch.cat(
            [
                point_coords,
                torch.rand(num_boxes, num_random_points, 2, device=coarse_logits.device),
            ],
            dim=1,
        )
    return point_coords


def calculate_uncertainty(logits: torch.Tensor) -> torch.Tensor:
    """执行 `calculate_uncertainty`。
    
    参数：
    - `logits`：传入的 `logits` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    assert logits.shape[1] == 1
    gt_class_logits = logits.clone()
    return -(torch.abs(gt_class_logits))
