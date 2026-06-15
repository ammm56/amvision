"""RF-DETR core 工具函数模块：`utilities.tensors`。"""

from functools import partial
from typing import Any, Callable

import torch
import torchvision
from torch import Tensor


def _round_up_to_multiple(value: int, multiple: int) -> int:
    """执行 `_round_up_to_multiple`。
    
    参数：
    - `value`：传入的 `value` 参数。
    - `multiple`：传入的 `multiple` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if value < 0:
        raise ValueError(f"value must be non-negative, got {value}")
    if multiple <= 0:
        raise ValueError(f"multiple must be a positive integer, got {multiple}")
    return ((value + multiple - 1) // multiple) * multiple


def _max_by_axis(the_list: list[list[int]]) -> list[int]:
    """执行 `_max_by_axis`。
    
    参数：
    - `the_list`：传入的 `the_list` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    maxes = the_list[0]
    for sublist in the_list[1:]:
        for index, item in enumerate(sublist):
            maxes[index] = max(maxes[index], item)
    return maxes


class NestedTensor:
    """RF-DETR core 类：`NestedTensor`。"""

    def __init__(self, tensors: Tensor, mask: Tensor | None) -> None:
        self.tensors = tensors
        self.mask = mask

    def to(self, device: torch.device, **kwargs: Any) -> "NestedTensor":
        """执行 `to`。
        
        参数：
        - `device`：传入的 `device` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        cast_tensor = self.tensors.to(device, **kwargs)
        mask = self.mask
        if mask is not None:
            assert mask is not None
            cast_mask = mask.to(device, **kwargs)
        else:
            cast_mask = None
        return NestedTensor(cast_tensor, cast_mask)

    def pin_memory(self) -> "NestedTensor":
        """执行 `pin_memory`。
        
        返回：
        - 当前函数的执行结果。
        """
        return NestedTensor(
            self.tensors.pin_memory(),
            self.mask.pin_memory() if self.mask is not None else None,
        )

    def decompose(self) -> tuple[Tensor, Tensor | None]:
        """执行 `decompose`。
        
        返回：
        - 当前函数的执行结果。
        """
        return self.tensors, self.mask

    def __repr__(self) -> str:
        return str(self.tensors)


def nested_tensor_from_tensor_list(
    tensor_list: list[Tensor],
    block_size: int | None = None,
) -> NestedTensor:
    """执行 `nested_tensor_from_tensor_list`。
    
    参数：
    - `tensor_list`：传入的 `tensor_list` 参数。
    - `block_size`：传入的 `block_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if tensor_list[0].ndim == 3:
        if torchvision._is_tracing():
            return _onnx_nested_tensor_from_tensor_list(tensor_list, block_size=block_size)

        max_size = _max_by_axis([list(img.shape) for img in tensor_list])
        if block_size is not None:
            max_size[1] = _round_up_to_multiple(max_size[1], block_size)
            max_size[2] = _round_up_to_multiple(max_size[2], block_size)
        batch_shape = [len(tensor_list)] + max_size
        b, c, h, w = batch_shape
        dtype = tensor_list[0].dtype
        device = tensor_list[0].device
        tensor = torch.zeros(batch_shape, dtype=dtype, device=device)
        mask = torch.ones((b, h, w), dtype=torch.bool, device=device)
        for img, pad_img, m in zip(tensor_list, tensor, mask):
            pad_img[: img.shape[0], : img.shape[1], : img.shape[2]].copy_(img)
            m[: img.shape[1], : img.shape[2]] = False
    else:
        raise ValueError("not supported")
    return NestedTensor(tensor, mask)


@torch.jit.unused
def _onnx_nested_tensor_from_tensor_list(
    tensor_list: list[Tensor],
    block_size: int | None = None,
) -> NestedTensor:
    """执行 `_onnx_nested_tensor_from_tensor_list`。
    
    参数：
    - `tensor_list`：传入的 `tensor_list` 参数。
    - `block_size`：传入的 `block_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    max_size = []
    for i in range(tensor_list[0].dim()):
        max_size_i = torch.max(torch.stack([img.shape[i] for img in tensor_list]).to(torch.float32)).to(torch.int64)
        max_size.append(max_size_i)
    if block_size is not None:
        bs = torch.as_tensor(block_size, dtype=torch.int64)
        max_size[1] = ((max_size[1] + bs - 1) // bs) * bs
        max_size[2] = ((max_size[2] + bs - 1) // bs) * bs
    max_size = tuple(max_size)

    padded_imgs = []
    padded_masks = []
    for img in tensor_list:
        padding = [(s1 - s2) for s1, s2 in zip(max_size, tuple(img.shape))]
        padded_img = torch.nn.functional.pad(img, (0, padding[2], 0, padding[1], 0, padding[0]))
        padded_imgs.append(padded_img)

        m = torch.zeros_like(img[0], dtype=torch.int, device=img.device)
        padded_mask = torch.nn.functional.pad(m, (0, padding[2], 0, padding[1]), "constant", 1)
        padded_masks.append(padded_mask.to(torch.bool))

    tensor = torch.stack(padded_imgs)
    mask = torch.stack(padded_masks)

    return NestedTensor(tensor, mask=mask)


def _bilinear_grid_sample(
    input: torch.Tensor,
    grid: torch.Tensor,
    padding_mode: str = "zeros",
    align_corners: bool = False,
) -> torch.Tensor:
    """执行 `_bilinear_grid_sample`。
    
    参数：
    - `input`：传入的 `input` 参数。
    - `grid`：传入的 `grid` 参数。
    - `padding_mode`：传入的 `padding_mode` 参数。
    - `align_corners`：传入的 `align_corners` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    import torch.nn.functional as F  # noqa: N812

    if input.device.type != "mps":
        return F.grid_sample(input, grid, mode="bilinear", padding_mode=padding_mode, align_corners=align_corners)

    if padding_mode not in ("zeros", "border"):
        msg = (
            f"Unsupported padding_mode={padding_mode!r} for manual grid sampling. "
            "Only 'zeros' and 'border' are supported in this path."
        )
        raise ValueError(msg)

    batch_size, channels, height, width = input.shape
    grid_height, grid_width = grid.shape[1], grid.shape[2]

    if align_corners:
        ix = (grid[..., 0] + 1) * (width - 1) / 2
        iy = (grid[..., 1] + 1) * (height - 1) / 2
    else:
        ix = (grid[..., 0] + 1) * width / 2 - 0.5
        iy = (grid[..., 1] + 1) * height / 2 - 0.5

    ix0 = ix.floor().long()
    iy0 = iy.floor().long()
    ix1 = ix0 + 1
    iy1 = iy0 + 1

    wx1 = (ix - ix0.float()).to(input.dtype).unsqueeze(1)
    wy1 = (iy - iy0.float()).to(input.dtype).unsqueeze(1)
    one = wx1.new_tensor(1.0)
    wx0 = one - wx1
    wy0 = one - wy1

    if padding_mode == "border":
        ix0 = ix0.clamp(0, width - 1)
        iy0 = iy0.clamp(0, height - 1)
        ix1 = ix1.clamp(0, width - 1)
        iy1 = iy1.clamp(0, height - 1)
    else:
        in_x0 = (ix0 >= 0) & (ix0 < width)
        in_x1 = (ix1 >= 0) & (ix1 < width)
        in_y0 = (iy0 >= 0) & (iy0 < height)
        in_y1 = (iy1 >= 0) & (iy1 < height)
        ix0 = ix0.clamp(0, width - 1)
        iy0 = iy0.clamp(0, height - 1)
        ix1 = ix1.clamp(0, width - 1)
        iy1 = iy1.clamp(0, height - 1)

    flat = input.flatten(2)

    def _gather(iy_: torch.Tensor, ix_: torch.Tensor) -> torch.Tensor:
        idx = (iy_ * width + ix_).flatten(1).unsqueeze(1).expand(batch_size, channels, -1)
        return flat.gather(2, idx).view(batch_size, channels, grid_height, grid_width)

    v00 = _gather(iy0, ix0)
    v10 = _gather(iy0, ix1)
    v01 = _gather(iy1, ix0)
    v11 = _gather(iy1, ix1)

    if padding_mode == "zeros":
        v00 = v00 * (in_x0 & in_y0).unsqueeze(1)
        v10 = v10 * (in_x1 & in_y0).unsqueeze(1)
        v01 = v01 * (in_x0 & in_y1).unsqueeze(1)
        v11 = v11 * (in_x1 & in_y1).unsqueeze(1)

    return wx0 * wy0 * v00 + wx1 * wy0 * v10 + wx0 * wy1 * v01 + wx1 * wy1 * v11


def _collate_with_block_size(
    batch: list[tuple[Any, ...]],
    block_size: int | None = None,
) -> tuple[Any, ...]:
    """执行 `_collate_with_block_size`。
    
    参数：
    - `batch`：传入的 `batch` 参数。
    - `block_size`：传入的 `block_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    batch = list(zip(*batch))
    batch[0] = nested_tensor_from_tensor_list(batch[0], block_size=block_size)
    return tuple(batch)


def collate_fn(batch: list[tuple[Any, ...]]) -> tuple[Any, ...]:
    """执行 `collate_fn`。
    
    参数：
    - `batch`：传入的 `batch` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    return _collate_with_block_size(batch, block_size=None)


def make_collate_fn(
    block_size: int | None = None,
) -> Callable[[list[tuple[Any, ...]]], tuple[Any, ...]]:
    """执行 `make_collate_fn`。
    
    参数：
    - `block_size`：传入的 `block_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    return partial(_collate_with_block_size, block_size=block_size)


