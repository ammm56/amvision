"""Conditional/Switch 真正图控制流测试。"""

from __future__ import annotations

from collections.abc import Callable

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
from backend.nodes.core_nodes.logic.control.conditional_end import (
    CORE_NODE_SPEC as CONDITIONAL_END_SPEC,
)
from backend.nodes.core_nodes.logic.control.conditional_start import (
    CORE_NODE_SPEC as CONDITIONAL_START_SPEC,
)
from backend.nodes.core_nodes.logic.control.switch_end import (
    CORE_NODE_SPEC as SWITCH_END_SPEC,
)
from backend.nodes.core_nodes.logic.control.switch_start import (
    CORE_NODE_SPEC as SWITCH_START_SPEC,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)


PASSTHROUGH_DEFINITION = NodeDefinition(
    node_type_id="test.selection.passthrough",
    display_name="Selection Passthrough",
    category="test.logic",
    implementation_kind=NODE_IMPLEMENTATION_CORE,
    runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
    input_ports=(
        NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
    ),
    output_ports=(
        NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
    ),
    parameter_schema={"type": "object", "properties": {}},
    capability_tags=("execution.pure",),
)


def _build_registry(
    handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
) -> WorkflowNodeRuntimeRegistry:
    """注册选择边界和测试副作用节点。"""

    registry = WorkflowNodeRuntimeRegistry()
    for spec in (
        CONDITIONAL_START_SPEC,
        CONDITIONAL_END_SPEC,
        SWITCH_START_SPEC,
        SWITCH_END_SPEC,
    ):
        registry.register_python_callable(spec.node_definition, spec.handler)
    registry.register_python_callable(PASSTHROUGH_DEFINITION, handler)
    return registry


@pytest.mark.parametrize(
    ("condition", "expected_branch"),
    ((True, "if_true"), (False, "if_false")),
)
def test_conditional_executes_only_selected_branch(
    condition: bool,
    expected_branch: str,
) -> None:
    """验证未选分支 handler 完全不会运行。"""

    invoked_branches: list[str] = []

    def handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        branch_name = str(request.parameters["branch_name"])
        invoked_branches.append(branch_name)
        return {"value": {"value": branch_name}}

    result = WorkflowGraphExecutor(registry=_build_registry(handler)).execute(
        template=_build_conditional_template(),
        input_values={
            "condition": {"value": condition},
            "value": {"value": "input"},
        },
    )

    assert invoked_branches == [expected_branch]
    assert result.outputs["result"] == {"value": expected_branch}
    assert result.outputs["selected_branch"] == {"value": expected_branch}
    assert {record.node_id for record in result.node_records} == {
        "conditional_start",
        f"{expected_branch}_node",
        "conditional_end",
    }


@pytest.mark.parametrize(
    ("selector", "expected_branch"),
    (("A", "case_1"), (7, "case_2"), (True, "default"), ("missing", "default")),
)
def test_switch_executes_matching_case_or_default(
    selector: object,
    expected_branch: str,
) -> None:
    """验证 Switch 使用类型明确的 scalar case 匹配。"""

    invoked_branches: list[str] = []

    def handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        branch_name = str(request.parameters["branch_name"])
        invoked_branches.append(branch_name)
        return {"value": {"value": branch_name}}

    result = WorkflowGraphExecutor(registry=_build_registry(handler)).execute(
        template=_build_switch_template(),
        input_values={
            "selector": {"value": selector},
            "value": {"value": "input"},
        },
    )

    assert invoked_branches == [expected_branch]
    assert result.outputs["result"] == {"value": expected_branch}
    assert result.outputs["selected_branch"] == {"value": expected_branch}


def test_selection_rejects_missing_branch_path_before_running_handlers() -> None:
    """验证不完整边界在任何分支副作用前失败。"""

    invocation_count = 0

    def handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        nonlocal invocation_count
        invocation_count += 1
        return {"value": request.input_values["value"]}

    template = _build_conditional_template()
    invalid_template = template.model_copy(
        update={
            "edges": tuple(
                edge
                for edge in template.edges
                if edge.edge_id != "edge-false-start"
            )
        }
    )
    with pytest.raises(InvalidRequestError, match="每个选择分支端口"):
        WorkflowGraphExecutor(registry=_build_registry(handler)).execute(
            template=invalid_template,
            input_values={
                "condition": {"value": True},
                "value": {"value": "input"},
            },
        )
    assert invocation_count == 0


