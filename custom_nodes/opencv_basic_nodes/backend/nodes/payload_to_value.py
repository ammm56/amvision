"""OpenCV 结构化 payload 转 value 节点。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload
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

    candidate_values: list[tuple[str, dict[str, object]]] = []
    for port_name in ("contours", "measurements", "rotated_rects"):
        raw_payload = request.input_values.get(port_name)
        if raw_payload is None:
            continue
        if not isinstance(raw_payload, dict):
            raise InvalidRequestError(
                "opencv payload-to-value 节点要求输入 payload 必须是对象",
                details={"node_id": request.node_id, "port_name": port_name},
            )
        candidate_values.append((port_name, dict(raw_payload)))

    if not candidate_values:
        raise InvalidRequestError(
            "opencv payload-to-value 节点至少需要连接 contours、measurements 或 rotated_rects 输入",
            details={"node_id": request.node_id},
        )
    if len(candidate_values) > 1:
        raise InvalidRequestError(
            "opencv payload-to-value 节点一次只能连接一个输入端口",
            details={"node_id": request.node_id, "connected_ports": [name for name, _ in candidate_values]},
        )
    return {"value": build_value_payload(candidate_values[0][1])}
