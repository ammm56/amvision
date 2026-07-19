"""通用三路并行列表基础节点与执行边界测试。"""

from __future__ import annotations

from threading import Lock
from time import perf_counter, sleep
from typing import Callable

import pytest

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.core_nodes.logic.collections.parallel_list_merge_3 import (
    CORE_NODE_SPEC as PARALLEL_LIST_MERGE_3_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.collections.parallel_list_split_3 import (
    CORE_NODE_SPEC as PARALLEL_LIST_SPLIT_3_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.control.for_each_end import (
    CORE_NODE_SPEC as FOR_EACH_END_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.control.for_each_start import (
    CORE_NODE_SPEC as FOR_EACH_START_NODE_SPEC,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution_cleanup import (
    list_registered_execution_cleanups,
    register_execution_cleanup,
)
from backend.service.application.workflows.execution.variables import (
    read_workflow_variable_snapshot,
)


PASSTHROUGH_NODE_TYPE_ID = "test.logic.delayed-passthrough"
PASSTHROUGH_NODE_DEFINITION = NodeDefinition(
    node_type_id=PASSTHROUGH_NODE_TYPE_ID,
    display_name="Delayed Passthrough",
    category="test.logic",
    implementation_kind=NODE_IMPLEMENTATION_CORE,
    runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
    input_ports=(
        NodePortDefinition(
            name="value",
            display_name="Value",
            payload_type_id="value.v1",
        ),
    ),
    output_ports=(
        NodePortDefinition(
            name="value",
            display_name="Value",
            payload_type_id="value.v1",
        ),
    ),
    parameter_schema={"type": "object", "properties": {}},
    capability_tags=("execution.pure",),
)


def test_parallel_list_split_and_merge_preserve_all_item_order() -> None:
    """验证80项按27、27、26拆分后仍按原始顺序合并。"""

    split_handler = PARALLEL_LIST_SPLIT_3_NODE_SPEC.handler
    merge_handler = PARALLEL_LIST_MERGE_3_NODE_SPEC.handler
    source_items = list(range(80))
    split_outputs = split_handler(
        WorkflowNodeExecutionRequest(
            node_id="split",
            node_definition=PARALLEL_LIST_SPLIT_3_NODE_SPEC.node_definition,
            input_values={"items": {"value": source_items}},
        )
    )

    assert [len(split_outputs[f"part_{index}"]["value"]) for index in range(1, 4)] == [
        27,
        27,
        26,
    ]

    merge_outputs = merge_handler(
        WorkflowNodeExecutionRequest(
            node_id="merge",
            node_definition=PARALLEL_LIST_MERGE_3_NODE_SPEC.node_definition,
            input_values=split_outputs,
        )
    )
    assert merge_outputs["items"]["value"] == source_items
    assert merge_outputs["count"]["value"] == 80


def test_parallel_list_boundary_runs_three_explicit_for_each_branches_concurrently() -> (
    None
):
    """验证三条可见 For Each 分支并发执行且结果顺序确定。"""

    state_lock = Lock()
    active_count = 0
    max_active_count = 0

    def delayed_passthrough_handler(
        request: WorkflowNodeExecutionRequest,
    ) -> dict[str, object]:
        nonlocal active_count, max_active_count
        with state_lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
        try:
            sleep(0.02)
            item_exists, item_value = read_workflow_variable_snapshot(
                execution_metadata=request.execution_metadata,
                name="item",
            )
            assert item_exists is True
            assert item_value == request.input_values["value"]["value"]
            register_execution_cleanup(
                request.execution_metadata,
                resource_kind="test-resource",
                resource_id=(
                    f"{request.node_id}:{request.input_values['value']['value']}"
                ),
            )
            return {"value": request.input_values["value"]}
        finally:
            with state_lock:
                active_count -= 1

    registry = _build_registry(delayed_passthrough_handler)
    template = _build_parallel_for_each_template()

    started_at = perf_counter()
    execution_metadata: dict[str, object] = {
        "workflow_variables": {"seed": "kept"},
    }
    result = WorkflowGraphExecutor(registry=registry).execute(
        template=template,
        input_values={"source_items": {"value": list(range(9))}},
        execution_metadata=execution_metadata,
    )
    elapsed_seconds = perf_counter() - started_at

    assert result.outputs["items"]["value"] == list(range(9))
    assert result.outputs["count"]["value"] == 9
    assert max_active_count == 3
    assert elapsed_seconds < 0.15
    assert len(list_registered_execution_cleanups(execution_metadata)) == 9
    assert execution_metadata["workflow_variables"] == {"seed": "kept"}
    assert [
        record.node_id
        for record in result.node_records
        if PASSTHROUGH_NODE_TYPE_ID in record.node_type_id
    ] == [
        "branch_1_end[1].branch_1_work",
        "branch_1_end[2].branch_1_work",
        "branch_1_end[3].branch_1_work",
        "branch_2_end[1].branch_2_work",
        "branch_2_end[2].branch_2_work",
        "branch_2_end[3].branch_2_work",
        "branch_3_end[1].branch_3_work",
        "branch_3_end[2].branch_3_work",
        "branch_3_end[3].branch_3_work",
    ]


def test_parallel_list_boundary_handles_empty_partitions() -> None:
    """验证空列表不会制造占位项或跳过合并节点。"""

    registry = _build_registry(
        lambda request: {"value": request.input_values["value"]},
    )
    result = WorkflowGraphExecutor(registry=registry).execute(
        template=_build_parallel_for_each_template(),
        input_values={"source_items": {"value": []}},
    )

    assert result.outputs["items"]["value"] == []
    assert result.outputs["count"]["value"] == 0


def test_parallel_list_boundary_preserves_failed_branch_context() -> None:
    """验证分支异常包含真实失败节点和明确的分支编号。"""

    def fail_on_branch_two(
        request: WorkflowNodeExecutionRequest,
    ) -> dict[str, object]:
        value = request.input_values["value"]["value"]
        if value == 4:
            raise InvalidRequestError("分支测试失败")
        return {"value": request.input_values["value"]}

    registry = _build_registry(fail_on_branch_two)
    with pytest.raises(InvalidRequestError) as exc_info:
        WorkflowGraphExecutor(registry=registry).execute(
            template=_build_parallel_for_each_template(),
            input_values={"source_items": {"value": list(range(9))}},
        )

    assert exc_info.value.details["node_id"] == "branch_2_work"
    assert exc_info.value.details["parallel_branch_index"] == 2
    assert exc_info.value.details["parallel_start_node_id"] == "parallel_split"
    assert exc_info.value.details["parallel_end_node_id"] == "parallel_merge"


def _build_registry(
    handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
) -> WorkflowNodeRuntimeRegistry:
    """注册三路边界、For Each 与测试处理节点。"""

    registry = WorkflowNodeRuntimeRegistry()
    for spec in (
        PARALLEL_LIST_SPLIT_3_NODE_SPEC,
        PARALLEL_LIST_MERGE_3_NODE_SPEC,
        FOR_EACH_START_NODE_SPEC,
        FOR_EACH_END_NODE_SPEC,
    ):
        registry.register_python_callable(spec.node_definition, spec.handler)
    registry.register_python_callable(PASSTHROUGH_NODE_DEFINITION, handler)
    return registry


def _build_parallel_for_each_template() -> WorkflowGraphTemplate:
    """构造与现场模型推理相同形态的通用三分支测试图。"""

    nodes: list[WorkflowGraphNode] = [
        WorkflowGraphNode(
            node_id="parallel_split",
            node_type_id=PARALLEL_LIST_SPLIT_3_NODE_SPEC.node_definition.node_type_id,
        ),
        WorkflowGraphNode(
            node_id="parallel_merge",
            node_type_id=PARALLEL_LIST_MERGE_3_NODE_SPEC.node_definition.node_type_id,
        ),
    ]
    edges: list[WorkflowGraphEdge] = []
    for branch_index in range(1, 4):
        start_node_id = f"branch_{branch_index}_start"
        work_node_id = f"branch_{branch_index}_work"
        end_node_id = f"branch_{branch_index}_end"
        nodes.extend(
            (
                WorkflowGraphNode(
                    node_id=start_node_id,
                    node_type_id=FOR_EACH_START_NODE_SPEC.node_definition.node_type_id,
                ),
                WorkflowGraphNode(
                    node_id=work_node_id,
                    node_type_id=PASSTHROUGH_NODE_TYPE_ID,
                ),
                WorkflowGraphNode(
                    node_id=end_node_id,
                    node_type_id=FOR_EACH_END_NODE_SPEC.node_definition.node_type_id,
                ),
            )
        )
        branch_port = f"part_{branch_index}"
        edges.extend(
            (
                WorkflowGraphEdge(
                    edge_id=f"edge-split-{branch_index}",
                    source_node_id="parallel_split",
                    source_port=branch_port,
                    target_node_id=start_node_id,
                    target_port="items",
                ),
                WorkflowGraphEdge(
                    edge_id=f"edge-item-{branch_index}",
                    source_node_id=start_node_id,
                    source_port="item",
                    target_node_id=work_node_id,
                    target_port="value",
                ),
                WorkflowGraphEdge(
                    edge_id=f"edge-result-{branch_index}",
                    source_node_id=work_node_id,
                    source_port="value",
                    target_node_id=end_node_id,
                    target_port="result",
                ),
                WorkflowGraphEdge(
                    edge_id=f"edge-merge-{branch_index}",
                    source_node_id=end_node_id,
                    source_port="results",
                    target_node_id="parallel_merge",
                    target_port=branch_port,
                ),
            )
        )
    return WorkflowGraphTemplate(
        template_id="parallel-list-three-branches",
        template_version="1.0.0",
        display_name="Parallel List Three Branches",
        nodes=tuple(nodes),
        edges=tuple(edges),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_items",
                display_name="Source Items",
                payload_type_id="value.v1",
                target_node_id="parallel_split",
                target_port="items",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="items",
                display_name="Items",
                payload_type_id="value.v1",
                source_node_id="parallel_merge",
                source_port="items",
            ),
            WorkflowGraphOutput(
                output_id="count",
                display_name="Count",
                payload_type_id="value.v1",
                source_node_id="parallel_merge",
                source_port="count",
            ),
        ),
    )
