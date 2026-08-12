"""OpenCV 结构化 payload 转 value 节点。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.payload_adapters import PAYLOAD_ADAPTER_REGISTRY
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_TYPE_ID = "custom.opencv.payload-to-value"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 OpenCV 结构化 payload 包装成 value.v1。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包装后的 value payload。
    """

    contract_by_port = {
        "contours": "contours.v1",
        "measurements": "measurements.v1",
        "rotated_rects": "rotated-rects.v1",
        "lines": "lines.v1",
        "circles": "circles.v1",
        "ellipses": "ellipses.v1",
        "regions": "regions.v1",
        "features": "local-features.v1",
        "matches": "feature-matches.v1",
        "planar_transform": "planar-transform.v1",
    }
    candidate_values: list[tuple[str, str, object]] = []
    for port_name, source_contract in contract_by_port.items():
        raw_payload = request.input_values.get(port_name)
        if raw_payload is None:
            continue
        candidate_values.append((port_name, source_contract, raw_payload))

    if not candidate_values:
        raise InvalidRequestError(
            "opencv payload-to-value 节点至少需要连接一个 OpenCV 结构化 payload 输入",
            details={"node_id": request.node_id},
        )
    if len(candidate_values) > 1:
        raise InvalidRequestError(
            "opencv payload-to-value 节点一次只能连接一个输入端口",
            details={"node_id": request.node_id, "connected_ports": [name for name, _, _ in candidate_values]},
        )
    _port_name, source_contract, payload = candidate_values[0]
    converted = PAYLOAD_ADAPTER_REGISTRY.convert(
        source_contract,
        "value.v1",
        payload,
        request=request,
    )
    return {"value": build_value_payload(converted)}
