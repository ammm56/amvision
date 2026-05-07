"""本地文件系统节点包加载器测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.nodes.local_node_pack_loader import LocalNodePackLoader


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


def _create_node_pack_fixture(tmp_path: Path) -> Path:
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
        "version": "0.1.0",
        "displayName": "OpenCV Basic Nodes",
        "description": "测试用 OpenCV 自定义节点包。",
        "category": "custom-node-pack",
        "capabilities": ["pipeline.node"],
        "entrypoints": {"backend": "custom_nodes.opencv_basic_nodes.backend.entry:register"},
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