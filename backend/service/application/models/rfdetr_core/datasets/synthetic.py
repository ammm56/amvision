"""RF-DETR core 数据集处理模块：`datasets.synthetic`。"""

import json
import logging
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Union

import cv2
import numpy as np
from tqdm.auto import tqdm
from typing_extensions import Literal

from backend.service.application.models.rfdetr_core import supervision_compat as sv

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatasetSplitRatios:
    """RF-DETR core 类：`DatasetSplitRatios`。"""

    train: float = 0.7
    val: float = 0.2
    test: float = 0.1

    def __post_init__(self):
        """执行 `__post_init__`。
        """
        total = self.train + self.val + self.test
        if any(r < 0 for r in [self.train, self.val, self.test]):
            raise ValueError(
                f"Split ratios must be non-negative, got train={self.train}, val={self.val}, test={self.test}"
            )
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"Split ratios must sum to 1.0, got {total}")

    def to_dict(self) -> Dict[str, float]:
        """执行 `to_dict`。
        
        返回：
        - 当前函数的执行结果。
        """
        return {k: v for k, v in {"train": self.train, "val": self.val, "test": self.test}.items() if v > 0}


DEFAULT_SPLIT_RATIOS = DatasetSplitRatios()


SplitRatiosType = Union[DatasetSplitRatios, Tuple[float, ...], Dict[str, float]]


def _normalize_split_ratios(split_ratios: SplitRatiosType) -> Dict[str, float]:
    """执行 `_normalize_split_ratios`。
    
    参数：
    - `split_ratios`：传入的 `split_ratios` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if isinstance(split_ratios, DatasetSplitRatios):
        return split_ratios.to_dict()

    if isinstance(split_ratios, tuple):
        if len(split_ratios) == 2:
            result = {"train": split_ratios[0], "val": split_ratios[1]}
        elif len(split_ratios) == 3:
            result = {"train": split_ratios[0], "val": split_ratios[1], "test": split_ratios[2]}
        else:
            raise ValueError(f"Split ratios tuple must have 2 or 3 elements, got {len(split_ratios)}")

        if any(ratio < 0 for ratio in split_ratios):
            raise ValueError(f"Split ratios must be non-negative, got {split_ratios}")
        total = sum(split_ratios)
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"Split ratios must sum to 1.0, got {total}")
        return result

    if isinstance(split_ratios, dict):
        if any(value < 0 for value in split_ratios.values()):
            raise ValueError(f"Split ratios must be non-negative, got {split_ratios}")
        total = sum(split_ratios.values())
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"Split ratios must sum to 1.0, got {total}")
        return split_ratios

    raise TypeError(f"split_ratios must be DatasetSplitRatios, tuple, or dict, got {type(split_ratios)}")


SYNTHETIC_SHAPES = ["square", "triangle", "circle"]
SYNTHETIC_COLORS = {"red": sv.Color.RED, "green": sv.Color.GREEN, "blue": sv.Color.BLUE}


def draw_synthetic_shape(
    img: np.ndarray, shape: str, color: sv.Color, center: Tuple[int, int], size: int
) -> Tuple[np.ndarray, List[float]]:
    """执行 `draw_synthetic_shape`。
    
    参数：
    - `img`：传入的 `img` 参数。
    - `shape`：传入的 `shape` 参数。
    - `color`：传入的 `color` 参数。
    - `center`：传入的 `center` 参数。
    - `size`：传入的 `size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    cx, cy = center
    half_size = size // 2

    if shape == "square":
        x1, y1 = cx - half_size, cy - half_size
        x2, y2 = cx + half_size, cy + half_size
        pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    elif shape == "triangle":
        height = int(size * 0.75)
        pts = [
            [cx, cy - 2 * height // 3],
            [cx - half_size, cy + height // 3],
            [cx + half_size, cy + height // 3],
        ]
    elif shape == "circle":
        r = half_size
        n_pts = 32
        pts = [
            [int(cx + r * math.cos(2 * math.pi * i / n_pts)), int(cy + r * math.sin(2 * math.pi * i / n_pts))]
            for i in range(n_pts)
        ]
    else:
        return img, []

    img = sv.draw_filled_polygon(scene=img, polygon=np.array(pts, dtype=np.int32), color=color)
    polygon = [float(v) for pt in pts for v in pt]
    return img, polygon


def calculate_boundary_overlap(bbox: np.ndarray, img_size: int) -> float:
    """执行 `calculate_boundary_overlap`。
    
    参数：
    - `bbox`：传入的 `bbox` 参数。
    - `img_size`：传入的 `img_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    x_min, y_min, x_max, y_max = bbox

    inside_x_min = max(x_min, 0)
    inside_y_min = max(y_min, 0)
    inside_x_max = min(x_max, img_size)
    inside_y_max = min(y_max, img_size)

    if inside_x_max > inside_x_min and inside_y_max > inside_y_min:
        inside_area = (inside_x_max - inside_x_min) * (inside_y_max - inside_y_min)
    else:
        inside_area = 0.0

    total_area = (x_max - x_min) * (y_max - y_min)
    return 1.0 - (inside_area / total_area) if total_area > 0 else 0.0


