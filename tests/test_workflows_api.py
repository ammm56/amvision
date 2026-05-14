"""workflow 模板与流程应用 API 测试。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import (
    BackendServiceCustomNodesConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)
from tests.api_test_support import build_test_headers, create_test_runtime


def test_validate_save_and_get_workflow_template_and_application(tmp_path: Path) -> None:
    """验证 workflow 模板和流程应用可以通过 API 完成校验、保存和读取。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    template_payload = _build_template_payload()
    application_payload = _build_application_payload()

    try:
        with client:
            validate_template_response = client.post(
                "/api/v1/workflows/templates/validate",
                headers=_build_workflow_read_headers(),
                json={"template": template_payload},
            )
            save_template_response = client.put(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0",
                headers=_build_workflow_write_headers(),
                json={"template": template_payload},
            )
            get_template_response = client.get(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0",
                headers=_build_workflow_read_headers(),
            )
            validate_application_response = client.post(
                "/api/v1/workflows/applications/validate",
                headers=_build_workflow_read_headers(),
                json={
                    "project_id": "project-1",
                    "application": application_payload,
                },
            )
            save_application_response = client.put(
                "/api/v1/workflows/projects/project-1/applications/inspection-api-app",
                headers=_build_workflow_write_headers(),
                json={"application": application_payload},
            )
            get_application_response = client.get(
                "/api/v1/workflows/projects/project-1/applications/inspection-api-app",
                headers=_build_workflow_read_headers(),
            )

        assert validate_template_response.status_code == 200
        assert validate_template_response.json()["valid"] is True
        assert validate_template_response.json()["node_count"] == 3

        assert save_template_response.status_code == 201
        template_object_key = save_template_response.json()["object_key"]
        assert template_object_key.endswith("/templates/inspection-demo/versions/1.0.0/template.json")
        assert dataset_storage.resolve(template_object_key).is_file()

        assert get_template_response.status_code == 200
        assert get_template_response.json()["template"]["template_id"] == "inspection-demo"

        assert validate_application_response.status_code == 200
        assert validate_application_response.json()["binding_count"] == 2

        assert save_application_response.status_code == 201
        application_object_key = save_application_response.json()["object_key"]
        assert application_object_key.endswith("/applications/inspection-api-app/application.json")
        assert dataset_storage.resolve(application_object_key).is_file()
        assert save_application_response.json()["application"]["template_ref"]["source_uri"] == template_object_key

        assert get_application_response.status_code == 200
        assert get_application_response.json()["application"]["application_id"] == "inspection-api-app"
        assert get_application_response.json()["application"]["template_ref"]["source_uri"] == template_object_key
    finally:
        session_factory.engine.dispose()


def test_validate_flow_application_supports_embedded_template_override(tmp_path: Path) -> None:
    """验证流程应用校验接口支持直接使用请求体中的模板覆盖。"""

    client, session_factory, _ = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/workflows/applications/validate",
                headers=_build_workflow_read_headers(),
                json={
                    "project_id": "project-1",
                    "application": _build_application_payload(),
                    "template": _build_template_payload(),
                },
            )

        assert response.status_code == 200
        assert response.json()["valid"] is True
        assert response.json()["template_id"] == "inspection-demo"
    finally:
        session_factory.engine.dispose()


