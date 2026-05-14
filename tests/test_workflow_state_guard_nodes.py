"""workflow 默认值与状态清理节点测试。"""

from __future__ import annotations

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


def test_preview_run_state_guard_nodes_support_exists_fallback_and_delete(tmp_path) -> None:
    """验证存在性判断、默认值回退与变量删除节点可以组成状态清理链。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_state_guard_application(),
            template=_build_state_guard_template(),
            input_bindings={
                "nullable_value": {"value": None},
                "fallback_value": {"value": "fallback-text"},
                "stored_value": {"value": {"step": 1}},
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert preview_run.outputs["exists_before_delete"]["value"] is True
    assert preview_run.outputs["coalesced_value"]["value"] == "fallback-text"
    assert preview_run.outputs["deleted_flag"]["value"] is True
    assert preview_run.outputs["deleted_value"]["value"] == {"step": 1}
    assert preview_run.outputs["exists_after_delete"]["value"] is False


def _build_state_guard_template() -> WorkflowGraphTemplate:
    """构造默认值与状态清理节点模板。"""

    return WorkflowGraphTemplate(
        template_id="state-guard-template",
        template_version="1.0.0",
        display_name="State Guard Template",
        nodes=(
            WorkflowGraphNode(
                node_id="set_value",
                node_type_id="core.logic.variable.set",
                parameters={"name": "temp_value"},
            ),
            WorkflowGraphNode(node_id="exists_before_delete", node_type_id="core.logic.value-exists"),
            WorkflowGraphNode(node_id="coalesce_value", node_type_id="core.logic.coalesce"),
            WorkflowGraphNode(
                node_id="delete_value",
                node_type_id="core.logic.variable.delete",
                parameters={"name": "temp_value"},
            ),
            WorkflowGraphNode(
                node_id="get_after_delete",
                node_type_id="core.logic.variable.get",
                parameters={"name": "temp_value", "default_value": None},
            ),
            WorkflowGraphNode(node_id="exists_after_delete", node_type_id="core.logic.value-exists"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="set-to-exists-before",
                source_node_id="set_value",
                source_port="value",
                target_node_id="exists_before_delete",
                target_port="value",
            ),
            WorkflowGraphEdge(
                edge_id="get-after-delete-to-exists-after",
                source_node_id="get_after_delete",
                source_port="value",
                target_node_id="exists_after_delete",
                target_port="value",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="nullable_value",
                display_name="Nullable Value",
                payload_type_id="value.v1",
                target_node_id="coalesce_value",
                target_port="primary",
            ),
            WorkflowGraphInput(
                input_id="fallback_value",
                display_name="Fallback Value",
                payload_type_id="value.v1",
                target_node_id="coalesce_value",
                target_port="fallback",
            ),
            WorkflowGraphInput(
                input_id="stored_value",
                display_name="Stored Value",
                payload_type_id="value.v1",
                target_node_id="set_value",
                target_port="value",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="exists_before_delete",
                display_name="Exists Before Delete",
                payload_type_id="boolean.v1",
                source_node_id="exists_before_delete",
                source_port="result",
            ),
            WorkflowGraphOutput(
                output_id="coalesced_value",
                display_name="Coalesced Value",
                payload_type_id="value.v1",
                source_node_id="coalesce_value",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="deleted_flag",
                display_name="Deleted Flag",
                payload_type_id="boolean.v1",
                source_node_id="delete_value",
                source_port="existed",
            ),
            WorkflowGraphOutput(
                output_id="deleted_value",
                display_name="Deleted Value",
                payload_type_id="value.v1",
                source_node_id="delete_value",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="exists_after_delete",
                display_name="Exists After Delete",
                payload_type_id="boolean.v1",
                source_node_id="exists_after_delete",
                source_port="result",
            ),
        ),
    )


def _build_state_guard_application() -> FlowApplication:
    """构造默认值与状态清理节点流程应用。"""

    return FlowApplication(
        application_id="state-guard-app",
        display_name="State Guard App",
        template_ref=FlowTemplateReference(
            template_id="state-guard-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="nullable_value",
                direction="input",
                template_port_id="nullable_value",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="fallback_value",
                direction="input",
                template_port_id="fallback_value",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="stored_value",
                direction="input",
                template_port_id="stored_value",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="exists_before_delete",
                direction="output",
                template_port_id="exists_before_delete",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="coalesced_value",
                direction="output",
                template_port_id="coalesced_value",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="deleted_flag",
                direction="output",
                template_port_id="deleted_flag",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="deleted_value",
                direction="output",
                template_port_id="deleted_value",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="exists_after_delete",
                direction="output",
                template_port_id="exists_after_delete",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )