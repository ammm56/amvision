"""detection 运行时公共序列化辅助。"""

from __future__ import annotations

from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionDetection,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)


def serialize_detection(detection: DetectionPredictionDetection) -> dict[str, object]:
    """把 detection 记录转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(detection.bbox_xyxy),
        "score": detection.score,
        "class_id": detection.class_id,
        "class_name": detection.class_name,
    }


def deserialize_detection(payload: object) -> DetectionPredictionDetection | None:
    """把 JSON 载荷反序列化为单条 detection 记录。"""

    if not isinstance(payload, dict):
        return None
    bbox = payload.get("bbox_xyxy")
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return None
    return DetectionPredictionDetection(
        bbox_xyxy=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
        score=float(payload.get("score") or 0.0),
        class_id=int(payload.get("class_id") or 0),
        class_name=str(payload.get("class_name")) if payload.get("class_name") is not None else None,
    )


def deserialize_detection_items(payload: object) -> tuple[DetectionPredictionDetection, ...]:
    """把 JSON detection 列表反序列化为 detection 元组。"""

    if not isinstance(payload, list | tuple):
        return ()
    items: list[DetectionPredictionDetection] = []
    for item in payload:
        parsed_item = deserialize_detection(item)
        if parsed_item is not None:
            items.append(parsed_item)
    return tuple(items)


def serialize_runtime_session_info(session_info: DetectionRuntimeSessionInfo) -> dict[str, object]:
    """把 runtime session info 转换为 JSON 字典。"""

    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": serialize_runtime_tensor_spec(session_info.input_spec),
        "output_spec": serialize_runtime_tensor_spec(session_info.output_spec),
        "metadata": dict(session_info.metadata),
    }


def serialize_runtime_tensor_spec(spec: DetectionRuntimeTensorSpec) -> dict[str, object]:
    """把 runtime tensor spec 转换为 JSON 字典。"""

    return {
        "name": spec.name,
        "shape": list(spec.shape),
        "dtype": spec.dtype,
    }


def deserialize_runtime_session_info(payload: object) -> DetectionRuntimeSessionInfo:
    """把 JSON 载荷反序列化为 runtime session info。"""

    info_payload = payload if isinstance(payload, dict) else {}
    input_spec_payload = info_payload.get("input_spec")
    output_spec_payload = info_payload.get("output_spec")
    return DetectionRuntimeSessionInfo(
        backend_name=str(info_payload.get("backend_name") or ""),
        model_uri=str(info_payload.get("model_uri") or ""),
        device_name=str(info_payload.get("device_name") or ""),
        input_spec=deserialize_runtime_tensor_spec(input_spec_payload, fallback_name="images"),
        output_spec=deserialize_runtime_tensor_spec(output_spec_payload, fallback_name="detections"),
        metadata=dict(info_payload.get("metadata")) if isinstance(info_payload.get("metadata"), dict) else {},
    )


def deserialize_runtime_tensor_spec(
    payload: object,
    *,
    fallback_name: str,
) -> DetectionRuntimeTensorSpec:
    """把 JSON 载荷反序列化为 runtime tensor spec。"""

    spec_payload = payload if isinstance(payload, dict) else {}
    shape_payload = spec_payload.get("shape")
    return DetectionRuntimeTensorSpec(
        name=str(spec_payload.get("name") or fallback_name),
        shape=tuple(int(item) for item in shape_payload) if isinstance(shape_payload, list | tuple) else (),
        dtype=str(spec_payload.get("dtype") or "float32"),
    )
