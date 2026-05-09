"""workflow 布尔与集合基础节点测试。"""

from __future__ import annotations

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


def test_preview_run_boolean_and_collection_nodes_support_basic_composition(tmp_path) -> None:
    """验证 boolean and/or/not 与 list-append 节点可以组成基础编排链。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_boolean_collection_application(),
            template=_build_boolean_collection_template(),
            input_bindings={
                "source_items": {"value": ["alpha"]},
                "new_item": {"value": "beta"},
                "flag_true": {"value": True},
                "flag_false": {"value": False},
                "flag_true_or": {"value": True},
                "flag_false_or": {"value": False},
                "flag_false_not": {"value": False},
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert preview_run.outputs["appended_items"]["value"] == ["alpha", "beta"]
    assert preview_run.outputs["and_result"]["value"] is False
    assert preview_run.outputs["or_result"]["value"] is True
    assert preview_run.outputs["not_result"]["value"] is True


def _build_boolean_collection_template() -> WorkflowGraphTemplate:
    """构造布尔与集合基础节点模板。"""

    return WorkflowGraphTemplate(
        template_id="boolean-collection-template",
        template_version="1.0.0",
        display_name="Boolean Collection Template",
        nodes=(
            WorkflowGraphNode(node_id="append_item", node_type_id="core.logic.list-append"),
            WorkflowGraphNode(node_id="boolean_and", node_type_id="core.logic.boolean-and"),
            WorkflowGraphNode(node_id="boolean_or", node_type_id="core.logic.boolean-or"),
            WorkflowGraphNode(node_id="boolean_not", node_type_id="core.logic.boolean-not"),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_items",
                display_name="Source Items",
                payload_type_id="value.v1",
                target_node_id="append_item",
                target_port="items",
            ),
            WorkflowGraphInput(
                input_id="new_item",
                display_name="New Item",
                payload_type_id="value.v1",
                target_node_id="append_item",
                target_port="item",
            ),
            WorkflowGraphInput(
                input_id="flag_true",
                display_name="Flag True",
                payload_type_id="boolean.v1",
                target_node_id="boolean_and",
                target_port="left",
            ),
            WorkflowGraphInput(
                input_id="flag_false",
                display_name="Flag False",
                payload_type_id="boolean.v1",
                target_node_id="boolean_and",
                target_port="right",
            ),
            WorkflowGraphInput(
                input_id="flag_true_or",
                display_name="Flag True Or",
                payload_type_id="boolean.v1",
                target_node_id="boolean_or",
                target_port="left",
                metadata={"alias_of": "flag_true"},
            ),
            WorkflowGraphInput(
                input_id="flag_false_or",
                display_name="Flag False Or",
                payload_type_id="boolean.v1",
                target_node_id="boolean_or",
                target_port="right",
                metadata={"alias_of": "flag_false"},
            ),
            WorkflowGraphInput(
                input_id="flag_false_not",
                display_name="Flag False Not",
                payload_type_id="boolean.v1",
                target_node_id="boolean_not",
                target_port="condition",
                metadata={"alias_of": "flag_false"},
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="appended_items",
                display_name="Appended Items",
                payload_type_id="value.v1",
                source_node_id="append_item",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="and_result",
                display_name="And Result",
                payload_type_id="boolean.v1",
                source_node_id="boolean_and",
                source_port="result",
            ),
            WorkflowGraphOutput(
                output_id="or_result",
                display_name="Or Result",
                payload_type_id="boolean.v1",
                source_node_id="boolean_or",
                source_port="result",
            ),
            WorkflowGraphOutput(
                output_id="not_result",
                display_name="Not Result",
                payload_type_id="boolean.v1",
                source_node_id="boolean_not",
                source_port="result",
            ),
        ),
    )


def _build_boolean_collection_application() -> FlowApplication:
    """构造布尔与集合基础节点流程应用。"""

    return FlowApplication(
        application_id="boolean-collection-app",
        display_name="Boolean Collection App",
        template_ref=FlowTemplateReference(
            template_id="boolean-collection-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="source_items",
                direction="input",
                template_port_id="source_items",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="new_item",
                direction="input",
                template_port_id="new_item",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="flag_true",
                direction="input",
                template_port_id="flag_true",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="flag_false",
                direction="input",
                template_port_id="flag_false",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="flag_true_or",
                direction="input",
                template_port_id="flag_true_or",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="flag_false_or",
                direction="input",
                template_port_id="flag_false_or",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="flag_false_not",
                direction="input",
                template_port_id="flag_false_not",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="appended_items",
                direction="output",
                template_port_id="appended_items",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="and_result",
                direction="output",
                template_port_id="and_result",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="or_result",
                direction="output",
                template_port_id="or_result",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="not_result",
                direction="output",
                template_port_id="not_result",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "boolean.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )