"""异物 / 多余物检查节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes._reference_diff_node_support import (
    compute_reference_diff_metrics,
    read_optional_non_negative_int,
    read_optional_ratio,
    require_regions_with_optional_roi,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "foreign-object-check"


def _foreign_object_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据差异数量和面积阈值判断是否存在异物或多余物。"""

    regions_payload, roi_payload = require_regions_with_optional_roi(request)
    metrics_payload = compute_reference_diff_metrics(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    max_region_count = _read_max_region_count(request.parameters.get("max_region_count"))
    max_total_diff_area = read_optional_non_negative_int(
        request.parameters.get("max_total_diff_area"),
        field_name="max_total_diff_area",
        node_name=NODE_NAME,
    )
    max_total_diff_area_ratio = read_optional_ratio(
        request.parameters.get("max_total_diff_area_ratio"),
        field_name="max_total_diff_area_ratio",
        node_name=NODE_NAME,
    )
    max_largest_diff_area = read_optional_non_negative_int(
        request.parameters.get("max_largest_diff_area"),
        field_name="max_largest_diff_area",
        node_name=NODE_NAME,
    )
    max_largest_diff_area_ratio = read_optional_ratio(
        request.parameters.get("max_largest_diff_area_ratio"),
        field_name="max_largest_diff_area_ratio",
        node_name=NODE_NAME,
    )
    failure_reasons: list[str] = []
    if metrics_payload["active_region_count"] > max_region_count:
        failure_reasons.append("too-many-foreign-objects")
    if max_total_diff_area is not None and metrics_payload["total_diff_area"] > max_total_diff_area:
        failure_reasons.append("total-diff-area-too-large")
    if (
        max_total_diff_area_ratio is not None
        and metrics_payload["total_diff_area_ratio"] > max_total_diff_area_ratio
    ):
        failure_reasons.append("total-diff-area-ratio-too-large")
    if max_largest_diff_area is not None and metrics_payload["largest_diff_area"] > max_largest_diff_area:
        failure_reasons.append("largest-foreign-object-too-large")
    if (
        max_largest_diff_area_ratio is not None
        and metrics_payload["largest_diff_area_ratio"] > max_largest_diff_area_ratio
    ):
        failure_reasons.append("largest-foreign-object-ratio-too-large")
    is_ok = len(failure_reasons) == 0
    return {
        "result": build_boolean_payload(is_ok),
        "metrics": build_value_payload(
            {
                **metrics_payload,
                "max_region_count": max_region_count,
                "max_total_diff_area": max_total_diff_area,
                "max_total_diff_area_ratio": max_total_diff_area_ratio,
                "max_largest_diff_area": max_largest_diff_area,
                "max_largest_diff_area_ratio": max_largest_diff_area_ratio,
                "failure_reasons": failure_reasons,
                "result": is_ok,
            }
        ),
    }


def _read_max_region_count(raw_value: object) -> int:
    """读取最大允许异物数量。"""

    normalized_value = read_optional_non_negative_int(
        raw_value,
        field_name="max_region_count",
        node_name=NODE_NAME,
    )
    if normalized_value is None:
        return 0
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.foreign-object-check",
        display_name="Foreign Object Check",
        category="vision.defect",
        description="根据差异区域数量和面积阈值判断是否存在异物、多余物或表面残留，适合参考图比对后的现场 OK/NG 判定。",
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
                "max_region_count": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "title": "最大异物数量",
                },
                "max_total_diff_area": {
                    "type": "integer",
                    "minimum": 0,
                    "title": "最大总差异面积",
                },
                "max_total_diff_area_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最大总差异占比",
                },
                "max_largest_diff_area": {
                    "type": "integer",
                    "minimum": 0,
                    "title": "最大单块异物面积",
                },
                "max_largest_diff_area_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "title": "最大单块异物占比",
                },
            },
        },
        capability_tags=("vision.defect", "inspection.foreign-object", "inspection.foreign-object.check"),
    ),
    handler=_foreign_object_check_handler,
)
