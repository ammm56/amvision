"""RF-DETR core 数据集处理模块：`datasets.transforms`。"""

from __future__ import annotations

import inspect
import os
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple, Union

os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

try:
    import albumentations as alb
except ImportError:
    alb = None  # type: ignore[assignment]
import numpy as np
import PIL
import torch
from PIL import Image
from torchvision.transforms import Normalize as _TVNormalize

from backend.service.application.models.rfdetr_core.utilities.box_ops import box_xyxy_to_cxcywh
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()


class Normalize(object):
    def __init__(
        self,
        mean: Tuple[float, ...] = (0.485, 0.456, 0.406),
        std: Tuple[float, ...] = (0.229, 0.224, 0.225),
    ) -> None:
        self._normalize = _TVNormalize(mean, std)

    def __call__(
        self, image: torch.Tensor, target: Optional[Dict[str, Any]] = None
    ) -> Tuple[torch.Tensor, Optional[Dict[str, Any]]]:
        image = self._normalize(image)
        if target is None:
            return image, None
        target = target.copy()
        h, w = image.shape[-2:]
        if "boxes" in target:
            boxes = target["boxes"]
            boxes = box_xyxy_to_cxcywh(boxes)
            boxes = boxes / torch.tensor([w, h, w, h], dtype=torch.float32)
            target["boxes"] = boxes
        return image, target



GEOMETRIC_TRANSFORMS = {
    "HorizontalFlip",
    "VerticalFlip",
    "Flip",
    "Transpose",
    "D4",
    "Rotate",
    "RandomRotate90",
    "Affine",
    "ShiftScaleRotate",
    "SafeRotate",
    "RandomCrop",
    "RandomSizedCrop",
    "CenterCrop",
    "Crop",
    "CropNonEmptyMaskIfExists",
    "RandomCropNearBBox",
    "RandomCropFromBorders",
    "RandomSizedBBoxSafeCrop",
    "BBoxSafeRandomCrop",
    "AtLeastOneBBoxRandomCrop",
    "RandomResizedCrop",
    "CropAndPad",
    "Perspective",
    "ElasticTransform",
    "GridDistortion",
    "GridElasticDeform",
    "OpticalDistortion",
    "PiecewiseAffine",
    "ThinPlateSpline",
    "RandomGridShuffle",
    "Resize",
    "SmallestMaxSize",
    "LongestMaxSize",
    "RandomScale",
    "Downscale",
    "PadIfNeeded",
    "Pad",
    "SquareSymmetry",
}

ALBUMENTATIONS_CONTAINERS = frozenset({"OneOf", "SomeOf", "Sequential"})


def _is_geometric_transform(transform: alb.BasicTransform) -> bool:
    """执行 `_is_geometric_transform`。
    
    参数：
    - `transform`：传入的 `transform` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if type(transform).__name__ in GEOMETRIC_TRANSFORMS:
        return True
    if hasattr(transform, "transforms"):
        return any(_is_geometric_transform(t) for t in transform.transforms)
    return False


def _build_albu_transform(name: str, params: Dict[str, Any]) -> alb.BasicTransform:
    """执行 `_build_albu_transform`。
    
    参数：
    - `name`：传入的 `name` 参数。
    - `params`：传入的 `params` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if name in ALBUMENTATIONS_CONTAINERS:
        raw_nested = params.get("transforms", [])
        if not isinstance(raw_nested, list):
            raise ValueError(f"'{name}.transforms' must be a list, got {type(raw_nested).__name__}")
        nested_transforms: List[alb.BasicTransform] = []
        for entry in raw_nested:
            if not isinstance(entry, dict) or len(entry) != 1:
                raise ValueError(f"Each nested transform entry must be a single-key dict, got {entry!r}")
            nested_name, nested_params = next(iter(entry.items()))
            if not isinstance(nested_params, dict):
                raise ValueError(
                    f"Parameters for nested transform '{nested_name}' must be a dict, "
                    f"got {type(nested_params).__name__}"
                )
            nested_transforms.append(_build_albu_transform(nested_name, nested_params))

        if name == "OneOf":
            if not nested_transforms:
                raise ValueError("'OneOf' requires at least one transform")
            other_params = {k: v for k, v in params.items() if k not in ("transforms", "p")}
            other_params["p"] = 1.0
        elif name == "Sequential":
            other_params = {k: v for k, v in params.items() if k not in ("transforms", "p")}
            other_params["p"] = 1.0
        else:
            other_params = {k: v for k, v in params.items() if k != "transforms"}

        container_cls = getattr(alb, name, None)
        if container_cls is None:
            raise ValueError(f"Unknown Albumentations container: {name!r}")
        return container_cls(transforms=nested_transforms, **other_params)

    aug_cls = getattr(alb, name, None)
    if aug_cls is None:
        raise ValueError(f"Unknown Albumentations transform: {name!r}")
    return aug_cls(**_normalize_albu_params(name, params, aug_cls))


