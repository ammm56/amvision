"""deployment reset service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.service import run_deployment_process_health_action


def _model_deployment_reset_handler(request) -> dict[str, object]:
    """重置指定 runtime_mode 的 deployment 实例池状态。"""

    return run_deployment_process_health_action(request, action="reset")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.model-deployment.reset",
        display_name="Reset Deployment",
        category="service.model.deployment.control",
        description="按 task_type 重置指定 sync 或 async 通道上的 deployment 实例池状态。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="request",
                display_name="Request",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="body",
                display_name="Body",
                payload_type_id="response-body.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "task_type": {"type": "string", "enum": ["detection", "classification", "segmentation", "pose", "obb"]},
                "deployment_instance_id": {"type": "string"},
                "runtime_mode": {"type": "string", "enum": ["sync", "async"]},
            },
            "required": ["task_type", "deployment_instance_id", "runtime_mode"],
        },
        capability_tags=("service.model.deployment", "runtime.control", "runtime.reset"),
    ),
    handler=_model_deployment_reset_handler,
)

