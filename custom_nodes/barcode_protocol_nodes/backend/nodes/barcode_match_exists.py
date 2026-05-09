"""Barcode 结果判断节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.support import filter_barcode_results_payload
from custom_nodes.barcode_protocol_nodes.specs import NODE_PACK_ID, NODE_PACK_VERSION


NODE_TYPE_ID = "custom.barcode.match-exists"

NODE_DEFINITION_PAYLOAD = {
    "format_id": "amvision.node-definition.v1",
    "node_type_id": NODE_TYPE_ID,
    "display_name": "Barcode Match Exists",
    "category": "barcode.logic",
    "description": "按 format、text、index 和区域范围判断 barcode-results.v1 中是否存在匹配项，并输出匹配数量。",
    "implementation_kind": "custom-node",
    "runtime_kind": "python-callable",
    "input_ports": [
        {
            "name": "results",
            "display_name": "Results",
            "payload_type_id": "barcode-results.v1",
        }
    ],
    "output_ports": [
        {
            "name": "result",
            "display_name": "Result",
            "payload_type_id": "boolean.v1",
        },
        {
            "name": "count",
            "display_name": "Count",
            "payload_type_id": "value.v1",
        },
    ],
    "parameter_schema": {
        "type": "object",
        "properties": {
            "formats": {"type": "array", "items": {"type": "string"}},
            "text_equals": {"type": "string"},
            "text_contains": {"type": "string"},
            "text_regex": {"type": "string"},
            "ignore_case": {"type": "boolean"},
            "indices": {"type": "array", "items": {"type": "integer"}},
            "min_index": {"type": "integer"},
            "max_index": {"type": "integer"},
            "region_bounds_xyxy": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 4,
            },
            "region_match_mode": {
                "type": "string",
                "enum": ["intersects", "center-in", "bounds-in"],
            },
        },
    },
    "capability_tags": ["barcode.logic", "barcode.match"],
    "runtime_requirements": {"python_packages": ["zxing-cpp", "opencv-python", "numpy"]},
    "node_pack_id": NODE_PACK_ID,
    "node_pack_version": NODE_PACK_VERSION,
    "metadata": {
        "input_kind": "barcode-results.v1",
        "output_boolean": "boolean.v1",
        "output_count": "value.v1",
    },
}


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """判断条码结果中是否存在符合条件的匹配项。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含布尔结果和匹配数量的节点输出。
    """

    filtered_results = filter_barcode_results_payload(
        request.input_values.get("results"),
        parameters=request.parameters,
    )
    matched_count = int(filtered_results.get("count", 0))
    return {
        "result": {"value": matched_count > 0},
        "count": {"value": matched_count},
    }