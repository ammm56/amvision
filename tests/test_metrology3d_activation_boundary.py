"""正式节点包使用既有发现与容量准入，不保留隐藏实现。"""

import json
from pathlib import Path

import pytest

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from backend.service.application.workflows.point_cloud.execution_policy import (
    PointCloudExecutionPolicy,
)


def test_formal_implementation_is_discovered_once():
    """沿正常目录发现单一实现，不同时保留内部入口。"""
    root = Path(__file__).resolve().parents[1] / "custom_nodes"
    assert (root / "metrology3d_nodes" / "shared" / "io" / "read_file.py").is_file()
    assert not (root / "_metrology3d_nodes").exists()
    loader = LocalNodePackLoader(root)
    loader.refresh()
    snapshot = loader.get_catalog_snapshot()
    assert (
        sum(m.node_pack_id == "metrology3d.nodes" for m in snapshot.node_pack_manifests)
        == 1
    )
    assert (
        sum(d.node_pack_id == "metrology3d.nodes" for d in snapshot.node_definitions)
        == 18
    )
    status = next(
        s
        for s in loader.get_node_pack_status_snapshot().items
        if s.node_pack_id == "metrology3d.nodes"
    )
    assert status.enabled
    assert not status.issues


def test_workstation_example_has_explicit_capacity_and_rejects_over_budget():
    """确认的本机容量是立即拒绝边界，不是等待队列或全平台默认值。"""
    root = Path(__file__).resolve().parents[1] / "custom_nodes/metrology3d_nodes"
    data = json.loads((root / "workstation.example.json").read_text("utf-8"))
    policy = PointCloudExecutionPolicy.model_validate(
        data["workflow_runtime"]["point_cloud"]
    )
    assert policy.io.max_live_array_bytes == 1024**3
    assert policy.io.max_working_bytes == 4 * 1024**3
    assert policy.preview.max_points == policy.renderer.max_points == 1000000
    budget = CloudArrayBudget(policy.io.max_live_array_bytes)
    reservation = budget.reserve(budget.limit)
    try:
        with pytest.raises(InvalidRequestError, match="超过运行预算"):
            budget.reserve(1)
        assert budget.used == budget.limit
    finally:
        reservation.close()
    assert budget.used == 0
    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    assert manifest["timeout"] == dict(
        defaultSeconds=180, maxSeconds=180, killGraceSeconds=2
    )
