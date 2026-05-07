"""YOLOX deployment health service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._service_node_support import run_deployment_process_health_action


def _yolox_deployment_health_handler(request) -> dict[str, object]:
    """读取指定 runtime_mode 的 deployment 健康状态。"""

    return run_deployment_process_health_action(request, action="health")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.yolox-deployment.health",
        display_name="Get YOLOX Deployment Health",
        category="service.model.deployment.control",
        description="读取指定 sync 或 async 通道上的 deployment 健康状态。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
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
                "deployment_instance_id": {"type": "string"},
                "runtime_mode": {"type": "string", "enum": ["sync", "async"]},
            },
            "required": ["deployment_instance_id", "runtime_mode"],
        },
        capability_tags=("service.model.deployment", "runtime.observe", "runtime.health"),
    ),
    handler=_yolox_deployment_health_handler,
)