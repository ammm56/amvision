"""YOLO instance segmentation 标注解析。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.datasets.imports.formats.common import (
    _build_bbox_from_polygon,
    _compute_polygon_area,
)
from backend.service.application.errors import InvalidRequestError


class YoloSegmentationAnnotationMixin:
    """解析 YOLO segmentation 标注行。"""

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