@pytest.mark.parametrize(
    ("outer_condition", "inner_condition", "expected_branch"),
    (
        (False, True, "outer_false"),
        (True, True, "inner_true"),
        (True, False, "inner_false"),
    ),
)
def test_conditional_boundaries_support_structured_nesting(
    outer_condition: bool,
    inner_condition: bool,
    expected_branch: str,
) -> None:
    """验证嵌套边界按共同汇合点配对，且外层未选时内层完全不执行。"""

    invoked_branches: list[str] = []

    def handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        branch_name = str(request.parameters["branch_name"])
        invoked_branches.append(branch_name)
        return {"value": {"value": branch_name}}

    result = WorkflowGraphExecutor(registry=_build_registry(handler)).execute(
        template=_build_nested_conditional_template(),
        input_values={
            "outer_condition": {"value": outer_condition},
            "inner_condition": {"value": inner_condition},
            "value": {"value": "input"},
        },
    )

    assert invoked_branches == [expected_branch]
    assert result.outputs["result"] == {"value": expected_branch}


def _build_conditional_template() -> WorkflowGraphTemplate:
    """构造两路 Conditional 测试图。"""

    return _build_selection_template(
        template_id="conditional-selection",
        start_node=WorkflowGraphNode(
            node_id="conditional_start",
            node_type_id=CONDITIONAL_START_SPEC.node_definition.node_type_id,
        ),
        end_node=WorkflowGraphNode(
            node_id="conditional_end",
            node_type_id=CONDITIONAL_END_SPEC.node_definition.node_type_id,
        ),
        branch_names=("if_true", "if_false"),
        selector_input_id="condition",
        selector_target_port="condition",
        selector_payload_type_id="boolean.v1",
    )


def _build_switch_template() -> WorkflowGraphTemplate:
    """构造两个 case 和 default 的 Switch 测试图。"""

    return _build_selection_template(
        template_id="switch-selection",
        start_node=WorkflowGraphNode(
            node_id="switch_start",
            node_type_id=SWITCH_START_SPEC.node_definition.node_type_id,
            parameters={"case_values": ["A", 7]},
        ),
        end_node=WorkflowGraphNode(
            node_id="switch_end",
            node_type_id=SWITCH_END_SPEC.node_definition.node_type_id,
        ),
        branch_names=("case_1", "case_2", "default"),
        selector_input_id="selector",
        selector_target_port="selector",
        selector_payload_type_id="value.v1",
    )


