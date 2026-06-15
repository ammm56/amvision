"""RF-DETR core 数据集处理模块：`datasets.coco`。"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import torch
import torch.utils.data
import torchvision
from PIL import Image
from torchvision.transforms.v2 import Compose, ToDtype, ToImage

from backend.service.application.models.rfdetr_core.datasets.aug_config import AUG_CONFIG
from backend.service.application.models.rfdetr_core.datasets.transforms import AlbumentationsWrapper, Normalize
from backend.service.application.models.rfdetr_core.utilities.logger import get_logger

logger = get_logger()


def is_valid_coco_dataset(dataset_dir: str) -> bool:
    return (Path(dataset_dir) / "train" / "_annotations.coco.json").exists()


def compute_multi_scale_scales(
    resolution: int,
    expanded_scales: bool = False,
    patch_size: int = 16,
    num_windows: int = 4,
) -> List[int]:
    base_num_patches_per_window = resolution // (patch_size * num_windows)
    offsets = [-3, -2, -1, 0, 1, 2, 3, 4] if not expanded_scales else [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]
    scales = [base_num_patches_per_window + offset for offset in offsets]
    proposed_scales = [scale * patch_size * num_windows for scale in scales]
    proposed_scales = [
        scale for scale in proposed_scales if scale >= patch_size * num_windows * 2
    ]
    return proposed_scales


def _is_rle(segmentation: Any) -> bool:
    """执行 `_is_rle`。
    
    参数：
    - `segmentation`：传入的 `segmentation` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    return isinstance(segmentation, dict) and "counts" in segmentation and "size" in segmentation


