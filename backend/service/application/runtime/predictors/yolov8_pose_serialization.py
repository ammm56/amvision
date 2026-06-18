"""YOLOv8 pose runtime 响应序列化工具。"""

from __future__ import annotations

from typing import Any


def serialize_yolov8_pose_instance(instance: Any) -> dict[str, object]:
    """把 YOLOv8 pose 实例转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(instance.bbox_xyxy),
        "score": instance.score,
        "class_id": instance.class_id,
        "class_name": instance.class_name,
        "keypoints": [
            {
                "x": keypoint.x,
                "y": keypoint.y,
                "confidence": keypoint.confidence,
            }
            for keypoint in instance.keypoints
        ],
        "kpt_shape": list(instance.kpt_shape),
    }


__all__ = ["serialize_yolov8_pose_instance"]
