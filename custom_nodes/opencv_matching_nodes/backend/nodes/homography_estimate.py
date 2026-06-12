"""Homography Estimate 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_planar_transform_payload,
    require_feature_matches_payload,
    require_local_features_payload,
    require_non_negative_float,
    require_opencv_imports,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.homography-estimate"


def _read_method(raw_value: object) -> str:
    """读取 homography 估计方法。"""

    if raw_value in {None, ""}:
        return "ransac"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("method 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"ransac", "lmeds"}:
        raise InvalidRequestError("method 仅支持 ransac 或 lmeds")
    return normalized_value


def _read_ransac_reprojection_threshold(raw_value: object) -> float:
    """读取 RANSAC 重投影阈值。"""

    if raw_value in {None, ""}:
        return 3.0
    normalized_value = require_non_negative_float(
        raw_value,
        field_name="ransac_reprojection_threshold",
    )
    if normalized_value <= 0.0:
        raise InvalidRequestError("ransac_reprojection_threshold 必须大于 0")
    return float(normalized_value)


def _read_confidence(raw_value: object) -> float:
    """读取 findHomography confidence。"""

    if raw_value in {None, ""}:
        return 0.995
    normalized_value = require_non_negative_float(raw_value, field_name="confidence")
    if normalized_value <= 0.0 or normalized_value >= 1.0:
        raise InvalidRequestError("confidence 必须在 0 到 1 之间")
    return float(normalized_value)


def _read_min_match_count(raw_value: object) -> int:
    """读取最小匹配数。"""

    if raw_value in {None, ""}:
        return 4
    return require_positive_int(raw_value, field_name="min_match_count")


def _read_max_iters(raw_value: object) -> int:
    """读取最大迭代次数。"""

    if raw_value in {None, ""}:
        return 2000
    return require_positive_int(raw_value, field_name="max_iters")


def _read_bool(raw_value: object, *, field_name: str, default_value: bool) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return bool(default_value)
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return raw_value


def _resolve_method(method_name: str, *, cv2_module) -> int:
    """把 method 名称解析为 OpenCV 常量。"""

    if method_name == "ransac":
        return cv2_module.RANSAC
    if method_name == "lmeds":
        return cv2_module.LMEDS
    raise InvalidRequestError("不支持的 homography 方法", details={"method": method_name})


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据两路 ORB 匹配估计平面 homography 变换。"""

    cv2_module, np_module = require_opencv_imports()
    matches_payload = require_feature_matches_payload(request.input_values.get("matches"))
    features_a_payload = require_local_features_payload(request.input_values.get("features_a"))
    features_b_payload = require_local_features_payload(request.input_values.get("features_b"))
    method_name = _read_method(request.parameters.get("method"))
    ransac_reprojection_threshold = _read_ransac_reprojection_threshold(
        request.parameters.get("ransac_reprojection_threshold")
    )
    confidence = _read_confidence(request.parameters.get("confidence"))
    min_match_count = _read_min_match_count(request.parameters.get("min_match_count"))
    max_iters = _read_max_iters(request.parameters.get("max_iters"))
    include_inverse_matrix = _read_bool(
        request.parameters.get("include_inverse_matrix"),
        field_name="include_inverse_matrix",
        default_value=True,
    )

    match_items = matches_payload["items"]
    if len(match_items) < max(4, min_match_count):
        raise InvalidRequestError(
            "当前匹配数量不足，无法估计 homography",
            details={
                "match_count": len(match_items),
                "min_match_count": max(4, min_match_count),
            },
        )

    feature_items_a = features_a_payload["items"]
    feature_items_b = features_b_payload["items"]
    source_points: list[list[float]] = []
    target_points: list[list[float]] = []
    match_ids: list[str] = []
    for match_item in match_items:
        query_index = int(match_item["query_index"])
        train_index = int(match_item["train_index"])
        if query_index >= len(feature_items_a) or train_index >= len(feature_items_b):
            raise InvalidRequestError("feature-matches 中的索引超出 local-features 范围")
        query_feature = feature_items_a[query_index]
        train_feature = feature_items_b[train_index]
        if str(query_feature["feature_id"]) != str(match_item["query_feature_id"]):
            raise InvalidRequestError("feature-matches.query_feature_id 与 features_a 不一致")
        if str(train_feature["feature_id"]) != str(match_item["train_feature_id"]):
            raise InvalidRequestError("feature-matches.train_feature_id 与 features_b 不一致")
        source_points.append([float(query_feature["x"]), float(query_feature["y"])])
        target_points.append([float(train_feature["x"]), float(train_feature["y"])])
        match_ids.append(str(match_item["match_id"]))

    source_point_matrix = np_module.array(source_points, dtype=np_module.float32)
    target_point_matrix = np_module.array(target_points, dtype=np_module.float32)
    homography_matrix, inlier_mask = cv2_module.findHomography(
        source_point_matrix,
        target_point_matrix,
        method=_resolve_method(method_name, cv2_module=cv2_module),
        ransacReprojThreshold=ransac_reprojection_threshold,
        maxIters=max_iters,
        confidence=confidence,
    )
    if homography_matrix is None:
        raise InvalidRequestError("当前匹配无法估计出稳定的 homography")

    inlier_flags = (
        [bool(int(flag_value)) for flag_value in inlier_mask.reshape(-1).tolist()]
        if inlier_mask is not None
        else [True] * len(match_ids)
    )
    inlier_match_ids = [
        match_id for match_id, inlier_flag in zip(match_ids, inlier_flags, strict=False) if inlier_flag
    ]
    projected_points = cv2_module.perspectiveTransform(
        source_point_matrix.reshape(-1, 1, 2),
        homography_matrix,
    ).reshape(-1, 2)
    reprojection_errors: list[float] = []
    for point_index, inlier_flag in enumerate(inlier_flags):
        if not inlier_flag:
            continue
        dx_value = float(projected_points[point_index][0] - target_point_matrix[point_index][0])
        dy_value = float(projected_points[point_index][1] - target_point_matrix[point_index][1])
        reprojection_errors.append(float((dx_value * dx_value + dy_value * dy_value) ** 0.5))
    reprojection_error = (
        round(sum(reprojection_errors) / len(reprojection_errors), 6) if reprojection_errors else None
    )

    inverse_matrix_payload: list[list[float]] | None = None
    if include_inverse_matrix:
        try:
            inverse_matrix = np_module.linalg.inv(homography_matrix)
        except np_module.linalg.LinAlgError:
            inverse_matrix_payload = None
        else:
            inverse_matrix_payload = [
                [round(float(cell_value), 8) for cell_value in row_values.tolist()]
                for row_values in inverse_matrix
            ]

    matrix_payload = [
        [round(float(cell_value), 8) for cell_value in row_values.tolist()]
        for row_values in homography_matrix
    ]
    transform_payload = build_planar_transform_payload(
        matrix_3x3=matrix_payload,
        inverse_matrix_3x3=inverse_matrix_payload,
        match_count=len(match_ids),
        inlier_count=len(inlier_match_ids),
        inlier_match_ids=inlier_match_ids,
        reprojection_error=reprojection_error,
        source_a_image=features_a_payload.get("source_image"),
        source_b_image=features_b_payload.get("source_image"),
        source_a_object_key=features_a_payload.get("source_object_key"),
        source_b_object_key=features_b_payload.get("source_object_key"),
    )
    return {
        "transform": transform_payload,
        "summary": build_value_payload(
            {
                "method": method_name,
                "match_count": len(match_ids),
                "inlier_count": len(inlier_match_ids),
                "inlier_ratio": round(len(inlier_match_ids) / len(match_ids), 6) if match_ids else 0.0,
                "ransac_reprojection_threshold": ransac_reprojection_threshold,
                "confidence": confidence,
                "max_iters": max_iters,
                "min_match_count": min_match_count,
                "reprojection_error": reprojection_error,
                "has_inverse_matrix": inverse_matrix_payload is not None,
                "matrix_3x3": matrix_payload,
                "inlier_match_ids": inlier_match_ids,
            }
        ),
    }
