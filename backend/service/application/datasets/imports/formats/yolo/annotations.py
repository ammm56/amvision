"""YOLO 标注解析公共组合。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.datasets.imports.formats.yolo.detection import (
    YoloDetectionAnnotationMixin,
)
from backend.service.application.datasets.imports.formats.yolo.obb import (
    YoloObbAnnotationMixin,
)
from backend.service.application.datasets.imports.formats.yolo.pose import (
    YoloPoseAnnotationMixin,
)
from backend.service.application.datasets.imports.formats.yolo.segmentation import (
    YoloSegmentationAnnotationMixin,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetAnnotation,
    DetectionAnnotation,
    InstanceSegmentationAnnotation,
    ObbAnnotation,
    PoseAnnotation,
)


class YoloAnnotationParserMixin(
    YoloDetectionAnnotationMixin,
    YoloSegmentationAnnotationMixin,
    YoloPoseAnnotationMixin,
    YoloObbAnnotationMixin,
):
    """组合 YOLO 各任务标注解析能力。"""

    def _normalize_yolo_class_id(
        self,
        *,
        raw_value: str,
        label_file: Path,
        dataset_root: Path,
        line_index: int,
    ) -> int:
        """读取并校验 YOLO 行首的类别 id。"""

        try:
            numeric_value = float(raw_value)
        except ValueError as error:
            raise InvalidRequestError(
                "YOLO 标注类别 id 必须是数字",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                },
            ) from error
        if numeric_value < 0 or not numeric_value.is_integer():
            raise InvalidRequestError(
                "YOLO 标注类别 id 必须是非负整数",
                details={
                    "label_file": self._relative_path_from_any(
                        label_file,
                        dataset_root,
                        label_file.parent,
                    ),
                    "line_index": line_index,
                    "value": raw_value,
                },
            )
        return int(numeric_value)

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
