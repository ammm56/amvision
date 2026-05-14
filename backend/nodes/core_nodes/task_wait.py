"""任务等待 service node。"""

from __future__ import annotations

import time

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._task_node_support import TASK_TERMINAL_STATES, build_task_detail_body
from backend.nodes.core_nodes._service_node_support import (
    build_response_body_output,
    get_optional_bool_parameter,
    get_optional_float_parameter,
    overlay_parameters_from_object_input,
    require_str_parameter,
    require_workflow_service_node_runtime,
)
from backend.service.application.errors import OperationTimeoutError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


_DEFAULT_WAIT_TIMEOUT_SECONDS = 300.0
_DEFAULT_POLL_INTERVAL_SECONDS = 1.0


def _task_wait_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """轮询任务直到进入终态，并返回最终详情。"""

    request = overlay_parameters_from_object_input(request)
    runtime_context = require_workflow_service_node_runtime(request)
    include_events = get_optional_bool_parameter(request, "include_events")
    timeout_seconds = get_optional_float_parameter(request, "timeout_seconds") or _DEFAULT_WAIT_TIMEOUT_SECONDS
    poll_interval_seconds = get_optional_float_parameter(request, "poll_interval_seconds") or _DEFAULT_POLL_INTERVAL_SECONDS
    if timeout_seconds <= 0:
        raise OperationTimeoutError(
            "task.wait timeout_seconds 必须大于 0",
            details={"node_id": request.node_id, "timeout_seconds": timeout_seconds},
        )
    if poll_interval_seconds <= 0:
        raise OperationTimeoutError(
            "task.wait poll_interval_seconds 必须大于 0",
            details={"node_id": request.node_id, "poll_interval_seconds": poll_interval_seconds},
        )

    task_id = require_str_parameter(request, "task_id")
    deadline = time.monotonic() + timeout_seconds
    task_service = runtime_context.build_task_service()
    while True:
        task_detail = task_service.get_task(task_id, include_events=True if include_events is None else include_events)
        if task_detail.task.state in TASK_TERMINAL_STATES:
            return build_response_body_output(build_task_detail_body(task_detail))
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise OperationTimeoutError(
                "等待任务进入终态超时",
                details={
                    "node_id": request.node_id,
                    "task_id": task_id,
                    "timeout_seconds": timeout_seconds,
                    "current_state": task_detail.task.state,
                },
            )
        time.sleep(min(poll_interval_seconds, max(remaining_seconds, 0.01)))


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.service.task.wait",
        display_name="Wait Task Terminal State",
        category="service.task.observe",
        description="轮询指定任务，直到进入 succeeded、failed 或 cancelled 终态。",
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
                "task_id": {"type": "string"},
                "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                "poll_interval_seconds": {"type": "number", "exclusiveMinimum": 0},
                "include_events": {"type": "boolean"},
            },
            "required": ["task_id"],
        },
        capability_tags=("service.task", "runtime.observe", "task.wait"),
    ),
    handler=_task_wait_handler,
)