def test_workflow_authoring_catalog_and_resource_management_endpoints(tmp_path: Path) -> None:
    """验证节点目录读取、模板版本浏览和流程应用列表删除接口可用。"""

    client, session_factory, _ = _create_test_client(tmp_path)
    template_v1_payload = _build_template_payload()
    template_v2_payload = json.loads(json.dumps(template_v1_payload))
    template_v2_payload["template_version"] = "1.1.0"
    template_v2_payload["nodes"][1]["parameters"]["score_threshold"] = 0.5

    application_payload = _build_application_payload()
    application_payload["template_ref"]["template_version"] = "1.1.0"

    try:
        with client:
            node_catalog_response = client.get(
                "/api/v1/workflows/node-catalog",
                headers=_build_workflow_read_headers(),
            )
            save_template_v1_response = client.put(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0",
                headers=_build_workflow_write_headers(),
                json={"template": template_v1_payload},
            )
            save_template_v2_response = client.put(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.1.0",
                headers=_build_workflow_write_headers(),
                json={"template": template_v2_payload},
            )
            save_application_response = client.put(
                "/api/v1/workflows/projects/project-1/applications/inspection-api-app",
                headers=_build_workflow_write_headers(),
                json={"application": application_payload},
            )
            list_templates_response = client.get(
                "/api/v1/workflows/projects/project-1/templates",
                headers=_build_workflow_read_headers(),
            )
            list_template_versions_response = client.get(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions",
                headers=_build_workflow_read_headers(),
            )
            list_applications_response = client.get(
                "/api/v1/workflows/projects/project-1/applications",
                headers=_build_workflow_read_headers(),
            )
            delete_template_response = client.delete(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0",
                headers=_build_workflow_write_headers(),
            )
            list_template_versions_after_delete_response = client.get(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions",
                headers=_build_workflow_read_headers(),
            )
            get_deleted_template_response = client.get(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0",
                headers=_build_workflow_read_headers(),
            )
            delete_application_response = client.delete(
                "/api/v1/workflows/projects/project-1/applications/inspection-api-app",
                headers=_build_workflow_write_headers(),
            )
            list_applications_after_delete_response = client.get(
                "/api/v1/workflows/projects/project-1/applications",
                headers=_build_workflow_read_headers(),
            )
            get_deleted_application_response = client.get(
                "/api/v1/workflows/projects/project-1/applications/inspection-api-app",
                headers=_build_workflow_read_headers(),
            )

        assert node_catalog_response.status_code == 200
        node_catalog_payload = node_catalog_response.json()
        assert node_catalog_payload["node_pack_manifests"][0]["id"] == "opencv.basic-nodes"
        assert any(
            item["node_type_id"] == "custom.opencv.draw-detections"
            for item in node_catalog_payload["node_definitions"]
        )
        assert any(
            group["category"] == "opencv.render"
            and any(
                node_item["node_type_id"] == "custom.opencv.draw-detections"
                for node_item in group["node_definitions"]
            )
            for group in node_catalog_payload["palette_groups"]
        )

        assert save_template_v1_response.status_code == 201
        assert save_template_v2_response.status_code == 201
        assert save_application_response.status_code == 201

        assert list_templates_response.status_code == 200
        templates_payload = list_templates_response.json()
        assert len(templates_payload) == 1
        assert templates_payload[0]["template_id"] == "inspection-demo"
        assert templates_payload[0]["created_at"].endswith("Z")
        assert templates_payload[0]["updated_at"].endswith("Z")
        assert templates_payload[0]["latest_template_version"] == "1.1.0"
        assert templates_payload[0]["version_count"] == 2
        assert templates_payload[0]["versions"] == ["1.0.0", "1.1.0"]

        assert list_template_versions_response.status_code == 200
        template_versions_payload = list_template_versions_response.json()
        assert [item["template_version"] for item in template_versions_payload] == ["1.0.0", "1.1.0"]
        assert template_versions_payload[0]["object_key"].endswith(
            "/templates/inspection-demo/versions/1.0.0/template.json"
        )
        assert template_versions_payload[0]["created_at"].endswith("Z")
        assert template_versions_payload[0]["updated_at"].endswith("Z")
        assert template_versions_payload[1]["node_count"] == 3

        assert list_applications_response.status_code == 200
        applications_payload = list_applications_response.json()
        assert len(applications_payload) == 1
        assert applications_payload[0]["application_id"] == "inspection-api-app"
        assert applications_payload[0]["created_at"].endswith("Z")
        assert applications_payload[0]["updated_at"].endswith("Z")
        assert applications_payload[0]["template_version"] == "1.1.0"
        assert applications_payload[0]["binding_count"] == 2

        assert delete_template_response.status_code == 204
        assert list_template_versions_after_delete_response.status_code == 200
        assert [
            item["template_version"]
            for item in list_template_versions_after_delete_response.json()
        ] == ["1.1.0"]
        assert get_deleted_template_response.status_code == 404

        assert delete_application_response.status_code == 204
        assert list_applications_after_delete_response.status_code == 200
        assert list_applications_after_delete_response.json() == []
        assert get_deleted_application_response.status_code == 404
    finally:
        session_factory.engine.dispose()


