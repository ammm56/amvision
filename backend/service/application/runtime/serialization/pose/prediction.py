"""pose 运行时公共序列化辅助。"""

from __future__ import annotations

from backend.service.application.runtime.contracts.pose.prediction import (
    PosePredictionInstance,
    PosePredictionKeypoint,
    PoseRuntimeSessionInfo,
    PoseRuntimeTensorSpec,
)


def serialize_pose_keypoint(keypoint: PosePredictionKeypoint) -> dict[str, object]:
    """把 pose keypoint 转换为 JSON 字典。"""

    return {
        "x": keypoint.x,
        "y": keypoint.y,
        "confidence": keypoint.confidence,
    }


def deserialize_pose_keypoint(payload: object) -> PosePredictionKeypoint | None:
    """把 JSON 载荷反序列化为单个 pose keypoint。"""

    if not isinstance(payload, dict):
        return None
    x = payload.get("x")
    y = payload.get("y")
    if isinstance(x, bool) or not isinstance(x, int | float):
        return None
    if isinstance(y, bool) or not isinstance(y, int | float):
        return None
    confidence = payload.get("confidence")
    return PosePredictionKeypoint(
        x=float(x),
        y=float(y),
        confidence=float(confidence) if isinstance(confidence, int | float) else None,
    )


def serialize_pose_instance(instance: PosePredictionInstance) -> dict[str, object]:
    """把 pose instance 转换为 JSON 字典。"""

    return {
        "bbox_xyxy": list(instance.bbox_xyxy),
        "score": instance.score,
        "class_id": instance.class_id,
        "class_name": instance.class_name,
        "keypoints": [serialize_pose_keypoint(item) for item in instance.keypoints],
        "kpt_shape": list(instance.kpt_shape),
    }


def deserialize_pose_instance(payload: object) -> PosePredictionInstance | None:
    """把 JSON 载荷反序列化为单条 pose instance。"""

    if not isinstance(payload, dict):
        return None
    bbox = payload.get("bbox_xyxy")
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return None
    keypoints_payload = payload.get("keypoints")
    keypoints: list[PosePredictionKeypoint] = []
    if isinstance(keypoints_payload, list | tuple):
        for item in keypoints_payload:
            parsed = deserialize_pose_keypoint(item)
            if parsed is not None:
                keypoints.append(parsed)
    kpt_shape_payload = payload.get("kpt_shape")
    kpt_shape = (17, 3)
    if isinstance(kpt_shape_payload, list | tuple) and len(kpt_shape_payload) == 2:
        kpt_shape = (int(kpt_shape_payload[0]), int(kpt_shape_payload[1]))
    return PosePredictionInstance(
        bbox_xyxy=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
        score=float(payload.get("score") or 0.0),
        class_id=int(payload.get("class_id") or 0),
        class_name=(
            str(payload.get("class_name"))
            if payload.get("class_name") is not None
            else None
        ),
        keypoints=tuple(keypoints),
        kpt_shape=kpt_shape,
    )


def deserialize_pose_instances(payload: object) -> tuple[PosePredictionInstance, ...]:
    """把 JSON 列表反序列化为 pose instance 元组。"""

    if not isinstance(payload, list | tuple):
        return ()
    items: list[PosePredictionInstance] = []
    for item in payload:
        parsed = deserialize_pose_instance(item)
        if parsed is not None:
            items.append(parsed)
    return tuple(items)


def serialize_pose_runtime_session_info(
    session_info: PoseRuntimeSessionInfo,
) -> dict[str, object]:
    """把 pose runtime session info 转换为 JSON 字典。"""

    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": serialize_pose_runtime_tensor_spec(session_info.input_spec),
        "output_specs": [
            serialize_pose_runtime_tensor_spec(item)
            for item in session_info.output_specs
        ],
        "metadata": dict(session_info.metadata),
    }


def serialize_pose_runtime_tensor_spec(spec: PoseRuntimeTensorSpec) -> dict[str, object]:
    """把 pose runtime tensor spec 转换为 JSON 字典。"""

    return {
        "name": spec.name,
        "shape": list(spec.shape),
        "dtype": spec.dtype,
    }


def deserialize_pose_runtime_session_info(payload: object) -> PoseRuntimeSessionInfo:
    """把 JSON 载荷反序列化为 pose runtime session info。"""

    info_payload = payload if isinstance(payload, dict) else {}
    output_specs_payload = info_payload.get("output_specs")
    output_specs: list[PoseRuntimeTensorSpec] = []
    if isinstance(output_specs_payload, list | tuple):
        for index, item in enumerate(output_specs_payload):
            output_specs.append(
                deserialize_pose_runtime_tensor_spec(
                    item,
                    fallback_name=f"output_{index}",
                )
            )
    return PoseRuntimeSessionInfo(
        backend_name=str(info_payload.get("backend_name") or ""),
        model_uri=str(info_payload.get("model_uri") or ""),
        device_name=str(info_payload.get("device_name") or ""),
        input_spec=deserialize_pose_runtime_tensor_spec(
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


def deserialize_pose_runtime_tensor_spec(
    payload: object,
    *,
    fallback_name: str,
) -> PoseRuntimeTensorSpec:
    """把 JSON 载荷反序列化为 pose runtime tensor spec。"""

    spec_payload = payload if isinstance(payload, dict) else {}
    shape_payload = spec_payload.get("shape")
    return PoseRuntimeTensorSpec(
        name=str(spec_payload.get("name") or fallback_name),
        shape=(
            tuple(int(item) for item in shape_payload)
            if isinstance(shape_payload, list | tuple)
            else ()
        ),
        dtype=str(spec_payload.get("dtype") or "float32"),
    )