def _build_nested_conditional_template() -> WorkflowGraphTemplate:
    """构造外层 True 分支包含另一组 Conditional 的测试图。"""

    nodes = (
        WorkflowGraphNode(
            node_id="outer_start",
            node_type_id=CONDITIONAL_START_SPEC.node_definition.node_type_id,
        ),
        WorkflowGraphNode(
            node_id="outer_false_node",
            node_type_id=PASSTHROUGH_DEFINITION.node_type_id,
            parameters={"branch_name": "outer_false"},
        ),
        WorkflowGraphNode(
            node_id="inner_start",
            node_type_id=CONDITIONAL_START_SPEC.node_definition.node_type_id,
        ),
        WorkflowGraphNode(
            node_id="inner_true_node",
            node_type_id=PASSTHROUGH_DEFINITION.node_type_id,
            parameters={"branch_name": "inner_true"},
        ),
        WorkflowGraphNode(
            node_id="inner_false_node",
            node_type_id=PASSTHROUGH_DEFINITION.node_type_id,
            parameters={"branch_name": "inner_false"},
        ),
        WorkflowGraphNode(
            node_id="inner_end",
            node_type_id=CONDITIONAL_END_SPEC.node_definition.node_type_id,
        ),
        WorkflowGraphNode(
            node_id="outer_end",
            node_type_id=CONDITIONAL_END_SPEC.node_definition.node_type_id,
        ),
    )
    edges = (
        WorkflowGraphEdge(
            edge_id="outer-true-inner-start",
            source_node_id="outer_start",
            source_port="if_true",
            target_node_id="inner_start",
            target_port="value",
        ),
        WorkflowGraphEdge(
            edge_id="outer-false-node",
            source_node_id="outer_start",
            source_port="if_false",
            target_node_id="outer_false_node",
            target_port="value",
        ),
        WorkflowGraphEdge(
            edge_id="outer-false-end",
            source_node_id="outer_false_node",
            source_port="value",
            target_node_id="outer_end",
            target_port="result",
        ),
        WorkflowGraphEdge(
            edge_id="inner-true-node",
            source_node_id="inner_start",
            source_port="if_true",
            target_node_id="inner_true_node",
            target_port="value",
        ),
        WorkflowGraphEdge(
            edge_id="inner-false-node",
            source_node_id="inner_start",
            source_port="if_false",
            target_node_id="inner_false_node",
            target_port="value",
        ),
        WorkflowGraphEdge(
            edge_id="inner-true-end",
            source_node_id="inner_true_node",
            source_port="value",
            target_node_id="inner_end",
            target_port="result",
        ),
        WorkflowGraphEdge(
            edge_id="inner-false-end",
            source_node_id="inner_false_node",
            source_port="value",
            target_node_id="inner_end",
            target_port="result",
        ),
        WorkflowGraphEdge(
            edge_id="inner-end-outer-end",
            source_node_id="inner_end",
            source_port="result",
            target_node_id="outer_end",
            target_port="result",
        ),
    )
    return WorkflowGraphTemplate(
        template_id="nested-conditional-selection",
        template_version="1.0.0",
        display_name="Nested Conditional Selection",
        nodes=nodes,
        edges=edges,
        template_inputs=(
            WorkflowGraphInput(
                input_id="outer_condition",
                display_name="Outer Condition",
                payload_type_id="boolean.v1",
                target_node_id="outer_start",
                target_port="condition",
            ),
            WorkflowGraphInput(
                input_id="inner_condition",
                display_name="Inner Condition",
                payload_type_id="boolean.v1",
                target_node_id="inner_start",
                target_port="condition",
            ),
            WorkflowGraphInput(
                input_id="value",
                display_name="Value",
                payload_type_id="value.v1",
                target_node_id="outer_start",
                target_port="value",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="result",
                display_name="Result",
                payload_type_id="value.v1",
                source_node_id="outer_end",
                source_port="result",
            ),
        ),
    )


def _build_selection_template(
    *,
    template_id: str,
    start_node: WorkflowGraphNode,
    end_node: WorkflowGraphNode,
    branch_names: tuple[str, ...],
    selector_input_id: str,
    selector_target_port: str,
    selector_payload_type_id: str,
) -> WorkflowGraphTemplate:
    """构造具有显式分支节点和统一 End 的选择图。"""

    nodes = [start_node, end_node]
    edges: list[WorkflowGraphEdge] = []
    for branch_name in branch_names:
        branch_node_id = f"{branch_name}_node"
        nodes.append(
            WorkflowGraphNode(
                node_id=branch_node_id,
                node_type_id=PASSTHROUGH_DEFINITION.node_type_id,
                parameters={"branch_name": branch_name},
            )
        )
        edges.extend(
            (
                WorkflowGraphEdge(
                    edge_id=f"edge-{branch_name.removeprefix('if_')}-start",
                    source_node_id=start_node.node_id,
                    source_port=branch_name,
                    target_node_id=branch_node_id,
                    target_port="value",
                ),
                WorkflowGraphEdge(
                    edge_id=f"edge-{branch_name}-end",
                    source_node_id=branch_node_id,
                    source_port="value",
                    target_node_id=end_node.node_id,
                    target_port="result",
                ),
            )
        )
    return WorkflowGraphTemplate(
        template_id=template_id,
        template_version="1.0.0",
        display_name=template_id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        template_inputs=(
            WorkflowGraphInput(
                input_id=selector_input_id,
                display_name=selector_input_id,
                payload_type_id=selector_payload_type_id,
                target_node_id=start_node.node_id,
                target_port=selector_target_port,
            ),
            WorkflowGraphInput(
                input_id="value",
                display_name="Value",
                payload_type_id="value.v1",
                target_node_id=start_node.node_id,
                target_port="value",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="result",
                display_name="Result",
                payload_type_id="value.v1",
                source_node_id=end_node.node_id,
                source_port="result",
            ),
            WorkflowGraphOutput(
                output_id="selected_branch",
                display_name="Selected Branch",
                payload_type_id="value.v1",
                source_node_id=end_node.node_id,
                source_port="selected_branch",
            ),
        ),
    )
