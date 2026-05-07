"""节点包加载器抽象定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.contracts.workflows.workflow_graph import NodeDefinition, WorkflowPayloadContract


@dataclass(frozen=True)
class NodeCatalogSnapshot:
    """描述当前节点系统暴露的节点目录快照。

    字段：
    - node_pack_manifests：已发现的节点包 manifest 列表。
    - payload_contracts：已注册的 payload contract 列表。
    - node_definitions：已注册的 NodeDefinition 列表。
    """

    node_pack_manifests: tuple[NodePackManifest, ...] = ()
    payload_contracts: tuple[WorkflowPayloadContract, ...] = ()
    node_definitions: tuple[NodeDefinition, ...] = ()


@runtime_checkable
class NodePackLoader(Protocol):
    """描述 backend 当前使用的节点包加载器。"""

    def refresh(self) -> None:
        """刷新当前节点包目录缓存。"""

        ...

    def get_catalog_snapshot(self) -> NodeCatalogSnapshot:
        """返回当前节点目录快照。"""

        ...

    def get_node_pack_manifests(self) -> tuple[NodePackManifest, ...]:
        """返回已发现的节点包 manifest 列表。"""

        ...

    def get_workflow_payload_contracts(self) -> tuple[WorkflowPayloadContract, ...]:
        """返回已注册的 workflow payload contract 列表。"""

        ...

    def get_workflow_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回已注册的 workflow 节点定义列表。"""

        ...

    def get_runtime_module_search_paths(self) -> tuple[str, ...]:
        """返回导入 node pack entrypoint 时需要加入的模块搜索路径。"""

        ...
