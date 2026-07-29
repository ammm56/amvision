"""单条文本 Prompt 构造节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.prompt import build_text_prompts_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_text_prompt(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """用节点参数构造一条 text-prompts.v1 记录。"""

    return {
        "prompts": build_text_prompts_payload(
            (
                {
                    "prompt_id": request.parameters.get("prompt_id"),
                    "text": request.parameters.get("text"),
                    "display_name": request.parameters.get("display_name"),
                    "language": request.parameters.get("language"),
                    "negative": request.parameters.get("negative", False),
                },
            )
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.text-prompt",
        display_name="Text Prompt",
        category="core.input.prompt",
        description="构造一条带稳定 prompt_id、正负标记和可选语言的文本提示。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        output_ports=(
            NodePortDefinition(
                name="prompts",
                display_name="Prompts",
                payload_type_id="text-prompts.v1",
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
                "text": {"type": "string", "title": "Text"},
                "display_name": {"type": "string", "title": "Display Name"},
                "language": {"type": "string", "title": "Language"},
                "negative": {"type": "boolean", "title": "Negative", "default": False},
            },
            "required": ["prompt_id", "text"],
        },
        capability_tags=("prompt.text", "payload.create"),
    ),
    handler=_handle_text_prompt,
)
