"""框 Prompt 构造节点。"""

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


def _handle_box_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """构造一条 xyxy 框 Prompt。"""

    coordinates = tuple(
        float(request.parameters.get(name, 0.0)) for name in ("x1", "y1", "x2", "y2")
    )
    if coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
        raise InvalidRequestError(
            "Box Prompt 要求 x2 > x1 且 y2 > y1",
            details={"bbox_xyxy": list(coordinates)},
        )
    return {
        "prompts": build_prompt_regions_payload(
            (
                {
                    "prompt_id": request.parameters.get("prompt_id"),
                    "display_name": request.parameters.get("display_name"),
                    "prompt_kind": "box",
                    "bbox_xyxy": list(coordinates),
                },
            )
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.box-prompt",
        display_name="Box Prompt",
        category="core.input.prompt",
        description="构造一条 xyxy 矩形视觉提示。",
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
                "x1": {"type": "number", "title": "X1"},
                "y1": {"type": "number", "title": "Y1"},
                "x2": {"type": "number", "title": "X2"},
                "y2": {"type": "number", "title": "Y2"},
            },
            "required": ["prompt_id", "x1", "y1", "x2", "y2"],
        },
        capability_tags=("prompt.visual", "prompt.box", "payload.create"),
    ),
    handler=_handle_box_prompt,
)
