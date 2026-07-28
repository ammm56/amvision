"""使用 FLANN 对局部描述子执行 KNN ratio 匹配。"""

from __future__ import annotations

from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.features import (
    build_feature_matches_payload,
    require_feature_matches_payload,
    require_local_features_payload,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.flann-match"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按描述子类型选择 KDTree 或 LSH 索引并输出匹配结果。"""

    cv2, np = require_opencv_imports()
    features_a = require_local_features_payload(request.input_values.get("features_a"))
    features_b = require_local_features_payload(request.input_values.get("features_b"))
    if int(features_a["descriptor_length"]) != int(features_b["descriptor_length"]):
        raise InvalidRequestError("两路描述子的长度必须一致")
    if str(features_a["descriptor_dtype"]) != str(features_b["descriptor_dtype"]):
        raise InvalidRequestError("两路描述子的 dtype 必须一致")
    ratio = read_float(
        request.parameters.get("ratio_test_threshold"),
        field_name="ratio_test_threshold",
        default=0.75,
        minimum=0.01,
        maximum=0.99,
    )
    max_matches = read_int(
        request.parameters.get("max_matches"),
        field_name="max_matches",
        default=200,
        minimum=1,
    )
    descriptor_dtype = str(features_a["descriptor_dtype"])
    if descriptor_dtype == "float32":
        index_params = {"algorithm": 1, "trees": 5}
        matrix_a = np.asarray(features_a["descriptors"], dtype=np.float32)
        matrix_b = np.asarray(features_b["descriptors"], dtype=np.float32)
        matcher_kind = "flann-kdtree"
    else:
        index_params = {
            "algorithm": 6,
            "table_number": 12,
            "key_size": 20,
            "multi_probe_level": 2,
        }
        matrix_a = np.asarray(features_a["descriptors"], dtype=np.uint8)
        matrix_b = np.asarray(features_b["descriptors"], dtype=np.uint8)
        matcher_kind = "flann-lsh"
    selected: list[Any] = []
    raw_count = 0
    if len(matrix_a) > 0 and len(matrix_b) >= 2:
        matcher = cv2.FlannBasedMatcher(index_params, {"checks": 64})
        pairs = matcher.knnMatch(matrix_a, matrix_b, k=2)
        raw_count = len(pairs)
        selected = [
            pair[0]
            for pair in pairs
            if len(pair) >= 2 and pair[0].distance < ratio * pair[1].distance
        ]
    selected.sort(key=lambda item: float(item.distance))
    selected = selected[:max_matches]
    items: list[dict[str, object]] = []
    for index, match in enumerate(selected, start=1):
        query = features_a["items"][int(match.queryIdx)]
        train = features_b["items"][int(match.trainIdx)]
        items.append(
            {
                "match_id": f"match-{index}",
                "query_feature_id": str(query["feature_id"]),
                "train_feature_id": str(train["feature_id"]),
                "query_index": int(match.queryIdx),
                "train_index": int(match.trainIdx),
                "distance": float(match.distance),
                "query_xy": [float(query["x"]), float(query["y"])],
                "train_xy": [float(train["x"]), float(train["y"])],
            }
        )
    payload = require_feature_matches_payload(
        build_feature_matches_payload(
            items=items,
            source_a_image=features_a.get("source_image"),
            source_b_image=features_b.get("source_image"),
            matcher_kind=matcher_kind,
            cross_check=False,
            ratio_test_threshold=ratio,
            source_a_object_key=features_a.get("source_object_key"),
            source_b_object_key=features_b.get("source_object_key"),
        )
    )
    return {
        "matches": payload,
        "summary": build_value_payload(
            {
                "matcher_kind": matcher_kind,
                "descriptor_dtype": descriptor_dtype,
                "ratio_test_threshold": ratio,
                "raw_match_count": raw_count,
                "match_count": len(items),
            }
        ),
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
