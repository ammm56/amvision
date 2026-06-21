"""YOLO detection 标注解析。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.errors import InvalidRequestError


class YoloDetectionAnnotationMixin:
    """解析 YOLO detection 标注行。"""

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
