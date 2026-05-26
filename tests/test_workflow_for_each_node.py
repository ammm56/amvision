"""workflow for-each 节点测试。"""

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
from backend.nodes.core_nodes.list_item_get import CORE_NODE_SPEC as LIST_ITEM_GET_NODE_SPEC
from backend.nodes.core_nodes.variable_get import CORE_NODE_SPEC as VARIABLE_GET_NODE_SPEC
from backend.nodes.core_nodes.variable_set import CORE_NODE_SPEC as VARIABLE_SET_NODE_SPEC
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor, WorkflowNodeRuntimeRegistry


def test_workflow_graph_executor_runs_for_each_body_and_collects_results() -> None:
    """验证 for-each 会按循环体逐项执行并收集指定结果端口的值。"""

    registry = WorkflowNodeRuntimeRegistry()
    for core_node_spec in (
        VARIABLE_SET_NODE_SPEC,
        VARIABLE_GET_NODE_SPEC,
        LIST_ITEM_GET_NODE_SPEC,
        COMPARE_NODE_SPEC,
        FOR_EACH_NODE_SPEC,
    ):
        registry.register_python_callable(core_node_spec.node_definition, core_node_spec.handler)
    executor = WorkflowGraphExecutor(registry=registry)
    template = WorkflowGraphTemplate(
        template_id="for-each-template",
        template_version="1.0.0",
        display_name="For Each Template",
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
                        "get_item",
                        "get_index",
                        "get_all_items",
                        "pick_again",
                        "compare_item",
                    ],
                    "result_node_id": "compare_item",
                    "result_port": "result",
                    "item_variable_name": "item",
                    "index_variable_name": "index",
                },
            ),
            WorkflowGraphNode(
                node_id="get_item",
                node_type_id="core.logic.variable.get",
                parameters={"name": "item"},
            ),
            WorkflowGraphNode(
                node_id="get_index",
                node_type_id="core.logic.variable.get",
                parameters={"name": "index"},
            ),
            WorkflowGraphNode(
                node_id="get_all_items",
                node_type_id="core.logic.variable.get",
                parameters={"name": "items"},
            ),
            WorkflowGraphNode(
                node_id="pick_again",
                node_type_id="core.logic.list-item-get",
            ),
            WorkflowGraphNode(
                node_id="compare_item",
                node_type_id="core.logic.compare",
                parameters={"operator": "eq"},
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
                edge_id="edge-all-items-pick-again",
                source_node_id="get_all_items",
                source_port="value",
                target_node_id="pick_again",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-index-pick-again",
                source_node_id="get_index",
                source_port="value",
                target_node_id="pick_again",
                target_port="index",
            ),
            WorkflowGraphEdge(
                edge_id="edge-item-compare-left",
                source_node_id="get_item",
                source_port="value",
                target_node_id="compare_item",
                target_port="left",
            ),
            WorkflowGraphEdge(
                edge_id="edge-pick-again-compare-right",
                source_node_id="pick_again",
                source_port="value",
                target_node_id="compare_item",
                target_port="right",
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
        input_values={"source_items": {"value": ["alpha", "beta", "gamma"]}},
    )

    assert execution_result.outputs["results"]["value"] == [True, True, True]
    assert execution_result.outputs["count"]["value"] == 3
    assert execution_result.outputs["terminated_early"]["value"] is False
    assert execution_result.outputs["termination_reason"]["value"] is None
    assert execution_result.outputs["termination_index"]["value"] is None
    assert any(record.node_id == "iterate_items[1].compare_item" for record in execution_result.node_records)
    assert any(record.node_id == "iterate_items" for record in execution_result.node_records)