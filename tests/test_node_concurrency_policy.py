"""节点并发策略白名单和目录应用测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_SERIALIZED,
    NODE_CONCURRENCY_THREAD_SAFE,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry


def test_catalog_marks_verified_stateless_nodes_thread_safe() -> None:
    """纯计算与已受资源保护的节点应获得 thread-safe 策略。"""

    loader = LocalNodePackLoader(Path("custom_nodes"))
    loader.refresh()
    definitions = NodeCatalogRegistry(
        node_pack_loader=loader
    ).get_workflow_node_definitions()
    by_id = {definition.node_type_id: definition for definition in definitions}

    assert by_id["core.output.csv-append-local"].concurrency_policy == (
        NODE_CONCURRENCY_THREAD_SAFE
    )
    assert by_id["custom.http.request"].concurrency_policy == (
        NODE_CONCURRENCY_THREAD_SAFE
    )
    assert by_id["custom.yoloe.text-prompt-detect"].concurrency_policy == (
        NODE_CONCURRENCY_THREAD_SAFE
    )
    assert by_id["custom.camera.usb.open-device"].concurrency_policy == (
        NODE_CONCURRENCY_SERIALIZED
    )


def test_catalog_keeps_stateful_families_serialized() -> None:
    """Camera、PLC、SAM3 和数据库节点必须继续保守串行。"""

    loader = LocalNodePackLoader(Path("custom_nodes"))
    loader.refresh()
    definitions = NodeCatalogRegistry(
        node_pack_loader=loader
    ).get_workflow_node_definitions()

    for definition in definitions:
        if definition.category.startswith(("camera.", "plc.", "sam3.", "database.")):
            assert definition.concurrency_policy == NODE_CONCURRENCY_SERIALIZED


def test_catalog_thread_safe_count_reflects_stateless_families() -> None:
    """目录应大幅减少无状态节点的同类型串行阻塞。"""

    loader = LocalNodePackLoader(Path("custom_nodes"))
    loader.refresh()
    definitions = NodeCatalogRegistry(
        node_pack_loader=loader
    ).get_workflow_node_definitions()
    thread_safe_count = sum(
        definition.concurrency_policy == NODE_CONCURRENCY_THREAD_SAFE
        for definition in definitions
    )

    assert thread_safe_count >= 330
