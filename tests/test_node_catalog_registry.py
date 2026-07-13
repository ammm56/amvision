"""统一节点目录注册表测试。"""

from __future__ import annotations

import pytest

from backend.contracts.workflows.workflow_graph import WorkflowPayloadContract
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.nodes.node_pack_loader import NodeCatalogSnapshot


class _CatalogLoader:
    """测试用节点包加载器，只返回固定目录快照。"""

    def __init__(self, snapshot: NodeCatalogSnapshot) -> None:
        """保存测试目录快照。"""

        self._snapshot = snapshot

    def get_catalog_snapshot(self) -> NodeCatalogSnapshot:
        """返回测试目录快照。"""

        return self._snapshot


def test_node_catalog_registry_keeps_one_copy_for_duplicate_same_payload_contract() -> None:
    """验证 core 与 custom 中相同 payload 规则只在统一目录保留一份。"""

    core_contract = get_core_workflow_payload_contracts()[0]
    registry = NodeCatalogRegistry(
        node_pack_loader=_CatalogLoader(
            NodeCatalogSnapshot(payload_contracts=(core_contract,))
        )
    )

    snapshot = registry.get_catalog_snapshot()
    payload_type_ids = [
        contract.payload_type_id
        for contract in snapshot.payload_contracts
    ]

    assert payload_type_ids.count(core_contract.payload_type_id) == 1


def test_node_catalog_registry_rejects_duplicate_payload_contract_with_different_schema() -> None:
    """验证 custom 节点包不能用不同定义覆盖 core payload 规则。"""

    core_contract = get_core_workflow_payload_contracts()[0]
    conflicting_contract = WorkflowPayloadContract(
        payload_type_id=core_contract.payload_type_id,
        display_name="Conflicting Value Payload",
        transport_kind="inline-json",
        json_schema={"type": "object", "properties": {"other": {}}},
    )
    registry = NodeCatalogRegistry(
        node_pack_loader=_CatalogLoader(
            NodeCatalogSnapshot(payload_contracts=(conflicting_contract,))
        )
    )

    with pytest.raises(ValueError, match="定义不一致"):
        registry.get_catalog_snapshot()
