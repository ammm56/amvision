"""OpenCV 基础节点目录生成测试。"""

from __future__ import annotations

import json
from pathlib import Path

from custom_nodes.opencv_basic_nodes.workflow.catalog_builder import build_custom_node_catalog_payload


def test_opencv_basic_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证 catalog 碎片生成结果与仓库内 catalog.json 保持一致。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = repository_root / "custom_nodes" / "opencv_basic_nodes" / "workflow"
    expected_catalog_payload = json.loads((workflow_dir / "catalog.json").read_text(encoding="utf-8"))

    assert build_custom_node_catalog_payload(workflow_dir=workflow_dir) == expected_catalog_payload