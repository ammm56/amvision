"""image-base64 汇合节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _normalize_optional_image_base64_payload(
    payload: object,
    *,
    request: WorkflowNodeExecutionRequest,
    port_name: str,
) -> dict[str, object] | None:
    """校验可选 image-base64 payload。

    参数：
    - payload：待校验的 payload。
    - request：当前节点执行请求。
    - port_name：当前输入端口名称。

    返回：
    - dict[str, object] | None：输入为空时返回 None，否则返回规范化后的 payload。
    """

    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise InvalidRequestError(
            "image-base64-coalesce 输入必须是对象或 null",
            details={"node_id": request.node_id, "port_name": port_name},
        )
    image_base64 = payload.get("image_base64")
    if not isinstance(image_base64, str) or not image_base64.strip():
        raise InvalidRequestError(
            "image-base64-coalesce 输入缺少 image_base64 字段",
            details={"node_id": request.node_id, "port_name": port_name},
        )
    return dict(payload)


def _image_base64_coalesce_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 primary 优先、fallback 兜底的顺序返回首个可用 image-base64 payload。

    参数：
    - request：当前节点执行请求。

    返回：
    - dict[str, object]：选中的 image-base64 payload。
    """

    primary_payload = _normalize_optional_image_base64_payload(
        request.input_values.get("primary"),
        request=request,
        port_name="primary",
    )
    if primary_payload is not None:
        return {"payload": primary_payload}

    fallback_payload = _normalize_optional_image_base64_payload(
        request.input_values.get("fallback"),
        request=request,
        port_name="fallback",
    )
    if fallback_payload is not None:
        return {"payload": fallback_payload}

    raise InvalidRequestError(
        "image-base64-coalesce 至少需要一个可用输入",
        details={"node_id": request.node_id, "required_ports": ["primary", "fallback"]},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.image-base64-coalesce",
        display_name="Image Base64 Coalesce",
        category="logic.transform",
        description="按 primary 优先、fallback 兜底的顺序选出首个可用 image-base64 payload。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="primary",
                display_name="Primary",
                payload_type_id="image-base64.v1",
                required=False,
            ),
            NodePortDefinition(
                name="fallback",
                display_name="Fallback",
                payload_type_id="image-base64.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="payload",
                display_name="Payload",
                payload_type_id="image-base64.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("logic.transform", "coalesce", "image.base64"),
    ),
    handler=_image_base64_coalesce_handler,
)