"""统一节点目录注册表。"""

from __future__ import annotations

from threading import RLock

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
        self._catalog_snapshot: NodeCatalogSnapshot | None = None
        self._catalog_snapshot_lock = RLock()

    def get_catalog_snapshot(self) -> NodeCatalogSnapshot:
        """返回合并内建 core nodes 与自定义节点后的目录快照。"""

        if self._catalog_snapshot is not None:
            return self._catalog_snapshot

        with self._catalog_snapshot_lock:
            if self._catalog_snapshot is None:
                self._catalog_snapshot = self._build_catalog_snapshot()
            return self._catalog_snapshot

    def invalidate_cache(self) -> None:
        """清空已合并的节点目录快照缓存。

        说明：
        - node pack reload、enable、disable 后必须调用该方法。
        - 业务请求只读取稳定快照，不重复扫描和合并节点目录。
        """

        with self._catalog_snapshot_lock:
            self._catalog_snapshot = None

    def refresh(self) -> None:
        """刷新下层 node pack loader 并清空合并目录快照。"""

        if self.node_pack_loader is not None:
            self.node_pack_loader.refresh()
        self.invalidate_cache()

    def _build_catalog_snapshot(self) -> NodeCatalogSnapshot:
        """构建一次合并后的节点目录快照。"""

        custom_node_catalog = (
            self.node_pack_loader.get_catalog_snapshot()
            if self.node_pack_loader is not None
            else NodeCatalogSnapshot()
        )
        return NodeCatalogSnapshot(
            node_pack_manifests=custom_node_catalog.node_pack_manifests,
            payload_contracts=_merge_payload_contracts(
                get_core_workflow_payload_contracts(),
                custom_node_catalog.payload_contracts,
            ),
            node_definitions=get_core_workflow_node_definitions() + custom_node_catalog.node_definitions,
        )

    def get_node_pack_manifests(self) -> tuple[NodePackManifest, ...]:
        """返回已发现的节点包 manifest 列表。"""

        return self.get_catalog_snapshot().node_pack_manifests

    def get_workflow_payload_contracts(self) -> tuple[WorkflowPayloadContract, ...]:
        """返回统一目录中的 workflow payload 规则 列表。"""

        return self.get_catalog_snapshot().payload_contracts

    def get_workflow_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回统一目录中的 workflow 节点定义列表。"""

        return self.get_catalog_snapshot().node_definitions


def _merge_payload_contracts(
    *payload_contract_groups: tuple[WorkflowPayloadContract, ...],
) -> tuple[WorkflowPayloadContract, ...]:
    """按 payload_type_id 合并 core 与节点包 payload 规则。

    参数：
    - payload_contract_groups：按优先级传入的 payload 规则分组，core 规则应放在前面。

    返回：
    - tuple[WorkflowPayloadContract, ...]：去重后的 payload 规则。

    说明：
    - 相同 payload_type_id 且定义一致时只保留第一份，避免统一目录出现重复名称。
    - 相同 payload_type_id 但定义不一致时直接报错，防止节点包静默覆盖 core 规则。
    """

    merged_contracts: list[WorkflowPayloadContract] = []
    contract_index: dict[str, WorkflowPayloadContract] = {}
    for payload_contract_group in payload_contract_groups:
        for contract in payload_contract_group:
            existing_contract = contract_index.get(contract.payload_type_id)
            if existing_contract is None:
                contract_index[contract.payload_type_id] = contract
                merged_contracts.append(contract)
                continue
            if existing_contract.model_dump(mode="json") != contract.model_dump(mode="json"):
                raise ValueError(f"payload 规则 存在重复且定义不一致: {contract.payload_type_id}")
    return tuple(merged_contracts)
