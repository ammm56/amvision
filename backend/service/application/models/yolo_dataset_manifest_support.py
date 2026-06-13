"""YOLO 数据集 manifest 解析辅助。

把 YOLO segmentation / pose 的目录型标签转成项目内部统一消费的
COCO 风格内存载荷，供训练与评估链复用。
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image

from backend.service.application.errors import InvalidRequestError

_YOLO_IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def normalize_yolo_category_names(
    *,
    category_names: object,
    format_label: str,
) -> tuple[str, ...]:
    """归一化 YOLO manifest 中的类别名列表。"""

    normalized = tuple(
        name
        for item in (category_names if isinstance(category_names, list | tuple) else ())
        if (name := str(item).strip())
    )
    if not normalized:
        raise InvalidRequestError(f"{format_label} manifest 缺少有效的 category_names")
    return normalized


def build_coco_payload_from_yolo_segmentation_split(
    *,
    split_name: str,
    image_root: Path,
    label_root: Path,
    category_names: tuple[str, ...],
) -> dict[str, object]:
    """把 YOLO instance segmentation split 转成 COCO 风格内存载荷。"""

    images_payload: list[dict[str, object]] = []
    annotations_payload: list[dict[str, object]] = []
    categories_payload = [
        {"id": category_index, "name": category_name}
        for category_index, category_name in enumerate(category_names)
    ]
    annotation_id = 1
    for image_id, image_path in enumerate(iter_yolo_image_files(image_root), start=1):
        image_height, image_width = read_yolo_image_shape(image_path)
        relative_image_path = image_path.relative_to(image_root)
        images_payload.append(
            {
                "id": image_id,
                "file_name": relative_image_path.as_posix(),
                "width": image_width,
                "height": image_height,
            }
        )
        label_path = (label_root / relative_image_path).with_suffix(".txt")
        rows, annotation_id = _parse_yolo_segmentation_label_file(
            label_path=label_path,
            split_name=split_name,
            image_id=image_id,
            image_width=image_width,
            image_height=image_height,
            category_count=len(category_names),
            next_annotation_id=annotation_id,
        )
        annotations_payload.extend(rows)
    return {
        "images": images_payload,
        "annotations": annotations_payload,
        "categories": categories_payload,
    }


def build_coco_payload_from_yolo_pose_split(
    *,
    split_name: str,
    image_root: Path,
    label_root: Path,
    category_names: tuple[str, ...],
    pose_shape: tuple[int, int] | None = None,
) -> dict[str, object]:
    """把 YOLO pose split 转成 COCO 风格内存载荷。"""

    images_payload: list[dict[str, object]] = []
    annotations_payload: list[dict[str, object]] = []
    categories_payload = [
        {"id": category_index, "name": category_name}
        for category_index, category_name in enumerate(category_names)
    ]
    annotation_id = 1
    for image_id, image_path in enumerate(iter_yolo_image_files(image_root), start=1):
        image_height, image_width = read_yolo_image_shape(image_path)
        relative_image_path = image_path.relative_to(image_root)
        images_payload.append(
            {
                "id": image_id,
                "file_name": relative_image_path.as_posix(),
                "width": image_width,
                "height": image_height,
            }
        )
        label_path = (label_root / relative_image_path).with_suffix(".txt")
        rows, annotation_id = _parse_yolo_pose_label_file(
            label_path=label_path,
            split_name=split_name,
            image_id=image_id,
            image_width=image_width,
            image_height=image_height,
            category_count=len(category_names),
            next_annotation_id=annotation_id,
            pose_shape=pose_shape,
        )
        annotations_payload.extend(rows)
    return {
        "images": images_payload,
        "annotations": annotations_payload,
        "categories": categories_payload,
    }


def iter_yolo_image_files(image_root: Path) -> tuple[Path, ...]:
    """收集 YOLO 数据集目录下全部图片。"""

    return tuple(
        sorted(
            (
                candidate
                for candidate in image_root.rglob("*")
                if candidate.is_file() and candidate.suffix.lower() in _YOLO_IMAGE_SUFFIXES
            ),
            key=lambda item: item.as_posix().lower(),
        )
    )


def read_yolo_image_shape(image_path: Path) -> tuple[int, int]:
    """读取一张 YOLO 数据集图片的尺寸。"""

    try:
        with Image.open(image_path) as image:
            image_width, image_height = image.size
    except Exception as error:  # pragma: no cover - 依赖 Pillow 具体异常类型
        raise InvalidRequestError(
            "训练或评估输入图片无法读取",
            details={"image_path": str(image_path)},
        ) from error
    if image_height <= 0 or image_width <= 0:
        raise InvalidRequestError(
            "训练或评估输入图片尺寸无效",
            details={"image_path": str(image_path)},
        )
    return image_height, image_width


def _parse_yolo_segmentation_label_file(
    *,
    label_path: Path,
    split_name: str,
    image_id: int,
    image_width: int,
    image_height: int,
    category_count: int,
    next_annotation_id: int,
) -> tuple[list[dict[str, object]], int]:
    """解析一个 YOLO segmentation label 文件。"""

    if not label_path.is_file():
        return [], next_annotation_id
    annotation_rows: list[dict[str, object]] = []
    annotation_id = next_annotation_id
    for line_index, raw_line in enumerate(
        label_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 7 or (len(parts) - 1) % 2 != 0:
            raise InvalidRequestError(
                "YOLO segmentation 标注行必须是 class_id 加偶数个 polygon 坐标",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                },
            )
        try:
            category_index = int(parts[0])
            polygon_values = [float(value) for value in parts[1:]]
        except ValueError as error:
            raise InvalidRequestError(
                "YOLO segmentation 标注行包含非法数字",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                },
            ) from error
        if category_index < 0 or category_index >= category_count:
            raise InvalidRequestError(
                "YOLO segmentation 标注行类别索引越界",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                    "category_index": category_index,
                    "category_count": category_count,
                },
            )
        polygon_xy = _build_pixel_polygon_from_yolo_values(
            raw_values=polygon_values,
            image_width=image_width,
            image_height=image_height,
            label_path=label_path,
            split_name=split_name,
            line_index=line_index,
        )
        bbox_xywh = _build_bbox_from_polygon(polygon_xy)
        annotation_rows.append(
            {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": category_index,
                "bbox": list(bbox_xywh),
                "segmentation": [list(polygon_xy)],
                "area": _compute_polygon_area(polygon_xy),
                "iscrowd": 0,
            }
        )
        annotation_id += 1
    return annotation_rows, annotation_id


def _parse_yolo_pose_label_file(
    *,
    label_path: Path,
    split_name: str,
    image_id: int,
    image_width: int,
    image_height: int,
    category_count: int,
    next_annotation_id: int,
    pose_shape: tuple[int, int] | None,
) -> tuple[list[dict[str, object]], int]:
    """解析一个 YOLO pose label 文件。"""

    if not label_path.is_file():
        return [], next_annotation_id
    annotation_rows: list[dict[str, object]] = []
    annotation_id = next_annotation_id
    for line_index, raw_line in enumerate(
        label_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 7:
            raise InvalidRequestError(
                "YOLO pose 标注行至少需要 bbox 和一个关键点",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                },
            )
        try:
            category_index = int(parts[0])
            x_center = float(parts[1])
            y_center = float(parts[2])
            box_width = float(parts[3])
            box_height = float(parts[4])
            keypoint_values = [float(value) for value in parts[5:]]
        except ValueError as error:
            raise InvalidRequestError(
                "YOLO pose 标注行包含非法数字",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                },
            ) from error
        if category_index < 0 or category_index >= category_count:
            raise InvalidRequestError(
                "YOLO pose 标注行类别索引越界",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                    "category_index": category_index,
                    "category_count": category_count,
                },
            )
        if box_width <= 0.0 or box_height <= 0.0:
            continue
        point_count, point_dimensions = _resolve_yolo_pose_shape(
            keypoint_values=keypoint_values,
            pose_shape=pose_shape,
            split_name=split_name,
            label_path=label_path,
            line_index=line_index,
        )
        bbox_xywh = _build_bbox_from_yolo_normalized_xywh(
            x_center=x_center,
            y_center=y_center,
            box_width=box_width,
            box_height=box_height,
            image_width=image_width,
            image_height=image_height,
        )
        normalized_keypoints: list[float] = []
        num_keypoints = 0
        if point_dimensions == 3:
            for point_index in range(0, len(keypoint_values), 3):
                point_x = keypoint_values[point_index] * image_width
                point_y = keypoint_values[point_index + 1] * image_height
                visibility = float(keypoint_values[point_index + 2])
                normalized_keypoints.extend([point_x, point_y, visibility])
                if visibility > 0:
                    num_keypoints += 1
        else:
            for point_index in range(0, len(keypoint_values), 2):
                point_x = keypoint_values[point_index] * image_width
                point_y = keypoint_values[point_index + 1] * image_height
                normalized_keypoints.extend([point_x, point_y, 2.0])
                num_keypoints += 1
        annotation_rows.append(
            {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": category_index,
                "bbox": list(bbox_xywh),
                "keypoints": normalized_keypoints,
                "num_keypoints": num_keypoints,
                "area": float(bbox_xywh[2]) * float(bbox_xywh[3]),
                "iscrowd": 0,
                "metadata": {
                    "keypoint_count": point_count,
                    "point_dimensions": point_dimensions,
                },
            }
        )
        annotation_id += 1
    return annotation_rows, annotation_id


def _resolve_yolo_pose_shape(
    *,
    keypoint_values: list[float],
    pose_shape: tuple[int, int] | None,
    split_name: str,
    label_path: Path,
    line_index: int,
) -> tuple[int, int]:
    """解析单行 YOLO pose 标注的关键点维度。"""

    if pose_shape is not None:
        keypoint_count, point_dimensions = pose_shape
        expected_value_count = keypoint_count * point_dimensions
        if len(keypoint_values) != expected_value_count:
            raise InvalidRequestError(
                "YOLO pose 标注与 kpt_shape 不匹配",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                    "expected_value_count": expected_value_count,
                    "actual_value_count": len(keypoint_values),
                },
            )
        return keypoint_count, point_dimensions
    if len(keypoint_values) % 3 == 0:
        return len(keypoint_values) // 3, 3
    if len(keypoint_values) % 2 == 0:
        return len(keypoint_values) // 2, 2
    raise InvalidRequestError(
        "YOLO pose 标注关键点列数不合法",
        details={
            "split_name": split_name,
            "label_file": str(label_path),
            "line_index": line_index,
        },
    )


def _build_bbox_from_yolo_normalized_xywh(
    *,
    x_center: float,
    y_center: float,
    box_width: float,
    box_height: float,
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float]:
    """把 YOLO 归一化 bbox 转成像素 xywh。"""

    normalized_x1 = x_center - (box_width / 2.0)
    normalized_y1 = y_center - (box_height / 2.0)
    normalized_x2 = x_center + (box_width / 2.0)
    normalized_y2 = y_center + (box_height / 2.0)
    x1 = max(0.0, min(normalized_x1 * float(image_width), float(image_width)))
    y1 = max(0.0, min(normalized_y1 * float(image_height), float(image_height)))
    x2 = max(0.0, min(normalized_x2 * float(image_width), float(image_width)))
    y2 = max(0.0, min(normalized_y2 * float(image_height), float(image_height)))
    return (x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1))


def _build_pixel_polygon_from_yolo_values(
    *,
    raw_values: list[float],
    image_width: int,
    image_height: int,
    label_path: Path,
    split_name: str,
    line_index: int,
) -> tuple[float, ...]:
    """把 YOLO 归一化 polygon 坐标转成像素点。"""

    if len(raw_values) < 6 or len(raw_values) % 2 != 0:
        raise InvalidRequestError(
            "YOLO polygon 至少需要 3 个点，且坐标数量必须成对出现",
            details={
                "split_name": split_name,
                "label_file": str(label_path),
                "line_index": line_index,
            },
        )
    polygon_xy: list[float] = []
    for point_index in range(0, len(raw_values), 2):
        point_x = float(raw_values[point_index]) * image_width
        point_y = float(raw_values[point_index + 1]) * image_height
        polygon_xy.extend([point_x, point_y])
    return tuple(polygon_xy)


def _build_bbox_from_polygon(polygon_xy: tuple[float, ...]) -> tuple[float, float, float, float]:
    """根据 polygon 计算轴对齐 bbox。"""

    xs = [float(polygon_xy[index]) for index in range(0, len(polygon_xy), 2)]
    ys = [float(polygon_xy[index]) for index in range(1, len(polygon_xy), 2)]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    return (min_x, min_y, max_x - min_x, max_y - min_y)


def _compute_polygon_area(polygon_xy: tuple[float, ...]) -> float:
    """用鞋带公式计算 polygon 面积。"""

    points = [
        (float(polygon_xy[index]), float(polygon_xy[index + 1]))
        for index in range(0, len(polygon_xy), 2)
    ]
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


__all__ = [
    "build_coco_payload_from_yolo_pose_split",
    "build_coco_payload_from_yolo_segmentation_split",
    "iter_yolo_image_files",
    "normalize_yolo_category_names",
    "read_yolo_image_shape",
]
