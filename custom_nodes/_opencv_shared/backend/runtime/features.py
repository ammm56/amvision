"""OpenCV shared 局部特征和匹配 payload 工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes._opencv_shared.backend.runtime.geometry import normalize_point_xy
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_non_negative_int,
    require_number,
    require_positive_int,
    require_uint8_int,
)

def build_local_features_payload(
    *,
    items: list[dict[str, object]],
    descriptors: list[list[int]],
    source_image: object | None,
    source_object_key: str | None,
    descriptor_length: int,
    feature_extractor: str = "orb",
    descriptor_kind: str = "orb",
    descriptor_dtype: str = "uint8",
    descriptor_norm: str = "hamming",
    wta_k: int = 2,
    roi_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """构建规范化后的 local-features.v1 payload。"""

    payload: dict[str, object] = {
        "feature_extractor": feature_extractor,
        "descriptor_kind": descriptor_kind,
        "descriptor_dtype": descriptor_dtype,
        "descriptor_norm": descriptor_norm,
        "descriptor_length": int(descriptor_length),
        "wta_k": int(wta_k),
        "count": len(items),
        "items": [dict(item) for item in items],
        "descriptors": [[int(cell_value) for cell_value in descriptor] for descriptor in descriptors],
    }
    if isinstance(source_image, dict):
        payload["source_image"] = require_image_payload(source_image)
    if isinstance(source_object_key, str) and source_object_key:
        payload["source_object_key"] = source_object_key
    if roi_payload is not None:
        payload["roi_id"] = str(roi_payload["roi_id"])
        payload["roi_kind"] = str(roi_payload["roi_kind"])
        payload["roi_bbox_xyxy"] = [float(value) for value in roi_payload["bbox_xyxy"]]
    return payload

def require_local_features_payload(payload: object) -> dict[str, object]:
    """校验并规范化 local-features.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 local-features payload 必须是对象")
    raw_items = payload.get("items")
    raw_descriptors = payload.get("descriptors")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 local-features.items 必须是数组")
    if not isinstance(raw_descriptors, list):
        raise InvalidRequestError("当前节点要求 local-features.descriptors 必须是数组")
    if len(raw_items) != len(raw_descriptors):
        raise InvalidRequestError("local-features.items 与 descriptors 数量必须一致")

    descriptor_length = require_positive_int(
        payload.get("descriptor_length", 1),
        field_name="descriptor_length",
    )
    normalized_items: list[dict[str, object]] = []
    normalized_descriptors: list[list[int]] = []
    for feature_index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError("当前节点要求每个 feature item 必须是对象")
        raw_descriptor = raw_descriptors[feature_index]
        if not isinstance(raw_descriptor, list) or len(raw_descriptor) != descriptor_length:
            raise InvalidRequestError("当前节点要求每个 descriptor 都必须与 descriptor_length 一致")
        feature_id = raw_item.get("feature_id")
        if not isinstance(feature_id, str) or not feature_id.strip():
            raise InvalidRequestError("当前节点要求 feature_id 必须是非空字符串")
        feature_class_id = raw_item.get("class_id", -1)
        if isinstance(feature_class_id, bool) or not isinstance(feature_class_id, int):
            raise InvalidRequestError("当前节点要求 feature.class_id 必须是整数")
        feature_octave = raw_item.get("octave", 0)
        if isinstance(feature_octave, bool) or not isinstance(feature_octave, int):
            raise InvalidRequestError("当前节点要求 feature.octave 必须是整数")
        normalized_items.append(
            {
                "feature_id": feature_id.strip(),
                "feature_index": int(raw_item.get("feature_index", feature_index)),
                "x": require_number(raw_item.get("x"), field_name="feature.x"),
                "y": require_number(raw_item.get("y"), field_name="feature.y"),
                "point_xy": list(
                    normalize_point_xy(raw_item.get("point_xy"), field_name="feature.point_xy")
                ),
                "size": require_number(raw_item.get("size"), field_name="feature.size"),
                "angle_deg": require_number(raw_item.get("angle_deg"), field_name="feature.angle_deg"),
                "response": require_number(raw_item.get("response"), field_name="feature.response"),
                "octave": int(feature_octave),
                "class_id": int(feature_class_id),
            }
        )
        normalized_descriptors.append(
            [require_uint8_int(cell_value, field_name="descriptor") for cell_value in raw_descriptor]
        )

    normalized_payload = dict(payload)
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
    normalized_payload["descriptor_length"] = int(descriptor_length)
    normalized_payload["wta_k"] = int(payload.get("wta_k", 2))
    normalized_payload["items"] = normalized_items
    normalized_payload["descriptors"] = normalized_descriptors
    source_image = payload.get("source_image")
    if isinstance(source_image, dict):
        normalized_payload["source_image"] = require_image_payload(source_image)
    resolved_source_object_key = normalized_payload.get("source_object_key")
    if not isinstance(resolved_source_object_key, str) or not resolved_source_object_key:
        normalized_source_image = normalized_payload.get("source_image")
        if isinstance(normalized_source_image, dict):
            source_object_key = normalized_source_image.get("object_key")
            if isinstance(source_object_key, str) and source_object_key:
                normalized_payload["source_object_key"] = source_object_key
    return normalized_payload

