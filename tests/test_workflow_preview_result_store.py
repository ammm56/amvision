"""编辑态显示契约、原子发布及生命周期回归；不把合成图测试当模型精度验收。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.preview_result_store import PreviewResultStore, read_display_manifest
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage, DatasetStorageSettings


@pytest.fixture
def storage(tmp_path):
    """每项测试使用独立本地对象存储。"""
    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))


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


@pytest.mark.parametrize("node_type", NODE_TYPES)
def test_all_display_node_definitions_preserve_their_output_contract(storage, definitions, node_type):
    """使用真实端口定义验证捕获；算法 handler 的数值正确性另行验证。"""
    definition = definitions[node_type]
    port = next(p for p in definition.output_ports if p.name in {"body", "debug_preview"})
    payload = {"type": "image-preview", "image": {"image_base64": "x" * 10_000},
               "interaction": {"coordinate_space": "source", "tools": []}}
    writer = PreviewResultStore(storage, "run")
    writer.capture(node_id="node", definition=definition, outputs={port.name: payload}, invocation_id="node:0", duration_ms=1)
    manifest = storage.read_json("workflows/runtime/preview-runs/run/displays/manifest.json")
    descriptor = manifest["displays"][0]
    assert descriptor["error"] is None
    assert storage.read_json(f"workflows/runtime/preview-runs/run/displays/{descriptor['display_id']}.json") == payload


@pytest.mark.parametrize("value", [0, False, None, "", {"a": False}, list(range(5000))])
def test_values_survive_loop_replacement_and_restart_without_redaction(storage, value):
    """不以真假判断代替缺值判断；清单可由新进程读取。"""
    definition = SimpleNamespace(node_type_id="custom.no-preview-suffix", output_ports=[SimpleNamespace(name="body")])
    writer = PreviewResultStore(storage, "run")
    for index in range(3):
        writer.capture(node_id="n", definition=definition, outputs={"body": {"type": "value-preview", "value": value}},
                       invocation_id=f"n:{index}", duration_ms=1)
    manifest = read_display_manifest(storage, SimpleNamespace(preview_run_id="run", metadata={}))
    assert len(manifest["displays"]) == 1
    item = manifest["displays"][0]
    assert item["invocation_id"] == "n:2"
    assert storage.read_json(f"{writer.root}/displays/{item['display_id']}.json")["value"] == value


def test_display_write_failure_preserves_other_completed_nodes(storage, monkeypatch):
    """失败项显式标记，不中止后续捕获，不把旧图片伪装为新调用结果。"""
    definition = SimpleNamespace(node_type_id="custom.display", output_ports=[SimpleNamespace(name="body")])
    writer = PreviewResultStore(storage, "run")
    payload = {"body": {"type": "value-preview", "value": False}}
    writer.capture(node_id="good", definition=definition, outputs=payload, invocation_id="1", duration_ms=1)
    original = storage.write_json
    def write(key, value):
        """仅注入节点资产写入失败。"""
        if key.endswith("manifest.json"):
            return original(key, value)
        raise OSError("disk unavailable")
    monkeypatch.setattr(storage, "write_json", write)
    writer.capture(node_id="bad", definition=definition, outputs=payload, invocation_id="2", duration_ms=1)
    manifest = read_display_manifest(storage, SimpleNamespace(preview_run_id="run", metadata={}))
    assert [d["error"] for d in manifest["displays"]] == [None, "preview_display_write_failed"]


def test_uploaded_source_image_has_run_owned_lifetime(storage):
    """任务输入删除后显示资产仍有效，交互坐标信息保持原值。"""
    source = "workflows/runtime-inputs/upload/image.png"
    storage.write_bytes(source, b"image-bytes")
    writer = PreviewResultStore(storage, "run")
    definition = SimpleNamespace(node_type_id="custom.display", output_ports=[SimpleNamespace(name="body")])
    payload = {"type": "image-preview", "image": {"source_width": 9000,
        "source_image": {"transport_kind": "storage-ref", "object_key": source}}}
    writer.capture(node_id="image", definition=definition, outputs={"body": payload}, invocation_id="1", duration_ms=1)
    storage.delete_tree("workflows/runtime-inputs/upload")
    item = next(iter(writer.descriptors.values()))
    saved = storage.read_json(f"{writer.root}/displays/{item['display_id']}.json")
    assert storage.resolve(saved["image"]["source_image"]["object_key"]).read_bytes() == b"image-bytes"
    assert saved["image"]["source_width"] == 9000
    assert payload["image"]["source_image"]["object_key"] == source


def test_real_spawn_publishes_display_before_cancellation(tmp_path):
    """真实子进程完成值预览后取消长节点，显示文件和完成记录继续可读。"""
    from time import monotonic, sleep
    from backend.contracts.workflows.workflow_graph import WorkflowGraphNode, WorkflowGraphEdge
    from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
    from tests.test_workflow_runtime_invoke_api import _build_file_metadata_application, _create_runtime_api_client
    from tests.api_test_support import build_test_headers
    client, sessions, storage = _create_runtime_api_client(tmp_path, database_name="partial.db", enable_local_buffer_broker=False)
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    with client:
        template, application = _build_file_metadata_application(multiple=True)
        template = template.model_copy(update={"nodes": (
            WorkflowGraphNode(node_id="text", node_type_id="core.logic.string-value", parameters={"value": "完整值" * 2000}),
            WorkflowGraphNode(node_id="display", node_type_id="core.io.value-preview"),
            WorkflowGraphNode(node_id="delay", node_type_id="core.logic.delay", parameters={"seconds": 30}),
        ), "edges": (
            WorkflowGraphEdge(edge_id="show", source_node_id="text", source_port="value", target_node_id="display", target_port="value"),
            WorkflowGraphEdge(edge_id="wait", source_node_id="text", source_port="value", target_node_id="delay", target_port="value"),
        ), "template_inputs": (), "template_outputs": (
            template.template_outputs[0].model_copy(update={"source_node_id": "delay", "source_port": "value"}),)})
        application = application.model_copy(update={"bindings": tuple(b for b in application.bindings if b.direction == "output")})
        service = LocalWorkflowJsonService(dataset_storage=storage, node_catalog_registry=client.app.state.node_catalog_registry)
        service.save_template(project_id="project-1", template=template)
        service.save_application(project_id="project-1", application=application)
        response = client.post("/api/v1/workflows/preview-runs", headers=headers, json={"project_id": "project-1", "wait_mode": "async",
            "application_ref": {"application_id": application.application_id}, "execution_metadata": {"retain_node_records_enabled": True}})
        assert response.status_code == 201, response.text
        base = f"/api/v1/workflows/preview-runs/{response.json()['preview_run_id']}"
        deadline = monotonic() + 15
        while monotonic() < deadline:
            manifest = client.get(f"{base}/displays", headers=headers).json()
            if manifest.get("displays"):
                break
            sleep(.1)
        assert manifest.get("displays"), manifest
        descriptor = manifest["displays"][0]
        assert client.get(f"{base}/displays").status_code == 401
        client.post(f"{base}/cancel", headers=headers).raise_for_status()
        while monotonic() < deadline:
            record = client.get(base, headers=headers).json()
            if record["state"] not in {"running", "created"}:
                break
            sleep(.1)
        assert record["state"] == "cancelled", record
        body = client.get(f"{base}/displays/{descriptor['display_id']}", headers=headers)
        assert body.status_code == 200, body.text
        assert body.json()["value"] == "完整值" * 2000
        assert any(r["node_id"] == "display" for r in record["node_records"])
        assert not any(r["node_id"] == "delay" for r in record["node_records"])
        assert client.get(f"{base}/displays/invalid", headers=headers).status_code == 404
    sessions.engine.dispose()


def test_idle_node_pack_refresh_replaces_catalog_and_handlers_together(tmp_path):
    """真实 hello-world 节点包升级/禁用后，旧目录缓存不能继续提供旧定义。"""
    import json
    from shutil import copytree
    from unittest.mock import Mock
    from backend.service.application.workflows.preview_process import refresh_preview_node_resources
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
    assert refresh_preview_node_resources(loader, catalog, registry_loader, models, cache, signature) == signature
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
    signature = refresh_preview_node_resources(loader, catalog, registry_loader, models, cache, signature)
    assert registry.get_node_definition(node_id).node_pack_version == "0.1.1"
    assert "new_parameter" in registry.get_node_definition(node_id).parameter_schema["properties"]
    models.close_all.assert_called_once()
    cache.clear.assert_called_once()
    manifest["enabledByDefault"] = False
    path.write_text(json.dumps(manifest), encoding="utf8")
    refresh_preview_node_resources(loader, catalog, registry_loader, models, cache, signature)
    assert node_id not in {d.node_type_id for d in catalog.get_workflow_node_definitions()}
    from backend.service.application.errors import ServiceConfigurationError
    with pytest.raises(ServiceConfigurationError, match="节点"):
        registry.get_node_definition(node_id)
