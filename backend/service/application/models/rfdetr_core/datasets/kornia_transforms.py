"""RF-DETR core 数据集处理模块：`datasets.kornia_transforms`。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import torch
from torch import Tensor

from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()

__doctest_requires__ = {"build_kornia_pipeline": ["kornia"]}

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

_MASK_BINARIZE_THRESHOLD: float = 0.5


def _has_cuda_device() -> bool:
    """执行 `_has_cuda_device`。
    
    返回：
    - 当前函数的执行结果。
    """
    from backend.service.application.models.rfdetr_core.config import DEVICE

    return str(DEVICE).startswith("cuda")


def resolve_augmentation_backend(backend: str) -> str:
    """执行 `resolve_augmentation_backend`。
    
    参数：
    - `backend`：传入的 `backend` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if backend == "cpu":
        return "cpu"
    if backend == "auto":
        if not _has_cuda_device():
            return "cpu"
        try:
            import kornia.augmentation  # noqa: F401 # type: ignore[import-not-found]
        except ImportError:
            return "cpu"
        return "gpu"
    if backend == "gpu":
        if not _has_cuda_device():
            raise RuntimeError("augmentation_backend='gpu' requires a CUDA device")
        _require_kornia()
        return "gpu"
    raise ValueError(f"Unknown augmentation_backend {backend!r}; expected 'cpu', 'auto', or 'gpu'.")


def _require_kornia() -> None:
    """执行 `_require_kornia`。
    
    返回：
    - 当前函数的执行结果。
    """
    try:
        import kornia.augmentation  # noqa: F401
    except ImportError as e:
        raise ImportError("GPU augmentation 需要 kornia，请先按本项目 requirements.txt 安装依赖。") from e


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _make_horizontal_flip(params: dict[str, Any]) -> Any:
    """执行 `_make_horizontal_flip`。
    
    参数：
    - `params`：传入的 `params` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from kornia.augmentation import RandomHorizontalFlip

    return RandomHorizontalFlip(p=params.get("p", 0.5))


def _make_vertical_flip(params: dict[str, Any]) -> Any:
    """执行 `_make_vertical_flip`。
    
    参数：
    - `params`：传入的 `params` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from kornia.augmentation import RandomVerticalFlip

    return RandomVerticalFlip(p=params.get("p", 0.5))


def _make_rotate(params: dict[str, Any]) -> Any:
    """执行 `_make_rotate`。
    
    参数：
    - `params`：传入的 `params` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from kornia.augmentation import RandomRotation

    limit = params.get("limit", 15)
    degrees = tuple(limit) if isinstance(limit, (list, tuple)) else (-limit, limit)
    rotation = RandomRotation(degrees=degrees, p=params.get("p", 0.5))

    flags = getattr(rotation, "flags", None)
    if isinstance(flags, dict) and "degrees" not in flags:
        flags["degrees"] = degrees

    return rotation


def _make_affine(params: dict[str, Any]) -> Any:
    """执行 `_make_affine`。
    
    参数：
    - `params`：传入的 `params` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from kornia.augmentation import RandomAffine

    translate_percent = params.get("translate_percent")
    if translate_percent is not None:
        if isinstance(translate_percent, (list, tuple)) and len(translate_percent) == 2:
            t = max(abs(translate_percent[0]), abs(translate_percent[1]))
            translate: float | tuple[float, float] | None = (t, t)
        else:
            translate = translate_percent
    else:
        translate = None

    return RandomAffine(
        degrees=params.get("rotate", (-15, 15)),
        translate=translate,
        scale=params.get("scale"),
        shear=params.get("shear"),
        p=params.get("p", 0.5),
    )


