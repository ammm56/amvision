"""obb 运行时公共序列化辅助。"""

from __future__ import annotations

from backend.service.application.runtime.contracts.obb import (
    ObbPredictionInstance,
    ObbRuntimeSessionInfo,
    ObbRuntimeTensorSpec,
)


def serialize_obb_instance(instance: ObbPredictionInstance) -> dict[str, object]:
    """把 obb instance 转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(instance.bbox_xyxy),
        "score": instance.score,
        "class_id": instance.class_id,
        "class_name": instance.class_name,
        "angle": instance.angle,
    }


def deserialize_obb_instance(payload: object) -> ObbPredictionInstance | None:
    """把 JSON 载荷反序列化为单条 obb instance。"""

    if not isinstance(payload, dict):
        return None
    bbox = payload.get("bbox_xyxy")
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return None
    angle = payload.get("angle")
    return ObbPredictionInstance(
        bbox_xyxy=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
        score=float(payload.get("score") or 0.0),
        class_id=int(payload.get("class_id") or 0),
        class_name=(
            str(payload.get("class_name"))
            if payload.get("class_name") is not None
            else None
        ),
        angle=float(angle) if isinstance(angle, int | float) else None,
    )


def deserialize_obb_instances(payload: object) -> tuple[ObbPredictionInstance, ...]:
    """把 JSON 列表反序列化为 obb instance 元组。"""

    if not isinstance(payload, list | tuple):
        return ()
    items: list[ObbPredictionInstance] = []
    for item in payload:
        parsed = deserialize_obb_instance(item)
        if parsed is not None:
            items.append(parsed)
    return tuple(items)


def serialize_obb_runtime_session_info(
    session_info: ObbRuntimeSessionInfo,
) -> dict[str, object]:
    """把 obb runtime session info 转换为 JSON 字典。"""

    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": serialize_obb_runtime_tensor_spec(session_info.input_spec),
        "output_specs": [
            serialize_obb_runtime_tensor_spec(item)
            for item in session_info.output_specs
        ],
        "metadata": dict(session_info.metadata),
    }


def serialize_obb_runtime_tensor_spec(spec: ObbRuntimeTensorSpec) -> dict[str, object]:
    """把 obb runtime tensor spec 转换为 JSON 字典。"""

    return {
        "name": spec.name,
        "shape": list(spec.shape),
        "dtype": spec.dtype,
    }


def deserialize_obb_runtime_session_info(payload: object) -> ObbRuntimeSessionInfo:
    """把 JSON 载荷反序列化为 obb runtime session info。"""

    info_payload = payload if isinstance(payload, dict) else {}
    output_specs_payload = info_payload.get("output_specs")
    output_specs: list[ObbRuntimeTensorSpec] = []
    if isinstance(output_specs_payload, list | tuple):
        for index, item in enumerate(output_specs_payload):
            output_specs.append(
                deserialize_obb_runtime_tensor_spec(
                    item,
                    fallback_name=f"output_{index}",
                )
            )
    return ObbRuntimeSessionInfo(
        backend_name=str(info_payload.get("backend_name") or ""),
        model_uri=str(info_payload.get("model_uri") or ""),
        device_name=str(info_payload.get("device_name") or ""),
        input_spec=deserialize_obb_runtime_tensor_spec(
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


def deserialize_obb_runtime_tensor_spec(
    payload: object,
    *,
    fallback_name: str,
) -> ObbRuntimeTensorSpec:
    """把 JSON 载荷反序列化为 obb runtime tensor spec。"""

    spec_payload = payload if isinstance(payload, dict) else {}
    shape_payload = spec_payload.get("shape")
    return ObbRuntimeTensorSpec(
        name=str(spec_payload.get("name") or fallback_name),
        shape=(
            tuple(int(item) for item in shape_payload)
            if isinstance(shape_payload, list | tuple)
            else ()
        ),
        dtype=str(spec_payload.get("dtype") or "float32"),
    )
