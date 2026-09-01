"""结构化 payload 转 value 节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.payload_adapters import PAYLOAD_ADAPTER_REGISTRY
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _payload_to_value_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把单个结构化输入包装成 value.v1。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包装后的 value payload。
    """

    contract_by_port = {
        "value": "value.v1",
        "boolean": "boolean.v1",
        "field": "object-field.v1",
        "item": "list-item.v1",
        "roi": "roi.v1",
        "rois": "roi-list.v1",
        "image": "image-ref.v1",
        "images": "image-refs.v1",
        "result": "result-record.v1",
        "body": "response-body.v1",
        "prompts": "prompt-regions.v1",
        "detections": "detections.v1",
        "segments": "segments.v1",
        "categories": "categories.v1",
        "poses": "poses.v1",
        "obbs": "obbs.v1",
        "circles": "circles.v1",
        "video": "video-ref.v1",
        "frames": "frame-window.v1",
        "tracks": "tracks.v1",
        "regions": "regions.v1",
    }
    candidate_values: list[tuple[str, str, object]] = []
    for port_name, source_contract in contract_by_port.items():
        raw_payload = request.input_values.get(port_name)
        if raw_payload is None:
            continue
        candidate_values.append((port_name, source_contract, raw_payload))

    if not candidate_values:
        raise InvalidRequestError(
            "payload-to-value 节点至少需要连接一个 value、boolean、field、item、roi、rois、image、images、result、body、prompts、detections、segments、categories、poses、obbs、circles、video、frames、tracks 或 regions 输入",
            details={"node_id": request.node_id},
        )
    if len(candidate_values) > 1:
        raise InvalidRequestError(
            "payload-to-value 节点一次只能连接一个输入端口",
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


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.payload-to-value",
        display_name="Payload To Value",
        category="core.logic.transform",
        description="把 value、boolean、字段项、列表项、ROI、图片引用和各类视觉结果显式包装成 value.v1，供 Parallel、For Each、对象组合和结果预览继续使用。",
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
                name="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
                required=False,
            ),
            NodePortDefinition(
                name="rois",
                display_name="ROIs",
                payload_type_id="roi-list.v1",
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
                name="field",
                display_name="Object Field",
                payload_type_id="object-field.v1",
                required=False,
            ),
            NodePortDefinition(
                name="item",
                display_name="List Item",
                payload_type_id="list-item.v1",
                required=False,
            ),
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                required=False,
            ),
            NodePortDefinition(
                name="images",
                display_name="Images",
                payload_type_id="image-refs.v1",
                required=False,
            ),
            NodePortDefinition(
                name="prompts",
                display_name="Prompts",
                payload_type_id="prompt-regions.v1",
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
                name="circles",
                display_name="Circles",
                payload_type_id="circles.v1",
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
