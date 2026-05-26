"""workflow 变量与列表基础节点测试。"""

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


def test_preview_run_variable_and_list_nodes_support_shared_state_and_collection_reads(tmp_path: Path) -> None:
    """验证 variable.set/get、list-item-get 和 list-length 可以组成最小状态与集合读取链。

    参数：
    - tmp_path：pytest 提供的临时目录。
    """

    service, _, _ = _build_runtime_service(tmp_path)
    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_state_nodes_application(),
            template=_build_state_nodes_template(),
            input_bindings={
                "source_items": {"value": ["alpha", "beta", "gamma"]},
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert preview_run.outputs["stored_items"]["value"] == ["alpha", "beta", "gamma"]
    assert preview_run.outputs["last_item"]["value"] == "gamma"
    assert preview_run.outputs["items_length"]["value"] == 3
    assert preview_run.outputs["missing_with_default"]["value"] == "fallback-value"


def _build_state_nodes_template() -> WorkflowGraphTemplate:
    """构造变量与列表基础节点模板。

    返回：
    - WorkflowGraphTemplate：测试使用的最小图模板。
    """

    return WorkflowGraphTemplate(
        template_id="state-nodes-template",
        template_version="1.0.0",
        display_name="State Nodes Template",
        nodes=(
            WorkflowGraphNode(
                node_id="set_items",
                node_type_id="core.logic.variable.set",
                parameters={"name": "items"},
            ),
            WorkflowGraphNode(
                node_id="get_items",
                node_type_id="core.logic.variable.get",
                parameters={"name": "items"},
            ),
            WorkflowGraphNode(
                node_id="get_last_item",
                node_type_id="core.logic.list-item-get",
                parameters={"index": -1},
            ),
            WorkflowGraphNode(
                node_id="get_items_length",
                node_type_id="core.logic.list-length",
            ),
            WorkflowGraphNode(
                node_id="get_missing_default",
                node_type_id="core.logic.variable.get",
                parameters={"name": "missing-key", "default_value": "fallback-value"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-set-get-items",
                source_node_id="set_items",
                source_port="value",
                target_node_id="get_items",
                target_port="default",
            ),
            WorkflowGraphEdge(
                edge_id="edge-items-last-item",
                source_node_id="get_items",
                source_port="value",
                target_node_id="get_last_item",
                target_port="items",
            ),
            WorkflowGraphEdge(
                edge_id="edge-items-length",
                source_node_id="get_items",
                source_port="value",
                target_node_id="get_items_length",
                target_port="items",
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
                output_id="stored_items",
                display_name="Stored Items",
                payload_type_id="value.v1",
                source_node_id="get_items",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="last_item",
                display_name="Last Item",
                payload_type_id="value.v1",
                source_node_id="get_last_item",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="items_length",
                display_name="Items Length",
                payload_type_id="value.v1",
                source_node_id="get_items_length",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="missing_with_default",
                display_name="Missing With Default",
                payload_type_id="value.v1",
                source_node_id="get_missing_default",
                source_port="value",
            ),
        ),
    )


def _build_state_nodes_application() -> FlowApplication:
    """构造变量与列表基础节点流程应用。

    返回：
    - FlowApplication：测试使用的流程应用。
    """

    return FlowApplication(
        application_id="state-nodes-app",
        display_name="State Nodes App",
        template_ref=FlowTemplateReference(
            template_id="state-nodes-template",
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
                binding_id="stored_items",
                direction="output",
                template_port_id="stored_items",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="last_item",
                direction="output",
                template_port_id="last_item",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="items_length",
                direction="output",
                template_port_id="items_length",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="missing_with_default",
                direction="output",
                template_port_id="missing_with_default",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "value.v1"},
                metadata={},
            ),
        ),
        runtime_mode="python-json-workflow",
        metadata={},
    )