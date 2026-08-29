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
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)


def test_template_input_value_and_object_nodes_passthrough_payloads(
    tmp_path: Path,
) -> None:
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
    executor = WorkflowGraphExecutor(
        registry=runtime_registry_loader.get_runtime_registry()
    )
    template = WorkflowGraphTemplate(
        template_id="template-input-value-object-template",
        template_version="1.0.0",
        display_name="Template Input Value And Object Template",
        nodes=(
            WorkflowGraphNode(
                node_id="value_input", node_type_id="core.io.template-input.value"
            ),
            WorkflowGraphNode(
                node_id="object_input", node_type_id="core.io.template-input.object"
            ),
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
            "request_object": {
                "value": {"project_id": "project-1", "dataset_id": "dataset-1"}
            },
        },
    )

    assert execution_result.outputs["value_output"] == {"value": "queued"}
    assert execution_result.outputs["object_output"] == {
        "value": {"project_id": "project-1", "dataset_id": "dataset-1"}
    }


def test_text_and_file_nodes_preserve_explicit_payload_boundaries(
    tmp_path: Path,
) -> None:
    """验证文本转换、文件引用透传和有序多文件取项不包含隐藏读取。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(
        registry=runtime_registry_loader.get_runtime_registry()
    )
    file_ref = {
        "transport_kind": "storage",
        "storage_ref": "object-store",
        "object_key": "projects/project-1/files/example.json",
        "file_name": "example.json",
        "media_type": "application/json",
        "content_length": 2,
        "checksum_algorithm": "sha256",
        "checksum": "0" * 64,
        "immutable_version": f"sha256:{'0' * 64}",
    }
    template = WorkflowGraphTemplate(
        template_id="text-file-boundary-template",
        template_version="1.0.0",
        display_name="Text File Boundary Template",
        nodes=(
            WorkflowGraphNode(
                node_id="text_input", node_type_id="core.io.template-input.text"
            ),
            WorkflowGraphNode(
                node_id="text_to_value", node_type_id="core.logic.text-to-value"
            ),
            WorkflowGraphNode(
                node_id="files_input", node_type_id="core.io.template-input.files"
            ),
            WorkflowGraphNode(
                node_id="file_item",
                node_type_id="core.logic.file-refs-get-item",
                parameters={"index": 1},
            ),
        ),
        edges=(
            {
                "edge_id": "text-edge",
                "source_node_id": "text_input",
                "source_port": "text",
                "target_node_id": "text_to_value",
                "target_port": "text",
            },
            {
                "edge_id": "files-edge",
                "source_node_id": "files_input",
                "source_port": "files",
                "target_node_id": "file_item",
                "target_port": "files",
            },
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_text",
                display_name="Request Text",
                payload_type_id="text.v1",
                target_node_id="text_input",
                target_port="payload",
            ),
            WorkflowGraphInput(
                input_id="request_files",
                display_name="Request Files",
                payload_type_id="file-refs.v1",
                target_node_id="files_input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="text_value",
                display_name="Text Value",
                payload_type_id="value.v1",
                source_node_id="text_to_value",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="selected_file",
                display_name="Selected File",
                payload_type_id="file-ref.v1",
                source_node_id="file_item",
                source_port="file",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_text": {
                "text": "hello",
                "media_type": "text/plain",
                "charset": "utf-8",
            },
            "request_files": {"items": [file_ref, file_ref], "count": 2},
        },
    )

    assert execution_result.outputs["text_value"] == {"value": "hello"}
    assert execution_result.outputs["selected_file"] == file_ref


def test_unconnected_optional_template_input_is_not_executed(tmp_path: Path) -> None:
    """验证未连接的 optional App Entry 不会变成隐藏的必填执行步骤。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(
        registry=runtime_registry_loader.get_runtime_registry()
    )
    template = WorkflowGraphTemplate(
        template_id="optional-template-input-template",
        template_version="1.0.0",
        display_name="Optional Template Input Template",
        nodes=(
            WorkflowGraphNode(
                node_id="value_input", node_type_id="core.io.template-input.value"
            ),
            WorkflowGraphNode(
                node_id="unused_text_input",
                node_type_id="core.io.template-input.text",
            ),
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
                input_id="request_text",
                display_name="Request Text",
                payload_type_id="text.v1",
                target_node_id="unused_text_input",
                target_port="payload",
                required=False,
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
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={"request_value": {"value": "ready"}},
    )

    assert execution_result.outputs == {"value_output": {"value": "ready"}}
    assert [record.node_id for record in execution_result.node_records] == [
        "value_input"
    ]
