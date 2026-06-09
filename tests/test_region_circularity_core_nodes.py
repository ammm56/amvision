"""region 圆度 core 节点测试。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.circularity_check import _circularity_check_handler
from backend.nodes.runtime_support import build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_circularity_check_passes_round_region() -> None:
    """验证 circularity-check 可判定圆形区域为通过。"""

    image_registry = ExecutionImageRegistry()
    round_mask = np.zeros((96, 96), dtype=np.uint8)
    cv2.circle(round_mask, (48, 48), 22, 1, thickness=-1)

    output = _circularity_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="circularity-check",
            node_definition=object(),
            parameters={
                "match_mode": "all",
                "min_circularity": 0.82,
                "min_fill_ratio": 0.75,
            },
            input_values={
                "regions": _build_regions_payload(
                    image_registry=image_registry,
                    masks=[round_mask],
                )
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is True
    assert output["metrics"]["value"]["passed_count"] == 1
    assert output["metrics"]["value"]["items"][0]["circularity"] >= 0.82


def test_circularity_check_rejects_rect_region() -> None:
    """验证 circularity-check 会拒绝明显非圆形区域。"""

    image_registry = ExecutionImageRegistry()
    rect_mask = np.zeros((96, 96), dtype=np.uint8)
    cv2.rectangle(rect_mask, (18, 34), (78, 62), 1, thickness=-1)

    output = _circularity_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="circularity-check",
            node_definition=object(),
            parameters={
                "match_mode": "all",
                "min_circularity": 0.82,
                "min_fill_ratio": 0.75,
            },
            input_values={
                "regions": _build_regions_payload(
                    image_registry=image_registry,
                    masks=[rect_mask],
                )
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is False
    assert output["metrics"]["value"]["failed_count"] == 1
    assert "low-circularity" in output["metrics"]["value"]["items"][0]["failure_reasons"]


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
                "class_name": "round-shape",
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
            "image_handle": "image-circularity-test",
            "media_type": "image/png",
            "width": 96,
            "height": 96,
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
