"""ORB Match 节点实现。"""

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
from custom_nodes._opencv_shared.backend.runtime.features import (
    build_feature_matches_payload,
    require_feature_matches_payload,
    require_local_features_payload,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.orb-match"


def _read_matcher_kind(raw_value: object, *, descriptor_norm: str) -> str:
    """读取 matcher_kind。"""

    default_value = "bf-hamming2" if descriptor_norm == "hamming2" else "bf-hamming"
    if is_empty_parameter(raw_value):
        return default_value
    if not isinstance(raw_value, str):
        raise InvalidRequestError("matcher_kind 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"bf-hamming", "bf-hamming2"}:
        raise InvalidRequestError("matcher_kind 仅支持 bf-hamming 或 bf-hamming2")
    return normalized_value


def _read_ratio_test_threshold(raw_value: object) -> float:
    """读取 ratio_test_threshold。"""

    if is_empty_parameter(raw_value):
        return 0.75
    normalized_value = require_non_negative_float(raw_value, field_name="ratio_test_threshold")
    if normalized_value <= 0.0 or normalized_value >= 1.0:
        raise InvalidRequestError("ratio_test_threshold 必须在 0 到 1 之间")
    return float(normalized_value)


def _read_max_matches(raw_value: object) -> int:
    """读取最大匹配数。"""

    if is_empty_parameter(raw_value):
        return 100
    return require_positive_int(raw_value, field_name="max_matches")


def _read_optional_max_distance(raw_value: object) -> float | None:
    """读取可选最大距离阈值。"""

    if is_empty_parameter(raw_value):
        return None
    return float(require_non_negative_float(raw_value, field_name="max_distance"))


def _read_debug_max_match_lines(raw_value: object) -> int:
    """读取 debug_preview 中最多绘制的匹配线数量。"""

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


def _resolve_norm_type(*, matcher_kind: str, cv2_module) -> int:
    """把 matcher_kind 解析为 OpenCV BFMatcher normType。"""

    if matcher_kind == "bf-hamming":
        return cv2_module.NORM_HAMMING
    if matcher_kind == "bf-hamming2":
        return cv2_module.NORM_HAMMING2
    raise InvalidRequestError("不支持的 matcher_kind", details={"matcher_kind": matcher_kind})


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对两组 ORB 局部特征执行描述子匹配与过滤。"""

    cv2_module, np_module = require_opencv_imports()
    features_a_payload = require_local_features_payload(request.input_values.get("features_a"))
    features_b_payload = require_local_features_payload(request.input_values.get("features_b"))
    if str(features_a_payload.get("descriptor_kind")) != "orb" or str(features_b_payload.get("descriptor_kind")) != "orb":
        raise InvalidRequestError("orb-match 当前只支持 ORB 描述子输入")
    descriptor_norm = str(features_a_payload.get("descriptor_norm", "hamming"))
    if str(features_b_payload.get("descriptor_norm", "hamming")) != descriptor_norm:
        raise InvalidRequestError("两路 local-features 的 descriptor_norm 必须一致")
    if int(features_a_payload["descriptor_length"]) != int(features_b_payload["descriptor_length"]):
        raise InvalidRequestError("两路 local-features 的 descriptor_length 必须一致")

    matcher_kind = _read_matcher_kind(
        request.parameters.get("matcher_kind"),
        descriptor_norm=descriptor_norm,
    )
    cross_check = _read_bool(
        request.parameters.get("cross_check"),
        field_name="cross_check",
        default_value=False,
    )
    ratio_test_threshold = _read_ratio_test_threshold(request.parameters.get("ratio_test_threshold"))
    max_matches = _read_max_matches(request.parameters.get("max_matches"))
    max_distance = _read_optional_max_distance(request.parameters.get("max_distance"))
    debug_show_match_lines = _read_bool(
        request.parameters.get("debug_show_match_lines"),
        field_name="debug_show_match_lines",
        default_value=True,
    )
    debug_max_match_lines = _read_debug_max_match_lines(request.parameters.get("debug_max_match_lines"))
    debug_selected_match_ids = _read_debug_selected_match_ids(
        request.parameters.get("debug_selected_match_ids")
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
    descriptor_matrix_a = np_module.array(features_a_payload["descriptors"], dtype=np_module.uint8)
    descriptor_matrix_b = np_module.array(features_b_payload["descriptors"], dtype=np_module.uint8)
    raw_match_count = 0
    selected_matches: list[object] = []
    if descriptor_matrix_a.size > 0 and descriptor_matrix_b.size > 0:
        matcher = cv2_module.BFMatcher(
            _resolve_norm_type(matcher_kind=matcher_kind, cv2_module=cv2_module),
            crossCheck=cross_check,
        )
        if cross_check:
            raw_matches = matcher.match(descriptor_matrix_a, descriptor_matrix_b)
            raw_match_count = len(raw_matches)
            selected_matches = list(raw_matches)
        else:
            raw_knn_matches = matcher.knnMatch(descriptor_matrix_a, descriptor_matrix_b, k=2)
            raw_match_count = len(raw_knn_matches)
            for knn_item in raw_knn_matches:
                if len(knn_item) < 2:
                    continue
                best_match, second_match = knn_item[:2]
                if float(best_match.distance) < float(second_match.distance) * ratio_test_threshold:
                    selected_matches.append(best_match)

    selected_matches.sort(key=lambda current_match: float(current_match.distance))
    if max_distance is not None:
        selected_matches = [
            current_match for current_match in selected_matches if float(current_match.distance) <= max_distance
        ]
    selected_matches = selected_matches[:max_matches]

    feature_items_a = features_a_payload["items"]
    feature_items_b = features_b_payload["items"]
    match_items: list[dict[str, object]] = []
    for match_index, current_match in enumerate(selected_matches, start=1):
        query_index = int(current_match.queryIdx)
        train_index = int(current_match.trainIdx)
        feature_item_a = feature_items_a[query_index]
        feature_item_b = feature_items_b[train_index]
        match_items.append(
            {
                "match_id": f"match-{match_index}",
                "query_feature_id": str(feature_item_a["feature_id"]),
                "train_feature_id": str(feature_item_b["feature_id"]),
                "query_index": query_index,
                "train_index": train_index,
                "distance": round(float(current_match.distance), 6),
                "query_xy": [float(feature_item_a["x"]), float(feature_item_a["y"])],
                "train_xy": [float(feature_item_b["x"]), float(feature_item_b["y"])],
            }
        )
    matches_payload = build_feature_matches_payload(
        items=match_items,
        source_a_image=features_a_payload.get("source_image"),
        source_b_image=features_b_payload.get("source_image"),
        matcher_kind=matcher_kind,
        cross_check=cross_check,
        ratio_test_threshold=None if cross_check else ratio_test_threshold,
        source_a_object_key=features_a_payload.get("source_object_key"),
        source_b_object_key=features_b_payload.get("source_object_key"),
    )
    matches_payload = require_feature_matches_payload(matches_payload)
    distance_values = [float(item["distance"]) for item in match_items]
    outputs: dict[str, object] = {
        "matches": matches_payload,
        "summary": build_value_payload(
            {
                "matcher_kind": matcher_kind,
                "cross_check": cross_check,
                "ratio_test_threshold": None if cross_check else ratio_test_threshold,
                "max_matches": max_matches,
                "max_distance": max_distance,
                "query_feature_count": int(features_a_payload["count"]),
                "train_feature_count": int(features_b_payload["count"]),
                "raw_match_count": raw_match_count,
                "match_count": len(match_items),
                "mean_distance": round(sum(distance_values) / len(distance_values), 6) if distance_values else None,
                "min_distance": round(min(distance_values), 6) if distance_values else None,
                "max_distance_observed": round(max(distance_values), 6) if distance_values else None,
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
            title="ORB Match",
            artifact_name="orb-match-debug-preview",
            match_items=match_items,
            interaction=_build_orb_match_interaction(
                ratio_test_threshold=ratio_test_threshold,
                max_matches=max_matches,
                max_distance=max_distance,
                debug_show_match_lines=debug_show_match_lines,
                debug_max_match_lines=debug_max_match_lines,
                debug_selected_match_only=debug_selected_match_only,
                debug_show_left_points=debug_show_left_points,
                debug_show_right_points=debug_show_right_points,
            ),
            selected_match_ids=debug_selected_match_ids,
            show_match_lines=debug_show_match_lines,
            selected_match_only=debug_selected_match_only,
            show_left_points=debug_show_left_points,
            show_right_points=debug_show_right_points,
            manual_pair_lines_xyxy=debug_manual_pair_lines_xyxy,
            max_match_lines=debug_max_match_lines,
        )
    )
    return outputs


def _build_orb_match_interaction(
    *,
    ratio_test_threshold: float,
    max_matches: int,
    max_distance: float | None,
    debug_show_match_lines: bool,
    debug_max_match_lines: int,
    debug_selected_match_only: bool,
    debug_show_left_points: bool,
    debug_show_right_points: bool,
) -> dict[str, object]:
    """声明 ORB Match 在双图图片面板中的调参能力。"""

    resolved_max_distance = float(max_distance) if max_distance is not None else 256.0
    return build_debug_panel_interaction(
        coordinate_space="source-image-pair",
        tools=[
            build_interaction_tool("match-line", "点选匹配线", ["debug_selected_match_ids"]),
            build_interaction_tool("point-pair", "手动点对", ["debug_manual_pair_lines_xyxy"]),
        ],
        controls=[
            build_numeric_control(
                "ratio_test_threshold",
                "Ratio Test",
                ratio_test_threshold,
                min_value=0.05,
                max_value=0.99,
                step=0.01,
            ),
            build_numeric_control(
                "max_matches",
                "Max Matches",
                max_matches,
                min_value=1.0,
                max_value=1000.0,
                step=1.0,
            ),
            build_numeric_control(
                "max_distance",
                "Max Distance",
                resolved_max_distance,
                min_value=0.0,
                max_value=512.0,
                step=1.0,
            ),
            build_checkbox_control("debug_show_match_lines", "显示匹配线", debug_show_match_lines),
            build_checkbox_control("debug_selected_match_only", "只显示点选匹配", debug_selected_match_only),
            build_checkbox_control("debug_show_left_points", "显示左图端点", debug_show_left_points),
            build_checkbox_control("debug_show_right_points", "显示右图端点", debug_show_right_points),
            build_numeric_control(
                "debug_max_match_lines",
                "最多显示匹配线",
                debug_max_match_lines,
                min_value=1.0,
                max_value=1000.0,
                step=1.0,
            ),
        ],
    )
