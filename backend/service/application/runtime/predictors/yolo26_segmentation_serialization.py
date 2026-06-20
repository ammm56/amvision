"""YOLO26 segmentation runtime 响应序列化工具。"""

from __future__ import annotations

from typing import Any


def serialize_yolo26_segmentation_instance(instance: Any) -> dict[str, object]:
    """把 YOLO26 segmentation 实例转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(instance.bbox_xyxy),
        "score": instance.score,
        "class_id": instance.class_id,
        "class_name": instance.class_name,
        "segments": [
            [list(point) for point in segment] for segment in instance.segments
        ],
        "mask_area": instance.mask_area,
    }


def serialize_yolo26_segmentation_runtime_session_info(
    session_info: Any,
) -> dict[str, object]:
    """把 YOLO26 segmentation runtime session info 转换为 JSON 字典。"""

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
    "serialize_yolo26_segmentation_instance",
    "serialize_yolo26_segmentation_runtime_session_info",
]