def generate_synthetic_sample(
    img_size: int,
    min_objects: int,
    max_objects: int,
    class_mode: Literal["shape", "color"],
    min_size_ratio: float = 0.1,
    max_size_ratio: float = 0.3,
    overlap_threshold: float = 0.1,
) -> Tuple[np.ndarray, sv.Detections]:
    """执行 `generate_synthetic_sample`。
    
    参数：
    - `img_size`：传入的 `img_size` 参数。
    - `min_objects`：传入的 `min_objects` 参数。
    - `max_objects`：传入的 `max_objects` 参数。
    - `class_mode`：传入的 `class_mode` 参数。
    - `min_size_ratio`：传入的 `min_size_ratio` 参数。
    - `max_size_ratio`：传入的 `max_size_ratio` 参数。
    - `overlap_threshold`：传入的 `overlap_threshold` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    img = np.ones((img_size, img_size, 3), dtype=np.uint8) * 128
    color_names = list(SYNTHETIC_COLORS.keys())
    num_objects = random.randint(min_objects, max_objects)

    xyxys = []
    class_ids = []
    polygons: List[List[float]] = []
    failed_attempts = 0
    max_failed_attempts = 3

    for _ in range(num_objects):
        shape = random.choice(SYNTHETIC_SHAPES)
        color_name = random.choice(color_names)
        color = SYNTHETIC_COLORS[color_name]

        if class_mode == "shape":
            category_id = SYNTHETIC_SHAPES.index(shape)
        else:
            category_id = color_names.index(color_name)

        min_size = max(10, int(img_size * min_size_ratio))
        max_size = max(min_size + 1, int(img_size * max_size_ratio))

        placed = False
        for _ in range(100):
            obj_size = random.randint(min_size, max_size)
            cx = random.randint(obj_size // 2, img_size - obj_size // 2)
            cy = random.randint(obj_size // 2, img_size - obj_size // 2)

            bbox = np.array(
                [float(cx - obj_size / 2), float(cy - obj_size / 2), float(cx + obj_size / 2), float(cy + obj_size / 2)]
            )

            if calculate_boundary_overlap(bbox, img_size) > 0.05:
                continue

            if len(xyxys) > 0:
                ious = sv.box_iou_batch(np.array([bbox]), np.array(xyxys))[0]
                if np.any(ious > overlap_threshold):
                    continue

            img, polygon = draw_synthetic_shape(img, shape, color, (cx, cy), obj_size)

            polygon_array = np.asarray(polygon, dtype=float).reshape(-1, 2)
            poly_x_min = float(np.min(polygon_array[:, 0]))
            poly_y_min = float(np.min(polygon_array[:, 1]))
            poly_x_max = float(np.max(polygon_array[:, 0]))
            poly_y_max = float(np.max(polygon_array[:, 1]))
            bbox_from_polygon = np.array([poly_x_min, poly_y_min, poly_x_max, poly_y_max], dtype=float)

            xyxys.append(bbox_from_polygon)
            class_ids.append(category_id)
            polygons.append(polygon)
            placed = True
            break

        if not placed:
            failed_attempts += 1
            if failed_attempts >= max_failed_attempts:
                break

    polygon_data = np.empty(len(class_ids), dtype=object)
    for i, poly in enumerate(polygons):
        polygon_data[i] = poly

    detections = sv.Detections(
        xyxy=np.array(xyxys) if xyxys else np.empty((0, 4)),
        class_id=np.array(class_ids) if class_ids else np.empty((0,), dtype=int),
        data={"polygons": polygon_data},
    )
    return img, detections


def _calculate_polygon_area(polygon: List[float]) -> float:
    """执行 `_calculate_polygon_area`。
    
    参数：
    - `polygon`：传入的 `polygon` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if len(polygon) < 6 or len(polygon) % 2 != 0:
        return 0.0

    points = np.asarray(polygon, dtype=float).reshape(-1, 2)
    x_coords = points[:, 0]
    y_coords = points[:, 1]
    return float(0.5 * abs(np.dot(x_coords, np.roll(y_coords, -1)) - np.dot(y_coords, np.roll(x_coords, -1))))


