"""region 完整性原子指标节点轻量回归测试。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.nodes.core_nodes.region_component_count import _region_component_count_handler
from backend.nodes.core_nodes.region_hole_count import _region_hole_count_handler
from backend.nodes.core_nodes.region_largest_component_ratio import _region_largest_component_ratio_handler
from backend.nodes.runtime_support import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_region_integrity_nodes_report_component_ratio_and_hole_metrics() -> None:
    """验证连通域、最大主体占比和空洞指标输出。"""

    image_registry = ExecutionImageRegistry()
    regions_payload = _build_regions_payload(image_registry)
    execution_metadata = {"execution_image_registry": image_registry}

    component_output = _region_component_count_handler(
        WorkflowNodeExecutionRequest(
            node_id="region-component-count",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload},
            execution_metadata=dict(execution_metadata),
        )
    )
    component_value = component_output["value"]["value"]
    assert component_value["count"] == 2
    assert component_value["items"][0]["component_count"] == 2
    assert component_value["items"][0]["component_areas"] == [9, 4]
    assert component_value["items"][1]["component_count"] == 1
    assert component_value["total_component_count"] == 3
    assert component_value["fragmented_region_count"] == 1

    ratio_output = _region_largest_component_ratio_handler(
        WorkflowNodeExecutionRequest(
            node_id="region-largest-component-ratio",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload},
            execution_metadata=dict(execution_metadata),
        )
    )
    ratio_value = ratio_output["value"]["value"]
    assert ratio_value["count"] == 2
    assert ratio_value["items"][0]["largest_component_ratio"] == 9 / 13
    assert ratio_value["items"][1]["largest_component_ratio"] == 1.0
    assert ratio_value["min_ratio"] == 9 / 13
    assert ratio_value["max_ratio"] == 1.0

    hole_output = _region_hole_count_handler(
        WorkflowNodeExecutionRequest(
            node_id="region-hole-count",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload},
            execution_metadata=dict(execution_metadata),
        )
    )
    hole_value = hole_output["value"]["value"]
    assert hole_value["count"] == 2
    assert hole_value["items"][0]["hole_count"] == 0
    assert hole_value["items"][1]["hole_count"] == 1
    assert hole_value["total_hole_count"] == 1
    assert hole_value["regions_with_holes"] == 1


def _build_regions_payload(image_registry: ExecutionImageRegistry) -> dict[str, object]:
    """构造带 mask_image 的测试用 regions.v1 payload。"""

    component_mask = np.zeros((12, 12), dtype=np.uint8)
    component_mask[1:4, 1:4] = 1
    component_mask[7:9, 7:9] = 1

    hole_mask = np.zeros((12, 12), dtype=np.uint8)
    hole_mask[2:10, 2:10] = 1
    hole_mask[4:8, 4:8] = 0

    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "source-image",
            "media_type": "image/png",
            "width": 12,
            "height": 12,
        },
        "count": 2,
        "items": [
            {
                "region_id": "region-components",
                "score": 0.91,
                "class_id": 1,
                "class_name": "sealant",
                "bbox_xyxy": [1.0, 1.0, 9.0, 9.0],
                "polygon_xy": [],
                "area": int(np.count_nonzero(component_mask)),
                "mask_image": _build_mask_image_payload(image_registry, component_mask),
                "prompt_id": "prompt-a",
                "state": "tracked",
            },
            {
                "region_id": "region-hole",
                "score": 0.87,
                "class_id": 2,
                "class_name": "coating",
                "bbox_xyxy": [2.0, 2.0, 10.0, 10.0],
                "polygon_xy": [],
                "area": int(np.count_nonzero(hole_mask)),
                "mask_image": _build_mask_image_payload(image_registry, hole_mask),
                "prompt_id": "prompt-b",
                "state": "tracked",
            },
        ],
    }


def _build_mask_image_payload(image_registry: ExecutionImageRegistry, mask_matrix: np.ndarray) -> dict[str, object]:
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
