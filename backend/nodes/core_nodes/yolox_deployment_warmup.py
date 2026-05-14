"""YOLOX deployment warmup service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._service_node_support import run_deployment_process_health_action


def _yolox_deployment_warmup_handler(request) -> dict[str, object]:
    """预热指定 runtime_mode 的 deployment 进程。"""

    return run_deployment_process_health_action(request, action="warmup")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.yolox-deployment.warmup",
        display_name="Warmup YOLOX Deployment",
        category="service.model.deployment.control",
        description="预热指定 sync 或 async 通道上的 deployment 进程。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="request",
                display_name="Request",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="dependency",
                display_name="Dependency",
                payload_type_id="response-body.v1",
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
                "deployment_instance_id": {"type": "string"},
                "runtime_mode": {"type": "string", "enum": ["sync", "async"]},
            },
            "required": ["deployment_instance_id", "runtime_mode"],
        },
        capability_tags=("service.model.deployment", "runtime.control", "runtime.warmup"),
    ),
    handler=_yolox_deployment_warmup_handler,
)