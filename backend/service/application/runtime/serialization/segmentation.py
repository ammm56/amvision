"""segmentation 运行时公共序列化辅助。"""

from __future__ import annotations

from backend.service.application.runtime.contracts.segmentation import (
    SegmentationPredictionInstance,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)


def serialize_segmentation_instance(
    instance: SegmentationPredictionInstance,
) -> dict[str, object]:
    """把 segmentation instance 转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(instance.bbox_xyxy),
        "score": instance.score,
        "class_id": instance.class_id,
        "class_name": instance.class_name,
        "segments": [
            [[float(point[0]), float(point[1])] for point in polygon]
            for polygon in instance.segments
        ],
        "mask_area": instance.mask_area,
    }


def deserialize_segmentation_instance(
    payload: object,
) -> SegmentationPredictionInstance | None:
    """把 JSON 载荷反序列化为单条 segmentation instance。"""

    if not isinstance(payload, dict):
        return None
    bbox = payload.get("bbox_xyxy")
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return None
    segments_payload = payload.get("segments")
    segments: list[tuple[tuple[float, float], ...]] = []
    if isinstance(segments_payload, list | tuple):
        for polygon in segments_payload:
            if not isinstance(polygon, list | tuple):
                continue
            points: list[tuple[float, float]] = []
            for point in polygon:
                if not isinstance(point, list | tuple) or len(point) != 2:
                    continue
                points.append((float(point[0]), float(point[1])))
            if points:
                segments.append(tuple(points))
    return SegmentationPredictionInstance(
        bbox_xyxy=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
        score=float(payload.get("score") or 0.0),
        class_id=int(payload.get("class_id") or 0),
        class_name=(
            str(payload.get("class_name"))
            if payload.get("class_name") is not None
            else None
        ),
        segments=tuple(segments),
        mask_area=(
            float(payload.get("mask_area"))
            if isinstance(payload.get("mask_area"), int | float)
            else None
        ),
    )


def deserialize_segmentation_instances(
    payload: object,
) -> tuple[SegmentationPredictionInstance, ...]:
    """把 JSON 列表反序列化为 segmentation instance 元组。"""

    if not isinstance(payload, list | tuple):
        return ()
    items: list[SegmentationPredictionInstance] = []
    for item in payload:
        parsed = deserialize_segmentation_instance(item)
        if parsed is not None:
            items.append(parsed)
    return tuple(items)


def serialize_segmentation_runtime_session_info(
    session_info: SegmentationRuntimeSessionInfo,
) -> dict[str, object]:
    """把 segmentation runtime session info 转换为 JSON 字典。"""

    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": serialize_segmentation_runtime_tensor_spec(session_info.input_spec),
        "output_specs": [
            serialize_segmentation_runtime_tensor_spec(item)
            for item in session_info.output_specs
        ],
        "metadata": dict(session_info.metadata),
    }


def serialize_segmentation_runtime_tensor_spec(
    spec: SegmentationRuntimeTensorSpec,
) -> dict[str, object]:
    """把 segmentation runtime tensor spec 转换为 JSON 字典。"""

    return {
        "name": spec.name,
        "shape": list(spec.shape),
        "dtype": spec.dtype,
    }


def deserialize_segmentation_runtime_session_info(
    payload: object,
) -> SegmentationRuntimeSessionInfo:
    """把 JSON 载荷反序列化为 segmentation runtime session info。"""

    info_payload = payload if isinstance(payload, dict) else {}
    output_specs_payload = info_payload.get("output_specs")
    output_specs: list[SegmentationRuntimeTensorSpec] = []
    if isinstance(output_specs_payload, list | tuple):
        for index, item in enumerate(output_specs_payload):
            output_specs.append(
                deserialize_segmentation_runtime_tensor_spec(
                    item,
                    fallback_name=f"output_{index}",
                )
            )
    return SegmentationRuntimeSessionInfo(
        backend_name=str(info_payload.get("backend_name") or ""),
        model_uri=str(info_payload.get("model_uri") or ""),
        device_name=str(info_payload.get("device_name") or ""),
        input_spec=deserialize_segmentation_runtime_tensor_spec(
            info_payload.get("input_spec"),
            fallback_name="images",
        ),
        output_specs=tuple(output_specs),
        metadata=(
            dict(info_payload.get("metadata"))
            if isinstance(info_payload.get("metadata"), dict)
            else {}
        ),
    )


def deserialize_segmentation_runtime_tensor_spec(
    payload: object,
    *,
    fallback_name: str,
) -> SegmentationRuntimeTensorSpec:
    """把 JSON 载荷反序列化为 segmentation runtime tensor spec。"""

    spec_payload = payload if isinstance(payload, dict) else {}
    shape_payload = spec_payload.get("shape")
    return SegmentationRuntimeTensorSpec(
        name=str(spec_payload.get("name") or fallback_name),
        shape=(
            tuple(int(item) for item in shape_payload)
            if isinstance(shape_payload, list | tuple)
            else ()
        ),
        dtype=str(spec_payload.get("dtype") or "float32"),
    )
