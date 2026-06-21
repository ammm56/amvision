"""YOLOv8 detection runtime 响应序列化工具。"""

from __future__ import annotations

from typing import Any


def serialize_yolov8_detection(detection: Any) -> dict[str, object]:
    """把 YOLOv8 detection 记录转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(detection.bbox_xyxy),
        "score": detection.score,
        "class_id": detection.class_id,
        "class_name": detection.class_name,
    }


def serialize_yolov8_detection_runtime_session_info(session_info: Any) -> dict[str, object]:
    """把 YOLOv8 detection runtime session info 转换为 JSON 字典。"""

    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": {
            "name": session_info.input_spec.name,
            "shape": list(session_info.input_spec.shape),
            "dtype": session_info.input_spec.dtype,
        },
        "output_spec": {
            "name": session_info.output_spec.name,
            "shape": list(session_info.output_spec.shape),
            "dtype": session_info.output_spec.dtype,
        },
        "metadata": dict(session_info.metadata),
    }


__all__ = [
    "serialize_yolov8_detection",
    "serialize_yolov8_detection_runtime_session_info",
]
