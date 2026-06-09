"""参考图差异 / 表面异常 core 节点回归测试。"""

from __future__ import annotations

import cv2
import numpy as np

from backend.nodes.core_nodes.foreign_object_check import _foreign_object_check_handler
from backend.nodes.core_nodes.reference_diff_metrics import _reference_diff_metrics_handler
from backend.nodes.core_nodes.surface_uniformity_check import _surface_uniformity_check_handler
from backend.nodes.runtime_support import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def test_reference_diff_metrics_uses_roi_scope() -> None:
    """验证 reference-diff-metrics 会按 ROI 内有效差异面积统计。"""

    image_registry = ExecutionImageRegistry()
    regions_payload = _build_diff_regions_payload(image_registry)

    output = _reference_diff_metrics_handler(
        WorkflowNodeExecutionRequest(
            node_id="reference-diff-metrics",
            node_definition=object(),
            parameters={},
            input_values={
                "regions": regions_payload,
                "roi": _build_roi_payload(),
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    metrics_value = output["value"]["value"]
    assert metrics_value["scope_kind"] == "roi"
    assert metrics_value["scope_area"] == 36
    assert metrics_value["input_region_count"] == 2
    assert metrics_value["active_region_count"] == 1
    assert metrics_value["ignored_region_count"] == 1
    assert metrics_value["total_diff_area"] == 9
    assert metrics_value["total_diff_area_ratio"] == 0.25
    assert metrics_value["largest_diff_area"] == 9
    assert metrics_value["class_distribution"] == {"foreign-object": 1}


def test_foreign_object_check_defaults_to_strict_presence_gate() -> None:
    """验证 foreign-object-check 默认只要 ROI 内有异物就判失败。"""

    image_registry = ExecutionImageRegistry()
    regions_payload = _build_diff_regions_payload(image_registry)

    output = _foreign_object_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="foreign-object-check",
            node_definition=object(),
            parameters={},
            input_values={
                "regions": regions_payload,
                "roi": _build_roi_payload(),
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is False
    assert output["metrics"]["value"]["failure_reasons"] == ["too-many-foreign-objects"]


def test_surface_uniformity_check_supports_ratio_thresholds() -> None:
    """验证 surface-uniformity-check 可按比例阈值放宽表面异常判定。"""

    image_registry = ExecutionImageRegistry()
    regions_payload = _build_diff_regions_payload(image_registry)

    output = _surface_uniformity_check_handler(
        WorkflowNodeExecutionRequest(
            node_id="surface-uniformity-check",
            node_definition=object(),
            parameters={
                "max_total_diff_area_ratio": 0.3,
                "max_largest_diff_area_ratio": 0.3,
                "max_region_count": 1,
            },
            input_values={
                "regions": regions_payload,
                "roi": _build_roi_payload(),
            },
            execution_metadata={"execution_image_registry": image_registry},
        )
    )

    assert output["result"]["value"] is True
    assert output["metrics"]["value"]["failure_reasons"] == []
    assert output["metrics"]["value"]["avg_diff_area_ratio"] == 0.25


def _build_diff_regions_payload(image_registry: ExecutionImageRegistry) -> dict[str, object]:
    """构造带两块差异区域的 regions.v1。"""

    inside_mask = np.zeros((10, 12), dtype=np.uint8)
    inside_mask[1:4, 1:4] = 1

    outside_mask = np.zeros((10, 12), dtype=np.uint8)
    outside_mask[7:9, 8:10] = 1

    return {
        "source_image": {
            "transport_kind": "memory",
            "image_handle": "image-reference-diff",
            "media_type": "image/png",
            "width": 12,
            "height": 10,
        },
        "count": 2,
        "items": [
            {
                "region_id": "diff-1",
                "score": 0.96,
                "class_id": 1,
                "class_name": "foreign-object",
                "bbox_xyxy": [1.0, 1.0, 4.0, 4.0],
                "polygon_xy": [[1.0, 1.0], [4.0, 1.0], [4.0, 4.0], [1.0, 4.0]],
                "area": 9,
                "mask_image": _build_mask_image_payload(image_registry, inside_mask),
            },
            {
                "region_id": "diff-2",
                "score": 0.73,
                "class_id": 1,
                "class_name": "foreign-object",
                "bbox_xyxy": [8.0, 7.0, 10.0, 9.0],
                "polygon_xy": [[8.0, 7.0], [10.0, 7.0], [10.0, 9.0], [8.0, 9.0]],
                "area": 4,
                "mask_image": _build_mask_image_payload(image_registry, outside_mask),
            },
        ],
    }


def _build_roi_payload() -> dict[str, object]:
    """构造测试用 ROI。"""

    return {
        "roi_id": "roi-check",
        "roi_kind": "bbox",
        "bbox_xyxy": [0.0, 0.0, 6.0, 6.0],
        "polygon_xy": [[0.0, 0.0], [6.0, 0.0], [6.0, 6.0], [0.0, 6.0]],
        "area": 36,
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
