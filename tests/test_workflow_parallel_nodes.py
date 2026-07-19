"""通用 Split List 与显式 Parallel 执行边界测试。"""

from __future__ import annotations

from threading import Lock
from time import sleep
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
from backend.nodes.core_nodes.logic.collections.list_item_get import (
    CORE_NODE_SPEC as LIST_ITEM_GET_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.collections.list_split import (
    CORE_NODE_SPEC as LIST_SPLIT_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.control.for_each_end import (
    CORE_NODE_SPEC as FOR_EACH_END_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.control.for_each_start import (
    CORE_NODE_SPEC as FOR_EACH_START_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.control.parallel_end import (
    CORE_NODE_SPEC as PARALLEL_END_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.control.parallel_start import (
    CORE_NODE_SPEC as PARALLEL_START_NODE_SPEC,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.variables import (
    read_workflow_variable_snapshot,
)
from backend.service.application.workflows.execution_cleanup import (
    list_registered_execution_cleanups,
    register_execution_cleanup,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
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


def test_parallel_nodes_follow_existing_catalog_names_and_categories() -> None:
    """验证公开名称保持 English，且只使用现有 node categories。"""

    assert LIST_SPLIT_NODE_SPEC.node_definition.display_name == "Split List"
    assert LIST_SPLIT_NODE_SPEC.node_definition.category == "logic.collection"
    assert PARALLEL_START_NODE_SPEC.node_definition.display_name == "Parallel Start"
    assert PARALLEL_START_NODE_SPEC.node_definition.category == "logic.iteration"
    assert PARALLEL_END_NODE_SPEC.node_definition.display_name == "Parallel End"
    assert PARALLEL_END_NODE_SPEC.node_definition.category == "logic.iteration"
    assert "localized_display_name" not in LIST_SPLIT_NODE_SPEC.node_definition.metadata
    assert "localized_display_name" not in PARALLEL_START_NODE_SPEC.node_definition.metadata
    assert "localized_display_name" not in PARALLEL_END_NODE_SPEC.node_definition.metadata


@pytest.mark.parametrize(
    ("item_count", "partition_count", "expected_sizes"),
    (
        (5, 1, [5]),
        (80, 3, [27, 27, 26]),
        (23, 10, [3, 3, 3, 2, 2, 2, 2, 2, 2, 2]),
    ),
)
def test_split_list_supports_user_selected_partition_count(
    item_count: int,
    partition_count: int,
    expected_sizes: list[int],
) -> None:
    """验证 Split List 不把当前现场的 3 路写进公开契约。"""

    outputs = LIST_SPLIT_NODE_SPEC.handler(
        WorkflowNodeExecutionRequest(
            node_id="split",
            node_definition=LIST_SPLIT_NODE_SPEC.node_definition,
            parameters={"partition_count": partition_count},
            input_values={"items": {"value": list(range(item_count))}},
        )
    )
    partitions = outputs["partitions"]["value"]

    assert [len(partition) for partition in partitions] == expected_sizes
    assert [item for partition in partitions for item in partition] == list(
        range(item_count)
    )


@pytest.mark.parametrize("branch_count", (1, 3, 10))
def test_parallel_boundary_uses_actual_visible_branch_count(branch_count: int) -> None:
    """验证 1、3、10 个显式分支都能并发运行并有序 concat。"""

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
            sleep(0.01)
            item_exists, item_value = read_workflow_variable_snapshot(
                execution_metadata=request.execution_metadata,
                name="item",
            )
            assert item_exists is True
            assert item_value == request.input_values["value"]["value"]
            register_execution_cleanup(
                request.execution_metadata,
                resource_kind="test-resource",
                resource_id=f"{request.node_id}:{item_value}",
            )
            return {"value": request.input_values["value"]}
        finally:
            with state_lock:
                active_count -= 1

    registry = _build_registry(delayed_passthrough_handler)
    source_items = list(range(branch_count * 2))
    execution_metadata: dict[str, object] = {
        "workflow_variables": {"seed": "kept"},
    }
    result = WorkflowGraphExecutor(registry=registry).execute(
        template=_build_parallel_template(
            branch_count=branch_count,
            max_concurrency=branch_count,
        ),
        input_values={"source_items": {"value": source_items}},
        execution_metadata=execution_metadata,
    )

    assert result.outputs["results"]["value"] == source_items
    assert result.outputs["count"]["value"] == len(source_items)
    assert max_active_count == branch_count
    assert len(list_registered_execution_cleanups(execution_metadata)) == len(
        source_items
    )
    assert execution_metadata["workflow_variables"] == {"seed": "kept"}


def test_parallel_boundary_limits_concurrency_without_changing_branch_count() -> None:
    """验证 10 个可见分支可以由 max_concurrency=3 受控调度。"""

    state_lock = Lock()
    active_count = 0
    max_active_count = 0

    def delayed_handler(
        request: WorkflowNodeExecutionRequest,
    ) -> dict[str, object]:
        nonlocal active_count, max_active_count
        with state_lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
        try:
            sleep(0.02)
            return {"value": request.input_values["value"]}
        finally:
            with state_lock:
                active_count -= 1

    result = WorkflowGraphExecutor(registry=_build_registry(delayed_handler)).execute(
        template=_build_parallel_template(branch_count=10, max_concurrency=3),
        input_values={"source_items": {"value": list(range(10))}},
    )

    assert result.outputs["results"]["value"] == list(range(10))
    assert max_active_count == 3


def test_parallel_boundary_handles_empty_partitions() -> None:
    """验证空列表不会制造占位项或跳过 Parallel End。"""

    registry = _build_registry(
        lambda request: {"value": request.input_values["value"]},
    )
    result = WorkflowGraphExecutor(registry=registry).execute(
        template=_build_parallel_template(branch_count=10, max_concurrency=4),
        input_values={"source_items": {"value": []}},
    )

    assert result.outputs["results"]["value"] == []
    assert result.outputs["count"]["value"] == 0


def test_parallel_boundary_preserves_failed_branch_context() -> None:
    """验证分支异常包含真实失败节点和明确的分支编号。"""

    def fail_on_branch_two(
        request: WorkflowNodeExecutionRequest,
    ) -> dict[str, object]:
        value = request.input_values["value"]["value"]
        if value == 2:
            raise InvalidRequestError("分支测试失败")
        return {"value": request.input_values["value"]}

    with pytest.raises(InvalidRequestError) as exc_info:
        WorkflowGraphExecutor(registry=_build_registry(fail_on_branch_two)).execute(
            template=_build_parallel_template(branch_count=3, max_concurrency=3),
            input_values={"source_items": {"value": list(range(6))}},
        )

    assert exc_info.value.details["node_id"] == "branch_2_work"
    assert exc_info.value.details["parallel_branch_index"] == 2
    assert exc_info.value.details["parallel_start_node_id"] == "parallel_start"
    assert exc_info.value.details["parallel_end_node_id"] == "parallel_end"


def _build_registry(
    handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
) -> WorkflowNodeRuntimeRegistry:
    """注册 Parallel、List 和 For Each 测试节点。"""

    registry = WorkflowNodeRuntimeRegistry()
    for spec in (
        LIST_SPLIT_NODE_SPEC,
        LIST_ITEM_GET_NODE_SPEC,
        PARALLEL_START_NODE_SPEC,
        PARALLEL_END_NODE_SPEC,
        FOR_EACH_START_NODE_SPEC,
        FOR_EACH_END_NODE_SPEC,
    ):
        registry.register_python_callable(spec.node_definition, spec.handler)
    registry.register_python_callable(PASSTHROUGH_NODE_DEFINITION, handler)
    return registry


def _build_parallel_template(
    *,
    branch_count: int,
    max_concurrency: int,
) -> WorkflowGraphTemplate:
    """构造 Split List + 任意数量显式 Parallel 分支。"""

    nodes: list[WorkflowGraphNode] = [
        WorkflowGraphNode(
            node_id="split_list",
            node_type_id=LIST_SPLIT_NODE_SPEC.node_definition.node_type_id,
            parameters={"partition_count": branch_count},
        ),
        WorkflowGraphNode(
            node_id="parallel_start",
            node_type_id=PARALLEL_START_NODE_SPEC.node_definition.node_type_id,
            parameters={"max_concurrency": max_concurrency},
        ),
        WorkflowGraphNode(
            node_id="parallel_end",
            node_type_id=PARALLEL_END_NODE_SPEC.node_definition.node_type_id,
            parameters={"mode": "concat"},
        ),
    ]
    edges: list[WorkflowGraphEdge] = [
        WorkflowGraphEdge(
            edge_id="edge-split-start",
            source_node_id="split_list",
            source_port="partitions",
            target_node_id="parallel_start",
            target_port="value",
        ),
    ]
    for branch_index in range(1, branch_count + 1):
        item_node_id = f"branch_{branch_index}_item"
        start_node_id = f"branch_{branch_index}_start"
        work_node_id = f"branch_{branch_index}_work"
        end_node_id = f"branch_{branch_index}_end"
        nodes.extend(
            (
                WorkflowGraphNode(
                    node_id=item_node_id,
                    node_type_id=LIST_ITEM_GET_NODE_SPEC.node_definition.node_type_id,
                    parameters={"index": branch_index - 1},
                ),
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
        edges.extend(
            (
                WorkflowGraphEdge(
                    edge_id=f"edge-parallel-item-{branch_index}",
                    source_node_id="parallel_start",
                    source_port="value",
                    target_node_id=item_node_id,
                    target_port="items",
                ),
                WorkflowGraphEdge(
                    edge_id=f"edge-item-loop-{branch_index}",
                    source_node_id=item_node_id,
                    source_port="value",
                    target_node_id=start_node_id,
                    target_port="items",
                ),
                WorkflowGraphEdge(
                    edge_id=f"edge-loop-work-{branch_index}",
                    source_node_id=start_node_id,
                    source_port="item",
                    target_node_id=work_node_id,
                    target_port="value",
                ),
                WorkflowGraphEdge(
                    edge_id=f"edge-work-loop-{branch_index}",
                    source_node_id=work_node_id,
                    source_port="value",
                    target_node_id=end_node_id,
                    target_port="result",
                ),
                WorkflowGraphEdge(
                    edge_id=f"edge-loop-parallel-{branch_index}",
                    source_node_id=end_node_id,
                    source_port="results",
                    target_node_id="parallel_end",
                    target_port="results",
                ),
            )
        )
    return WorkflowGraphTemplate(
        template_id=f"parallel-{branch_count}-branches",
        template_version="1.0.0",
        display_name=f"Parallel {branch_count} Branches",
        nodes=tuple(nodes),
        edges=tuple(edges),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_items",
                display_name="Source Items",
                payload_type_id="value.v1",
                target_node_id="split_list",
                target_port="items",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="results",
                display_name="Results",
                payload_type_id="value.v1",
                source_node_id="parallel_end",
                source_port="results",
            ),
            WorkflowGraphOutput(
                output_id="count",
                display_name="Count",
                payload_type_id="value.v1",
                source_node_id="parallel_end",
                source_port="count",
            ),
        ),
    )
