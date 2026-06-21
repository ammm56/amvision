"""YOLO OBB 标注解析。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.datasets.imports.formats.common import (
    _build_bbox_from_polygon,
    _compute_polygon_area,
)
from backend.service.application.errors import InvalidRequestError


class YoloObbAnnotationMixin:
    """解析 YOLO OBB 标注行。"""

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