def test_workflow_node_catalog_supports_filters(tmp_path: Path) -> None:
    """验证节点目录接口支持按节点包、分类、payload 类型和关键词过滤。"""

    client, session_factory, _ = _create_test_client(tmp_path)

    try:
        with client:
            by_node_pack_response = client.get(
                "/api/v1/workflows/node-catalog",
                params={"node_pack_id": "opencv.basic-nodes"},
                headers=_build_workflow_read_headers(),
            )
            by_category_response = client.get(
                "/api/v1/workflows/node-catalog",
                params={"category": "opencv.render"},
                headers=_build_workflow_read_headers(),
            )
            by_payload_type_response = client.get(
                "/api/v1/workflows/node-catalog",
                params={"payload_type_id": "detections.v1"},
                headers=_build_workflow_read_headers(),
            )
            by_keyword_response = client.get(
                "/api/v1/workflows/node-catalog",
                params={"q": "draw detections"},
                headers=_build_workflow_read_headers(),
            )

        assert by_node_pack_response.status_code == 200
        by_node_pack_payload = by_node_pack_response.json()
        assert [item["id"] for item in by_node_pack_payload["node_pack_manifests"]] == ["opencv.basic-nodes"]
        assert by_node_pack_payload["node_definitions"]
        assert by_node_pack_payload["palette_groups"]
        assert all(
            item["node_pack_id"] == "opencv.basic-nodes"
            for item in by_node_pack_payload["node_definitions"]
        )
        assert all(
            all(node_item["node_pack_id"] == "opencv.basic-nodes" for node_item in group["node_definitions"])
            for group in by_node_pack_payload["palette_groups"]
        )
        assert any(
            item["node_type_id"] == "custom.opencv.draw-detections"
            for item in by_node_pack_payload["node_definitions"]
        )

        assert by_category_response.status_code == 200
        by_category_payload = by_category_response.json()
        assert by_category_payload["node_definitions"]
        assert by_category_payload["palette_groups"]
        assert all(
            item["category"].startswith("opencv.render")
            for item in by_category_payload["node_definitions"]
        )
        assert all(group["category"].startswith("opencv.render") for group in by_category_payload["palette_groups"])
        assert any(
            item["node_type_id"] == "custom.opencv.draw-detections"
            for item in by_category_payload["node_definitions"]
        )

        assert by_payload_type_response.status_code == 200
        by_payload_type_payload = by_payload_type_response.json()
        assert any(
            item["payload_type_id"] == "detections.v1"
            for item in by_payload_type_payload["payload_contracts"]
        )
        assert any(
            item["node_type_id"] == "custom.opencv.draw-detections"
            for item in by_payload_type_payload["node_definitions"]
        )

        assert by_keyword_response.status_code == 200
        by_keyword_payload = by_keyword_response.json()
        assert by_keyword_payload["node_definitions"]
        assert by_keyword_payload["palette_groups"]
        assert any(
            item["node_type_id"] == "custom.opencv.draw-detections"
            for item in by_keyword_payload["node_definitions"]
        )
        assert all(
            "draw detections" in (
                f"{item['node_type_id']} {item['display_name']} {item['description']} {item['category']}".lower()
            )
            for item in by_keyword_payload["node_definitions"]
        )
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage]:
    """创建 workflow API 测试客户端。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflows-api.db",
    )
    plugins_root_dir = _create_node_pack_fixture(tmp_path)
    application = create_app(
        settings=BackendServiceSettings(
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(plugins_root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    return TestClient(application), session_factory, dataset_storage


def _build_workflow_write_headers() -> dict[str, str]:
    """构建具备 workflows:write scope 的测试请求头。"""

    return build_test_headers(scopes="workflows:write,workflows:read")


def _build_workflow_read_headers() -> dict[str, str]:
    """构建具备 workflows:read scope 的测试请求头。"""

    return build_test_headers(scopes="workflows:read")


def _build_template_payload() -> dict[str, object]:
    """构造测试使用的最小 workflow 模板 JSON。"""

    return {
        "format_id": "amvision.workflow-graph-template.v1",
        "template_id": "inspection-demo",
        "template_version": "1.0.0",
        "display_name": "Inspection Demo",
        "description": "模板负责图结构，应用负责现场端点绑定。",
        "nodes": [
            {
                "node_id": "input_image",
                "node_type_id": "core.io.template-input.image",
                "parameters": {},
                "ui_state": {"position": {"x": 20, "y": 60}},
                "metadata": {},
            },
            {
                "node_id": "detect",
                "node_type_id": "core.model.yolox-detection",
                "parameters": {"score_threshold": 0.3},
                "ui_state": {"position": {"x": 280, "y": 60}},
                "metadata": {},
            },
            {
                "node_id": "draw_response",
                "node_type_id": "custom.opencv.draw-detections",
                "parameters": {"line_thickness": 2, "render_preview": True},
                "ui_state": {"position": {"x": 560, "y": 60}},
                "metadata": {},
            },
        ],
        "edges": [
            {
                "edge_id": "edge-input-image",
                "source_node_id": "input_image",
                "source_port": "image",
                "target_node_id": "detect",
                "target_port": "image",
                "metadata": {},
            },
            {
                "edge_id": "edge-input-preview",
                "source_node_id": "input_image",
                "source_port": "image",
                "target_node_id": "draw_response",
                "target_port": "image",
                "metadata": {},
            },
            {
                "edge_id": "edge-detect-draw",
                "source_node_id": "detect",
                "source_port": "detections",
                "target_node_id": "draw_response",
                "target_port": "detections",
                "metadata": {},
            },
        ],
        "template_inputs": [
            {
                "input_id": "request_image",
                "display_name": "Request Image",
                "payload_type_id": "image-ref.v1",
                "target_node_id": "input_image",
                "target_port": "payload",
                "metadata": {},
            }
        ],
        "template_outputs": [
            {
                "output_id": "inspection_response",
                "display_name": "Inspection Response",
                "payload_type_id": "http-response.v1",
                "source_node_id": "draw_response",
                "source_port": "response",
                "metadata": {},
            }
        ],
        "metadata": {},
    }


def _build_application_payload() -> dict[str, object]:
    """构造测试使用的最小流程应用 JSON。"""

    return {
        "format_id": "amvision.flow-application.v1",
        "application_id": "inspection-api-app",
        "display_name": "Inspection API App",
        "template_ref": {
            "template_id": "inspection-demo",
            "template_version": "1.0.0",
            "source_kind": "json-file",
            "source_uri": "workflows/inspection-demo.template.json",
            "metadata": {},
        },
        "runtime_mode": "python-json-workflow",
        "description": "应用只负责端点绑定。",
        "bindings": [
            {
                "binding_id": "api-entry",
                "direction": "input",
                "template_port_id": "request_image",
                "binding_kind": "api-request",
                "config": {"route": "/api/v1/inspect", "method": "POST"},
                "metadata": {},
            },
            {
                "binding_id": "api-return",
                "direction": "output",
                "template_port_id": "inspection_response",
                "binding_kind": "http-response",
                "config": {"status_code": 200},
                "metadata": {},
            },
        ],
        "metadata": {},
    }


def _create_node_pack_fixture(tmp_path: Path) -> Path:
    """创建 workflow API 测试使用的最小自定义节点包目录。"""

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
        "description": "测试用 OpenCV workflow 节点包。",
        "category": "custom-node-pack",
        "capabilities": ["pipeline.node", "result.postprocess"],
        "permissionScopes": ["task.read", "task.result.write"],
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
                "description": "通过 OpenCV 把 detection 结果叠加到图片上，并生成结构化 HTTP 回包。",
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
                "parameter_schema": {
                    "type": "object",
                    "properties": {
                        "line_thickness": {"type": "integer", "minimum": 1},
                        "render_preview": {"type": "boolean"},
                    },
                },
                "capability_tags": ["opencv.draw", "vision.render", "result.aggregate"],
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
