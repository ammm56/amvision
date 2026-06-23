"""孔位模式与缺角 core 节点测试。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.vision.pattern.corner_missing_check import _corner_missing_check_handler
from backend.nodes.core_nodes.vision.pattern.hole_pattern_check import _hole_pattern_check_handler
from backend.nodes.runtime_support import build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_hole_pattern_check_passes_even_horizontal_holes() -> None:
    """验证 hole-pattern-check 可放行数量和节距都正确的横向孔列。"""

    output = _hole_pattern_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="hole-pattern-check",
            node_definition=object(),
            parameters={
                "hole_filter": {"class_name": "mount-hole"},
                "axis": "x",
                "expected_count": 3,
                "expected_pitch": 30.0,
                "max_abs_pitch_error": 1.0,
                "max_orthogonal_deviation": 1.0,
            },
            input_values={"regions": _build_hole_regions_payload()},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is True
    metrics_value = output["metrics"]["value"]
    assert metrics_value["matched_count"] == 3
    assert metrics_value["resolved_axis"] == "x"
    assert metrics_value["matched_region_ids"] == ["hole-left", "hole-middle", "hole-right"]
    assert metrics_value["pitches"] == [30.0, 30.0]
    assert metrics_value["max_actual_orthogonal_deviation"] == 0.0


def test_hole_pattern_check_rejects_pitch_mismatch() -> None:
    """验证 hole-pattern-check 会拒绝节距超差的孔列。"""

    output = _hole_pattern_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="hole-pattern-check",
            node_definition=object(),
            parameters={
                "hole_filter": {"class_name": "mount-hole"},
                "axis": "x",
                "expected_count": 3,
                "expected_pitch": 30.0,
                "max_abs_pitch_error": 1.0,
                "max_orthogonal_deviation": 1.0,
            },
            input_values={"regions": _build_hole_regions_payload(pitch_offset=4.0)},
            execution_metadata={},
        )
    )

    assert output["result"]["value"] is False
    metrics_value = output["metrics"]["value"]
    assert "pitch-error-too-large" in metrics_value["failure_reasons"]
    assert metrics_value["pitches"] == [30.0, 34.0]


def test_corner_missing_check_passes_complete_corner() -> None:
    """验证 corner-missing-check 会放行完整角点。"""

    image_registry = ExecutionImageRegistry()
    output = _corner_missing_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="corner-missing-check",
            node_definition=object(),
            parameters={
                "selector": {"class_name": "plate-body", "strategy": "largest-area"},
                "corner": "top-right",
                "window_ratio": 0.25,
                "min_corner_fill_ratio": 0.8,
                "window_shape": "triangle",
            },
            input_values={"regions": _build_corner_regions_payload(image_registry, missing_corner=False)},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is True
    metrics_value = output["metrics"]["value"]
    assert metrics_value["selected_region_id"] == "plate-body"
    assert metrics_value["corner_fill_ratio"] >= 0.8


def test_corner_missing_check_rejects_missing_corner() -> None:
    """验证 corner-missing-check 会拒绝缺角目标。"""

    image_registry = ExecutionImageRegistry()
    output = _corner_missing_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="corner-missing-check",
            node_definition=object(),
            parameters={
                "selector": {"class_name": "plate-body", "strategy": "largest-area"},
                "corner": "top-right",
                "window_ratio": 0.25,
                "min_corner_fill_ratio": 0.8,
                "window_shape": "triangle",
            },
            input_values={"regions": _build_corner_regions_payload(image_registry, missing_corner=True)},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is False
    metrics_value = output["metrics"]["value"]
    assert "low-corner-fill-ratio" in metrics_value["failure_reasons"]
    assert metrics_value["corner_fill_ratio"] < 0.8


def _build_hole_regions_payload(*, pitch_offset: float = 0.0) -> dict[str, object]:
    """构造三孔横向排布的 regions.v1。"""

    left_center_x = 24.0
    middle_center_x = 54.0
    right_center_x = 84.0 + pitch_offset
    centers = [left_center_x, middle_center_x, right_center_x]
    items: list[dict[str, object]] = []
    for index, center_x in enumerate(centers, start=1):
        x1_value = center_x - 4.0
        x2_value = center_x + 4.0
        items.append(
            {
                "region_id": ["hole-left", "hole-middle", "hole-right"][index - 1],
                "score": 0.98 - (index * 0.01),
                "class_id": 1,
                "class_name": "mount-hole",
                "bbox_xyxy": [x1_value, 20.0, x2_value, 28.0],
                "polygon_xy": [[x1_value, 20.0], [x2_value, 20.0], [x2_value, 28.0], [x1_value, 28.0]],
                "area": 64,
            }
        )
    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "hole-pattern-image",
            "media_type": "image/png",
            "width": 128,
            "height": 64,
        },
        "count": len(items),
        "items": items,
    }


def _build_corner_regions_payload(
    image_registry: ExecutionImageRegistry,
    *,
    missing_corner: bool,
) -> dict[str, object]:
    """构造完整或缺角板件 regions.v1。"""

    mask_matrix = np.zeros((96, 96), dtype=np.uint8)
    cv2.rectangle(mask_matrix, (16, 16), (80, 80), 1, thickness=-1)
    if missing_corner:
        triangle = np.array([[64, 16], [80, 16], [80, 32]], dtype=np.int32)
        cv2.fillConvexPoly(mask_matrix, triangle, 0)
    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "corner-check-image",
            "media_type": "image/png",
            "width": 96,
            "height": 96,
        },
        "count": 1,
        "items": [
            {
                "region_id": "plate-body",
                "score": 0.97,
                "class_id": 1,
                "class_name": "plate-body",
                "bbox_xyxy": [16.0, 16.0, 81.0, 81.0],
                "polygon_xy": [[16.0, 16.0], [81.0, 16.0], [81.0, 81.0], [16.0, 81.0]],
                "area": int(np.count_nonzero(mask_matrix)),
                "mask_image": _build_mask_image_payload(image_registry, mask_matrix),
            }
        ],
    }


def _build_mask_image_payload(
    image_registry: ExecutionImageRegistry,
    mask_matrix: np.ndarray,
) -> dict[str, object]:
    """把测试 mask 编码成 memory image-ref payload。"""

    success, encoded = cv2.imencode(".png", (mask_matrix.astype(np.uint8) * 255))
    assert success is True
    entry = image_registry.register_image_bytes(
        content=encoded.tobytes(),
        media_type="image/png",
        width=int(mask_matrix.shape[1]),
        height=int(mask_matrix.shape[0]),
        created_by_node_id="fixture",
    )
    return build_memory_image_payload(
        image_handle=entry.image_handle,
        media_type="image/png",
        width=int(mask_matrix.shape[1]),
        height=int(mask_matrix.shape[0]),
    )
