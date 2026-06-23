"""region 线性度 core 节点测试。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.vision.geometry.linearity_check import _linearity_check_handler
from backend.nodes.runtime_support import build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_linearity_check_passes_straight_region() -> None:
    """验证 linearity-check 可判定直条区域为通过。"""

    image_registry = ExecutionImageRegistry()
    straight_mask = np.zeros((80, 80), dtype=np.uint8)
    cv2.line(straight_mask, (10, 60), (70, 20), 1, thickness=4)

    output = _linearity_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="linearity-check",
            node_definition=object(),
            parameters={
                "match_mode": "all",
                "min_line_length_pixels": 30.0,
                "max_rms_distance_pixels": 2.5,
            },
            input_values={
                "regions": _build_regions_payload(
                    image_registry=image_registry,
                    masks=[straight_mask],
                )
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is True
    assert output["metrics"]["value"]["passed_count"] == 1
    assert output["metrics"]["value"]["items"][0]["rms_distance_pixels"] <= 2.5


def test_linearity_check_rejects_bent_region() -> None:
    """验证 linearity-check 会拒绝明显弯折区域。"""

    image_registry = ExecutionImageRegistry()
    bent_mask = np.zeros((80, 80), dtype=np.uint8)
    bent_points = np.array([[10, 60], [34, 44], [52, 28], [70, 42]], dtype=np.int32).reshape((-1, 1, 2))
    cv2.polylines(bent_mask, [bent_points], isClosed=False, color=1, thickness=4)

    output = _linearity_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="linearity-check",
            node_definition=object(),
            parameters={
                "match_mode": "all",
                "min_line_length_pixels": 30.0,
                "max_rms_distance_pixels": 2.5,
            },
            input_values={
                "regions": _build_regions_payload(
                    image_registry=image_registry,
                    masks=[bent_mask],
                )
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is False
    assert output["metrics"]["value"]["failed_count"] == 1
    assert "rms-distance-too-large" in output["metrics"]["value"]["items"][0]["failure_reasons"]


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
                "score": 0.95,
                "class_id": 1,
                "class_name": "strip",
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
            "image_handle": "image-linearity-test",
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
