"""workflow 循环控制节点测试。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.core_nodes.compare import CORE_NODE_SPEC as COMPARE_NODE_SPEC
from backend.nodes.core_nodes.for_each import CORE_NODE_SPEC as FOR_EACH_NODE_SPEC
from backend.nodes.core_nodes.if_else import CORE_NODE_SPEC as IF_ELSE_NODE_SPEC
from backend.nodes.core_nodes.loop_control import CORE_NODE_SPEC as LOOP_CONTROL_NODE_SPEC
from backend.nodes.core_nodes.variable_get import CORE_NODE_SPEC as VARIABLE_GET_NODE_SPEC
from backend.nodes.core_nodes.variable_set import CORE_NODE_SPEC as VARIABLE_SET_NODE_SPEC
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor, WorkflowNodeRuntimeRegistry


def test_workflow_graph_executor_honors_loop_control_break_and_continue() -> None:
    """验证 for-each 循环体中的 loop-control 可以触发 continue 与 break。"""

    registry = WorkflowNodeRuntimeRegistry()
    for core_node_spec in (
        VARIABLE_SET_NODE_SPEC,
        VARIABLE_GET_NODE_SPEC,
        COMPARE_NODE_SPEC,
        IF_ELSE_NODE_SPEC,
        LOOP_CONTROL_NODE_SPEC,
        FOR_EACH_NODE_SPEC,
    ):
        registry.register_python_callable(core_node_spec.node_definition, core_node_spec.handler)
    executor = WorkflowGraphExecutor(registry=registry)
    template = WorkflowGraphTemplate(
        template_id="loop-control-template",
        template_version="1.0.0",
        display_name="Loop Control Template",
        nodes=(
            WorkflowGraphNode(
                node_id="set_items",
                node_type_id="core.logic.variable.set",
                parameters={"name": "items"},
            ),
            WorkflowGraphNode(
                node_id="iterate_items",
                node_type_id="core.logic.for-each",
                parameters={
                    "body_node_ids": [
                        "get_item_for_compare",
                        "compare_skip",
                        "continue_loop",
                        "compare_break",
                        "break_loop",
                        "select_item_result",
                    ],
                    "result_node_id": "select_item_result",
                    "result_port": "value",
                    "item_variable_name": "item",
                    "index_variable_name": "index",
                },
            ),
            WorkflowGraphNode(
                node_id="get_item_for_compare",
                node_type_id="core.logic.variable.get",
                parameters={"name": "item"},
            ),
            WorkflowGraphNode(
                node_id="compare_skip",
                node_type_id="core.logic.compare",
                parameters={"operator": "eq", "right_value": "skip"},
            ),
            WorkflowGraphNode(
                node_id="continue_loop",
                node_type_id="core.logic.loop-control",
                parameters={"action": "continue"},
            ),
            WorkflowGraphNode(
                node_id="compare_break",
                node_type_id="core.logic.compare",
                parameters={"operator": "eq", "right_value": "stop"},
            ),
            WorkflowGraphNode(
                node_id="break_loop",
                node_type_id="core.logic.loop-control",
                parameters={"action": "break"},
            ),
            WorkflowGraphNode(
                node_id="select_item_result",
                node_type_id="core.logic.if-else",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-set-items-iterate",
                source_node_id="set_items",
                source_port="value",
                target_node_id="iterate_items",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-get-item-compare-skip",
                source_node_id="get_item_for_compare",
                source_port="value",
                target_node_id="compare_skip",
                target_port="left",
            ),
            WorkflowGraphEdge(
                edge_id="edge-compare-skip-continue",
                source_node_id="compare_skip",
                source_port="result",
                target_node_id="continue_loop",
                target_port="condition",
            ),
            WorkflowGraphEdge(
                edge_id="edge-get-item-compare-break",
                source_node_id="get_item_for_compare",
                source_port="value",
                target_node_id="compare_break",
                target_port="left",
            ),
            WorkflowGraphEdge(
                edge_id="edge-compare-break-break-loop",
                source_node_id="compare_break",
                source_port="result",
                target_node_id="break_loop",
                target_port="condition",
            ),
            WorkflowGraphEdge(
                edge_id="edge-break-loop-select-condition",
                source_node_id="break_loop",
                source_port="activated",
                target_node_id="select_item_result",
                target_port="condition",
            ),
            WorkflowGraphEdge(
                edge_id="edge-get-item-select-if-true",
                source_node_id="get_item_for_compare",
                source_port="value",
                target_node_id="select_item_result",
                target_port="if_true",
            ),
            WorkflowGraphEdge(
                edge_id="edge-get-item-select-if-false",
                source_node_id="get_item_for_compare",
                source_port="value",
                target_node_id="select_item_result",
                target_port="if_false",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_items",
                display_name="Source Items",
                payload_type_id="value.v1",
                target_node_id="set_items",
                target_port="value",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="results",
                display_name="Results",
                payload_type_id="value.v1",
                source_node_id="iterate_items",
                source_port="results",
            ),
            WorkflowGraphOutput(
                output_id="count",
                display_name="Count",
                payload_type_id="value.v1",
                source_node_id="iterate_items",
                source_port="count",
            ),
            WorkflowGraphOutput(
                output_id="terminated_early",
                display_name="Terminated Early",
                payload_type_id="boolean.v1",
                source_node_id="iterate_items",
                source_port="terminated_early",
            ),
            WorkflowGraphOutput(
                output_id="termination_reason",
                display_name="Termination Reason",
                payload_type_id="value.v1",
                source_node_id="iterate_items",
                source_port="termination_reason",
            ),
            WorkflowGraphOutput(
                output_id="termination_index",
                display_name="Termination Index",
                payload_type_id="value.v1",
                source_node_id="iterate_items",
                source_port="termination_index",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={"source_items": {"value": ["keep-1", "skip", "keep-2", "stop", "keep-3"]}},
    )

    assert execution_result.outputs["results"]["value"] == ["keep-1", "keep-2"]
    assert execution_result.outputs["count"]["value"] == 2
    assert execution_result.outputs["terminated_early"]["value"] is True
    assert execution_result.outputs["termination_reason"]["value"] == "break"
    assert execution_result.outputs["termination_index"]["value"] == 3
    assert any(record.node_id == "iterate_items[2].continue_loop" for record in execution_result.node_records)
    assert any(record.node_id == "iterate_items[4].break_loop" for record in execution_result.node_records)
    assert not any(record.node_id == "iterate_items[2].select_item_result" for record in execution_result.node_records)
    assert not any(record.node_id == "iterate_items[4].select_item_result" for record in execution_result.node_records)
    assert not any(record.node_id.startswith("iterate_items[5].") for record in execution_result.node_records)