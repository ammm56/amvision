"""YOLO pose 标注解析。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.errors import InvalidRequestError


class YoloPoseAnnotationMixin:
    """解析 YOLO pose 标注行。"""

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
