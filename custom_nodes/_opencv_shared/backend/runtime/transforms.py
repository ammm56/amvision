"""OpenCV shared 平面变换 payload 工具。"""

from __future__ import annotations

from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_non_negative_int,
    require_number,
)

def build_planar_transform_payload(
    *,
    matrix_3x3: list[list[float]],
    inverse_matrix_3x3: list[list[float]] | None,
    match_count: int,
    inlier_count: int,
    inlier_match_ids: list[str],
    reprojection_error: float | None,
    source_a_image: object | None,
    source_b_image: object | None,
    source_a_object_key: str | None = None,
    source_b_object_key: str | None = None,
    transform_kind: str = "homography",
) -> dict[str, object]:
    """构建规范化后的 planar-transform.v1 payload。"""

    payload: dict[str, object] = {
        "transform_kind": transform_kind,
        "matrix_3x3": [[float(cell_value) for cell_value in row_values] for row_values in matrix_3x3],
        "match_count": int(match_count),
        "inlier_count": int(inlier_count),
        "inlier_match_ids": [str(match_id) for match_id in inlier_match_ids],
    }
    if inverse_matrix_3x3 is not None:
        payload["inverse_matrix_3x3"] = [
            [float(cell_value) for cell_value in row_values] for row_values in inverse_matrix_3x3
        ]
    if reprojection_error is not None:
        payload["reprojection_error"] = float(reprojection_error)
    if isinstance(source_a_image, dict):
        payload["source_a_image"] = require_image_payload(source_a_image)
    if isinstance(source_b_image, dict):
        payload["source_b_image"] = require_image_payload(source_b_image)
    if isinstance(source_a_object_key, str) and source_a_object_key:
        payload["source_a_object_key"] = source_a_object_key
    if isinstance(source_b_object_key, str) and source_b_object_key:
        payload["source_b_object_key"] = source_b_object_key
    return payload

def require_planar_transform_payload(payload: object) -> dict[str, object]:
    """校验并规范化 planar-transform.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("当前节点要求 planar-transform payload 必须是对象")

    transform_kind = payload.get("transform_kind")
    if not isinstance(transform_kind, str) or not transform_kind.strip():
        raise InvalidRequestError("当前节点要求 transform_kind 必须是非空字符串")

    matrix_3x3 = _normalize_matrix_3x3(payload.get("matrix_3x3"), field_name="matrix_3x3")
    inverse_matrix_3x3 = None
    if payload.get("inverse_matrix_3x3") is not None:
        inverse_matrix_3x3 = _normalize_matrix_3x3(
            payload.get("inverse_matrix_3x3"),
            field_name="inverse_matrix_3x3",
        )

    match_count = require_non_negative_int(payload.get("match_count"), field_name="match_count")
    inlier_count = require_non_negative_int(payload.get("inlier_count"), field_name="inlier_count")
    if inlier_count > match_count:
        raise InvalidRequestError("inlier_count 不能大于 match_count")

    raw_inlier_match_ids = payload.get("inlier_match_ids")
    if not isinstance(raw_inlier_match_ids, list):
        raise InvalidRequestError("当前节点要求 inlier_match_ids 必须是数组")
    normalized_inlier_match_ids: list[str] = []
    for match_id in raw_inlier_match_ids:
        if not isinstance(match_id, str) or not match_id.strip():
            raise InvalidRequestError("当前节点要求每个 inlier_match_id 都必须是非空字符串")
        normalized_inlier_match_ids.append(match_id.strip())

    normalized_payload: dict[str, object] = {
        "transform_kind": transform_kind.strip(),
        "matrix_3x3": matrix_3x3,
        "match_count": int(match_count),
        "inlier_count": int(inlier_count),
        "inlier_match_ids": normalized_inlier_match_ids,
    }
    if inverse_matrix_3x3 is not None:
        normalized_payload["inverse_matrix_3x3"] = inverse_matrix_3x3
    if payload.get("reprojection_error") is not None:
        normalized_payload["reprojection_error"] = require_non_negative_float(
            payload.get("reprojection_error"),
            field_name="reprojection_error",
        )

    source_a_image = payload.get("source_a_image")
    source_b_image = payload.get("source_b_image")
    if isinstance(source_a_image, dict):
        normalized_payload["source_a_image"] = require_image_payload(source_a_image)
    if isinstance(source_b_image, dict):
        normalized_payload["source_b_image"] = require_image_payload(source_b_image)

    resolved_source_a_object_key = payload.get("source_a_object_key")
    if isinstance(resolved_source_a_object_key, str) and resolved_source_a_object_key.strip():
        normalized_payload["source_a_object_key"] = resolved_source_a_object_key.strip()
    elif isinstance(normalized_payload.get("source_a_image"), dict):
        source_object_key = normalized_payload["source_a_image"].get("object_key")
        if isinstance(source_object_key, str) and source_object_key:
            normalized_payload["source_a_object_key"] = source_object_key

    resolved_source_b_object_key = payload.get("source_b_object_key")
    if isinstance(resolved_source_b_object_key, str) and resolved_source_b_object_key.strip():
        normalized_payload["source_b_object_key"] = resolved_source_b_object_key.strip()
    elif isinstance(normalized_payload.get("source_b_image"), dict):
        source_object_key = normalized_payload["source_b_image"].get("object_key")
        if isinstance(source_object_key, str) and source_object_key:
            normalized_payload["source_b_object_key"] = source_object_key
    return normalized_payload

def _normalize_matrix_3x3(raw_value: object, *, field_name: str) -> list[list[float]]:
    """把 3x3 数值矩阵规范化为嵌套浮点数组。"""

    if not isinstance(raw_value, list) or len(raw_value) != 3:
        raise InvalidRequestError(f"{field_name} 必须是 3x3 数值矩阵")

    normalized_rows: list[list[float]] = []
    for row_index, row_value in enumerate(raw_value):
        if not isinstance(row_value, list) or len(row_value) != 3:
            raise InvalidRequestError(f"{field_name}[{row_index}] 必须是长度为 3 的数组")
        normalized_rows.append(
            [
                float(require_number(cell_value, field_name=f"{field_name}[{row_index}][{column_index}]"))
                for column_index, cell_value in enumerate(row_value)
            ]
        )
    return normalized_rows