@lru_cache(maxsize=None)
def _random_sized_crop_uses_size_param(aug_cls: type) -> bool:
    """执行 `_random_sized_crop_uses_size_param`。
    
    参数：
    - `aug_cls`：传入的 `aug_cls` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    signature = inspect.signature(aug_cls.__init__)
    return "size" in signature.parameters


def _normalize_albu_params(name: str, params: Dict[str, Any], aug_cls: type) -> Dict[str, Any]:
    """执行 `_normalize_albu_params`。
    
    参数：
    - `name`：传入的 `name` 参数。
    - `params`：传入的 `params` 参数。
    - `aug_cls`：传入的 `aug_cls` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    normalized_params = dict(params)
    if name != "RandomSizedCrop":
        return normalized_params

    uses_size = _random_sized_crop_uses_size_param(aug_cls)

    if uses_size:
        has_size = "size" in normalized_params
        has_height = "height" in normalized_params
        has_width = "width" in normalized_params

        if has_size:
            normalized_params.pop("height", None)
            normalized_params.pop("width", None)
            return normalized_params

        if has_height and has_width:
            height = normalized_params.pop("height")
            width = normalized_params.pop("width")
            normalized_params["size"] = (height, width)
            return normalized_params

        if has_height != has_width:
            missing = "width" if has_height and not has_width else "height"
            raise ValueError(
                f"RandomSizedCrop for the installed Albumentations version expects "
                f"'size=(height, width)'. Received only one of 'height'/'width' "
                f"without 'size' (missing '{missing}')."
            )

        return normalized_params

    if not uses_size and "size" in normalized_params:
        size = normalized_params.get("size")
        if isinstance(size, Sequence) and len(size) == 2:
            normalized_params.setdefault("height", size[0])
            normalized_params.setdefault("width", size[1])
            normalized_params.pop("size", None)

    return normalized_params


