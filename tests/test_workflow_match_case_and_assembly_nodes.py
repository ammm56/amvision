"""workflow 装配与条件匹配节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.service.application.workflows.runtime_service import WorkflowPreviewRunCreateRequest
from tests.test_workflow_runtime_sanitization import _build_runtime_service


def test_preview_run_match_case_and_assembly_nodes_build_dynamic_cases_and_reduce_inputs(tmp_path: Path) -> None:
    """验证 list-create、object-create 与 match-case 可以构造条件分支和 reduce 输入。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_match_case_application(),
            template=_build_match_case_template(),
            input_bindings={
                "applicant_score": {"value": 72},
                "applicant_state": {"value": "inactive"},
                "high_result": {"value": {"tier": "high"}},
                "medium_result": {"value": {"tier": "medium"}},
                "active_result": {"value": {"tier": "active"}},
                "default_result": {"value": {"tier": "default"}},
                "reduce_item_1": {"value": 5},
                "reduce_item_2": {"value": 7},
                "reduce_item_3": {"value": 9},
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert preview_run.outputs["matched_value"]["value"] == {"tier": "medium"}
    assert preview_run.outputs["matched_flag"]["value"] is True
    assert preview_run.outputs["matched_case_index"]["value"] == 1
    assert preview_run.outputs["reduced_sum"]["value"] == 21


def _build_match_case_template() -> WorkflowGraphTemplate:
    """构造装配与条件匹配节点最小组合模板。"""

    return WorkflowGraphTemplate(
        template_id="match-case-assembly-template",
        template_version="1.0.0",
        display_name="Match Case Assembly Template",
        nodes=(
            WorkflowGraphNode(
                node_id="build_target",
                node_type_id="core.logic.object-create",
                parameters={"keys": ["score", "state"]},
            ),
            WorkflowGraphNode(
                node_id="build_case_high",
                node_type_id="core.logic.object-create",
                parameters={
                    "keys": ["then"],
                    "fields": {
                        "condition": {
                            "operator": "ge",
                            "path": "score",
                            "right": 90,
                        }
                    },
                },
            ),
            WorkflowGraphNode(
                node_id="build_case_medium",
                node_type_id="core.logic.object-create",
                parameters={
                    "keys": ["then"],
                    "fields": {
                        "condition": {
                            "operator": "and",
                            "conditions": [
                                {"operator": "ge", "path": "score", "right": 60},
                                {"operator": "lt", "path": "score", "right": 90},
                            ],
                        }
                    },
                },
            ),
            WorkflowGraphNode(
                node_id="build_case_active",
                node_type_id="core.logic.object-create",
                parameters={
                    "keys": ["then"],
                    "fields": {
                        "condition": {
                            "operator": "eq",
                            "path": "state",
                            "right": "active",
                        }
                    },
                },
            ),
            WorkflowGraphNode(node_id="build_cases", node_type_id="core.logic.list-create"),
            WorkflowGraphNode(node_id="match_value", node_type_id="core.logic.match-case"),
            WorkflowGraphNode(node_id="build_reduce_items", node_type_id="core.logic.list-create"),
            WorkflowGraphNode(
                node_id="reduce_items",
                node_type_id="core.logic.reduce",
                parameters={"operator": "sum"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-target-to-match",
                source_node_id="build_target",
                source_port="value",
                target_node_id="match_value",
                target_port="value",
            ),
            WorkflowGraphEdge(
                edge_id="edge-case-high-to-cases",
                source_node_id="build_case_high",
                source_port="value",
                target_node_id="build_cases",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-case-medium-to-cases",
                source_node_id="build_case_medium",
                source_port="value",
                target_node_id="build_cases",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-case-active-to-cases",
                source_node_id="build_case_active",
                source_port="value",
                target_node_id="build_cases",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-cases-to-match",
                source_node_id="build_cases",
                source_port="value",
                target_node_id="match_value",
                target_port="cases",
            ),
            WorkflowGraphEdge(
                edge_id="edge-reduce-items-to-reduce",
                source_node_id="build_reduce_items",
                source_port="value",
                target_node_id="reduce_items",
                target_port="items",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="applicant_score",
                display_name="Applicant Score",
                payload_type_id="value.v1",
                target_node_id="build_target",
                target_port="values",
            ),
            WorkflowGraphInput(
                input_id="applicant_state",
                display_name="Applicant State",
                payload_type_id="value.v1",
                target_node_id="build_target",
                target_port="values",
            ),
            WorkflowGraphInput(
                input_id="high_result",
                display_name="High Result",
                payload_type_id="value.v1",
                target_node_id="build_case_high",
                target_port="values",
            ),
            WorkflowGraphInput(
                input_id="medium_result",
                display_name="Medium Result",
                payload_type_id="value.v1",
                target_node_id="build_case_medium",
                target_port="values",
            ),
            WorkflowGraphInput(
                input_id="active_result",
                display_name="Active Result",
                payload_type_id="value.v1",
                target_node_id="build_case_active",
                target_port="values",
            ),
            WorkflowGraphInput(
                input_id="default_result",
                display_name="Default Result",
                payload_type_id="value.v1",
                target_node_id="match_value",
                target_port="default",
            ),
            WorkflowGraphInput(
                input_id="reduce_item_1",
                display_name="Reduce Item 1",
                payload_type_id="value.v1",
                target_node_id="build_reduce_items",
                target_port="items",
            ),
            WorkflowGraphInput(
                input_id="reduce_item_2",
                display_name="Reduce Item 2",
                payload_type_id="value.v1",
                target_node_id="build_reduce_items",
                target_port="items",
            ),
            WorkflowGraphInput(
                input_id="reduce_item_3",
                display_name="Reduce Item 3",
                payload_type_id="value.v1",
                target_node_id="build_reduce_items",
                target_port="items",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="matched_value",
                display_name="Matched Value",
                payload_type_id="value.v1",
                source_node_id="match_value",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="matched_flag",
                display_name="Matched Flag",
                payload_type_id="boolean.v1",
                source_node_id="match_value",
                source_port="matched",
            ),
            WorkflowGraphOutput(
                output_id="matched_case_index",
                display_name="Matched Case Index",
                payload_type_id="value.v1",
                source_node_id="match_value",
                source_port="matched_case_index",
            ),
            WorkflowGraphOutput(
                output_id="reduced_sum",
                display_name="Reduced Sum",
                payload_type_id="value.v1",
                source_node_id="reduce_items",
                source_port="value",
            ),
        ),
    )


def _build_match_case_application() -> FlowApplication:
    """构造装配与条件匹配节点流程应用。"""

    return FlowApplication(
        application_id="match-case-assembly-app",
        display_name="Match Case Assembly App",
        template_ref=FlowTemplateReference(
            template_id="match-case-assembly-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="applicant_score",
                direction="input",
                template_port_id="applicant_score",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="applicant_state",
                direction="input",
                template_port_id="applicant_state",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="high_result",
                direction="input",
                template_port_id="high_result",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="medium_result",
                direction="input",
                template_port_id="medium_result",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="active_result",
                direction="input",
                template_port_id="active_result",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="default_result",
                direction="input",
                template_port_id="default_result",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="reduce_item_1",
                direction="input",
                template_port_id="reduce_item_1",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="reduce_item_2",
                direction="input",
                template_port_id="reduce_item_2",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="reduce_item_3",
                direction="input",
                template_port_id="reduce_item_3",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="matched_value",
                direction="output",
                template_port_id="matched_value",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="matched_flag",
                direction="output",
                template_port_id="matched_flag",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="matched_case_index",
                direction="output",
                template_port_id="matched_case_index",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="reduced_sum",
                direction="output",
                template_port_id="reduced_sum",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )