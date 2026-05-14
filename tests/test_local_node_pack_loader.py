"""本地文件系统节点包加载器测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.service.application.errors import ServiceConfigurationError


def test_local_node_pack_loader_loads_enabled_custom_node_pack(tmp_path: Path) -> None:
    """验证 LocalNodePackLoader 可以从本地目录加载启用的自定义节点包。"""

    custom_nodes_root_dir = _create_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)

    node_pack_loader.refresh()
    catalog_snapshot = node_pack_loader.get_catalog_snapshot()

    assert len(catalog_snapshot.node_pack_manifests) == 1
    assert catalog_snapshot.node_pack_manifests[0].node_pack_id == "opencv.basic-nodes"
    assert [node.node_type_id for node in catalog_snapshot.node_definitions] == [
        "custom.opencv.draw-detections"
    ]


def test_local_node_pack_loader_skips_disabled_node_pack_registration(tmp_path: Path) -> None:
    """验证 disabled 节点包只保留 manifest，不进入目录定义注册。"""

    custom_nodes_root_dir = _create_node_pack_fixture(tmp_path, enabled_by_default=False)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)

    node_pack_loader.refresh()
    catalog_snapshot = node_pack_loader.get_catalog_snapshot()

    assert len(catalog_snapshot.node_pack_manifests) == 1
    assert catalog_snapshot.node_pack_manifests[0].node_pack_id == "opencv.basic-nodes"
    assert catalog_snapshot.node_pack_manifests[0].enabled_by_default is False
    assert catalog_snapshot.payload_contracts == ()
    assert catalog_snapshot.node_definitions == ()


def test_local_node_pack_loader_loads_enabled_node_pack_with_satisfied_dependencies(
    tmp_path: Path,
) -> None:
    """验证启用节点包在依赖满足时可以正常进入目录快照。"""

    custom_nodes_root_dir = _create_node_pack_fixture(tmp_path)
    _create_dependent_node_pack_fixture(
        tmp_path,
        dependency_node_pack_id="opencv.basic-nodes",
        dependency_version_range=">=0.1.0 <1.0",
    )
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)

    node_pack_loader.refresh()
    catalog_snapshot = node_pack_loader.get_catalog_snapshot()

    assert {manifest.node_pack_id for manifest in catalog_snapshot.node_pack_manifests} == {
        "opencv.basic-nodes",
        "barcode.protocol-nodes",
    }
    assert {node.node_type_id for node in catalog_snapshot.node_definitions} == {
        "custom.opencv.draw-detections",
        "custom.barcode.summarize-results",
    }


def test_local_node_pack_loader_requires_declared_dependency_to_exist_before_enable(
    tmp_path: Path,
) -> None:
    """验证启用节点包前会检查 manifest dependencies 中声明的节点包是否存在。"""

    custom_nodes_root_dir = _create_dependent_node_pack_fixture(
        tmp_path,
        dependency_node_pack_id="opencv.basic-nodes",
        dependency_version_range=">=0.1.0 <1.0",
    )
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)

    with pytest.raises(ServiceConfigurationError, match="缺少依赖节点包"):
        node_pack_loader.refresh()


def test_local_node_pack_loader_requires_dependency_to_be_enabled_before_enable(
    tmp_path: Path,
) -> None:
    """验证启用节点包前会检查依赖节点包是否已经启用。"""

    custom_nodes_root_dir = _create_node_pack_fixture(tmp_path, enabled_by_default=False)
    _create_dependent_node_pack_fixture(
        tmp_path,
        dependency_node_pack_id="opencv.basic-nodes",
        dependency_version_range=">=0.1.0 <1.0",
    )
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)

    with pytest.raises(ServiceConfigurationError, match="依赖节点包未启用"):
        node_pack_loader.refresh()


def test_local_node_pack_loader_requires_dependency_version_to_match_before_enable(
    tmp_path: Path,
) -> None:
    """验证启用节点包前会检查依赖节点包版本是否满足 manifest 要求。"""

    custom_nodes_root_dir = _create_node_pack_fixture(tmp_path, version="0.2.0")
    _create_dependent_node_pack_fixture(
        tmp_path,
        dependency_node_pack_id="opencv.basic-nodes",
        dependency_version_range="==0.1.0",
    )
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)

    with pytest.raises(ServiceConfigurationError, match="依赖节点包版本不满足要求"):
        node_pack_loader.refresh()


def _create_node_pack_fixture(
    tmp_path: Path,
    *,
    version: str = "0.1.0",
    enabled_by_default: bool = True,
) -> Path:
    """创建 LocalNodePackLoader 测试使用的最小节点包目录。"""

    node_pack_dir = tmp_path / "custom_nodes" / "opencv_basic_nodes"
    backend_dir = node_pack_dir / "backend"
    workflow_dir = node_pack_dir / "workflow"
    backend_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (node_pack_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "entry.py").write_text(
        """