def _make_color_jitter(params: dict[str, Any]) -> Any:
    """执行 `_make_color_jitter`。
    
    参数：
    - `params`：传入的 `params` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from kornia.augmentation import ColorJiggle

    return ColorJiggle(
        brightness=params.get("brightness", 0.0),
        contrast=params.get("contrast", 0.0),
        saturation=params.get("saturation", 0.0),
        hue=params.get("hue", 0.0),
        p=params.get("p", 0.5),
    )


def _make_random_brightness_contrast(params: dict[str, Any]) -> Any:
    """执行 `_make_random_brightness_contrast`。
    
    参数：
    - `params`：传入的 `params` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from kornia.augmentation import ColorJiggle

    return ColorJiggle(
        brightness=params.get("brightness_limit", 0.2),
        contrast=params.get("contrast_limit", 0.2),
        p=params.get("p", 0.5),
    )


def _make_gaussian_blur(params: dict[str, Any]) -> Any:
    """执行 `_make_gaussian_blur`。
    
    参数：
    - `params`：传入的 `params` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from kornia.augmentation import RandomGaussianBlur

    blur_limit = params.get("blur_limit", 3)
    if blur_limit % 2 == 0:
        blur_limit = blur_limit + 1
    blur_limit = max(3, blur_limit)
    return RandomGaussianBlur(
        kernel_size=(blur_limit, blur_limit),
        sigma=(0.1, 2.0),
        p=params.get("p", 0.5),
    )


def _make_gauss_noise(params: dict[str, Any]) -> Any:
    """执行 `_make_gauss_noise`。
    
    参数：
    - `params`：传入的 `params` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from kornia.augmentation import RandomGaussianNoise

    std_range = params.get("std_range", (0.01, 0.05))
    return RandomGaussianNoise(
        std=std_range[1],
        p=params.get("p", 0.5),
    )


