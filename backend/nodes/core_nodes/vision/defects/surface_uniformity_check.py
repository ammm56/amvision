"""表面均匀性检查节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes.support.reference_diff import (
    compute_reference_diff_metrics,
    read_optional_non_negative_int,
    read_optional_ratio,
    require_regions_with_optional_roi,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "surface-uniformity-check"


def _surface_uniformity_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据差异覆盖率和聚集面积判断表面是否均匀。"""

    regions_payload, roi_payload = require_regions_with_optional_roi(request)
    metrics_payload = compute_reference_diff_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    max_total_diff_area_ratio = _read_max_total_diff_area_ratio(
        request.parameters.get("max_total_diff_area_ratio")
    )
    max_largest_diff_area_ratio = read_optional_ratio(
        request.parameters.get("max_largest_diff_area_ratio"),
        field_name="max_largest_diff_area_ratio",
        node_name=NODE_NAME,
    )
    max_avg_diff_area_ratio = read_optional_ratio(
        request.parameters.get("max_avg_diff_area_ratio"),
        field_name="max_avg_diff_area_ratio",
        node_name=NODE_NAME,
    )
    max_region_count = read_optional_non_negative_int(
        request.parameters.get("max_region_count"),
        field_name="max_region_count",
        node_name=NODE_NAME,
    )
    failure_reasons: list[str] = []
    if metrics_payload["total_diff_area_ratio"] > max_total_diff_area_ratio:
        failure_reasons.append("surface-coverage-too-large")
    if (
        max_largest_diff_area_ratio is not None
        and metrics_payload["largest_diff_area_ratio"] > max_largest_diff_area_ratio
    ):
        failure_reasons.append("largest-defect-cluster-too-large")
    if max_avg_diff_area_ratio is not None and metrics_payload["avg_diff_area_ratio"] > max_avg_diff_area_ratio:
        failure_reasons.append("average-defect-cluster-too-large")
    if max_region_count is not None and metrics_payload["active_region_count"] > max_region_count:
        failure_reasons.append("too-many-defect-clusters")
    is_ok = len(failure_reasons) == 0
    return {
        "result": build_boolean_payload(is_ok),
        "metrics": build_value_payload(
            {
                **metrics_payload,
                "max_total_diff_area_ratio": max_total_diff_area_ratio,
                "max_largest_diff_area_ratio": max_largest_diff_area_ratio,
                "max_avg_diff_area_ratio": max_avg_diff_area_ratio,
                "max_region_count": max_region_count,
                "failure_reasons": failure_reasons,
                "result": is_ok,
            }
        ),
    }


def _read_max_total_diff_area_ratio(raw_value: object) -> float:
    """读取最大允许表面异常覆盖率。"""

    normalized_value = read_optional_ratio(
        raw_value,
        field_name="max_total_diff_area_ratio",
        node_name=NODE_NAME,
    )
    if normalized_value is None:
        return 0.0
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.surface-uniformity-check",
        display_name="Surface Uniformity Check",
        category="vision.defect",
        description="根据表面异常区域的总覆盖率、最大异常块占比和聚集数量判断表面是否均匀，适合脏污、油污和涂层不均场景。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
            ),
            NodePortDefinition(
                name="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "max_total_diff_area_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0.0,
                    "title": "最大总异常占比",
                },
                "max_largest_diff_area_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最大单块异常占比",
                },
                "max_avg_diff_area_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最大平均异常占比",
                },
                "max_region_count": {
                    "type": "integer",
                    "minimum": 0,
                    "title": "最大异常块数量",
                },
            },
        },
        capability_tags=("vision.defect", "inspection.surface", "inspection.surface.uniformity"),
    ),
    handler=_surface_uniformity_check_handler,
)
