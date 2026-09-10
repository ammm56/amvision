"""真实节点目录的显示契约和空闲刷新验证；所有显示捕获仅存内存。"""
from pathlib import Path
import pytest
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.preview.display import PreviewDisplayCapture
from backend.service.application.workflows.preview.buffers import PreviewBuffers
from tests.test_workflow_preview_values import Bridge

@pytest.fixture(scope="module")
def definitions():
    """读取真实启用目录，核对 5 类显示和 36 类调试图节点。"""
    loader = LocalNodePackLoader(Path(__file__).resolve().parents[1] / "custom_nodes")
    loader.refresh()
    return {d.node_type_id: d for d in NodeCatalogRegistry(node_pack_loader=loader).get_catalog_snapshot().node_definitions}

NODE_TYPES = [
    "core.input.box-prompt", "core.input.mask-editor", "core.input.point-prompt", "core.input.polygon-prompt",
    "core.io.frame-window-preview", "core.io.image-preview", "core.io.table-preview", "core.io.value-preview",
    "core.vision.roi-create", "core.vision.roi-from-contour", "core.vision.roi-from-rotated-rect", "core.vision.roi-grid-create",
    *[f"custom.opencv.{name}" for name in (
        "affine-transform", "bilateral-filter", "caliper-edge", "canny", "circle-measure", "contour",
        "contour-approx", "contour-filter", "convex-hull", "fit-ellipse", "fit-line", "gallery-preview",
        "homography-estimate", "hough-circles", "hough-lines", "image-refs-empty-check", "image-refs-occupied-check",
        "image-refs-slot-metrics", "min-area-rect", "min-enclosing-circle", "orb-keypoints", "orb-match",
        "perspective-transform", "quadrilateral-from-circle-centers", "quadrilateral-from-lines", "remap",
        "rotation-correct", "template-match", "undistort")],
]


def test_explicit_image_save_keeps_file_and_saved_output_metadata(tmp_path):
    """只写节点明确指定的业务文件，异步显示解析后仍保留保存结果。"""
    from types import SimpleNamespace
    from backend.nodes.runtime_support import ExecutionImageRegistry, build_memory_image_payload
    from tests.api_test_support import build_valid_test_png_bytes
    content = build_valid_test_png_bytes()
    images = ExecutionImageRegistry()
    entry = images.register_image_bytes(content=content, media_type="image/png")
    request = SimpleNamespace(execution_metadata={"execution_image_registry": images}, node_id="save", parameters={}, node_deadline_monotonic=None, node_cancellation_event=None, runtime_context=None)
    buffers = PreviewBuffers()
    capture = PreviewDisplayCapture(Bridge(buffers), lambda *args: None)
    target = tmp_path / "explicit.png"
    try:
        pending = capture.image(request, image_payload=build_memory_image_payload(image_handle=entry.image_handle, media_type="image/png"), save_location=str(target))
        capture.close()
        result = capture.resolve_outputs(pending)
        assert target.read_bytes() == content
        assert result["saved_output"] == pending["saved_output"]
        assert result["blob_id"]
        assert list(tmp_path.iterdir()) == [target]
    finally:
        capture.close()
        images.clear()
        buffers.close()

@pytest.mark.parametrize("node_type", NODE_TYPES)
def test_all_display_node_definitions_preserve_their_output_contract(definitions, node_type):
    """按真实端口定义捕获 body 和交互属性；算法精度由各节点测试覆盖。"""
    definition = definitions[node_type]
    port = next(p for p in definition.output_ports if p.name in {"body", "debug_preview"})
    payload = {"type": "image-preview", "image": {"image_base64": "x" * 10_000},
               "interaction": {"coordinate_space": "source", "tools": []}}
    buffers = PreviewBuffers()
    events = []
    capture = PreviewDisplayCapture(Bridge(buffers), lambda kind, value: events.append((kind, value)))
    try:
        capture.capture(node_id="node", definition=definition, outputs={port.name: payload}, invocation_id="node:0", duration_ms=1)
        capture.close()
        result = next(value for kind, value in events if kind == "display.updated")
        assert result["payload"] == payload
        assert buffers.stats()["reserved_bytes"] == 0
    finally:
        capture.close()
        buffers.close()