def _draw_detections_handler(request):
    return {\"response\": {\"status_code\": 200, \"body\": {\"node_id\": request.node_id}}}


def register(context):
    context.register_python_callable(\"custom.opencv.draw-detections\", _draw_detections_handler)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest_payload = {
        "format_id": "amvision.node-pack-manifest.v1",
        "id": "opencv.basic-nodes",
        "version": version,
        "displayName": "OpenCV Basic Nodes",
        "description": "测试用 OpenCV 自定义节点包。",
        "category": "custom-node-pack",
        "capabilities": ["pipeline.node"],
        "entrypoints": {"backend": "custom_nodes.opencv_basic_nodes.backend.entry:register"},
        "compatibility": {"api": ">=0.1 <1.0", "runtime": ">=3.12"},
        "timeout": {"defaultSeconds": 30},
        "enabledByDefault": enabled_by_default,
        "customNodeCatalogPath": "workflow/catalog.json",
    }
    workflow_catalog_payload = {
        "format_id": "amvision.custom-node-catalog.v1",
        "payload_contracts": [],
        "node_definitions": [
            {
                "format_id": "amvision.node-definition.v1",
                "node_type_id": "custom.opencv.draw-detections",
                "display_name": "Draw Detections",
                "category": "opencv.render",
                "description": "通过 OpenCV 把 detection 结果叠加到图片上。",
                "implementation_kind": "custom-node",
                "runtime_kind": "python-callable",
                "input_ports": [
                    {
                        "name": "image",
                        "display_name": "Image",
                        "payload_type_id": "image-ref.v1",
                    },
                    {
                        "name": "detections",
                        "display_name": "Detections",
                        "payload_type_id": "detections.v1",
                    },
                ],
                "output_ports": [
                    {
                        "name": "response",
                        "display_name": "Response",
                        "payload_type_id": "http-response.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["opencv.draw"],
                "runtime_requirements": {"python_packages": ["opencv-python", "numpy"]},
                "node_pack_id": "opencv.basic-nodes",
                "node_pack_version": version,
            }
        ],
    }
    (node_pack_dir / "manifest.json").write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (workflow_dir / "catalog.json").write_text(
        json.dumps(workflow_catalog_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return tmp_path / "custom_nodes"


def _create_dependent_node_pack_fixture(
    tmp_path: Path,
    *,
    dependency_node_pack_id: str,
    dependency_version_range: str | None = None,
) -> Path:
    """创建带有 manifest dependencies 声明的最小节点包目录。"""

    node_pack_dir = tmp_path / "custom_nodes" / "barcode_protocol_nodes"
    backend_dir = node_pack_dir / "backend"
    workflow_dir = node_pack_dir / "workflow"
    backend_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (node_pack_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "entry.py").write_text(
        """
def _summarize_results_handler(request):
    return {"summary": {"count": 0, "items": []}}


def register(context):
    context.register_python_callable("custom.barcode.summarize-results", _summarize_results_handler)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    dependency_payload: dict[str, object] = {"nodePackId": dependency_node_pack_id}
    if dependency_version_range is not None:
        dependency_payload["versionRange"] = dependency_version_range
    manifest_payload = {
        "format_id": "amvision.node-pack-manifest.v1",
        "id": "barcode.protocol-nodes",
        "version": "0.1.0",
        "displayName": "Barcode Protocol Nodes",
        "description": "测试用带依赖声明的条码节点包。",
        "category": "custom-node-pack",
        "capabilities": ["pipeline.node", "barcode.summary"],
        "dependencies": [dependency_payload],
        "entrypoints": {"backend": "custom_nodes.barcode_protocol_nodes.backend.entry:register"},
        "compatibility": {"api": ">=0.1 <1.0", "runtime": ">=3.12"},
        "timeout": {"defaultSeconds": 30},
        "enabledByDefault": True,
        "customNodeCatalogPath": "workflow/catalog.json",
    }
    workflow_catalog_payload = {
        "format_id": "amvision.custom-node-catalog.v1",
        "payload_contracts": [],
        "node_definitions": [
            {
                "format_id": "amvision.node-definition.v1",
                "node_type_id": "custom.barcode.summarize-results",
                "display_name": "Summarize Barcode Results",
                "category": "barcode.summary",
                "description": "把条码结果整理成轻量摘要。",
                "implementation_kind": "custom-node",
                "runtime_kind": "python-callable",
                "input_ports": [],
                "output_ports": [
                    {
                        "name": "summary",
                        "display_name": "Summary",
                        "payload_type_id": "barcode-results-summary.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["barcode.summary"],
                "runtime_requirements": {},
                "node_pack_id": "barcode.protocol-nodes",
                "node_pack_version": "0.1.0",
            }
        ],
    }
    (node_pack_dir / "manifest.json").write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (workflow_dir / "catalog.json").write_text(
        json.dumps(workflow_catalog_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return tmp_path / "custom_nodes"