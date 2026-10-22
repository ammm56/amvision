"""内部验证阶段不发布空节点，也不污染现有节点包状态。"""

from pathlib import Path

from backend.nodes.local_node_pack_loader import LocalNodePackLoader


def test_internal_implementation_is_not_discovered_or_registered():
    """复用既有下划线目录约定，无需改变加载器或伪造运行策略。"""
    root = Path(__file__).resolve().parents[1] / "custom_nodes"
    assert (root / "_metrology3d_nodes" / "shared" / "io" / "read_file.py").is_file()
    loader = LocalNodePackLoader(root)
    loader.refresh()
    snapshot = loader.get_catalog_snapshot()
    assert all(
        "metrology3d" not in item.node_pack_id for item in snapshot.node_pack_manifests
    )
    assert all(
        "metrology3d" not in item.node_type_id for item in snapshot.node_definitions
    )
    assert all(
        "metrology3d" not in item.node_pack_id
        for item in loader.get_node_pack_status_snapshot().items
    )
