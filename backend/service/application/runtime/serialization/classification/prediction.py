"""classification 运行时公共序列化辅助。"""

from __future__ import annotations

from backend.service.application.runtime.contracts.classification.prediction import (
    ClassificationPredictionCategory,
    ClassificationRuntimeSessionInfo,
    ClassificationRuntimeTensorSpec,
)


def serialize_classification_category(
    category: ClassificationPredictionCategory,
) -> dict[str, object]:
    """把 classification category 转换为 JSON 字典。"""

    return {
        "class_id": category.class_id,
        "probability": category.probability,
        "class_name": category.class_name,
        "logit": category.logit,
    }


def deserialize_classification_category(
    payload: object,
) -> ClassificationPredictionCategory | None:
    """把 JSON 载荷反序列化为单条 classification category。"""

    if not isinstance(payload, dict):
        return None
    class_id = payload.get("class_id")
    probability = payload.get("probability")
    if isinstance(class_id, bool) or not isinstance(class_id, int):
        return None
    if isinstance(probability, bool) or not isinstance(probability, int | float):
        return None
    logit = payload.get("logit")
    return ClassificationPredictionCategory(
        class_id=class_id,
        probability=float(probability),
        class_name=(
            str(payload.get("class_name"))
            if payload.get("class_name") is not None
            else None
        ),
        logit=float(logit) if isinstance(logit, int | float) else None,
    )


def deserialize_classification_categories(
    payload: object,
) -> tuple[ClassificationPredictionCategory, ...]:
    """把 JSON 列表反序列化为 classification category 元组。"""

    if not isinstance(payload, list | tuple):
        return ()
    categories: list[ClassificationPredictionCategory] = []
    for item in payload:
        parsed = deserialize_classification_category(item)
        if parsed is not None:
            categories.append(parsed)
    return tuple(categories)


def serialize_classification_runtime_session_info(
    session_info: ClassificationRuntimeSessionInfo,
) -> dict[str, object]:
    """把 classification runtime session info 转换为 JSON 字典。"""

    return {
        "backend_name": session_info.backend_name,
        "model_uri": session_info.model_uri,
        "device_name": session_info.device_name,
        "input_spec": serialize_classification_runtime_tensor_spec(session_info.input_spec),
        "output_spec": serialize_classification_runtime_tensor_spec(session_info.output_spec),
        "metadata": dict(session_info.metadata),
    }


def serialize_classification_runtime_tensor_spec(
    spec: ClassificationRuntimeTensorSpec,
) -> dict[str, object]:
    """把 classification runtime tensor spec 转换为 JSON 字典。"""

    return {
        "name": spec.name,
        "shape": list(spec.shape),
        "dtype": spec.dtype,
    }


def deserialize_classification_runtime_session_info(
    payload: object,
) -> ClassificationRuntimeSessionInfo:
    """把 JSON 载荷反序列化为 classification runtime session info。"""

    info_payload = payload if isinstance(payload, dict) else {}
    return ClassificationRuntimeSessionInfo(
        backend_name=str(info_payload.get("backend_name") or ""),
        model_uri=str(info_payload.get("model_uri") or ""),
        device_name=str(info_payload.get("device_name") or ""),
        input_spec=deserialize_classification_runtime_tensor_spec(
            info_payload.get("input_spec"),
            fallback_name="images",
        ),
        output_spec=deserialize_classification_runtime_tensor_spec(
            info_payload.get("output_spec"),
            fallback_name="scores",
        ),
        metadata=(
            dict(info_payload.get("metadata"))
            if isinstance(info_payload.get("metadata"), dict)
            else {}
        ),
    )


def deserialize_classification_runtime_tensor_spec(
    payload: object,
    *,
    fallback_name: str,
) -> ClassificationRuntimeTensorSpec:
    """把 JSON 载荷反序列化为 classification runtime tensor spec。"""

    spec_payload = payload if isinstance(payload, dict) else {}
    shape_payload = spec_payload.get("shape")
    return ClassificationRuntimeTensorSpec(
        name=str(spec_payload.get("name") or fallback_name),
        shape=(
            tuple(int(item) for item in shape_payload)
            if isinstance(shape_payload, list | tuple)
            else ()
        ),
        dtype=str(spec_payload.get("dtype") or "float32"),
    )