class AlbumentationsWrapper:
    """RF-DETR core 类：`AlbumentationsWrapper`。"""

    def __init__(self, transform: alb.BasicTransform) -> None:
        self._is_geometric = _is_geometric_transform(transform)

        if self._is_geometric:
            self.transform = alb.Compose(
                [transform],
                bbox_params=alb.BboxParams(
                    format="pascal_voc",
                    label_fields=["category_ids", "idxs"],
                    min_visibility=0.0,
                    clip=True,
                ),
            )
        else:
            self.transform = alb.Compose([transform])

    def __repr__(self) -> str:
        """执行 `__repr__`。
        
        返回：
        - 当前函数的执行结果。
        """
        transform = None
        if isinstance(self.transform, alb.Compose):
            for candidate in self.transform.transforms:
                if isinstance(candidate, alb.BasicTransform):
                    transform = candidate
                    break
        elif isinstance(self.transform, alb.BasicTransform):
            transform = self.transform

        if transform is None:
            return object.__repr__(self)

        transform_type = "geometric" if self._is_geometric else "pixel-level"
        return f"{self.__class__.__name__}(transform={transform}, type={transform_type})"

    @staticmethod
    def _boxes_to_numpy(boxes: Union[torch.Tensor, np.ndarray]) -> np.ndarray:
        """执行 `_boxes_to_numpy`。
        
        参数：
        - `boxes`：传入的 `boxes` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        boxes_np = boxes.cpu().numpy() if torch.is_tensor(boxes) else np.array(boxes)
        if len(boxes_np.shape) != 2 or boxes_np.shape[1] != 4:
            raise ValueError(f"boxes must have shape (N, 4), got {boxes_np.shape}")
        return boxes_np

    @staticmethod
    def _clear_per_instance_fields(target: Dict[str, Any], num_boxes: int) -> Dict[str, Any]:
        """执行 `_clear_per_instance_fields`。
        
        参数：
        - `target`：传入的 `target` 参数。
        - `num_boxes`：传入的 `num_boxes` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        global_fields = {"boxes", "labels", "orig_size", "size", "image_id"}

        result = {}
        for key, value in target.items():
            if key in global_fields:
                continue
            if torch.is_tensor(value):
                if value.ndim >= 1 and value.shape[0] == num_boxes:
                    result[key] = value.new_empty((0, *value.shape[1:]))
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                if len(value) == num_boxes:
                    result[key] = []
        return result

    @staticmethod
    def _filter_per_instance_fields(target: Dict[str, Any], num_boxes: int, kept_idxs: List[int]) -> Dict[str, Any]:
        """执行 `_filter_per_instance_fields`。
        
        参数：
        - `target`：传入的 `target` 参数。
        - `num_boxes`：传入的 `num_boxes` 参数。
        - `kept_idxs`：传入的 `kept_idxs` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        global_fields = {"boxes", "labels", "orig_size", "size", "image_id"}

        result = {}
        kept_idxs_tensor = torch.as_tensor(kept_idxs, dtype=torch.long)
        for key, value in target.items():
            if key in global_fields:
                continue
            if torch.is_tensor(value):
                if value.ndim >= 1 and value.shape[0] == num_boxes:
                    result[key] = value[kept_idxs_tensor]
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                if len(value) == num_boxes:
                    result[key] = [value[i] for i in kept_idxs]
        return result

    def _apply_geometric_transform(
        self, image_np: np.ndarray, target: Dict[str, Any], labels: List[int]
    ) -> Tuple[Image.Image, Dict[str, Any]]:
        """执行 `_apply_geometric_transform`。
        
        参数：
        - `image_np`：传入的 `image_np` 参数。
        - `target`：传入的 `target` 参数。
        - `labels`：传入的 `labels` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        boxes_np = self._boxes_to_numpy(target["boxes"])
        num_boxes = boxes_np.shape[0]
        idxs = list(range(num_boxes))
        masks_list = None
        if "masks" in target:
            masks = target["masks"]
            masks_np = masks.cpu().numpy() if torch.is_tensor(masks) else np.array(masks)
            if masks_np.ndim != 3:
                raise ValueError(f"masks must have shape (N, H, W), got {masks_np.shape}")
            masks_np = masks_np.astype(np.uint8, copy=False)
            masks_list = [mask for mask in masks_np]
        if num_boxes > 0:
            valid_mask = (boxes_np[:, 2] > boxes_np[:, 0]) & (boxes_np[:, 3] > boxes_np[:, 1])
            if not valid_mask.all():
                valid_positions = np.where(valid_mask)[0].tolist()
                boxes_np = boxes_np[valid_mask]
                labels = [labels[i] for i in valid_positions]
                idxs = [idxs[i] for i in valid_positions]
        transform_kwargs = {"image": image_np, "bboxes": boxes_np, "category_ids": labels, "idxs": idxs}
        if masks_list is not None and len(masks_list) > 0:
            transform_kwargs["masks"] = masks_list
        augmented = self.transform(**transform_kwargs)
        target_out: Dict[str, Any] = target.copy()
        bboxes_aug = augmented["bboxes"]
        kept_idxs = augmented.get("idxs", idxs)
        if len(bboxes_aug) == 0:
            target_out["boxes"] = torch.zeros((0, 4), dtype=torch.float32)
            target_out["labels"] = torch.zeros((0,), dtype=torch.long)
            target_out.update(self._clear_per_instance_fields(target, num_boxes))
            if "masks" in target:
                aug_height, aug_width = augmented["image"].shape[:2]
                target_out["masks"] = torch.zeros((0, aug_height, aug_width), dtype=torch.bool)
        else:
            target_out["boxes"] = torch.as_tensor(bboxes_aug, dtype=torch.float32).reshape(-1, 4)
            target_out["labels"] = torch.tensor(augmented["category_ids"], dtype=torch.long)
            target_out.update(self._filter_per_instance_fields(target, num_boxes, kept_idxs))
            if "area" in target_out:
                boxes = target_out["boxes"]
                target_out["area"] = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        image_out = Image.fromarray(augmented["image"])
        if masks_list is not None and "masks" in augmented:
            height, width = augmented["image"].shape[:2]
            masks_aug = augmented["masks"]
            masks_aug = [masks_aug[int(i)] for i in kept_idxs]
            if len(masks_aug) == 0:
                target_out["masks"] = torch.zeros((0, height, width), dtype=torch.bool)
            else:
                target_out["masks"] = torch.as_tensor(np.stack(masks_aug), dtype=torch.bool)
        return image_out, target_out

    def __call__(
        self, image: PIL.Image.Image, target: Optional[Dict[str, Any]]
    ) -> Tuple[PIL.Image.Image, Optional[Dict[str, Any]]]:
        """执行 `__call__`。
        
        参数：
        - `image`：传入的 `image` 参数。
        - `target`：传入的 `target` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if target is None:
            image_np = np.array(image)
            if self._is_geometric:
                augmented = self.transform(image=image_np, bboxes=[], category_ids=[], idxs=[])
            else:
                augmented = self.transform(image=image_np)
            return Image.fromarray(augmented["image"]), None

        if not isinstance(target, dict):
            raise TypeError(f"target must be a dictionary, got {type(target)}")
        if "labels" not in target:
            raise KeyError("target must contain 'labels' key")

        image_np = np.array(image)

        labels = target["labels"].cpu().tolist() if torch.is_tensor(target["labels"]) else list(target["labels"])

        if self._is_geometric and "masks" in target and "boxes" not in target:
            logger.warning(
                "AlbumentationsWrapper: geometric transform requested with 'masks' but without 'boxes'. "
                "Masks will not be geometrically transformed because bounding boxes are missing."
            )
        if self._is_geometric and "boxes" in target:
            image_out, target_out = self._apply_geometric_transform(image_np, target, labels)
        else:
            augmented = self.transform(image=image_np)
            image_out = Image.fromarray(augmented["image"])
            target_out = target.copy()

        if "size" in target_out:
            width, height = image_out.size
            target_out["size"] = torch.as_tensor([height, width], dtype=torch.int64)
        return image_out, target_out

    @staticmethod
    def from_config(
        config_dict: Union[Dict[str, Any], List[Dict[str, Any]]],
    ) -> List["AlbumentationsWrapper"]:
        """执行 `from_config`。
        
        参数：
        - `config_dict`：传入的 `config_dict` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        if isinstance(config_dict, list):
            entries = config_dict
        elif isinstance(config_dict, dict):
            entries = [{k: v} for k, v in config_dict.items()]
        else:
            raise TypeError(f"config_dict must be a dictionary or list, got {type(config_dict)}")

        if not entries:
            logger.warning("Empty augmentation config provided, no transforms will be applied")
            return []

        transforms = []
        for entry in entries:
            if not isinstance(entry, dict) or len(entry) != 1:
                logger.warning(
                    "Skipping invalid config entry (must be a single-key dict): %r",
                    entry,
                )
                continue
            aug_name, params = next(iter(entry.items()))

            if isinstance(params, list) and aug_name in ALBUMENTATIONS_CONTAINERS:
                params = {"transforms": params}

            if not isinstance(params, dict):
                logger.warning(
                    "Skipping %s: parameters must be a dictionary, got %s",
                    aug_name,
                    type(params).__name__,
                )
                continue

            try:
                transform = _build_albu_transform(aug_name, params)
                transforms.append(AlbumentationsWrapper(transform))
            except Exception as e:
                logger.warning(
                    "Failed to initialize %s with params %r: %s. Skipping.",
                    aug_name,
                    params,
                    e,
                )
                continue

        logger.info("Built %d Albumentations transforms from config", len(transforms))
        return transforms


