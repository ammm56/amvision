"""Homography Estimate 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_checkbox_control,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_numeric_control,
)
from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_matching_nodes.backend.nodes.debug_pair_preview import (
    build_pair_match_debug_preview_output,
)
from custom_nodes._opencv_shared.backend.runtime.transforms import build_planar_transform_payload
from custom_nodes._opencv_shared.backend.runtime.features import (
    require_feature_matches_payload,
    require_local_features_payload,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.homography-estimate"


def _read_method(raw_value: object) -> str:
    """读取 homography 估计方法。"""

    if is_empty_parameter(raw_value):
        return "ransac"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("method 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"ransac", "lmeds"}:
        raise InvalidRequestError("method 仅支持 ransac 或 lmeds")
    return normalized_value


def _read_ransac_reprojection_threshold(raw_value: object) -> float:
    """读取 RANSAC 重投影阈值。"""

    if is_empty_parameter(raw_value):
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

    if is_empty_parameter(raw_value):
        return 0.995
    normalized_value = require_non_negative_float(raw_value, field_name="confidence")
    if normalized_value <= 0.0 or normalized_value >= 1.0:
        raise InvalidRequestError("confidence 必须在 0 到 1 之间")
    return float(normalized_value)


def _read_min_match_count(raw_value: object) -> int:
    """读取最小匹配数。"""

    if is_empty_parameter(raw_value):
        return 4
    return require_positive_int(raw_value, field_name="min_match_count")


def _read_max_iters(raw_value: object) -> int:
    """读取最大迭代次数。"""

    if is_empty_parameter(raw_value):
        return 2000
    return require_positive_int(raw_value, field_name="max_iters")


def _read_debug_max_match_lines(raw_value: object) -> int:
    """读取 debug_preview 中最多绘制的内点匹配线数量。"""

    if is_empty_parameter(raw_value):
        return 200
    return require_positive_int(raw_value, field_name="debug_max_match_lines")


def _read_debug_selected_match_ids(raw_value: object) -> set[str]:
    """读取图片面板点选的 match id 集合，仅用于调试图高亮和筛选。"""

    if is_empty_parameter(raw_value):
        return set()
    if not isinstance(raw_value, list):
        raise InvalidRequestError("debug_selected_match_ids 必须是字符串数组")
    selected_match_ids: set[str] = set()
    for item in raw_value:
        if not isinstance(item, str):
            raise InvalidRequestError("debug_selected_match_ids 必须是字符串数组")
        normalized_value = item.strip()
        if normalized_value:
            selected_match_ids.add(normalized_value)
    return selected_match_ids


def _read_optional_debug_selected_projection_id(raw_value: object) -> str | None:
    """读取图片面板点选的 homography 投影框 id，仅用于调试图高亮。"""

    if is_empty_parameter(raw_value):
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError("debug_selected_projection_id 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def _read_debug_manual_pair_lines(raw_value: object) -> list[list[float]]:
    """读取图片面板手动画出的双图点对线列表，仅用于调试显示。"""

    if raw_value is None or raw_value == "":
        return []
    if not isinstance(raw_value, list):
        raise InvalidRequestError("debug_manual_pair_lines_xyxy 必须是点对线数组")
    normalized_lines: list[list[float]] = []
    for raw_line in raw_value:
        if not isinstance(raw_line, list) or len(raw_line) < 4:
            raise InvalidRequestError("debug_manual_pair_lines_xyxy 的每一项必须是 4 个数字组成的数组")
        try:
            normalized_lines.append([float(item) for item in raw_line[:4]])
        except (TypeError, ValueError) as error:
            raise InvalidRequestError("debug_manual_pair_lines_xyxy 的每一项必须是 4 个数字组成的数组") from error
    return normalized_lines


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
    debug_show_match_lines = _read_bool(
        request.parameters.get("debug_show_match_lines"),
        field_name="debug_show_match_lines",
        default_value=True,
    )
    debug_show_homography_projection = _read_bool(
        request.parameters.get("debug_show_homography_projection"),
        field_name="debug_show_homography_projection",
        default_value=True,
    )
    debug_max_match_lines = _read_debug_max_match_lines(request.parameters.get("debug_max_match_lines"))
    debug_selected_match_ids = _read_debug_selected_match_ids(
        request.parameters.get("debug_selected_match_ids")
    )
    debug_selected_projection_id = _read_optional_debug_selected_projection_id(
        request.parameters.get("debug_selected_projection_id")
    )
    debug_selected_match_only = _read_bool(
        request.parameters.get("debug_selected_match_only"),
        field_name="debug_selected_match_only",
        default_value=False,
    )
    debug_show_left_points = _read_bool(
        request.parameters.get("debug_show_left_points"),
        field_name="debug_show_left_points",
        default_value=True,
    )
    debug_show_right_points = _read_bool(
        request.parameters.get("debug_show_right_points"),
        field_name="debug_show_right_points",
        default_value=True,
    )
    debug_manual_pair_lines_xyxy = _read_debug_manual_pair_lines(
        request.parameters.get("debug_manual_pair_lines_xyxy")
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
    outputs: dict[str, object] = {
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
    outputs.update(
        build_pair_match_debug_preview_output(
            request,
            cv2_module=cv2_module,
            np_module=np_module,
            source_a_image=features_a_payload.get("source_image"),
            source_b_image=features_b_payload.get("source_image"),
            title="Homography Estimate",
            artifact_name="homography-estimate-debug-preview",
            match_items=match_items,
            interaction=_build_homography_interaction(
                ransac_reprojection_threshold=ransac_reprojection_threshold,
                confidence=confidence,
                max_iters=max_iters,
                min_match_count=min_match_count,
                debug_show_match_lines=debug_show_match_lines,
                debug_show_homography_projection=debug_show_homography_projection,
                debug_max_match_lines=debug_max_match_lines,
                debug_selected_match_only=debug_selected_match_only,
                debug_show_left_points=debug_show_left_points,
                debug_show_right_points=debug_show_right_points,
            ),
            inlier_match_ids=set(inlier_match_ids),
            homography_matrix=homography_matrix,
            selected_match_ids=debug_selected_match_ids,
            show_match_lines=debug_show_match_lines,
            show_homography_projection=debug_show_homography_projection,
            selected_match_only=debug_selected_match_only,
            show_left_points=debug_show_left_points,
            show_right_points=debug_show_right_points,
            manual_pair_lines_xyxy=debug_manual_pair_lines_xyxy,
            selected_projection_id=debug_selected_projection_id,
            max_match_lines=debug_max_match_lines,
        )
    )
    return outputs


def _build_homography_interaction(
    *,
    ransac_reprojection_threshold: float,
    confidence: float,
    max_iters: int,
    min_match_count: int,
    debug_show_match_lines: bool,
    debug_show_homography_projection: bool,
    debug_max_match_lines: int,
    debug_selected_match_only: bool,
    debug_show_left_points: bool,
    debug_show_right_points: bool,
) -> dict[str, object]:
    """声明 Homography Estimate 在双图图片面板中的调参能力。"""

    return build_debug_panel_interaction(
        coordinate_space="source-image-pair",
        tools=[
            build_interaction_tool("match-line", "点选内点线", ["debug_selected_match_ids"]),
            build_interaction_tool("point-pair", "手动点对", ["debug_manual_pair_lines_xyxy"]),
            build_interaction_tool("homography-overlay", "点选投影框", ["debug_selected_projection_id"]),
        ],
        controls=[
            build_numeric_control(
                "ransac_reprojection_threshold",
                "RANSAC Threshold",
                ransac_reprojection_threshold,
                min_value=0.1,
                max_value=20.0,
                step=0.1,
            ),
            build_numeric_control(
                "confidence",
                "Confidence",
                confidence,
                min_value=0.5,
                max_value=0.999,
                step=0.001,
            ),
            build_numeric_control(
                "max_iters",
                "Max Iters",
                max_iters,
                min_value=100.0,
                max_value=10000.0,
                step=100.0,
            ),
            build_numeric_control(
                "min_match_count",
                "Min Matches",
                min_match_count,
                min_value=4.0,
                max_value=200.0,
                step=1.0,
            ),
            build_checkbox_control("debug_show_match_lines", "显示内点线", debug_show_match_lines),
            build_checkbox_control("debug_selected_match_only", "只显示点选内点", debug_selected_match_only),
            build_checkbox_control("debug_show_left_points", "显示左图端点", debug_show_left_points),
            build_checkbox_control("debug_show_right_points", "显示右图端点", debug_show_right_points),
            build_checkbox_control(
                "debug_show_homography_projection",
                "显示投影框",
                debug_show_homography_projection,
            ),
            build_numeric_control(
                "debug_max_match_lines",
                "最多显示内点线",
                debug_max_match_lines,
                min_value=1.0,
                max_value=1000.0,
                step=1.0,
            ),
        ],
    )
