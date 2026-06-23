"""缺陷语义 core 节点测试。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.vision.defects.defect_cluster_count import _defect_cluster_count_handler
from backend.nodes.core_nodes.vision.defects.defect_density import _defect_density_handler
from backend.nodes.core_nodes.vision.defects.defect_largest_cluster_ratio import (
    _defect_largest_cluster_ratio_handler,
)
from backend.nodes.core_nodes.vision.defects.edge_profile_gap_check import _edge_profile_gap_check_handler
from backend.nodes.runtime_support import build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_defect_cluster_metrics_with_roi_scope() -> None:
    """验证缺陷聚类数量、最大聚类占比和密度指标都会按 ROI 生效。"""

    image_registry = ExecutionImageRegistry()
    regions_payload = _build_cluster_regions_payload(image_registry)
    roi_payload = _build_cluster_roi_payload()

    cluster_count_output = _defect_cluster_count_handler(
        WorkflowNodeExecutionRequest(
            node_id="defect-cluster-count",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload, "roi": roi_payload},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )
    largest_ratio_output = _defect_largest_cluster_ratio_handler(
        WorkflowNodeExecutionRequest(
            node_id="defect-largest-cluster-ratio",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload, "roi": roi_payload},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )
    density_output = _defect_density_handler(
        WorkflowNodeExecutionRequest(
            node_id="defect-density",
            node_definition=object(),
            parameters={},
            input_values={"regions": regions_payload, "roi": roi_payload},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    cluster_value = cluster_count_output["value"]["value"]
    largest_ratio_value = largest_ratio_output["value"]["value"]
    density_value = density_output["value"]["value"]

    assert cluster_value["scope_kind"] == "roi"
    assert cluster_value["scope_area"] == 100
    assert cluster_value["cluster_count"] == 3
    assert cluster_value["total_diff_area"] == 17
    assert cluster_value["class_distribution"] == {"defect": 3}
    assert largest_ratio_value["largest_diff_area"] == 9
    assert round(float(largest_ratio_value["largest_cluster_ratio"]), 6) == round(9.0 / 17.0, 6)
    assert largest_ratio_value["largest_cluster_region_id"] == "cluster-1"
    assert density_value["cluster_count_per_10k_pixels"] == 300.0
    assert density_value["total_diff_area_ratio"] == 0.17
    assert density_value["sum_effective_area_ratio"] == 0.17


def test_edge_profile_gap_check_passes_continuous_horizontal_profile() -> None:
    """验证 edge-profile-gap-check 会放行连续横向边缘 profile。"""

    image_registry = ExecutionImageRegistry()
    continuous_mask = np.zeros((64, 96), dtype=np.uint8)
    cv2.line(continuous_mask, (12, 30), (84, 30), 1, thickness=4)

    output = _edge_profile_gap_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="edge-profile-gap-check",
            node_definition=object(),
            parameters={
                "edge_orientation": "horizontal",
                "min_gap_pixels_to_count": 2,
                "max_gap_pixels": 0,
                "max_gap_count": 0,
                "min_axis_occupancy_ratio": 0.95,
            },
            input_values={"regions": _build_profile_regions_payload(image_registry, continuous_mask)},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is True
    assert output["metrics"]["value"]["gap_count"] == 0
    assert output["metrics"]["value"]["longest_gap_pixels"] == 0.0
    assert output["metrics"]["value"]["axis_occupancy_ratio"] >= 0.95


def test_edge_profile_gap_check_rejects_broken_horizontal_profile() -> None:
    """验证 edge-profile-gap-check 会拒绝存在明显横向缺口的边缘 profile。"""

    image_registry = ExecutionImageRegistry()
    broken_mask = np.zeros((64, 96), dtype=np.uint8)
    cv2.line(broken_mask, (12, 30), (84, 30), 1, thickness=4)
    cv2.rectangle(broken_mask, (44, 24), (54, 36), 0, thickness=-1)

    output = _edge_profile_gap_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="edge-profile-gap-check",
            node_definition=object(),
            parameters={
                "edge_orientation": "horizontal",
                "min_gap_pixels_to_count": 2,
                "max_gap_pixels": 0,
                "max_gap_count": 0,
                "min_axis_occupancy_ratio": 0.95,
            },
            input_values={"regions": _build_profile_regions_payload(image_registry, broken_mask)},
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is False
    assert output["metrics"]["value"]["gap_count"] >= 1
    assert output["metrics"]["value"]["longest_gap_pixels"] > 0.0
    assert "too-many-profile-gaps" in output["metrics"]["value"]["failure_reasons"] or "profile-gap-too-large" in output["metrics"]["value"]["failure_reasons"]


def _build_cluster_regions_payload(image_registry: ExecutionImageRegistry) -> dict[str, object]:
    """构造三块缺陷聚类的 regions.v1。"""

    mask_1 = np.zeros((12, 12), dtype=np.uint8)
    mask_1[1:4, 1:4] = 1
    mask_2 = np.zeros((12, 12), dtype=np.uint8)
    mask_2[5:7, 5:7] = 1
    mask_3 = np.zeros((12, 12), dtype=np.uint8)
    mask_3[7:9, 1:3] = 1
    masks = [mask_1, mask_2, mask_3]

    items: list[dict[str, object]] = []
    for item_index, mask_matrix in enumerate(masks, start=1):
        y_indices, x_indices = np.nonzero(mask_matrix > 0)
        x1_value = float(np.min(x_indices))
        y1_value = float(np.min(y_indices))
        x2_value = float(np.max(x_indices) + 1)
        y2_value = float(np.max(y_indices) + 1)
        items.append(
            {
                "region_id": f"cluster-{item_index}",
                "score": 0.9 - (item_index * 0.05),
                "class_id": 1,
                "class_name": "defect",
                "bbox_xyxy": [x1_value, y1_value, x2_value, y2_value],
                "polygon_xy": [[x1_value, y1_value], [x2_value, y1_value], [x2_value, y2_value], [x1_value, y2_value]],
                "area": int(np.count_nonzero(mask_matrix)),
                "mask_image": _build_mask_image_payload(image_registry, mask_matrix),
            }
        )
    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "image-defect-cluster",
            "media_type": "image/png",
            "width": 12,
            "height": 12,
        },
        "count": len(items),
        "items": items,
    }


def _build_cluster_roi_payload() -> dict[str, object]:
    """构造 10x10 ROI。"""

    return {
        "roi_id": "roi-defect-cluster",
        "roi_kind": "bbox",
        "bbox_xyxy": [0.0, 0.0, 10.0, 10.0],
        "polygon_xy": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        "area": 100,
    }


def _build_profile_regions_payload(
    image_registry: ExecutionImageRegistry,
    mask_matrix: np.ndarray,
) -> dict[str, object]:
    """构造带单条边缘前景的 regions.v1。"""

    y_indices, x_indices = np.nonzero(mask_matrix > 0)
    x1_value = float(np.min(x_indices))
    y1_value = float(np.min(y_indices))
    x2_value = float(np.max(x_indices) + 1)
    y2_value = float(np.max(y_indices) + 1)
    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "image-edge-profile",
            "media_type": "image/png",
            "width": int(mask_matrix.shape[1]),
            "height": int(mask_matrix.shape[0]),
        },
        "count": 1,
        "items": [
            {
                "region_id": "edge-profile-1",
                "score": 0.97,
                "class_id": 1,
                "class_name": "edge-strip",
                "bbox_xyxy": [x1_value, y1_value, x2_value, y2_value],
                "polygon_xy": [[x1_value, y1_value], [x2_value, y1_value], [x2_value, y2_value], [x1_value, y2_value]],
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
