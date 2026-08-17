"""node pack staging 代码的当前进程注册验证。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    WorkflowPayloadContract,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.nodes.node_pack_loader import NodeCatalogSnapshot
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)


@dataclass(frozen=True)
class _StagedNodePackLoader:
    """只暴露一个 staging 节点包的最小只读 loader。"""

    staged_custom_nodes_root: Path
    active_custom_nodes_root: Path
    active_directory: str
    manifest: NodePackManifest
    payload_contracts: tuple[WorkflowPayloadContract, ...]
    node_definitions: tuple[NodeDefinition, ...]

    def refresh(self) -> None:
        """staging 快照已经校验且不可变，无需重新扫描。"""

    def get_catalog_snapshot(self) -> NodeCatalogSnapshot:
        """返回当前 staging 节点包目录快照。"""

        return NodeCatalogSnapshot(
            node_pack_manifests=(self.manifest,),
            payload_contracts=self.payload_contracts,
            node_definitions=self.node_definitions,
        )

    def get_node_pack_manifests(self) -> tuple[NodePackManifest, ...]:
        """返回 staging manifest。"""

        return (self.manifest,)

    def get_workflow_payload_contracts(self) -> tuple[WorkflowPayloadContract, ...]:
        """返回 staging payload 规则。"""

        return self.payload_contracts

    def get_workflow_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回 staging 节点定义。"""

        return self.node_definitions

    def get_runtime_module_search_paths(self) -> tuple[str, ...]:
        """优先从 staging 导入，并允许读取已激活的依赖包。"""

        search_paths = [str(self.staged_custom_nodes_root.parent)]
        active_search_path = str(self.active_custom_nodes_root.parent)
        if active_search_path not in search_paths:
            search_paths.append(active_search_path)
        return tuple(search_paths)

    def get_node_pack_runtime_module_prefix(
        self,
        node_pack_id: str,
        node_pack_version: str,
    ) -> str:
        """返回 staging 一级目录对应的 module 前缀。"""

        if (
            node_pack_id != self.manifest.node_pack_id
            or node_pack_version != self.manifest.version
        ):
            raise LookupError("staging loader 收到不匹配的 node pack 身份")
        return f"{self.staged_custom_nodes_root.name}.{self.active_directory}"


def validate_staged_node_pack_runtime(
    *,
    staged_custom_nodes_root: Path,
    active_custom_nodes_root: Path,
    active_directory: str,
    expected_node_pack_id: str,
    expected_version: str,
) -> tuple[str, ...]:
    """在当前服务进程导入 entrypoint 并验证全部可执行节点已注册。"""

    staged_root = staged_custom_nodes_root.resolve()
    package_dir = (staged_root / active_directory).resolve()
    validator = LocalNodePackLoader(staged_root)
    manifest, catalog = validator.validate_node_pack_directory(package_dir)
    if (
        manifest.node_pack_id != expected_node_pack_id
        or manifest.version != expected_version
    ):
        raise ValueError("staging manifest 身份在验证期间发生变化")
    staged_loader = _StagedNodePackLoader(
        staged_custom_nodes_root=staged_root,
        active_custom_nodes_root=active_custom_nodes_root.resolve(),
        active_directory=active_directory,
        manifest=manifest,
        payload_contracts=(catalog.payload_contracts if catalog is not None else ()),
        node_definitions=(catalog.node_definitions if catalog is not None else ()),
    )
    catalog_registry = NodeCatalogRegistry(node_pack_loader=staged_loader)
    runtime_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=catalog_registry,
        node_pack_loader=staged_loader,
        load_custom_node_handlers=True,
    )
    runtime_loader.refresh()
    return tuple(
        sorted(
            definition.node_type_id
            for definition in staged_loader.node_definitions
            if runtime_loader.get_runtime_registry().has_registered_handler(
                node_definition=definition
            )
        )
    )


__all__ = ["validate_staged_node_pack_runtime"]
