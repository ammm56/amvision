"""edge-break-check core 节点测试。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.edge_break_check import _edge_break_check_handler
from backend.nodes.runtime_support import build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_edge_break_check_passes_continuous_diagonal_edge_region() -> None:
    """验证 edge-break-check 会放行连续对角边。"""

    image_registry = ExecutionImageRegistry()
    continuous_mask = np.zeros((80, 80), dtype=np.uint8)
    cv2.line(continuous_mask, (10, 64), (68, 18), 1, thickness=4)

    output = _edge_break_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="edge-break-check",
            node_definition=object(),
            parameters={
                "match_mode": "all",
                "min_gap_pixels_to_count": 2,
                "max_gap_pixels": 0,
                "max_gap_count": 0,
                "min_elongation_ratio": 2.0,
            },
            input_values={
                "regions": _build_regions_payload(
                    image_registry=image_registry,
                    masks=[continuous_mask],
                )
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is True
    assert output["metrics"]["value"]["passed_count"] == 1
    assert output["metrics"]["value"]["items"][0]["gap_count"] == 0
    assert output["metrics"]["value"]["items"][0]["longest_gap_pixels"] == 0.0
    assert output["metrics"]["value"]["items"][0]["elongation_ratio"] >= 2.0


def test_edge_break_check_rejects_broken_diagonal_edge_region() -> None:
    """验证 edge-break-check 会拒绝沿主方向存在明显断段的边。"""

    image_registry = ExecutionImageRegistry()
    broken_mask = np.zeros((80, 80), dtype=np.uint8)
    cv2.line(broken_mask, (10, 64), (68, 18), 1, thickness=4)
    cv2.line(broken_mask, (34, 46), (46, 34), 0, thickness=8)

    output = _edge_break_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="edge-break-check",
            node_definition=object(),
            parameters={
                "match_mode": "all",
                "min_gap_pixels_to_count": 2,
                "max_gap_pixels": 0,
                "max_gap_count": 0,
                "min_elongation_ratio": 2.0,
            },
            input_values={
                "regions": _build_regions_payload(
                    image_registry=image_registry,
                    masks=[broken_mask],
                )
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is False
    assert output["metrics"]["value"]["failed_count"] == 1
    checked_item = output["metrics"]["value"]["items"][0]
    assert checked_item["gap_count"] >= 1
    assert checked_item["longest_gap_pixels"] > 0.0
    assert "too-many-axis-gaps" in checked_item["failure_reasons"] or "axis-gap-too-large" in checked_item["failure_reasons"]


def _build_regions_payload(
    *,
    image_registry: ExecutionImageRegistry,
    masks: list[np.ndarray],
) -> dict[str, object]:
    """构造带 mask_image 的 regions.v1 payload。"""

    items: list[dict[str, object]] = []
    for item_index, mask_matrix in enumerate(masks, start=1):
        y_indices, x_indices = np.nonzero(mask_matrix > 0)
        x1_value = float(np.min(x_indices))
        y1_value = float(np.min(y_indices))
        x2_value = float(np.max(x_indices) + 1)
        y2_value = float(np.max(y_indices) + 1)
        items.append(
            {
                "region_id": f"region-{item_index}",
                "score": 0.96,
                "class_id": 1,
                "class_name": "edge-strip",
                "bbox_xyxy": [x1_value, y1_value, x2_value, y2_value],
                "polygon_xy": [
                    [x1_value, y1_value],
                    [x2_value, y1_value],
                    [x2_value, y2_value],
                    [x1_value, y2_value],
                ],
                "area": int(np.count_nonzero(mask_matrix)),
                "mask_image": _build_mask_image_payload(image_registry, mask_matrix),
            }
        )
    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "image-edge-break-test",
            "media_type": "image/png",
            "width": 80,
            "height": 80,
        },
        "count": len(items),
        "items": items,
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
