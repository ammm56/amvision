"""YOLOv8 OBB runtime 响应序列化工具。"""

from __future__ import annotations

from typing import Any


def serialize_yolov8_obb_instance(instance: Any) -> dict[str, object]:
    """把 YOLOv8 OBB 实例转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(instance.bbox_xyxy),
        "score": instance.score,
        "class_id": instance.class_id,
        "class_name": instance.class_name,
        "angle": instance.angle,
    }


def serialize_yolov8_obb_runtime_session_info(session_info: Any) -> dict[str, object]:
    """把 YOLOv8 OBB runtime session info 转换为 JSON 字典。"""

    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": {
            "name": session_info.input_spec.name,
            "shape": list(session_info.input_spec.shape),
            "dtype": session_info.input_spec.dtype,
        },
        "output_specs": [
            {
                "name": item.name,
                "shape": list(item.shape),
                "dtype": item.dtype,
            }
            for item in session_info.output_specs
        ],
        "metadata": dict(session_info.metadata),
    }


__all__ = [
    "serialize_yolov8_obb_instance",
    "serialize_yolov8_obb_runtime_session_info",
]
