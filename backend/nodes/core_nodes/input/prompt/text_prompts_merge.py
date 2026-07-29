"""文本 Prompt 合并节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.prompt import merge_text_prompts_payloads
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handle_text_prompts_merge(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """合并多路 text-prompts.v1 输入。"""

    return {"prompts": merge_text_prompts_payloads(request.input_values.get("prompts"))}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.input.text-prompts-merge",
        display_name="Text Prompts Merge",
        category="core.input.prompt",
        description="按连线顺序合并多路 Text Prompts。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="prompts",
                display_name="Prompts",
                payload_type_id="text-prompts.v1",
                multiple=True,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="prompts",
                display_name="Prompts",
                payload_type_id="text-prompts.v1",
            ),
        ),
        capability_tags=("prompt.text", "payload.merge"),
    ),
    handler=_handle_text_prompts_merge,
)
