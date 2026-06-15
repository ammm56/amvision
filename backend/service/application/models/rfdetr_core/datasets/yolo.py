from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import torch

if TYPE_CHECKING:
    from backend.service.application.models.rfdetr_core import supervision_compat as sv
from PIL import Image, ImageDraw
from torchvision.datasets import VisionDataset

from backend.service.application.models.rfdetr_core.datasets.coco import (
    _resolve_runtime_augmentation_backend,
    make_coco_transforms,
    make_coco_transforms_square_div_64,
)

REQUIRED_YOLO_YAML_FILES = ["data.yaml", "data.yml"]
REQUIRED_SPLIT_DIRS = ["train", "valid"]
REQUIRED_DATA_SUBDIRS = ["images", "labels"]
YOLO_IMAGE_EXTENSIONS = {".bmp", ".dng", ".jpg", ".jpeg", ".mpo", ".png", ".tif", ".tiff", ".webp"}


def _parse_yolo_box(values: list[str]) -> np.ndarray:
    """执行 `_parse_yolo_box`。
    
    参数：
    - `values`：传入的 `values` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    x_center, y_center, width, height = values
    return np.array(
        [
            float(x_center) - float(width) / 2,
            float(y_center) - float(height) / 2,
            float(x_center) + float(width) / 2,
            float(y_center) + float(height) / 2,
        ],
        dtype=np.float32,
    )


def _box_to_polygon(box: np.ndarray) -> np.ndarray:
    """执行 `_box_to_polygon`。
    
    参数：
    - `box`：传入的 `box` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    return np.array(
        [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]],
        dtype=np.float32,
    )


def _parse_yolo_polygon(values: list[str]) -> np.ndarray:
    """执行 `_parse_yolo_polygon`。
    
    参数：
    - `values`：传入的 `values` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    return np.array(values, dtype=np.float32).reshape(-1, 2)


def _polygon_to_mask(polygon: np.ndarray, resolution_wh: tuple[int, int]) -> np.ndarray:
    """执行 `_polygon_to_mask`。
    
    参数：
    - `polygon`：传入的 `polygon` 参数。
    - `resolution_wh`：传入的 `resolution_wh` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    width, height = resolution_wh
    mask = Image.new("L", (width, height), 0)
    if polygon.size > 0:
        ImageDraw.Draw(mask).polygon([tuple(point) for point in polygon.tolist()], fill=1)
    return np.array(mask, dtype=bool)


