"""Mask Prompt 构造节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.prompt import build_prompt_regions_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_mask_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """用 image-ref.v1 构造 Mask Prompt。"""

    mask_image = request.input_values.get("mask_image")
    if not isinstance(mask_image, dict):
        raise InvalidRequestError("Mask Prompt 要求 mask_image 输入是 image-ref.v1")
    return {
        "prompts": build_prompt_regions_payload(
            (
                {
                    "prompt_id": request.parameters.get("prompt_id"),
                    "display_name": request.parameters.get("display_name"),
                    "prompt_kind": "mask",
                    "mask_image": dict(mask_image),
                },
            )
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.mask-prompt",
        display_name="Mask Prompt",
        category="core.input.prompt",
        description="用二值 Mask 图片引用构造视觉提示。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="mask_image",
                display_name="Mask Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="prompts",
                display_name="Prompts",
                payload_type_id="prompt-regions.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "prompt_id": {
                    "type": "string",
                    "title": "Prompt ID",
                    "default": "prompt-1",
                },
                "display_name": {"type": "string", "title": "Display Name"},
            },
            "required": ["prompt_id"],
        },
        capability_tags=("prompt.visual", "prompt.mask", "payload.create"),
    ),
    handler=_handle_mask_prompt,
)
