"""workflow 对象字段变换节点测试。"""

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


def test_preview_run_object_field_nodes_support_pick_remove_and_update(tmp_path: Path) -> None:
    """验证 object-pick、object-remove 与 object-update 可以组成对象字段裁剪和改写链。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_object_field_application(),
            template=_build_object_field_template(),
            input_bindings={
                "source_object": {
                    "value": {
                        "status": "draft",
                        "meta": {"owner": "ops", "temp": "remove-me"},
                        "stats": {"passed": 8, "failed": 2},
                        "debug": {"trace": "remove"},
                    }
                },
                "source_object_for_remove": {
                    "value": {
                        "status": "draft",
                        "meta": {"owner": "ops", "temp": "remove-me"},
                        "stats": {"passed": 8, "failed": 2},
                        "debug": {"trace": "remove"},
                    }
                },
                "new_status": {"value": "approved"},
                "reviewer": {"value": "qa-team"},
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert preview_run.outputs["picked_object"]["value"] == {
        "status": "draft",
        "meta": {"owner": "ops"},
        "stats": {"passed": 8},
    }
    assert preview_run.outputs["clean_object"]["value"] == {
        "status": "draft",
        "meta": {"owner": "ops"},
        "stats": {"passed": 8, "failed": 2},
    }
    assert preview_run.outputs["updated_object"]["value"] == {
        "status": "approved",
        "meta": {"owner": "ops", "reviewer": "qa-team", "source": "workflow"},
        "stats": {"passed": 8, "failed": 0},
    }


def _build_object_field_template() -> WorkflowGraphTemplate:
    """构造对象字段变换节点最小组合模板。"""

    return WorkflowGraphTemplate(
        template_id="object-field-template",
        template_version="1.0.0",
        display_name="Object Field Template",
        nodes=(
            WorkflowGraphNode(
                node_id="pick_object",
                node_type_id="core.logic.object-pick",
                parameters={"paths": ["status", "meta.owner", "stats.passed"]},
            ),
            WorkflowGraphNode(
                node_id="remove_object",
                node_type_id="core.logic.object-remove",
                parameters={"paths": ["debug", "meta.temp"]},
            ),
            WorkflowGraphNode(
                node_id="update_object",
                node_type_id="core.logic.object-update",
                parameters={
                    "paths": ["status", "meta.reviewer"],
                    "updates": {
                        "meta.source": "workflow",
                        "stats.failed": 0,
                    },
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-remove-object-update-object",
                source_node_id="remove_object",
                source_port="value",
                target_node_id="update_object",
                target_port="object",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_object",
                display_name="Source Object",
                payload_type_id="value.v1",
                target_node_id="pick_object",
                target_port="object",
            ),
            WorkflowGraphInput(
                input_id="source_object_for_remove",
                display_name="Source Object For Remove",
                payload_type_id="value.v1",
                target_node_id="remove_object",
                target_port="object",
            ),
            WorkflowGraphInput(
                input_id="new_status",
                display_name="New Status",
                payload_type_id="value.v1",
                target_node_id="update_object",
                target_port="values",
            ),
            WorkflowGraphInput(
                input_id="reviewer",
                display_name="Reviewer",
                payload_type_id="value.v1",
                target_node_id="update_object",
                target_port="values",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="picked_object",
                display_name="Picked Object",
                payload_type_id="value.v1",
                source_node_id="pick_object",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="clean_object",
                display_name="Clean Object",
                payload_type_id="value.v1",
                source_node_id="remove_object",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="updated_object",
                display_name="Updated Object",
                payload_type_id="value.v1",
                source_node_id="update_object",
                source_port="value",
            ),
        ),
    )


def _build_object_field_application() -> FlowApplication:
    """构造对象字段变换节点流程应用。"""

    return FlowApplication(
        application_id="object-field-app",
        display_name="Object Field App",
        template_ref=FlowTemplateReference(
            template_id="object-field-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="source_object",
                direction="input",
                template_port_id="source_object",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="source_object_for_remove",
                direction="input",
                template_port_id="source_object_for_remove",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="new_status",
                direction="input",
                template_port_id="new_status",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="reviewer",
                direction="input",
                template_port_id="reviewer",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="picked_object",
                direction="output",
                template_port_id="picked_object",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="clean_object",
                direction="output",
                template_port_id="clean_object",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="updated_object",
                direction="output",
                template_port_id="updated_object",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )