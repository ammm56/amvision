"""统一节点目录注册表。"""

from __future__ import annotations

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.contracts.workflows.workflow_graph import NodeDefinition, WorkflowPayloadContract
from backend.nodes.core_catalog import (
    get_core_workflow_node_definitions,
    get_core_workflow_payload_contracts,
)
from backend.nodes.node_pack_loader import NodeCatalogSnapshot, NodePackLoader


class NodeCatalogRegistry:
    """把内建 core nodes 与自定义节点包合并为统一目录。"""

    def __init__(self, *, node_pack_loader: NodePackLoader | None = None) -> None:
        """初始化统一节点目录注册表。

        参数：
        - node_pack_loader：可选的节点包加载器；提供时合并自定义节点目录。
        """

        self.node_pack_loader = node_pack_loader

    def get_catalog_snapshot(self) -> NodeCatalogSnapshot:
        """返回合并内建 core nodes 与自定义节点后的目录快照。"""

        custom_node_catalog = (
            self.node_pack_loader.get_catalog_snapshot()
            if self.node_pack_loader is not None
            else NodeCatalogSnapshot()
        )
        return NodeCatalogSnapshot(
            node_pack_manifests=custom_node_catalog.node_pack_manifests,
            payload_contracts=get_core_workflow_payload_contracts() + custom_node_catalog.payload_contracts,
            node_definitions=get_core_workflow_node_definitions() + custom_node_catalog.node_definitions,
        )

    def get_node_pack_manifests(self) -> tuple[NodePackManifest, ...]:
        """返回已发现的节点包 manifest 列表。"""

        return self.get_catalog_snapshot().node_pack_manifests

    def get_workflow_payload_contracts(self) -> tuple[WorkflowPayloadContract, ...]:
        """返回统一目录中的 workflow payload contract 列表。"""

        return self.get_catalog_snapshot().payload_contracts

    def get_workflow_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回统一目录中的 workflow 节点定义列表。"""

        return self.get_catalog_snapshot().node_definitions
