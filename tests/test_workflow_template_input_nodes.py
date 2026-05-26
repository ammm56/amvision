"""template input 节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.runtime_registry_loader import WorkflowNodeRuntimeRegistryLoader


def test_template_input_value_and_object_nodes_passthrough_payloads(tmp_path: Path) -> None:
    """验证 template-input.value 与 template-input.object 可以稳定透传绑定值。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="template-input-value-object-template",
        template_version="1.0.0",
        display_name="Template Input Value And Object Template",
        nodes=(
            WorkflowGraphNode(node_id="value_input", node_type_id="core.io.template-input.value"),
            WorkflowGraphNode(node_id="object_input", node_type_id="core.io.template-input.object"),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_value",
                display_name="Request Value",
                payload_type_id="value.v1",
                target_node_id="value_input",
                target_port="payload",
            ),
            WorkflowGraphInput(
                input_id="request_object",
                display_name="Request Object",
                payload_type_id="value.v1",
                target_node_id="object_input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="value_output",
                display_name="Value Output",
                payload_type_id="value.v1",
                source_node_id="value_input",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="object_output",
                display_name="Object Output",
                payload_type_id="value.v1",
                source_node_id="object_input",
                source_port="value",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_value": {"value": "queued"},
            "request_object": {"value": {"project_id": "project-1", "dataset_id": "dataset-1"}},
        },
    )

    assert execution_result.outputs["value_output"] == {"value": "queued"}
    assert execution_result.outputs["object_output"] == {
        "value": {"project_id": "project-1", "dataset_id": "dataset-1"}
    }