def _write_coco_json(
    annotations_path: Path,
    classes: List[str],
    file_paths: List[str],
    detections_list: List[sv.Detections],
    img_size: int,
    with_segmentation: bool = False,
) -> None:
    """执行 `_write_coco_json`。
    
    参数：
    - `annotations_path`：传入的 `annotations_path` 参数。
    - `classes`：传入的 `classes` 参数。
    - `file_paths`：传入的 `file_paths` 参数。
    - `detections_list`：传入的 `detections_list` 参数。
    - `img_size`：传入的 `img_size` 参数。
    - `with_segmentation`：传入的 `with_segmentation` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if len(file_paths) != len(detections_list):
        raise ValueError(
            "file_paths and detections_list must have the same length, "
            f"but got {len(file_paths)} and {len(detections_list)}"
        )

    categories = [{"id": idx * 2 + 1, "name": name, "supercategory": "synthetic"} for idx, name in enumerate(classes)]
    images_list = []
    annotations_list = []
    ann_id = 1

    for img_id, (file_path, detections) in enumerate(zip(file_paths, detections_list), start=1):
        images_list.append(
            {
                "id": img_id,
                "file_name": Path(file_path).name,
                "width": img_size,
                "height": img_size,
            }
        )
        if with_segmentation:
            polygon_data = detections.data.get("polygons")
            if polygon_data is None:
                raise ValueError(
                    f"with_segmentation=True but no 'polygons' found in detections.data "
                    f"for image index {img_id} (file: {file_path})"
                )
            if len(polygon_data) < len(detections):
                raise ValueError(
                    "with_segmentation=True requires a polygon entry for every detection (one per detection index), "
                    f"but got only {len(polygon_data)} polygon entries for {len(detections)} detections "
                    f"in image index {img_id} (file: {file_path})"
                )
        else:
            polygon_data = np.empty(0, dtype=object)
        for det_idx in range(len(detections)):
            x1, y1, x2, y2 = (float(v) for v in detections.xyxy[det_idx])
            w, h_box = x2 - x1, y2 - y1
            class_id = int(detections.class_id[det_idx])
            if class_id < 0 or class_id >= len(classes):
                raise ValueError(
                    "Invalid class_id {class_id} for detection index {det_idx} "
                    "in image index {img_id} (file: {file_path}); "
                    "expected 0 <= class_id < {num_classes}".format(
                        class_id=class_id,
                        det_idx=det_idx,
                        img_id=img_id,
                        file_path=file_path,
                        num_classes=len(classes),
                    )
                )
            category_id = class_id * 2 + 1
            annotation_area = w * h_box
            if with_segmentation:
                poly = polygon_data[det_idx] if det_idx < len(polygon_data) else None
                if poly is not None and hasattr(poly, "__len__") and len(poly) > 0:
                    poly_list = [float(value) for value in poly]
                    segmentation = [poly_list]
                    polygon_area = _calculate_polygon_area(poly_list)
                    if polygon_area > 0.0:
                        annotation_area = polygon_area
                else:
                    segmentation = []
            else:
                segmentation = []
            annotations_list.append(
                {
                    "id": ann_id,
                    "image_id": img_id,
                    "category_id": category_id,
                    "bbox": [x1, y1, w, h_box],
                    "area": annotation_area,
                    "iscrowd": 0,
                    "segmentation": segmentation,
                }
            )
            ann_id += 1

    with open(annotations_path, "w") as fh:
        json.dump({"images": images_list, "annotations": annotations_list, "categories": categories}, fh)


def generate_coco_dataset(
    output_dir: str,
    num_images: int,
    img_size: int = 640,
    class_mode: Literal["shape", "color"] = "shape",
    min_objects: int = 1,
    max_objects: int = 10,
    split_ratios: SplitRatiosType = DEFAULT_SPLIT_RATIOS,
    with_segmentation: bool = False,
) -> None:
    """执行 `generate_coco_dataset`。
    
    参数：
    - `output_dir`：传入的 `output_dir` 参数。
    - `num_images`：传入的 `num_images` 参数。
    - `img_size`：传入的 `img_size` 参数。
    - `class_mode`：传入的 `class_mode` 参数。
    - `min_objects`：传入的 `min_objects` 参数。
    - `max_objects`：传入的 `max_objects` 参数。
    - `split_ratios`：传入的 `split_ratios` 参数。
    - `with_segmentation`：传入的 `with_segmentation` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    split_ratios_dict = _normalize_split_ratios(split_ratios)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if class_mode == "shape":
        classes = SYNTHETIC_SHAPES
    else:
        classes = list(SYNTHETIC_COLORS.keys())

    all_indices = list(range(num_images))
    random.shuffle(all_indices)

    start_idx = 0
    split_items = list(split_ratios_dict.items())
    for split_idx, (split, ratio) in enumerate(split_items):
        if split_idx == len(split_items) - 1:
            num_split = len(all_indices) - start_idx
        else:
            num_split = int(num_images * ratio)
            if num_split == 0 and ratio > 0:
                num_split = 1
        split_indices = all_indices[start_idx : start_idx + num_split]
        start_idx += num_split

        if not split_indices:
            continue

        split_dir = output_path / split
        split_dir.mkdir(parents=True, exist_ok=True)
        annotations_path = split_dir / "_annotations.coco.json"

        file_paths_ordered: List[str] = []
        detections_ordered: List[sv.Detections] = []

        logger.info(f"Generating {split} split with {len(split_indices)} images...")
        for i in tqdm(split_indices, desc=f"Generating {split} split"):
            img, detections = generate_synthetic_sample(
                img_size,
                min_objects,
                max_objects,
                class_mode,
            )

            file_name = f"{i:06d}.jpg"
            file_path = str(split_dir / file_name)
            cv2.imwrite(file_path, img)

            file_paths_ordered.append(file_path)
            detections_ordered.append(detections)

        _write_coco_json(annotations_path, classes, file_paths_ordered, detections_ordered, img_size, with_segmentation)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate synthetic COCO dataset")
    parser.add_argument("--output", type=str, default="synthetic_dataset", help="Output directory")
    parser.add_argument("--num_images", type=int, default=100, help="Total number of images")
    parser.add_argument("--img_size", type=int, default=640, help="Image size (square)")
    parser.add_argument("--mode", type=str, choices=["shape", "color"], default="shape", help="Classification mode")

    args = parser.parse_args()
    generate_coco_dataset(args.output, args.num_images, args.img_size, args.mode)