def build_feature_matches_payload(
    *,
    items: list[dict[str, object]],
    source_a_image: object | None,
    source_b_image: object | None,
    matcher_kind: str,
    cross_check: bool,
    ratio_test_threshold: float | None,
    source_a_object_key: str | None = None,
    source_b_object_key: str | None = None,
) -> dict[str, object]:
    """构建规范化后的 feature-matches.v1 payload。"""

    payload: dict[str, object] = {
        "matcher_kind": matcher_kind,
        "cross_check": bool(cross_check),
        "count": len(items),
        "items": [dict(item) for item in items],
    }
    if ratio_test_threshold is not None:
        payload["ratio_test_threshold"] = float(ratio_test_threshold)
    if isinstance(source_a_image, dict):
        payload["source_a_image"] = require_image_payload(source_a_image)
    if isinstance(source_b_image, dict):
        payload["source_b_image"] = require_image_payload(source_b_image)
    if isinstance(source_a_object_key, str) and source_a_object_key:
        payload["source_a_object_key"] = source_a_object_key
    if isinstance(source_b_object_key, str) and source_b_object_key:
        payload["source_b_object_key"] = source_b_object_key
    return payload

def require_feature_matches_payload(payload: object) -> dict[str, object]:
    """校验并规范化 feature-matches.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 feature-matches payload 必须是对象")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("当前节点要求 feature-matches.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for match_index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise InvalidRequestError("当前节点要求每个 match item 必须是对象")
        match_id = raw_item.get("match_id")
        query_feature_id = raw_item.get("query_feature_id")
        train_feature_id = raw_item.get("train_feature_id")
        if not isinstance(match_id, str) or not match_id.strip():
            raise InvalidRequestError("当前节点要求 match_id 必须是非空字符串")
        if not isinstance(query_feature_id, str) or not query_feature_id.strip():
            raise InvalidRequestError("当前节点要求 query_feature_id 必须是非空字符串")
        if not isinstance(train_feature_id, str) or not train_feature_id.strip():
            raise InvalidRequestError("当前节点要求 train_feature_id 必须是非空字符串")
        normalized_items.append(
            {
                "match_id": match_id.strip(),
                "query_feature_id": query_feature_id.strip(),
                "train_feature_id": train_feature_id.strip(),
                "query_index": require_non_negative_int(
                    raw_item.get("query_index"),
                    field_name="query_index",
                ),
                "train_index": require_non_negative_int(
                    raw_item.get("train_index"),
                    field_name="train_index",
                ),
                "distance": require_non_negative_float(raw_item.get("distance"), field_name="distance"),
                "query_xy": list(normalize_point_xy(raw_item.get("query_xy"), field_name="query_xy")),
                "train_xy": list(normalize_point_xy(raw_item.get("train_xy"), field_name="train_xy")),
            }
        )

    normalized_payload = dict(payload)
    normalized_payload["count"] = int(payload.get("count", len(normalized_items)))
    normalized_payload["items"] = normalized_items
    source_a_image = payload.get("source_a_image")
    source_b_image = payload.get("source_b_image")
    if isinstance(source_a_image, dict):
        normalized_payload["source_a_image"] = require_image_payload(source_a_image)
    if isinstance(source_b_image, dict):
        normalized_payload["source_b_image"] = require_image_payload(source_b_image)
    resolved_source_a_object_key = normalized_payload.get("source_a_object_key")
    if not isinstance(resolved_source_a_object_key, str) or not resolved_source_a_object_key:
        normalized_source_a_image = normalized_payload.get("source_a_image")
        if isinstance(normalized_source_a_image, dict):
            source_object_key = normalized_source_a_image.get("object_key")
            if isinstance(source_object_key, str) and source_object_key:
                normalized_payload["source_a_object_key"] = source_object_key
    resolved_source_b_object_key = normalized_payload.get("source_b_object_key")
    if not isinstance(resolved_source_b_object_key, str) or not resolved_source_b_object_key:
        normalized_source_b_image = normalized_payload.get("source_b_image")
        if isinstance(normalized_source_b_image, dict):
            source_object_key = normalized_source_b_image.get("object_key")
            if isinstance(source_object_key, str) and source_object_key:
                normalized_payload["source_b_object_key"] = source_object_key
    return normalized_payload
