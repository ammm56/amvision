"""结构化 payload 转 value 节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_boolean_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _payload_to_value_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把单个结构化输入包装成 value.v1。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包装后的 value payload。
    """

    candidate_values: list[tuple[str, object]] = []

    value_payload = request.input_values.get("value")
    if value_payload is not None:
        candidate_values.append(("value", require_value_payload(value_payload, field_name="value")["value"]))

    boolean_payload = request.input_values.get("boolean")
    if boolean_payload is not None:
        candidate_values.append(("boolean", require_boolean_payload(boolean_payload, field_name="boolean")["value"]))

    for port_name in (
        "result",
        "body",
        "detections",
        "segments",
        "categories",
        "poses",
        "obbs",
        "video",
        "frames",
        "tracks",
        "regions",
    ):
        raw_payload = request.input_values.get(port_name)
        if raw_payload is None:
            continue
        if not isinstance(raw_payload, dict):
            raise InvalidRequestError(
                "payload-to-value 节点要求结构化输入必须是对象",
                details={"node_id": request.node_id, "port_name": port_name},
            )
        candidate_values.append((port_name, dict(raw_payload)))

    if not candidate_values:
        raise InvalidRequestError(
            "payload-to-value 节点至少需要连接一个 value、boolean、result、body、detections、segments、categories、poses、obbs、video、frames、tracks 或 regions 输入",
            details={"node_id": request.node_id},
        )
    if len(candidate_values) > 1:
        raise InvalidRequestError(
            "payload-to-value 节点一次只能连接一个输入端口",
            details={"node_id": request.node_id, "connected_ports": [name for name, _ in candidate_values]},
        )

    return {"value": build_value_payload(candidate_values[0][1])}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.payload-to-value",
        display_name="Payload To Value",
        category="logic.transform",
        description="把 value、boolean、result-record、response-body、detections、segments、categories、poses、obbs、video、frame-window、tracks 或 regions 这类结构化结果包装成 value.v1，供 object-create、value-field-extract、response-envelope 和 value-preview 继续组合或预览。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="boolean",
                display_name="Boolean",
                payload_type_id="boolean.v1",
                required=False,
            ),
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="result-record.v1",
                required=False,
            ),
            NodePortDefinition(
                name="body",
                display_name="Body",
                payload_type_id="response-body.v1",
                required=False,
            ),
            NodePortDefinition(
                name="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
                required=False,
            ),
            NodePortDefinition(
                name="segments",
                display_name="Segments",
                payload_type_id="segments.v1",
                required=False,
            ),
            NodePortDefinition(
                name="categories",
                display_name="Categories",
                payload_type_id="categories.v1",
                required=False,
            ),
            NodePortDefinition(
                name="poses",
                display_name="Poses",
                payload_type_id="poses.v1",
                required=False,
            ),
            NodePortDefinition(
                name="obbs",
                display_name="OBBs",
                payload_type_id="obbs.v1",
                required=False,
            ),
            NodePortDefinition(
                name="video",
                display_name="Video",
                payload_type_id="video-ref.v1",
                required=False,
            ),
            NodePortDefinition(
                name="frames",
                display_name="Frames",
                payload_type_id="frame-window.v1",
                required=False,
            ),
            NodePortDefinition(
                name="tracks",
                display_name="Tracks",
                payload_type_id="tracks.v1",
                required=False,
            ),
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {},
        },
        capability_tags=("logic.transform", "payload.value.bridge"),
    ),
    handler=_payload_to_value_handler,
)
