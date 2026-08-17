"""统一节点目录注册表测试。"""

from __future__ import annotations

import pytest

from backend.contracts.workflows.workflow_graph import WorkflowPayloadContract
from backend.nodes.core_catalog import (
    get_core_workflow_node_definitions,
    get_core_workflow_payload_contracts,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.nodes.node_pack_loader import NodeCatalogSnapshot
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.execution.registry import (
    WorkflowNodeRuntimeRegistry,
)


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


def test_node_catalog_registry_keeps_one_copy_for_identical_node_definition() -> None:
    """验证 custom 重复声明相同节点时统一目录只保留一份。"""

    core_definition = get_core_workflow_node_definitions()[0]
    registry = NodeCatalogRegistry(
        node_pack_loader=_CatalogLoader(
            NodeCatalogSnapshot(node_definitions=(core_definition,))
        )
    )

    definitions = registry.get_workflow_node_definitions()

    assert sum(
        definition.node_type_id == core_definition.node_type_id
        for definition in definitions
    ) == 1


def test_node_catalog_registry_rejects_conflicting_node_definition() -> None:
    """验证 custom 节点不能使用相同 id 覆盖 core 节点。"""

    core_definition = get_core_workflow_node_definitions()[0]
    conflicting_definition = core_definition.model_copy(
        update={"display_name": f"{core_definition.display_name} Conflict"}
    )
    registry = NodeCatalogRegistry(
        node_pack_loader=_CatalogLoader(
            NodeCatalogSnapshot(node_definitions=(conflicting_definition,))
        )
    )

    with pytest.raises(ValueError, match="节点定义存在重复"):
        registry.get_catalog_snapshot()


def test_runtime_registry_rejects_definition_and_handler_overrides() -> None:
    """验证运行时注册允许幂等调用，但拒绝定义和 handler 静默覆盖。"""

    definition = next(
        item
        for item in get_core_workflow_node_definitions()
        if item.runtime_kind == "python-callable"
    )
    registry = WorkflowNodeRuntimeRegistry()
    registry.register_node_definition(definition)
    registry.register_node_definition(definition)

    with pytest.raises(ServiceConfigurationError, match="冲突定义"):
        registry.register_node_definition(
            definition.model_copy(
                update={"display_name": f"{definition.display_name} Conflict"}
            )
        )

    handler = lambda request: {}  # noqa: E731 - 测试需要稳定 callable identity
    registry.register_python_callable(definition, handler)
    registry.register_python_callable(definition, handler)

    with pytest.raises(ServiceConfigurationError, match="处理函数重复注册"):
        registry.register_python_callable(definition, lambda request: {})

    replacement_handler = lambda request: {"replaced": True}  # noqa: E731
    registry.replace_python_callable_handler(
        definition.node_type_id,
        replacement_handler,
    )

    assert registry.resolve_handler(node_definition=definition) is replacement_handler

    worker_definition = next(
        item
        for item in get_core_workflow_node_definitions()
        if item.runtime_kind == "worker-task"
    )
    worker_handler = lambda request: {}  # noqa: E731
    replacement_worker_handler = lambda request: {"replaced": True}  # noqa: E731
    registry.register_worker_task(worker_definition, worker_handler)
    registry.replace_worker_task_handler(
        worker_definition.node_type_id,
        replacement_worker_handler,
    )

    assert (
        registry.resolve_handler(node_definition=worker_definition)
        is replacement_worker_handler
    )
