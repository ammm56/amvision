"""Parallel 显式执行边界终点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


PARALLEL_END_MODE_COLLECT = "collect"
PARALLEL_END_MODE_CONCAT = "concat"


def _parallel_end_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按分支顺序 collect 或 concat Results。"""

    result_payloads = request.input_values.get("results")
    if not isinstance(result_payloads, tuple) or not result_payloads:
        raise InvalidRequestError(
            "Parallel End 要求 Results 至少连接一个分支",
            details={"node_id": request.node_id},
        )
    values = [
        require_value_payload(payload, field_name=f"results[{index}]")["value"]
        for index, payload in enumerate(result_payloads, start=1)
    ]
    mode = request.parameters.get("mode", PARALLEL_END_MODE_COLLECT)
    if mode == PARALLEL_END_MODE_COLLECT:
        merged_results = values
    elif mode == PARALLEL_END_MODE_CONCAT:
        merged_results: list[object] = []
        for index, value in enumerate(values, start=1):
            if not isinstance(value, list):
                raise InvalidRequestError(
                    "Parallel End 的 concat mode 要求每个分支结果都是 List",
                    details={
                        "node_id": request.node_id,
                        "branch_index": index,
                        "value_type": type(value).__name__,
                    },
                )
            merged_results.extend(value)
    else:
        raise InvalidRequestError(
            "Parallel End 的 mode 只支持 collect 或 concat",
            details={"node_id": request.node_id, "mode": mode},
        )
    return {
        "results": build_value_payload(merged_results),
        "count": build_value_payload(len(merged_results)),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.parallel-end",
        display_name="Parallel End",
        category="logic.iteration",
        description=(
            "等待 Parallel Start 的全部显式分支完成，并按画布分支顺序 collect 或 concat Results。"
        ),
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="results",
                display_name="Results",
                payload_type_id="value.v1",
                multiple=True,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="results",
                display_name="Results",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="count",
                display_name="Count",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": [PARALLEL_END_MODE_COLLECT, PARALLEL_END_MODE_CONCAT],
                    "default": PARALLEL_END_MODE_COLLECT,
                },
            },
        },
        capability_tags=(
            "logic.iteration",
            "parallel.boundary.end",
            "execution.pure",
        ),
    ),
    handler=_parallel_end_handler,
)