def _polygons_to_masks(polygons: tuple[np.ndarray, ...], resolution_wh: tuple[int, int]) -> np.ndarray:
    """执行 `_polygons_to_masks`。
    
    参数：
    - `polygons`：传入的 `polygons` 参数。
    - `resolution_wh`：传入的 `resolution_wh` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if len(polygons) == 0:
        width, height = resolution_wh
        return np.zeros((0, height, width), dtype=bool)
    return np.stack([_polygon_to_mask(polygon, resolution_wh) for polygon in polygons])


def _list_yolo_image_paths(images_directory_path: str) -> list[str]:
    """执行 `_list_yolo_image_paths`。
    
    参数：
    - `images_directory_path`：传入的 `images_directory_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    return sorted(
        str(path)
        for path in Path(images_directory_path).iterdir()
        if path.is_file() and path.suffix.lower() in YOLO_IMAGE_EXTENSIONS
    )


def _extract_yolo_class_names(data_file: str) -> list[str]:
    """执行 `_extract_yolo_class_names`。
    
    参数：
    - `data_file`：传入的 `data_file` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    import yaml

    with Path(data_file).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in data file {data_file!r}, got {type(data).__name__}.")
    names = data.get("names")
    if isinstance(names, dict):
        numeric_keys: list[int] = []
        non_numeric_keys: list[Any] = []
        for key in names.keys():
            key_str = str(key)
            if key_str.isdigit():
                numeric_keys.append(int(key_str))
            else:
                non_numeric_keys.append(key)

        if not numeric_keys:
            raise ValueError(
                "Unsupported 'names' mapping in data file "
                f"{data_file!r}: expected integer keys 0..N-1 when 'names' is a dict, "
                f"got only non-numeric keys {list(names.keys())!r}. "
                "Please provide 'names' as a list or as a dict with 0-based contiguous "
                "integer keys."
            )

        unique_sorted_keys = sorted(set(numeric_keys))
        expected_keys = list(range(len(unique_sorted_keys)))
        if unique_sorted_keys != expected_keys or non_numeric_keys:
            raise ValueError(
                "Unsupported 'names' mapping in data file "
                f"{data_file!r}: expected integer keys 0..N-1 with no gaps, "
                f"got numeric keys {unique_sorted_keys!r} and "
                f"non-numeric keys {non_numeric_keys!r}. "
                "This loader assumes class IDs are contiguous 0..N-1; please remap "
                "the 'names' keys or use the list form."
            )

        return [str(names[idx]) for idx in unique_sorted_keys]
    if isinstance(names, list):
        return [str(name) for name in names]
    raise ValueError(f"Expected 'names' to be a list or dict in {data_file!r}, got {type(names).__name__}.")


@dataclass(frozen=True)
class _LazyYoloSample:
    """RF-DETR core 类：`_LazyYoloSample`。"""

    image_path: str
    width: int
    height: int
    xyxy: np.ndarray
    class_id: np.ndarray
    polygons: tuple[np.ndarray, ...]

    def to_detections(self) -> "sv.Detections":
        """执行 `to_detections`。
        
        返回：
        - 当前函数的执行结果。
        """
        from backend.service.application.models.rfdetr_core import supervision_compat as sv

        if len(self.class_id) == 0:
            return sv.Detections.empty()
        if len(self.polygons) == 0:
            return sv.Detections(class_id=self.class_id, xyxy=self.xyxy)
        mask = _polygons_to_masks(self.polygons, (self.width, self.height))
        return sv.Detections(class_id=self.class_id, xyxy=self.xyxy, mask=mask)


class _LazyYoloDetectionDataset:
    """RF-DETR core 类：`_LazyYoloDetectionDataset`。"""

    def __init__(self, classes: list[str], samples: list[_LazyYoloSample]) -> None:
        self.classes = classes
        self._samples = samples

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, idx: int) -> tuple[str, np.ndarray, "sv.Detections"]:
        import cv2

        sample = self._samples[idx]
        image = cv2.imread(sample.image_path)
        if image is None:
            raise ValueError(f"Could not read image from path: {sample.image_path}")
        return sample.image_path, image, sample.to_detections()

    def get_image_info(self, idx: int) -> _LazyYoloSample:
        """执行 `get_image_info`。
        
        参数：
        - `idx`：传入的 `idx` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        return self._samples[idx]


def _parse_yolo_label_line(
    values: list[str],
    line_num: int,
    label_path: Path,
    num_classes: int,
    width: int,
    height: int,
    *,
    parse_polygons: bool = True,
) -> tuple[int, np.ndarray, np.ndarray | None]:
    """执行 `_parse_yolo_label_line`。
    
    参数：
    - `values`：传入的 `values` 参数。
    - `line_num`：传入的 `line_num` 参数。
    - `label_path`：传入的 `label_path` 参数。
    - `num_classes`：传入的 `num_classes` 参数。
    - `width`：传入的 `width` 参数。
    - `height`：传入的 `height` 参数。
    - `parse_polygons`：传入的 `parse_polygons` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if len(values) < 5:
        raise ValueError(
            f"Malformed label in {str(label_path)!r} at line {line_num}: "
            f"expected 5 (bbox) fields or ≥ 7 fields for polygons "
            f"(class_id + at least 3 (x, y) points), got {len(values)}."
        )
    if len(values) > 5 and len(values[1:]) % 2 != 0:
        raise ValueError(
            f"Malformed polygon in {str(label_path)!r} at line {line_num}: "
            f"polygon coordinates must be paired (x, y) values, "
            f"but got {len(values[1:])} coordinate values (odd count)."
        )
    try:
        cid = int(values[0])
    except ValueError as exc:
        raise ValueError(
            f"Label {str(label_path)!r} line {line_num}: invalid class ID {values[0]!r} (must be an integer)."
        ) from exc
    if cid < 0 or cid >= num_classes:
        raise ValueError(
            f"Label {str(label_path)!r} line {line_num}: "
            f"class ID {cid} is out of range for dataset with {num_classes} classes "
            f"(valid range 0\u2013{num_classes - 1})."
        )
    if len(values) == 5:
        box = _parse_yolo_box(values[1:])
        polygon: np.ndarray | None = _box_to_polygon(box) if parse_polygons else None
    else:
        try:
            _raw_polygon = _parse_yolo_polygon(values[1:])
        except ValueError as exc:
            raise ValueError(
                f"Malformed polygon in {str(label_path)!r} at line {line_num}: "
                f"could not parse coordinate values as floats."
            ) from exc
        box = np.array(
            [
                np.min(_raw_polygon[:, 0]),
                np.min(_raw_polygon[:, 1]),
                np.max(_raw_polygon[:, 0]),
                np.max(_raw_polygon[:, 1]),
            ],
            dtype=np.float32,
        )
        polygon = _raw_polygon if parse_polygons else None
    xyxy_px = box * np.array([width, height, width, height], dtype=np.float32)
    if polygon is None:
        return cid, xyxy_px, None
    polygon_px = polygon * np.array([width, height], dtype=np.float32)
    polygon_px[:, 0] = np.clip(polygon_px[:, 0], 0.0, float(width - 1))
    polygon_px[:, 1] = np.clip(polygon_px[:, 1], 0.0, float(height - 1))
    return cid, xyxy_px, polygon_px.astype(np.float32)


def _build_yolo_samples(
    img_folder: str, lb_folder: str, data_file: str, *, include_polygons: bool
) -> tuple[list[str], list[_LazyYoloSample]]:
    """执行 `_build_yolo_samples`。
    
    参数：
    - `img_folder`：传入的 `img_folder` 参数。
    - `lb_folder`：传入的 `lb_folder` 参数。
    - `data_file`：传入的 `data_file` 参数。
    - `include_polygons`：传入的 `include_polygons` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    classes = _extract_yolo_class_names(data_file)
    samples: list[_LazyYoloSample] = []

    for image_path in _list_yolo_image_paths(img_folder):
        label_path = Path(lb_folder) / f"{Path(image_path).stem}.txt"
        with Image.open(image_path) as image:
            width, height = image.size

        xyxy: list[np.ndarray] = []
        class_id: list[int] = []
        polygons: list[np.ndarray] = []
        if label_path.exists():
            with label_path.open(encoding="utf-8") as handle:
                lines = [line.strip() for line in handle if line.strip()]
            for i, line in enumerate(lines):
                cid, xyxy_px, polygon_px = _parse_yolo_label_line(
                    line.split(),
                    i + 1,
                    label_path,
                    len(classes),
                    width,
                    height,
                    parse_polygons=include_polygons,
                )
                class_id.append(cid)
                xyxy.append(xyxy_px)
                if include_polygons and polygon_px is not None:
                    polygons.append(polygon_px)

        samples.append(
            _LazyYoloSample(
                image_path=image_path,
                width=width,
                height=height,
                xyxy=np.array(xyxy, dtype=np.float32).reshape(-1, 4),
                class_id=np.array(class_id, dtype=np.int64),
                polygons=tuple(polygons),
            )
        )

    return classes, samples


def _build_lazy_yolo_detection_dataset(img_folder: str, lb_folder: str, data_file: str) -> _LazyYoloDetectionDataset:
    """执行 `_build_lazy_yolo_detection_dataset`。
    
    参数：
    - `img_folder`：传入的 `img_folder` 参数。
    - `lb_folder`：传入的 `lb_folder` 参数。
    - `data_file`：传入的 `data_file` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    classes, samples = _build_yolo_samples(img_folder, lb_folder, data_file, include_polygons=False)
    return _LazyYoloDetectionDataset(classes=classes, samples=samples)


def _build_lazy_yolo_segmentation_dataset(img_folder: str, lb_folder: str, data_file: str) -> _LazyYoloDetectionDataset:
    """执行 `_build_lazy_yolo_segmentation_dataset`。
    
    参数：
    - `img_folder`：传入的 `img_folder` 参数。
    - `lb_folder`：传入的 `lb_folder` 参数。
    - `data_file`：传入的 `data_file` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    classes, samples = _build_yolo_samples(img_folder, lb_folder, data_file, include_polygons=True)
    return _LazyYoloDetectionDataset(classes=classes, samples=samples)


def _build_coco_api_from_samples(classes: list[str], dataset: Any) -> Any:
    """执行 `_build_coco_api_from_samples`。
    
    参数：
    - `classes`：传入的 `classes` 参数。
    - `dataset`：传入的 `dataset` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from pycocotools.coco import COCO

    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = [
        {"id": idx, "name": class_name, "supercategory": "none"} for idx, class_name in enumerate(classes)
    ]

    use_lazy_path = hasattr(dataset, "get_image_info")
    ann_id = 0
    for img_id in range(len(dataset)):
        if use_lazy_path:
            sample = dataset.get_image_info(img_id)
            image_path = sample.image_path
            height, width = sample.height, sample.width
            xyxy = sample.xyxy
            class_id = sample.class_id
            has_masks = len(sample.polygons) > 0
        else:
            image_path, cv2_image, detections = dataset[img_id]
            height, width = cv2_image.shape[:2]
            xyxy = detections.xyxy
            class_id = detections.class_id
            has_masks = detections.mask is not None

        images.append({"id": img_id, "file_name": str(image_path), "height": int(height), "width": int(width)})

        for i in range(len(xyxy)):
            x1, y1, x2, y2 = xyxy[i]
            bbox_x, bbox_y = float(x1), float(y1)
            bbox_w, bbox_h = float(x2 - x1), float(y2 - y1)
            ann = {
                "id": ann_id,
                "image_id": img_id,
                "category_id": int(class_id[i]),
                "bbox": [bbox_x, bbox_y, bbox_w, bbox_h],
                "area": float(bbox_w * bbox_h),
                "iscrowd": 0,
            }
            if has_masks:
                ann["segmentation"] = []
            annotations.append(ann)
            ann_id += 1

    coco_dataset = {
        "info": {"description": "RF-DETR YOLO dataset"},
        "images": images,
        "annotations": annotations,
        "categories": categories,
    }
    coco = COCO()
    coco.dataset = coco_dataset
    coco.createIndex()
    return coco


def is_valid_yolo_dataset(dataset_dir: str) -> bool:
    """执行 `is_valid_yolo_dataset`。
    
    参数：
    - `dataset_dir`：传入的 `dataset_dir` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    contains_required_yolo_yaml = any(
        os.path.exists(os.path.join(dataset_dir, yaml_file)) for yaml_file in REQUIRED_YOLO_YAML_FILES
    )
    contains_required_split_dirs = all(
        os.path.exists(os.path.join(dataset_dir, split_dir)) for split_dir in REQUIRED_SPLIT_DIRS
    )
    contains_required_data_subdirs = all(
        os.path.exists(os.path.join(dataset_dir, split_dir, data_subdir))
        for split_dir in REQUIRED_SPLIT_DIRS
        for data_subdir in REQUIRED_DATA_SUBDIRS
    )
    return contains_required_yolo_yaml and contains_required_split_dirs and contains_required_data_subdirs


class ConvertYolo:
    """RF-DETR core 类：`ConvertYolo`。"""

    def __init__(self, include_masks: bool = False):
        self.include_masks = include_masks

    def __call__(self, image: Image.Image, target: dict) -> tuple:
        """执行 `__call__`。
        
        参数：
        - `image`：传入的 `image` 参数。
        - `target`：传入的 `target` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        w, h = image.size

        image_id = target["image_id"]
        image_id = torch.tensor([image_id])

        detections = target["detections"]

        if len(detections) > 0:
            boxes = torch.from_numpy(detections.xyxy).to(torch.float32)
            classes = torch.from_numpy(detections.class_id).to(torch.int64)
        else:
            boxes = torch.zeros((0, 4), dtype=torch.float32)
            classes = torch.zeros((0,), dtype=torch.int64)

        boxes[:, 0::2].clamp_(min=0, max=w)
        boxes[:, 1::2].clamp_(min=0, max=h)

        keep = (boxes[:, 3] > boxes[:, 1]) & (boxes[:, 2] > boxes[:, 0])
        boxes = boxes[keep]
        classes = classes[keep]

        target_out = {}
        target_out["boxes"] = boxes
        target_out["labels"] = classes
        target_out["image_id"] = image_id

        area = (boxes[:, 3] - boxes[:, 1]) * (boxes[:, 2] - boxes[:, 0])
        target_out["area"] = area

        iscrowd = torch.zeros((classes.shape[0],), dtype=torch.int64)
        target_out["iscrowd"] = iscrowd

        if self.include_masks:
            if detections.mask is not None and np.size(detections.mask) > 0:
                masks = torch.from_numpy(detections.mask[keep.cpu().numpy()]).to(torch.uint8)
                target_out["masks"] = masks
            else:
                target_out["masks"] = torch.zeros((0, h, w), dtype=torch.uint8)

            target_out["masks"] = target_out["masks"].bool()

        target_out["orig_size"] = torch.as_tensor([int(h), int(w)])
        target_out["size"] = torch.as_tensor([int(h), int(w)])

        return image, target_out


class YoloDetection(VisionDataset):
    """RF-DETR core 类：`YoloDetection`。"""

    def __init__(
        self,
        img_folder: str,
        lb_folder: str,
        data_file: str,
        transforms=None,
        include_masks: bool = False,
    ):
        super(YoloDetection, self).__init__(img_folder)
        self._transforms = transforms
        self.include_masks = include_masks
        self.prepare = ConvertYolo(include_masks=include_masks)

        if include_masks:
            self.sv_dataset = _build_lazy_yolo_segmentation_dataset(img_folder, lb_folder, data_file)
        else:
            self.sv_dataset = _build_lazy_yolo_detection_dataset(img_folder, lb_folder, data_file)

        self.classes = self.sv_dataset.classes
        self.ids = list(range(len(self.sv_dataset)))

        self.coco = _build_coco_api_from_samples(self.classes, self.sv_dataset)

    def __len__(self) -> int:
        return len(self.sv_dataset)

    def __getitem__(self, idx: int):
        image_id = self.ids[idx]
        image_path, cv2_image, detections = self.sv_dataset[idx]

        rgb_image = cv2_image[:, :, ::-1]
        img = Image.fromarray(rgb_image)

        target = {"image_id": image_id, "detections": detections}
        img, target = self.prepare(img, target)

        if self._transforms is not None:
            img, target = self._transforms(img, target)

        return img, target


def build_roboflow_from_yolo(image_set: str, args: Any, resolution: int) -> YoloDetection:
    """执行 `build_roboflow_from_yolo`。
    
    参数：
    - `image_set`：传入的 `image_set` 参数。
    - `args`：传入的 `args` 参数。
    - `resolution`：传入的 `resolution` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    root = Path(args.dataset_dir)
    assert root.exists(), f"provided Roboflow path {root} does not exist"

    PATHS = {  # noqa: N806
        "train": (root / "train" / "images", root / "train" / "labels"),
        "val": (root / "valid" / "images", root / "valid" / "labels"),
        "test": (root / "test" / "images", root / "test" / "labels"),
    }

    data_file = next((root / f for f in REQUIRED_YOLO_YAML_FILES if (root / f).exists()), root / "data.yaml")
    img_folder, lb_folder = PATHS[image_set.split("_")[0]]
    square_resize_div_64 = getattr(args, "square_resize_div_64", False)
    include_masks = getattr(args, "segmentation_head", False)
    multi_scale = getattr(args, "multi_scale", False)
    expanded_scales = getattr(args, "expanded_scales", None)
    do_random_resize_via_padding = getattr(args, "do_random_resize_via_padding", False)
    patch_size = getattr(args, "patch_size", None)
    num_windows = getattr(args, "num_windows", None)
    aug_config = getattr(args, "aug_config", None)
    resolved_augmentation_backend = _resolve_runtime_augmentation_backend(getattr(args, "augmentation_backend", "cpu"))
    gpu_postprocess = resolved_augmentation_backend != "cpu"

    if square_resize_div_64:
        dataset = YoloDetection(
            img_folder=str(img_folder),
            lb_folder=str(lb_folder),
            data_file=str(data_file),
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
        )
    else:
        dataset = YoloDetection(
            img_folder=str(img_folder),
            lb_folder=str(lb_folder),
            data_file=str(data_file),
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
        )
    return dataset


