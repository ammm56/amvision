"""workflow 集合与对象变换节点测试。"""

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


def test_preview_run_collection_transform_nodes_support_map_filter_and_merge(tmp_path: Path) -> None:
    """验证 list-map、list-filter 与 object-merge 可以组成集合和对象变换链。"""

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_collection_transform_application(),
            template=_build_collection_transform_template(),
            input_bindings={
                "users": {
                    "value": [
                        {"name": "A", "active": False, "tags": ["vip"], "score": 88},
                        {"name": "B", "active": True, "tags": ["trial"], "score": 64},
                        {"name": "C", "active": True, "tags": ["vip", "priority"], "score": 92},
                        {"name": "D", "active": True, "tags": ["vip"], "score": 81},
                    ]
                },
                "override_status": {"value": "approved"},
                "owner": {"value": "qa"},
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert preview_run.outputs["filtered_count"]["value"] == 2
    assert preview_run.outputs["mapped_names"]["value"] == ["C", "D"]
    assert preview_run.outputs["merged_summary"]["value"] == {
        "status": "approved",
        "names": ["C", "D"],
        "score_total": 173,
        "owner": "qa",
    }


def _build_collection_transform_template() -> WorkflowGraphTemplate:
    """构造集合与对象变换节点最小组合模板。"""

    return WorkflowGraphTemplate(
        template_id="collection-transform-template",
        template_version="1.0.0",
        display_name="Collection Transform Template",
        nodes=(
            WorkflowGraphNode(
                node_id="filter_users",
                node_type_id="core.logic.list-filter",
                parameters={
                    "condition": {
                        "operator": "and",
                        "conditions": [
                            {"operator": "eq", "path": "active", "right": True},
                            {"operator": "contains", "path": "tags", "right": "vip"},
                        ],
                    }
                },
            ),
            WorkflowGraphNode(
                node_id="map_names",
                node_type_id="core.logic.list-map",
                parameters={"path": "name"},
            ),
            WorkflowGraphNode(
                node_id="map_scores",
                node_type_id="core.logic.list-map",
                parameters={"path": "score"},
            ),
            WorkflowGraphNode(
                node_id="reduce_scores",
                node_type_id="core.logic.reduce",
                parameters={"operator": "sum"},
            ),
            WorkflowGraphNode(
                node_id="build_summary",
                node_type_id="core.logic.object-create",
                parameters={"keys": ["names", "score_total"], "fields": {"status": "reviewed"}},
            ),
            WorkflowGraphNode(
                node_id="build_override",
                node_type_id="core.logic.object-create",
                parameters={"keys": ["status", "owner"]},
            ),
            WorkflowGraphNode(node_id="merge_summary", node_type_id="core.logic.object-merge"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-filter-users-map-names",
                source_node_id="filter_users",
                source_port="value",
                target_node_id="map_names",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-filter-users-map-scores",
                source_node_id="filter_users",
                source_port="value",
                target_node_id="map_scores",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-map-scores-reduce",
                source_node_id="map_scores",
                source_port="value",
                target_node_id="reduce_scores",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-map-names-build-summary",
                source_node_id="map_names",
                source_port="value",
                target_node_id="build_summary",
                target_port="values",
            ),
            WorkflowGraphEdge(
                edge_id="edge-reduce-scores-build-summary",
                source_node_id="reduce_scores",
                source_port="value",
                target_node_id="build_summary",
                target_port="values",
            ),
            WorkflowGraphEdge(
                edge_id="edge-build-summary-merge-summary",
                source_node_id="build_summary",
                source_port="value",
                target_node_id="merge_summary",
                target_port="objects",
            ),
            WorkflowGraphEdge(
                edge_id="edge-build-override-merge-summary",
                source_node_id="build_override",
                source_port="value",
                target_node_id="merge_summary",
                target_port="objects",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="users",
                display_name="Users",
                payload_type_id="value.v1",
                target_node_id="filter_users",
                target_port="items",
            ),
            WorkflowGraphInput(
                input_id="override_status",
                display_name="Override Status",
                payload_type_id="value.v1",
                target_node_id="build_override",
                target_port="values",
            ),
            WorkflowGraphInput(
                input_id="owner",
                display_name="Owner",
                payload_type_id="value.v1",
                target_node_id="build_override",
                target_port="values",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="filtered_count",
                display_name="Filtered Count",
                payload_type_id="value.v1",
                source_node_id="filter_users",
                source_port="count",
            ),
            WorkflowGraphOutput(
                output_id="mapped_names",
                display_name="Mapped Names",
                payload_type_id="value.v1",
                source_node_id="map_names",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="merged_summary",
                display_name="Merged Summary",
                payload_type_id="value.v1",
                source_node_id="merge_summary",
                source_port="value",
            ),
        ),
    )


def _build_collection_transform_application() -> FlowApplication:
    """构造集合与对象变换节点流程应用。"""

    return FlowApplication(
        application_id="collection-transform-app",
        display_name="Collection Transform App",
        template_ref=FlowTemplateReference(
            template_id="collection-transform-template",
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
                binding_id="override_status",
                direction="input",
                template_port_id="override_status",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="owner",
                direction="input",
                template_port_id="owner",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="filtered_count",
                direction="output",
                template_port_id="filtered_count",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="mapped_names",
                direction="output",
                template_port_id="mapped_names",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="merged_summary",
                direction="output",
                template_port_id="merged_summary",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )