"""Barcode 结果摘要节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.support import build_barcode_results_summary
from custom_nodes.barcode_protocol_nodes.specs import NODE_PACK_ID, NODE_PACK_VERSION


NODE_TYPE_ID = "custom.barcode.results-summary"

NODE_DEFINITION_PAYLOAD = {
    "format_id": "amvision.node-definition.v1",
    "node_type_id": NODE_TYPE_ID,
    "display_name": "Summarize Barcode Results",
    "category": "barcode.logic",
    "description": "把 barcode-results.v1 转成更轻量的摘要对象，方便后续 workflow 条件分支直接读取。",
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
            "name": "body",
            "display_name": "Body",
            "payload_type_id": "response-body.v1",
        }
    ],
    "parameter_schema": {
        "type": "object",
        "properties": {},
    },
    "capability_tags": ["barcode.logic", "barcode.summary"],
    "runtime_requirements": {"python_packages": ["zxing-cpp", "opencv-python", "numpy"]},
    "node_pack_id": NODE_PACK_ID,
    "node_pack_version": NODE_PACK_VERSION,
    "metadata": {
        "input_kind": "barcode-results.v1",
        "output_kind": "response-body.v1",
    },
}


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """输出条码结果的轻量摘要对象。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 response-body.v1 摘要的节点输出。
    """

    return {"body": build_barcode_results_summary(request.input_values.get("results"))}