def test_idle_node_pack_refresh_replaces_catalog_and_handlers_together(tmp_path):
    """真实 hello-world 节点包升级/禁用后，旧目录缓存不能继续提供旧定义。"""
    import json
    from shutil import copytree
    from unittest.mock import Mock
    from backend.service.application.workflows.preview.worker import refresh_node_resources
    from backend.service.application.workflows.runtime_registry_loader import WorkflowNodeRuntimeRegistryLoader
    root = tmp_path / "custom_nodes"
    copytree(Path(__file__).resolve().parents[1] / "custom_nodes/hello_world_nodes", root / "hello_world_nodes")
    loader = LocalNodePackLoader(root)
    loader.refresh()
    catalog = NodeCatalogRegistry(node_pack_loader=loader)
    registry_loader = WorkflowNodeRuntimeRegistryLoader(node_catalog_registry=catalog, node_pack_loader=loader)
    registry_loader.refresh()
    models, cache = Mock(), Mock()
    signature = tuple(m.model_dump_json() for m in loader.get_node_pack_manifests())
    node_id = next(d.node_type_id for d in catalog.get_workflow_node_definitions() if d.node_pack_id == "hello.world-nodes")
    registry = registry_loader.get_runtime_registry()
    assert registry.get_node_definition(node_id).node_pack_version == "0.1.0"
    assert refresh_node_resources(loader, catalog, registry_loader, models, cache, signature) == signature
    models.close_all.assert_not_called()
    path = root / "hello_world_nodes/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf8"))
    manifest["version"] = "0.1.1"
    path.write_text(json.dumps(manifest), encoding="utf8")
    catalog_path = root / "hello_world_nodes/workflow/catalog.json"
    updated_catalog = json.loads(catalog_path.read_text(encoding="utf8"))
    updated_catalog["node_definitions"][0]["node_pack_version"] = "0.1.1"
    updated_catalog["node_definitions"][0]["parameter_schema"]["properties"]["new_parameter"] = {"type": "string"}
    catalog_path.write_text(json.dumps(updated_catalog), encoding="utf8")
    signature = refresh_node_resources(loader, catalog, registry_loader, models, cache, signature)
    assert registry.get_node_definition(node_id).node_pack_version == "0.1.1"
    assert "new_parameter" in registry.get_node_definition(node_id).parameter_schema["properties"]
    models.close_all.assert_called_once()
    cache.clear.assert_called_once()
    manifest["enabledByDefault"] = False
    path.write_text(json.dumps(manifest), encoding="utf8")
    refresh_node_resources(loader, catalog, registry_loader, models, cache, signature)
    assert node_id not in {d.node_type_id for d in catalog.get_workflow_node_definitions()}
    from backend.service.application.errors import ServiceConfigurationError
    with pytest.raises(ServiceConfigurationError, match="节点"):
        registry.get_node_definition(node_id)


def test_nested_custom_display_converts_binary_and_pages_values(definitions):
    """真实自定义端口容器的两个显示都可用；大表格原值从 SHM 分页读取。"""
    from base64 import b64encode
    from tests.api_test_support import build_valid_test_png_bytes
    import json
    definition = definitions["core.io.value-preview"]
    source = build_valid_test_png_bytes()
    payload = {"data": {"annotated_image": {"type": "image-preview", "image": {
        "transport_kind": "inline-base64", "image_base64": b64encode(source).decode(), "media_type": "image/png"}},
        "result_table": {"type": "table-preview", "columns": [{"key": "index"}], "rows": [{"index": i, "value": False} for i in range(2000)]}}}
    buffers, events = PreviewBuffers(), []
    capture = PreviewDisplayCapture(Bridge(buffers), lambda kind, data: events.append((kind, data)))
    try:
        capture.capture(node_id="n", definition=definition, outputs={"body": payload}, invocation_id="n:1", duration_ms=1)
        capture.close()
        displays = {data["output_port"]: data["payload"] for kind, data in events if kind == "display.updated"}
        image = displays["body/data/annotated_image"]["image"]
        assert "image_base64" not in image
        with buffers.borrow("session", image["blob_id"]) as content:
            import cv2
            import numpy as np
            assert bytes(content).startswith(b"\xff\xd8")
            assert image["media_type"] == "image/jpeg"
            assert cv2.imdecode(np.frombuffer(content, dtype=np.uint8), 1).shape == cv2.imdecode(np.frombuffer(source, dtype=np.uint8), 1).shape
        table = displays["body/data/result_table"]
        assert table["paged"] and len(table["rows"]) == 4
        with buffers.borrow("session", table["value_descriptor"]["blob_id"]) as content:
            full = json.loads(bytes(content))
        assert full["rows"][1999] == {"index": 1999, "value": False}
        assert payload["data"]["annotated_image"]["image"]["image_base64"] == b64encode(source).decode()
    finally:
        capture.close()
        buffers.close()
