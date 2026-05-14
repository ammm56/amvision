"""workflow 集合重排与聚合节点测试。"""

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


def test_preview_run_collection_reorder_nodes_support_sort_group_and_unique(tmp_path: Path) -> None:
    """验证 list-sort、list-group-by 与 list-unique 可以组成集合重排和聚合链。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_collection_reorder_application(),
            template=_build_collection_reorder_template(),
            input_bindings={
                "users": {
                    "value": [
                        {"name": "A", "status": "queued", "department": "Sales", "score": 88},
                        {"name": "B", "status": "running", "department": "Sales", "score": 64},
                        {"name": "C", "status": "queued", "department": "R&D", "score": 92},
                        {"name": "D", "status": "done", "department": "Ops", "score": 81},
                        {"name": "E", "status": "running", "department": "Ops", "score": 70},
                    ]
                },
                "users_for_group": {
                    "value": [
                        {"name": "A", "status": "queued", "department": "Sales", "score": 88},
                        {"name": "B", "status": "running", "department": "Sales", "score": 64},
                        {"name": "C", "status": "queued", "department": "R&D", "score": 92},
                        {"name": "D", "status": "done", "department": "Ops", "score": 81},
                        {"name": "E", "status": "running", "department": "Ops", "score": 70},
                    ]
                },
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert preview_run.outputs["sorted_names"]["value"] == ["C", "A", "D", "E", "B"]
    assert preview_run.outputs["group_keys"]["value"] == ["queued", "running", "done"]
    assert preview_run.outputs["group_count"]["value"] == 3
    assert preview_run.outputs["grouped_users"]["value"] == {
        "queued": [
            {"name": "A", "status": "queued", "department": "Sales", "score": 88},
            {"name": "C", "status": "queued", "department": "R&D", "score": 92},
        ],
        "running": [
            {"name": "B", "status": "running", "department": "Sales", "score": 64},
            {"name": "E", "status": "running", "department": "Ops", "score": 70},
        ],
        "done": [
            {"name": "D", "status": "done", "department": "Ops", "score": 81},
        ],
    }
    assert preview_run.outputs["unique_departments"]["value"] == ["R&D", "Sales", "Ops"]
    assert preview_run.outputs["unique_department_count"]["value"] == 3


def _build_collection_reorder_template() -> WorkflowGraphTemplate:
    """构造集合重排与聚合节点最小组合模板。"""

    return WorkflowGraphTemplate(
        template_id="collection-reorder-template",
        template_version="1.0.0",
        display_name="Collection Reorder Template",
        nodes=(
            WorkflowGraphNode(
                node_id="sort_users",
                node_type_id="core.logic.list-sort",
                parameters={"path": "score", "descending": True},
            ),
            WorkflowGraphNode(
                node_id="map_sorted_names",
                node_type_id="core.logic.list-map",
                parameters={"path": "name"},
            ),
            WorkflowGraphNode(
                node_id="group_users",
                node_type_id="core.logic.list-group-by",
                parameters={"path": "status"},
            ),
            WorkflowGraphNode(
                node_id="map_departments",
                node_type_id="core.logic.list-map",
                parameters={"path": "department"},
            ),
            WorkflowGraphNode(
                node_id="unique_departments",
                node_type_id="core.logic.list-unique",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-sort-users-map-names",
                source_node_id="sort_users",
                source_port="value",
                target_node_id="map_sorted_names",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-sort-users-map-departments",
                source_node_id="sort_users",
                source_port="value",
                target_node_id="map_departments",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-map-departments-unique",
                source_node_id="map_departments",
                source_port="value",
                target_node_id="unique_departments",
                target_port="items",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="users",
                display_name="Users",
                payload_type_id="value.v1",
                target_node_id="sort_users",
                target_port="items",
            ),
            WorkflowGraphInput(
                input_id="users_for_group",
                display_name="Users For Group",
                payload_type_id="value.v1",
                target_node_id="group_users",
                target_port="items",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="sorted_names",
                display_name="Sorted Names",
                payload_type_id="value.v1",
                source_node_id="map_sorted_names",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="grouped_users",
                display_name="Grouped Users",
                payload_type_id="value.v1",
                source_node_id="group_users",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="group_keys",
                display_name="Group Keys",
                payload_type_id="value.v1",
                source_node_id="group_users",
                source_port="keys",
            ),
            WorkflowGraphOutput(
                output_id="group_count",
                display_name="Group Count",
                payload_type_id="value.v1",
                source_node_id="group_users",
                source_port="count",
            ),
            WorkflowGraphOutput(
                output_id="unique_departments",
                display_name="Unique Departments",
                payload_type_id="value.v1",
                source_node_id="unique_departments",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="unique_department_count",
                display_name="Unique Department Count",
                payload_type_id="value.v1",
                source_node_id="unique_departments",
                source_port="count",
            ),
        ),
    )


def _build_collection_reorder_application() -> FlowApplication:
    """构造集合重排与聚合节点流程应用。"""

    return FlowApplication(
        application_id="collection-reorder-app",
        display_name="Collection Reorder App",
        template_ref=FlowTemplateReference(
            template_id="collection-reorder-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="users",
                direction="input",
                template_port_id="users",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="users_for_group",
                direction="input",
                template_port_id="users_for_group",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="sorted_names",
                direction="output",
                template_port_id="sorted_names",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="grouped_users",
                direction="output",
                template_port_id="grouped_users",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="group_keys",
                direction="output",
                template_port_id="group_keys",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="group_count",
                direction="output",
                template_port_id="group_count",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="unique_departments",
                direction="output",
                template_port_id="unique_departments",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="unique_department_count",
                direction="output",
                template_port_id="unique_department_count",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )