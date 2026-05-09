"""Barcode 结果过滤节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.support import filter_barcode_results_payload
from custom_nodes.barcode_protocol_nodes.specs import NODE_PACK_ID, NODE_PACK_VERSION


NODE_TYPE_ID = "custom.barcode.filter-results"

NODE_DEFINITION_PAYLOAD = {
    "format_id": "amvision.node-definition.v1",
    "node_type_id": NODE_TYPE_ID,
    "display_name": "Filter Barcode Results",
    "category": "barcode.logic",
    "description": "按 format、text、index 和区域范围筛选 barcode-results.v1，输出过滤后的结果集。",
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
            "name": "results",
            "display_name": "Results",
            "payload_type_id": "barcode-results.v1",
        }
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
    "capability_tags": ["barcode.logic", "barcode.filter"],
    "runtime_requirements": {"python_packages": ["zxing-cpp", "opencv-python", "numpy"]},
    "node_pack_id": NODE_PACK_ID,
    "node_pack_version": NODE_PACK_VERSION,
    "metadata": {
        "input_kind": "barcode-results.v1",
        "output_kind": "barcode-results.v1",
    },
}


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按指定条件过滤条码结果。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含过滤后 barcode-results.v1 的节点输出。
    """

    return {
        "results": filter_barcode_results_payload(
            request.input_values.get("results"),
            parameters=request.parameters,
        )
    }