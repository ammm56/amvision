"""image-ref 汇合节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _normalize_optional_image_ref_payload(
    payload: object,
    *,
    request: WorkflowNodeExecutionRequest,
    port_name: str,
) -> dict[str, object] | None:
    """校验可选 image-ref payload。"""

    if payload is None:
        return None
    try:
        return require_image_payload(payload)
    except InvalidRequestError as exc:
        raise InvalidRequestError(
            "image-ref-coalesce 输入缺少有效 image-ref payload",
            details={"node_id": request.node_id, "port_name": port_name},
        ) from exc


def _image_ref_coalesce_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 primary 优先、fallback 兜底的顺序返回首个可用 image-ref payload。"""

    allow_empty = bool(request.parameters.get("allow_empty"))
    primary_payload = _normalize_optional_image_ref_payload(
        request.input_values.get("primary"),
        request=request,
        port_name="primary",
    )
    if primary_payload is not None:
        return {"image": primary_payload}

    fallback_payload = _normalize_optional_image_ref_payload(
        request.input_values.get("fallback"),
        request=request,
        port_name="fallback",
    )
    if fallback_payload is not None:
        return {"image": fallback_payload}

    if allow_empty:
        return {"image": None}

    raise InvalidRequestError(
        "image-ref-coalesce 至少需要一个可用输入",
        details={"node_id": request.node_id, "required_ports": ["primary", "fallback"]},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.image-ref-coalesce",
        display_name="Image Ref Coalesce",
        category="logic.transform",
        description="按 primary 优先、fallback 兜底的顺序选出首个可用 image-ref payload。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="primary",
                display_name="Primary",
                payload_type_id="image-ref.v1",
                required=False,
            ),
            NodePortDefinition(
                name="fallback",
                display_name="Fallback",
                payload_type_id="image-ref.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "allow_empty": {
                    "type": "boolean",
                    "default": False,
                    "title": "Allow Empty",
                    "description": "允许两个输入都为空时输出空 image，用于上游可选输入继续交给后续 fallback 处理。",
                }
            },
        },
        capability_tags=("logic.transform", "coalesce", "image.ref"),
    ),
    handler=_image_ref_coalesce_handler,
)
