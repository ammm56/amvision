"""Workflow 多文件引用处理节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
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


def _build_executor(
    tmp_path: Path,
) -> tuple[WorkflowGraphExecutor, NodeCatalogRegistry]:
    """构建隔离 Core Node 执行器。"""

    loader = LocalNodePackLoader(tmp_path / "custom_nodes")
    loader.refresh()
    catalog = NodeCatalogRegistry(node_pack_loader=loader)
    runtime_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=catalog,
        node_pack_loader=loader,
    )
    runtime_loader.refresh()
    return (
        WorkflowGraphExecutor(registry=runtime_loader.get_runtime_registry()),
        catalog,
    )


def test_file_reference_nodes_publish_dynamic_index_and_metadata_list(
    tmp_path: Path,
) -> None:
    """验证动态索引和安全元数据列表均进入正式 Node Catalog。"""

    _, catalog = _build_executor(tmp_path)
    definitions = {
        item.node_type_id: item for item in catalog.get_workflow_node_definitions()
    }
    get_item = definitions["core.logic.file-refs-get-item"]
    assert [(port.name, port.required) for port in get_item.input_ports] == [
        ("files", True),
        ("index", False),
    ]
    assert [
        (binding.parameter_name, binding.input_port_name)
        for binding in get_item.parameter_input_bindings
    ] == [("index", "index")]

    metadata_list = definitions["core.io.file-refs-metadata-list"]
    assert [(port.name, port.payload_type_id) for port in metadata_list.input_ports] == [
        ("files", "file-refs.v1")
    ]
    assert [
        (port.name, port.payload_type_id) for port in metadata_list.output_ports
    ] == [("metadata", "value.v1")]


def test_request_files_preserves_order_and_supports_dynamic_index(
    tmp_path: Path,
) -> None:
    """验证多文件元数据顺序稳定且 index 可由 value.v1 覆盖。"""

    executor, _ = _build_executor(tmp_path)
    first = _build_file_ref("first.txt", "1" * 64)
    second = _build_file_ref("second.json", "2" * 64)
    template = WorkflowGraphTemplate(
        template_id="request-files-processing-template",
        template_version="1.0.0",
        display_name="Request Files Processing Template",
        nodes=(
            WorkflowGraphNode(
                node_id="files_input",
                node_type_id="core.io.template-input.files",
            ),
            WorkflowGraphNode(
                node_id="index",
                node_type_id="core.logic.number-value",
                parameters={"value": 1},
            ),
            WorkflowGraphNode(
                node_id="get_item",
                node_type_id="core.logic.file-refs-get-item",
                parameters={"index": 0},
            ),
            WorkflowGraphNode(
                node_id="metadata_list",
                node_type_id="core.io.file-refs-metadata-list",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="files-to-item",
                source_node_id="files_input",
                source_port="files",
                target_node_id="get_item",
                target_port="files",
            ),
            WorkflowGraphEdge(
                edge_id="index-to-item",
                source_node_id="index",
                source_port="value",
                target_node_id="get_item",
                target_port="index",
            ),
            WorkflowGraphEdge(
                edge_id="files-to-metadata",
                source_node_id="files_input",
                source_port="files",
                target_node_id="metadata_list",
                target_port="files",
            ),
        ),
        template_inputs=(
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
                output_id="selected",
                display_name="Selected",
                payload_type_id="file-ref.v1",
                source_node_id="get_item",
                source_port="file",
            ),
            WorkflowGraphOutput(
                output_id="metadata",
                display_name="Metadata",
                payload_type_id="value.v1",
                source_node_id="metadata_list",
                source_port="metadata",
            ),
        ),
    )

    result = executor.execute(
        template=template,
        input_values={"request_files": {"items": [first, second], "count": 2}},
    )

    assert result.outputs["selected"] == second
    metadata = result.outputs["metadata"]["value"]
    assert [item["file_name"] for item in metadata] == ["first.txt", "second.json"]


def _build_file_ref(file_name: str, checksum: str) -> dict[str, object]:
    """构造不包含文件字节和绝对路径的 file-ref.v1。"""

    return {
        "transport_kind": "storage",
        "storage_ref": "object-store",
        "object_key": f"projects/project-1/inputs/{file_name}",
        "file_name": file_name,
        "media_type": "application/json" if file_name.endswith(".json") else "text/plain",
        "content_length": 2,
        "checksum_algorithm": "sha256",
        "checksum": checksum,
        "immutable_version": f"sha256:{checksum}",
    }
