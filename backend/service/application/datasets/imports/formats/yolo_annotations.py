"""YOLO 各任务标注行解析逻辑。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.datasets.imports.formats.common import (
    _build_bbox_from_polygon,
    _compute_polygon_area,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetAnnotation,
    DetectionAnnotation,
    InstanceSegmentationAnnotation,
    ObbAnnotation,
    PoseAnnotation,
)


class YoloAnnotationParserMixin:
    """解析 YOLO detection / segmentation / pose / obb 标注。"""

    def _build_yolo_dataset_annotation(
        self,
        *,
        task_type: str,
        annotation_id: str,
        category_id: int,
        annotation_row: dict[str, object],
        metadata: dict[str, object],
    ) -> DatasetAnnotation:
        """把 YOLO raw annotation row 转成平台内部 annotation。"""

        if task_type == "segmentation":
            return InstanceSegmentationAnnotation(
                annotation_id=annotation_id,
                category_id=category_id,
                bbox_xywh=tuple(annotation_row["bbox_xywh"]),
                segmentation=list(annotation_row["segmentation"]),
                area=float(annotation_row["area"]),
                metadata=metadata,
            )
        if task_type == "pose":
            return PoseAnnotation(
                annotation_id=annotation_id,
                category_id=category_id,
                bbox_xywh=tuple(annotation_row["bbox_xywh"]),
                keypoints=list(annotation_row["keypoints"]),
                num_keypoints=int(annotation_row["num_keypoints"]),
                area=float(annotation_row["area"]),
                metadata=metadata,
            )
        if task_type == "obb":
            return ObbAnnotation(
                annotation_id=annotation_id,
                category_id=category_id,
                bbox_xywh=tuple(annotation_row["bbox_xywh"]),
                polygon_xy=tuple(annotation_row["polygon_xy"]),
                area=float(annotation_row["area"]),
                metadata=metadata,
            )
        return DetectionAnnotation(
            annotation_id=annotation_id,
            category_id=category_id,
            bbox_xywh=tuple(annotation_row["bbox_xywh"]),
            area=float(annotation_row["area"]),
            metadata=metadata,
        )

    def _parse_yolo_detection_annotation(
        self,
        *,
        line: str,
        image_width: int,
        image_height: int,
        label_file: Path,
        dataset_root: Path,
        line_index: int,
    ) -> dict[str, object]:
        """解析一行 YOLO detection 标注。"""

        parts = line.split()
        if len(parts) != 5:
            raise InvalidRequestError(
                "YOLO detection 标注行必须是 5 列",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            )
        class_id = self._normalize_yolo_class_id(
            raw_value=parts[0],
            label_file=label_file,
            dataset_root=dataset_root,
            line_index=line_index,
        )
        bbox_xywh = self._build_bbox_from_yolo_normalized_xywh(
            raw_values=parts[1:5],
            image_width=image_width,
            image_height=image_height,
            label_file=label_file,
            dataset_root=dataset_root,
            line_index=line_index,
        )
        return {
            "class_id": class_id,
            "bbox_xywh": bbox_xywh,
            "area": float(bbox_xywh[2]) * float(bbox_xywh[3]),
            "metadata": {},
        }

    def _parse_yolo_segmentation_annotation(
        self,
        *,
        line: str,
        image_width: int,
        image_height: int,
        label_file: Path,
        dataset_root: Path,
        line_index: int,
    ) -> dict[str, object]:
        """解析一行 YOLO instance segmentation 标注。"""

        parts = line.split()
        if len(parts) < 7 or (len(parts) - 1) % 2 != 0:
            raise InvalidRequestError(
                "YOLO segmentation 标注行必须是 class_id 加偶数个 polygon 坐标",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            )
        class_id = self._normalize_yolo_class_id(
            raw_value=parts[0],
            label_file=label_file,
            dataset_root=dataset_root,
            line_index=line_index,
        )
        polygon_xy = self._build_pixel_polygon_from_yolo_values(
            raw_values=parts[1:],
            image_width=image_width,
            image_height=image_height,
            label_file=label_file,
            dataset_root=dataset_root,
            line_index=line_index,
        )
        bbox_xywh = _build_bbox_from_polygon(polygon_xy)
        return {
            "class_id": class_id,
            "bbox_xywh": bbox_xywh,
            "segmentation": [list(polygon_xy)],
            "area": _compute_polygon_area(polygon_xy),
            "metadata": {},
        }

    def _parse_yolo_pose_annotation(
        self,
        *,
        line: str,
        image_width: int,
        image_height: int,
        label_file: Path,
        dataset_root: Path,
        line_index: int,
        pose_shape: tuple[int, int] | None,
    ) -> dict[str, object]:
        """解析一行 YOLO pose 标注。"""

        parts = line.split()
        if len(parts) < 7:
            raise InvalidRequestError(
                "YOLO pose 标注行至少需要 bbox 和一个关键点",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            )
        class_id = self._normalize_yolo_class_id(
            raw_value=parts[0],
            label_file=label_file,
            dataset_root=dataset_root,
            line_index=line_index,
        )
        bbox_xywh = self._build_bbox_from_yolo_normalized_xywh(
            raw_values=parts[1:5],
            image_width=image_width,
            image_height=image_height,
            label_file=label_file,
            dataset_root=dataset_root,
            line_index=line_index,
        )
        keypoint_values = [float(value) for value in parts[5:]]
        if pose_shape is not None:
            keypoint_count, point_dimensions = pose_shape
            expected_value_count = keypoint_count * point_dimensions
            if len(keypoint_values) != expected_value_count:
                raise InvalidRequestError(
                    "YOLO pose 标注与 kpt_shape 不匹配",
                    details={
                        "label_file": self._relative_path_from_any(
                            label_file,
                            dataset_root,
                            label_file.parent,
                        ),
                        "line_index": line_index,
                        "expected_value_count": expected_value_count,
                        "actual_value_count": len(keypoint_values),
                    },
                )
        elif len(keypoint_values) % 3 == 0:
            point_dimensions = 3
            keypoint_count = len(keypoint_values) // 3
        elif len(keypoint_values) % 2 == 0:
            point_dimensions = 2
            keypoint_count = len(keypoint_values) // 2
        else:
            raise InvalidRequestError(
                "YOLO pose 标注关键点列数不合法",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
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

        return {
            "class_id": class_id,
            "bbox_xywh": bbox_xywh,
            "keypoints": normalized_keypoints,
            "num_keypoints": num_keypoints,
            "area": float(bbox_xywh[2]) * float(bbox_xywh[3]),
            "metadata": {
                "keypoint_count": keypoint_count,
                "point_dimensions": point_dimensions,
            },
        }

    def _parse_yolo_obb_annotation(
        self,
        *,
        line: str,
        image_width: int,
        image_height: int,
        label_file: Path,
        dataset_root: Path,
        line_index: int,
    ) -> dict[str, object]:
        """解析一行 YOLO OBB 标注。"""

        parts = line.split()
        if len(parts) < 9:
            raise InvalidRequestError(
                "YOLO OBB 标注行至少需要 class_id 和 8 个四角点坐标",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            )
        class_id = self._normalize_yolo_class_id(
            raw_value=parts[0],
            label_file=label_file,
            dataset_root=dataset_root,
            line_index=line_index,
        )
        polygon_xy = self._build_pixel_polygon_from_yolo_values(
            raw_values=parts[1:9],
            image_width=image_width,
            image_height=image_height,
            label_file=label_file,
            dataset_root=dataset_root,
            line_index=line_index,
        )
        return {
            "class_id": class_id,
            "bbox_xywh": _build_bbox_from_polygon(polygon_xy),
            "polygon_xy": polygon_xy,
            "area": _compute_polygon_area(polygon_xy),
            "metadata": {
                "extra_values": parts[9:],
            }
            if len(parts) > 9
            else {},
        }

    def _build_bbox_from_yolo_normalized_xywh(
        self,
        *,
        raw_values: list[str],
        image_width: int,
        image_height: int,
        label_file: Path,
        dataset_root: Path,
        line_index: int,
    ) -> tuple[float, float, float, float]:
        """把 YOLO 归一化 xywh 转成像素 bbox。"""

        try:
            center_x, center_y, box_width, box_height = (
                float(value) for value in raw_values
            )
        except ValueError as error:
            raise InvalidRequestError(
                "YOLO bbox 必须是数字",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            ) from error
        if box_width <= 0 or box_height <= 0:
            raise InvalidRequestError(
                "YOLO bbox 宽高必须大于 0",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            )
        bbox_width = box_width * image_width
        bbox_height = box_height * image_height
        return (
            (center_x - box_width / 2.0) * image_width,
            (center_y - box_height / 2.0) * image_height,
            bbox_width,
            bbox_height,
        )

    def _build_pixel_polygon_from_yolo_values(
        self,
        *,
        raw_values: list[str],
        image_width: int,
        image_height: int,
        label_file: Path,
        dataset_root: Path,
        line_index: int,
    ) -> tuple[float, ...]:
        """把 YOLO 归一化 polygon 坐标转成像素点。"""

        if len(raw_values) < 6 or len(raw_values) % 2 != 0:
            raise InvalidRequestError(
                "YOLO polygon 至少需要 3 个点，且坐标数量必须成对出现",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            )
        try:
            normalized_values = [float(value) for value in raw_values]
        except ValueError as error:
            raise InvalidRequestError(
                "YOLO polygon 坐标必须是数字",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            ) from error
        pixel_values: list[float] = []
        for value_index in range(0, len(normalized_values), 2):
            pixel_values.append(normalized_values[value_index] * image_width)
            pixel_values.append(normalized_values[value_index + 1] * image_height)
        return tuple(pixel_values)