def convert_coco_poly_to_mask(segmentations: List[Any], height: int, width: int) -> torch.Tensor:
    """执行 `convert_coco_poly_to_mask`。
    
    参数：
    - `segmentations`：传入的 `segmentations` 参数。
    - `height`：传入的 `height` 参数。
    - `width`：传入的 `width` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    import pycocotools.mask as coco_mask

    masks = []
    for segmentation in segmentations:
        if segmentation is None or (not isinstance(segmentation, dict) and len(segmentation) == 0):
            masks.append(torch.zeros((height, width), dtype=torch.uint8))
            continue
        if _is_rle(segmentation):
            counts = segmentation["counts"]
            if not isinstance(counts, (str, bytes, list)):
                raise ValueError(
                    f"RLE segmentation has unsupported counts type {type(counts).__name__!r}; "
                    "expected str, bytes, or list"
                )
            if isinstance(counts, (str, bytes)):
                rles = [segmentation]
            else:
                rles = [coco_mask.frPyObjects(segmentation, height, width)]
        else:
            rles = coco_mask.frPyObjects(segmentation, height, width)
        mask = coco_mask.decode(rles)
        if mask.ndim < 3:
            mask = mask[..., None]
        mask = torch.as_tensor(mask, dtype=torch.uint8)
        mask = mask.any(dim=2).to(torch.uint8)
        masks.append(mask)
    if len(masks) == 0:
        return torch.zeros((0, height, width), dtype=torch.uint8)
    return torch.stack(masks, dim=0)


class CocoDetection(torchvision.datasets.CocoDetection):
    """RF-DETR core 类：`CocoDetection`。"""

    def __init__(
        self,
        img_folder: Union[str, Path],
        ann_file: Union[str, Path],
        transforms: Optional[Any],
        include_masks: bool = False,
        remap_category_ids: bool = False,
    ) -> None:
        super(CocoDetection, self).__init__(img_folder, ann_file)
        self._transforms = transforms
        self.include_masks = include_masks
        if remap_category_ids:
            self.cat2label = {cat_id: i for i, cat_id in enumerate(sorted(self.coco.cats.keys()))}
            self.label2cat = {label: cat_id for cat_id, label in self.cat2label.items()}
            setattr(self.coco, "label2cat", self.label2cat)
        else:
            self.cat2label = None
            self.label2cat = None
        self.prepare = ConvertCoco(include_masks=include_masks, cat2label=self.cat2label)

    def __getitem__(self, idx: int) -> Tuple[Any, Any]:
        img, target = super(CocoDetection, self).__getitem__(idx)
        image_id = self.ids[idx]
        target = {"image_id": image_id, "annotations": target}
        img, target = self.prepare(img, target)
        if self._transforms is not None:
            img, target = self._transforms(img, target)
        return img, target


class ConvertCoco(object):
    """RF-DETR core 类：`ConvertCoco`。"""

    def __init__(self, include_masks: bool = False, cat2label: Optional[Dict[int, int]] = None) -> None:
        self.include_masks = include_masks
        self.cat2label = cat2label

    def __call__(self, image: Image.Image, target: Dict[str, Any]) -> Tuple[Image.Image, Dict[str, Any]]:
        w, h = image.size

        image_id = target["image_id"]
        image_id = torch.tensor([image_id])

        anno = target["annotations"]

        anno = [obj for obj in anno if "iscrowd" not in obj or obj["iscrowd"] == 0]

        boxes = [obj["bbox"] for obj in anno]
        boxes = torch.as_tensor(boxes, dtype=torch.float32).reshape(-1, 4)
        boxes[:, 2:] += boxes[:, :2]
        boxes[:, 0::2].clamp_(min=0, max=w)
        boxes[:, 1::2].clamp_(min=0, max=h)

        classes: List[int] = []
        for obj in anno:
            category_id = obj["category_id"]
            if getattr(self, "cat2label", None) is not None:
                if category_id not in self.cat2label:
                    raise KeyError(
                        f"Unknown category_id {category_id} for image_id {target.get('image_id')} "
                        "encountered in annotations. Check that your category mapping matches the dataset."
                    )
                classes.append(self.cat2label[category_id])
            else:
                classes.append(category_id)
        classes = torch.tensor(classes, dtype=torch.int64)

        keep = (boxes[:, 3] > boxes[:, 1]) & (boxes[:, 2] > boxes[:, 0])
        boxes = boxes[keep]
        classes = classes[keep]

        target = {}
        target["boxes"] = boxes
        target["labels"] = classes
        target["image_id"] = image_id

        area = torch.tensor([obj["area"] for obj in anno])
        iscrowd = torch.tensor([obj["iscrowd"] if "iscrowd" in obj else 0 for obj in anno])
        target["area"] = area[keep]
        target["iscrowd"] = iscrowd[keep]

        if self.include_masks:
            if len(anno) > 0 and "segmentation" in anno[0]:
                segmentations = [obj.get("segmentation", []) for obj in anno]
                masks = convert_coco_poly_to_mask(segmentations, h, w)
                if masks.numel() > 0:
                    target["masks"] = masks[keep]
                else:
                    target["masks"] = torch.zeros((0, h, w), dtype=torch.uint8)
            else:
                target["masks"] = torch.zeros((0, h, w), dtype=torch.uint8)

            target["masks"] = target["masks"].bool()

        target["orig_size"] = torch.as_tensor([int(h), int(w)])
        target["size"] = torch.as_tensor([int(h), int(w)])

        return image, target


def _build_train_resize_config(
    scales: List[int],
    *,
    square: bool,
    max_size: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """执行 `_build_train_resize_config`。
    
    参数：
    - `scales`：传入的 `scales` 参数。
    - `square`：传入的 `square` 参数。
    - `max_size`：传入的 `max_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if square:
        option_a: Dict[str, Any] = {
            "OneOf": {
                "transforms": [{"Resize": {"height": s, "width": s}} for s in scales],
            }
        }
        option_b: Dict[str, Any] = {
            "Sequential": {
                "transforms": [
                    {"SmallestMaxSize": {"max_size": [400, 500, 600]}},
                    {
                        "OneOf": {
                            "transforms": [
                                {"RandomSizedCrop": {"min_max_height": [384, 600], "height": s, "width": s}}
                                for s in scales
                            ],
                        }
                    },
                ]
            }
        }
    else:
        cap = max_size or 1333
        size_param: Any = scales[0] if len(scales) == 1 else scales
        option_a = {
            "Sequential": {
                "transforms": [
                    {"SmallestMaxSize": {"max_size": size_param}},
                    {"LongestMaxSize": {"max_size": cap}},
                ]
            }
        }
        option_b = {
            "Sequential": {
                "transforms": [
                    {"SmallestMaxSize": {"max_size": [400, 500, 600]}},
                    {"RandomCrop": {"height": 384, "width": 384}},
                    {"SmallestMaxSize": {"max_size": size_param}},
                    {"LongestMaxSize": {"max_size": cap}},
                ]
            }
        }

    return [{"OneOf": {"transforms": [option_a, option_b]}}]


def make_coco_transforms(
    image_set: str,
    resolution: int,
    multi_scale: bool = False,
    expanded_scales: bool = False,
    skip_random_resize: bool = False,
    patch_size: int = 16,
    num_windows: int = 4,
    aug_config: Optional[Dict[str, Dict[str, Any]]] = None,
    gpu_postprocess: bool = False,
) -> Compose:
    """执行 `make_coco_transforms`。
    
    参数：
    - `image_set`：传入的 `image_set` 参数。
    - `resolution`：传入的 `resolution` 参数。
    - `multi_scale`：传入的 `multi_scale` 参数。
    - `expanded_scales`：传入的 `expanded_scales` 参数。
    - `skip_random_resize`：传入的 `skip_random_resize` 参数。
    - `patch_size`：传入的 `patch_size` 参数。
    - `num_windows`：传入的 `num_windows` 参数。
    - `aug_config`：传入的 `aug_config` 参数。
    - `gpu_postprocess`：传入的 `gpu_postprocess` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    to_image = ToImage()
    to_float = ToDtype(torch.float32, scale=True)
    normalize = Normalize()

    scales = [resolution]
    if multi_scale:
        scales = compute_multi_scale_scales(resolution, expanded_scales, patch_size, num_windows)
        if skip_random_resize:
            scales = [scales[-1]]
        logger.info(f"Using multi-scale training with scales: {scales}")

    if image_set == "train":
        resolved_aug_config = aug_config if aug_config is not None else AUG_CONFIG
        resize_wrappers = AlbumentationsWrapper.from_config(
            _build_train_resize_config(scales, square=False, max_size=1333)
        )
        pipeline = [*resize_wrappers]
        if not gpu_postprocess:
            aug_wrappers = AlbumentationsWrapper.from_config(resolved_aug_config)
            pipeline += [*aug_wrappers]
        pipeline += [to_image, to_float]
        if not gpu_postprocess:
            pipeline += [normalize]
        return Compose(pipeline)

    if image_set in ("val", "test"):
        resize_wrappers = AlbumentationsWrapper.from_config(
            [
                {"SmallestMaxSize": {"max_size": resolution}},
                {"LongestMaxSize": {"max_size": 1333}},
            ]
        )
        return Compose([*resize_wrappers, to_image, to_float, normalize])
    if image_set == "val_speed":
        resize_wrappers = AlbumentationsWrapper.from_config([{"Resize": {"height": resolution, "width": resolution}}])
        return Compose([*resize_wrappers, to_image, to_float, normalize])

    raise ValueError(f"unknown {image_set}")


def make_coco_transforms_square_div_64(
    image_set: str,
    resolution: int,
    multi_scale: bool = False,
    expanded_scales: bool = False,
    skip_random_resize: bool = False,
    patch_size: int = 16,
    num_windows: int = 4,
    aug_config: Optional[Dict[str, Dict[str, Any]]] = None,
    gpu_postprocess: bool = False,
) -> Compose:
    """执行 `make_coco_transforms_square_div_64`。
    
    参数：
    - `image_set`：传入的 `image_set` 参数。
    - `resolution`：传入的 `resolution` 参数。
    - `multi_scale`：传入的 `multi_scale` 参数。
    - `expanded_scales`：传入的 `expanded_scales` 参数。
    - `skip_random_resize`：传入的 `skip_random_resize` 参数。
    - `patch_size`：传入的 `patch_size` 参数。
    - `num_windows`：传入的 `num_windows` 参数。
    - `aug_config`：传入的 `aug_config` 参数。
    - `gpu_postprocess`：传入的 `gpu_postprocess` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    to_image = ToImage()
    to_float = ToDtype(torch.float32, scale=True)
    normalize = Normalize()

    scales = [resolution]
    if multi_scale:
        scales = compute_multi_scale_scales(resolution, expanded_scales, patch_size, num_windows)
        if skip_random_resize:
            scales = [scales[-1]]
        logger.info(f"Using multi-scale training with square resize and scales: {scales}")

    if image_set == "train":
        resolved_aug_config = aug_config if aug_config is not None else AUG_CONFIG
        resize_wrappers = AlbumentationsWrapper.from_config(_build_train_resize_config(scales, square=True))
        pipeline = [*resize_wrappers]
        if not gpu_postprocess:
            aug_wrappers = AlbumentationsWrapper.from_config(resolved_aug_config)
            pipeline += [*aug_wrappers]
        pipeline += [to_image, to_float]
        if not gpu_postprocess:
            pipeline += [normalize]
        return Compose(pipeline)

    if image_set in ("val", "test", "val_speed"):
        resize_wrappers = AlbumentationsWrapper.from_config([{"Resize": {"height": resolution, "width": resolution}}])
        return Compose([*resize_wrappers, to_image, to_float, normalize])

    raise ValueError(f"unknown {image_set}")


def build_coco(image_set: str, args: Any, resolution: int) -> CocoDetection:
    root = Path(getattr(args, "dataset_dir", None) or args.coco_path)
    if not root.exists():
        logger.error(f"COCO path {root} does not exist")
        raise FileNotFoundError(f"COCO path {root} does not exist")

    mode = "instances"
    PATHS = {  # noqa: N806
        "train": (root / "train2017", root / "annotations" / f"{mode}_train2017.json"),
        "val": (root / "val2017", root / "annotations" / f"{mode}_val2017.json"),
        "test": (root / "test2017", root / "annotations" / "image_info_test-dev2017.json"),
    }

    img_folder, ann_file = PATHS[image_set.split("_")[0]]

    square_resize_div_64 = getattr(args, "square_resize_div_64", False)
    include_masks = getattr(args, "segmentation_head", False)
    aug_config = getattr(args, "aug_config", None)
    augmentation_backend = getattr(args, "augmentation_backend", "cpu")
    resolved_augmentation_backend = _resolve_runtime_augmentation_backend(augmentation_backend)
    if resolved_augmentation_backend != augmentation_backend and resolved_augmentation_backend == "cpu":
        logger.warning(
            "augmentation_backend='auto' resolved to 'cpu' because CUDA or kornia is unavailable; "
            "disabling GPU postprocess transforms and retaining CPU normalization."
        )
    gpu_postprocess = resolved_augmentation_backend != "cpu"

    if square_resize_div_64:
        logger.info(f"Building COCO {image_set} dataset with square resize at resolution {resolution}")
        dataset = CocoDetection(
            img_folder,
            ann_file,
            transforms=make_coco_transforms_square_div_64(
                image_set,
                resolution,
                multi_scale=args.multi_scale,
                expanded_scales=args.expanded_scales,
                skip_random_resize=not args.do_random_resize_via_padding,
                patch_size=args.patch_size,
                num_windows=args.num_windows,
                aug_config=aug_config,
                gpu_postprocess=gpu_postprocess,
            ),
            include_masks=include_masks,
        )
    else:
        logger.info(f"Building COCO {image_set} dataset at resolution {resolution}")
        dataset = CocoDetection(
            img_folder,
            ann_file,
            transforms=make_coco_transforms(
                image_set,
                resolution,
                multi_scale=args.multi_scale,
                expanded_scales=args.expanded_scales,
                skip_random_resize=not args.do_random_resize_via_padding,
                patch_size=args.patch_size,
                num_windows=args.num_windows,
                aug_config=aug_config,
                gpu_postprocess=gpu_postprocess,
            ),
            include_masks=include_masks,
        )
    return dataset


def _resolve_runtime_augmentation_backend(backend: str) -> str:
    """执行 `_resolve_runtime_augmentation_backend`。
    
    参数：
    - `backend`：传入的 `backend` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from backend.service.application.models.rfdetr_core.datasets.kornia_transforms import resolve_augmentation_backend

    return resolve_augmentation_backend(backend)


def build_roboflow_from_coco(image_set: str, args: Any, resolution: int) -> CocoDetection:
    """执行 `build_roboflow_from_coco`。
    
    参数：
    - `image_set`：传入的 `image_set` 参数。
    - `args`：传入的 `args` 参数。
    - `resolution`：传入的 `resolution` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    root = Path(args.dataset_dir)
    if not root.exists():
        logger.error(f"Roboflow dataset path {root} does not exist")
        raise FileNotFoundError(f"Roboflow dataset path {root} does not exist")

    PATHS = {  # noqa: N806
        "train": (root / "train", root / "train" / "_annotations.coco.json"),
        "val": (root / "valid", root / "valid" / "_annotations.coco.json"),
        "test": (root / "test", root / "test" / "_annotations.coco.json"),
    }

    img_folder, ann_file = PATHS[image_set.split("_")[0]]
    square_resize_div_64 = getattr(args, "square_resize_div_64", False)
    include_masks = getattr(args, "segmentation_head", False)
    multi_scale = getattr(args, "multi_scale", False)
    expanded_scales = getattr(args, "expanded_scales", False)
    do_random_resize_via_padding = getattr(args, "do_random_resize_via_padding", False)
    patch_size = getattr(args, "patch_size", 16)
    num_windows = getattr(args, "num_windows", 4)
    aug_config = getattr(args, "aug_config", None)
    resolved_augmentation_backend = _resolve_runtime_augmentation_backend(getattr(args, "augmentation_backend", "cpu"))
    gpu_postprocess = resolved_augmentation_backend != "cpu"

    if square_resize_div_64:
        logger.info(f"Building Roboflow {image_set} dataset with square resize at resolution {resolution}")
        dataset = CocoDetection(
            img_folder,
            ann_file,
            transforms=make_coco_transforms_square_div_64(
                image_set,
                resolution,
                multi_scale=multi_scale,
                expanded_scales=expanded_scales,
                skip_random_resize=not do_random_resize_via_padding,
                patch_size=patch_size,
                num_windows=num_windows,
                aug_config=aug_config,
                gpu_postprocess=gpu_postprocess,
            ),
            include_masks=include_masks,
            remap_category_ids=True,
        )
    else:
        logger.info(f"Building Roboflow {image_set} dataset at resolution {resolution}")
        dataset = CocoDetection(
            img_folder,
            ann_file,
            transforms=make_coco_transforms(
                image_set,
                resolution,
                multi_scale=multi_scale,
                expanded_scales=expanded_scales,
                skip_random_resize=not do_random_resize_via_padding,
                patch_size=patch_size,
                num_windows=num_windows,
                aug_config=aug_config,
                gpu_postprocess=gpu_postprocess,
            ),
            include_masks=include_masks,
            remap_category_ids=True,
        )
    return dataset


