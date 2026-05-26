"""模板输入图片节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _template_input_image_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把模板注入的图片引用直接透传为节点输出。"""

    return {"image": require_image_payload(request.input_values.get("payload"))}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.template-input.image",
        display_name="Template Image Input",
        category="io.input",
        description="把流程应用绑定进来的图片引用透传给后续节点。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="payload",
                display_name="Payload",
                payload_type_id="image-ref.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("io.input",),
    ),
    handler=_template_input_image_handler,
)