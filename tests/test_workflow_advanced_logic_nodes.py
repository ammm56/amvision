"""workflow 高阶逻辑节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.service.application.workflows.runtime_service import WorkflowPreviewRunCreateRequest
from tests.test_workflow_runtime_sanitization import _build_runtime_service


def test_preview_run_advanced_logic_nodes_support_switch_and_collection_reduction(tmp_path: Path) -> None:
    """验证 switch、any、all、reduce 节点可以组成多分支与集合归约链。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_advanced_logic_application(),
            template=_build_advanced_logic_template(),
            input_bindings={
                "switch_target": {"value": "medium"},
                "case_low": {"value": {"when": "low", "then": {"rank": 1}}},
                "case_medium": {"value": {"when": "medium", "then": {"rank": 2}}},
                "case_high": {"value": {"when": "high", "then": {"rank": 3}}},
                "switch_default": {"value": {"rank": 99}},
                "any_items": {"value": [0, "", "enabled"]},
                "all_items": {"value": [True, 1, "ok"]},
                "sum_items": {"value": [1, 2, 3, 4]},
                "join_items": {"value": ["A", "B", "C"]},
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert preview_run.outputs["selected_value"]["value"] == {"rank": 2}
    assert preview_run.outputs["switch_matched"]["value"] is True
    assert preview_run.outputs["any_result"]["value"] is True
    assert preview_run.outputs["all_result"]["value"] is True
    assert preview_run.outputs["sum_result"]["value"] == 10
    assert preview_run.outputs["join_result"]["value"] == "A / B / C"


def _build_advanced_logic_template() -> WorkflowGraphTemplate:
    """构造高阶逻辑节点最小组合模板。"""

    return WorkflowGraphTemplate(
        template_id="advanced-logic-template",
        template_version="1.0.0",
        display_name="Advanced Logic Template",
        nodes=(
            WorkflowGraphNode(node_id="switch_value", node_type_id="core.logic.switch"),
            WorkflowGraphNode(node_id="any_items", node_type_id="core.logic.any"),
            WorkflowGraphNode(node_id="all_items", node_type_id="core.logic.all"),
            WorkflowGraphNode(
                node_id="sum_items",
                node_type_id="core.logic.reduce",
                parameters={"operator": "sum"},
            ),
            WorkflowGraphNode(
                node_id="join_items",
                node_type_id="core.logic.reduce",
                parameters={"operator": "join", "separator": " / "},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="switch_target",
                display_name="Switch Target",
                payload_type_id="value.v1",
                target_node_id="switch_value",
                target_port="value",
            ),
            WorkflowGraphInput(
                input_id="case_low",
                display_name="Case Low",
                payload_type_id="value.v1",
                target_node_id="switch_value",
                target_port="cases",
            ),
            WorkflowGraphInput(
                input_id="case_medium",
                display_name="Case Medium",
                payload_type_id="value.v1",
                target_node_id="switch_value",
                target_port="cases",
            ),
            WorkflowGraphInput(
                input_id="case_high",
                display_name="Case High",
                payload_type_id="value.v1",
                target_node_id="switch_value",
                target_port="cases",
            ),
            WorkflowGraphInput(
                input_id="switch_default",
                display_name="Switch Default",
                payload_type_id="value.v1",
                target_node_id="switch_value",
                target_port="default",
            ),
            WorkflowGraphInput(
                input_id="any_items",
                display_name="Any Items",
                payload_type_id="value.v1",
                target_node_id="any_items",
                target_port="items",
            ),
            WorkflowGraphInput(
                input_id="all_items",
                display_name="All Items",
                payload_type_id="value.v1",
                target_node_id="all_items",
                target_port="items",
            ),
            WorkflowGraphInput(
                input_id="sum_items",
                display_name="Sum Items",
                payload_type_id="value.v1",
                target_node_id="sum_items",
                target_port="items",
            ),
            WorkflowGraphInput(
                input_id="join_items",
                display_name="Join Items",
                payload_type_id="value.v1",
                target_node_id="join_items",
                target_port="items",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="selected_value",
                display_name="Selected Value",
                payload_type_id="value.v1",
                source_node_id="switch_value",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="switch_matched",
                display_name="Switch Matched",
                payload_type_id="boolean.v1",
                source_node_id="switch_value",
                source_port="matched",
            ),
            WorkflowGraphOutput(
                output_id="any_result",
                display_name="Any Result",
                payload_type_id="boolean.v1",
                source_node_id="any_items",
                source_port="result",
            ),
            WorkflowGraphOutput(
                output_id="all_result",
                display_name="All Result",
                payload_type_id="boolean.v1",
                source_node_id="all_items",
                source_port="result",
            ),
            WorkflowGraphOutput(
                output_id="sum_result",
                display_name="Sum Result",
                payload_type_id="value.v1",
                source_node_id="sum_items",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="join_result",
                display_name="Join Result",
                payload_type_id="value.v1",
                source_node_id="join_items",
                source_port="value",
            ),
        ),
    )


def _build_advanced_logic_application() -> FlowApplication:
    """构造高阶逻辑节点流程应用。"""

    return FlowApplication(
        application_id="advanced-logic-app",
        display_name="Advanced Logic App",
        template_ref=FlowTemplateReference(
            template_id="advanced-logic-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="switch_target",
                direction="input",
                template_port_id="switch_target",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="case_low",
                direction="input",
                template_port_id="case_low",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="case_medium",
                direction="input",
                template_port_id="case_medium",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="case_high",
                direction="input",
                template_port_id="case_high",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="switch_default",
                direction="input",
                template_port_id="switch_default",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="any_items",
                direction="input",
                template_port_id="any_items",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="all_items",
                direction="input",
                template_port_id="all_items",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="sum_items",
                direction="input",
                template_port_id="sum_items",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="join_items",
                direction="input",
                template_port_id="join_items",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="selected_value",
                direction="output",
                template_port_id="selected_value",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="switch_matched",
                direction="output",
                template_port_id="switch_matched",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="any_result",
                direction="output",
                template_port_id="any_result",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="all_result",
                direction="output",
                template_port_id="all_result",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="sum_result",
                direction="output",
                template_port_id="sum_result",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="join_result",
                direction="output",
                template_port_id="join_result",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )