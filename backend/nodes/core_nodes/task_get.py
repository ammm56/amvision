"""任务详情查询 service node。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._task_node_support import build_task_detail_body
from backend.nodes.core_nodes._service_node_support import (
    build_response_body_output,
    get_optional_bool_parameter,
    require_str_parameter,
    require_workflow_service_node_runtime,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _task_get_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """读取指定 task_id 的任务详情。"""

    runtime_context = require_workflow_service_node_runtime(request)
    include_events = get_optional_bool_parameter(request, "include_events")
    task_detail = runtime_context.build_task_service().get_task(
        require_str_parameter(request, "task_id"),
        include_events=True if include_events is None else include_events,
    )
    return build_response_body_output(build_task_detail_body(task_detail))


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.task.get",
        display_name="Get Task Detail",
        category="service.task.observe",
        description="读取指定任务的当前详情与可选事件列表。",
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
                "task_id": {"type": "string"},
                "include_events": {"type": "boolean"},
            },
            "required": ["task_id"],
        },
        capability_tags=("service.task", "runtime.observe", "task.detail"),
    ),
    handler=_task_get_handler,
)