_REGISTRY: dict[str, Callable[[dict[str, Any]], Any]] = {
    "HorizontalFlip": _make_horizontal_flip,
    "VerticalFlip": _make_vertical_flip,
    "Rotate": _make_rotate,
    "Affine": _make_affine,
    "ColorJitter": _make_color_jitter,
    "RandomBrightnessContrast": _make_random_brightness_contrast,
    "GaussianBlur": _make_gaussian_blur,
    "GaussNoise": _make_gauss_noise,
}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def build_kornia_pipeline(
    aug_config: dict[str, dict[str, Any]],
    resolution: int,
    with_masks: bool = False,
) -> Any:
    """执行 `build_kornia_pipeline`。
    
    参数：
    - `aug_config`：传入的 `aug_config` 参数。
    - `resolution`：传入的 `resolution` 参数。
    - `with_masks`：传入的 `with_masks` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    _require_kornia()
    from kornia.augmentation import AugmentationSequential

    transforms: list[Any] = []
    for name, params in aug_config.items():
        factory = _REGISTRY.get(name)
        if factory is None:
            raise ValueError(
                f"Unknown augmentation key {name!r} for Kornia GPU backend. Supported keys: {sorted(_REGISTRY)}."
            )
        transforms.append(factory(params))

    data_keys = ["input", "bbox_xyxy", "mask"] if with_masks else ["input", "bbox_xyxy"]
    return AugmentationSequential(
        *transforms,
        data_keys=data_keys,
    )


def build_normalize(
    mean: tuple[float, ...] = IMAGENET_MEAN,
    std: tuple[float, ...] = IMAGENET_STD,
) -> Any:
    """执行 `build_normalize`。
    
    参数：
    - `mean`：传入的 `mean` 参数。
    - `std`：传入的 `std` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    _require_kornia()
    from kornia.augmentation import Normalize

    return Normalize(
        mean=mean,
        std=std,
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def collate_boxes(
    targets: list[dict[str, Any]],
    device: torch.device,
) -> tuple[Tensor, Tensor]:
    """执行 `collate_boxes`。
    
    参数：
    - `targets`：传入的 `targets` 参数。
    - `device`：传入的 `device` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if len(targets) == 0:
        return (
            torch.zeros(0, 0, 4, device=device),
            torch.zeros(0, 0, dtype=torch.bool, device=device),
        )

    box_counts = [t["boxes"].shape[0] for t in targets]
    n_max = max(box_counts) if box_counts else 0
    batch_size = len(targets)

    if n_max == 0:
        return (
            torch.zeros(batch_size, 0, 4, device=device),
            torch.zeros(batch_size, 0, dtype=torch.bool, device=device),
        )

    boxes_padded = torch.zeros(batch_size, n_max, 4, device=device)
    valid_mask = torch.zeros(batch_size, n_max, dtype=torch.bool, device=device)

    for i, t in enumerate(targets):
        n = t["boxes"].shape[0]
        if n > 0:
            boxes_padded[i, :n] = t["boxes"]
            valid_mask[i, :n] = True

    return boxes_padded, valid_mask


def collate_masks(
    targets: list[dict[str, Any]],
    device: torch.device,
    n_max: int,
    image_height: int,
    image_width: int,
) -> Tensor:
    """执行 `collate_masks`。
    
    参数：
    - `targets`：传入的 `targets` 参数。
    - `device`：传入的 `device` 参数。
    - `n_max`：传入的 `n_max` 参数。
    - `image_height`：传入的 `image_height` 参数。
    - `image_width`：传入的 `image_width` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    batch_size = len(targets)
    masks_padded = torch.zeros(batch_size, n_max, image_height, image_width, dtype=torch.float32, device=device)
    for i, t in enumerate(targets):
        if "masks" not in t or n_max == 0:
            continue
        masks_i = t["masks"].to(dtype=torch.float32, device=device)
        n = min(masks_i.shape[0], n_max)
        if n > 0:
            masks_padded[i, :n] = masks_i[:n]
    return masks_padded


def unpack_boxes(
    boxes_aug: Tensor,
    valid: Tensor,
    targets: list[dict[str, Any]],
    image_height: int,
    image_width: int,
    masks_aug: Tensor | None = None,
) -> list[dict[str, Any]]:
    """执行 `unpack_boxes`。
    
    参数：
    - `boxes_aug`：传入的 `boxes_aug` 参数。
    - `valid`：传入的 `valid` 参数。
    - `targets`：传入的 `targets` 参数。
    - `image_height`：传入的 `image_height` 参数。
    - `image_width`：传入的 `image_width` 参数。
    - `masks_aug`：传入的 `masks_aug` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if masks_aug is not None:
        assert masks_aug.shape[:2] == valid.shape, (
            f"masks_aug batch/n_max dims {tuple(masks_aug.shape[:2])} must match "
            f"valid shape {tuple(valid.shape)}; ensure collate_masks is called with "
            "n_max=valid.shape[1] from collate_boxes"
        )
    new_targets: list[dict[str, Any]] = []
    for i, t in enumerate(targets):
        t = t.copy()
        n_orig = t["boxes"].shape[0]

        if n_orig == 0 or valid.shape[1] == 0:
            new_targets.append(t)
            continue

        v = valid[i, :n_orig]
        boxes_i = boxes_aug[i, :n_orig]

        boxes_i = boxes_i.clone()
        boxes_i[:, 0].clamp_(min=0, max=image_width)
        boxes_i[:, 1].clamp_(min=0, max=image_height)
        boxes_i[:, 2].clamp_(min=0, max=image_width)
        boxes_i[:, 3].clamp_(min=0, max=image_height)

        widths = boxes_i[:, 2] - boxes_i[:, 0]
        heights = boxes_i[:, 3] - boxes_i[:, 1]
        keep = v & (widths > 0) & (heights > 0)

        t["boxes"] = boxes_i[keep]
        if "labels" in t:
            t["labels"] = t["labels"][keep]
        if "area" in t:
            kept_boxes = t["boxes"]
            t["area"] = (kept_boxes[:, 2] - kept_boxes[:, 0]) * (kept_boxes[:, 3] - kept_boxes[:, 1])
        if "iscrowd" in t:
            t["iscrowd"] = t["iscrowd"][keep]
        if masks_aug is not None:
            masks_i = masks_aug[i, :n_orig]
            t["masks"] = masks_i[keep] > _MASK_BINARIZE_THRESHOLD

        new_targets.append(t)

    return new_targets


