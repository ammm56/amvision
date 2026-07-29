"""点 Prompt 构造节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.prompt import build_prompt_regions_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_point_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """构造一条正点或负点 Prompt。"""

    return {
        "prompts": build_prompt_regions_payload(
            (
                {
                    "prompt_id": request.parameters.get("prompt_id"),
                    "display_name": request.parameters.get("display_name"),
                    "prompt_kind": "point",
                    "point_xy": [
                        request.parameters.get("x"),
                        request.parameters.get("y"),
                    ],
                    "point_label": request.parameters.get("point_label", "positive"),
                },
            )
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.point-prompt",
        display_name="Point Prompt",
        category="core.input.prompt",
        description="构造一条正点或负点视觉提示。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
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
                "x": {"type": "number", "title": "X"},
                "y": {"type": "number", "title": "Y"},
                "point_label": {
                    "type": "string",
                    "title": "Point Label",
                    "enum": ["positive", "negative"],
                    "default": "positive",
                },
            },
            "required": ["prompt_id", "x", "y"],
        },
        capability_tags=("prompt.visual", "prompt.point", "payload.create"),
    ),
    handler=_handle_point_prompt,
)
