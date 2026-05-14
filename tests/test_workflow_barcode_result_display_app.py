"""barcode 结果展示 workflow app 示例测试。"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.runtime_service import (
    WorkflowPreviewRunCreateRequest,
    WorkflowRuntimeService,
)
from backend.service.settings import (
    BackendServiceCustomNodesConfig,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)
from tests.api_test_support import create_test_runtime
from tests.test_workflow_barcode_protocol_nodes import _build_mixed_barcode_test_png_bytes


def test_barcode_result_display_example_preview_run_returns_annotated_image_and_table(tmp_path: Path) -> None:
    """验证 barcode 示例 template 与 application 可以真实跑出预览图和结果表格。"""

    service, dataset_storage = _build_barcode_example_runtime_service(tmp_path)
    template, application = _load_barcode_example_documents()
    dataset_storage.write_bytes("inputs/mixed-readable.png", _build_mixed_barcode_test_png_bytes())

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=application,
            template=template,
            input_bindings={
                "request_image": {
                    "image_base64": base64.b64encode(
                        _build_mixed_barcode_test_png_bytes()
                    ).decode("ascii"),
                    "media_type": "image/png",
                }
            },
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    response_payload = preview_run.outputs["http_response"]
    assert response_payload["status_code"] == 200

    response_body = response_payload["body"]
    assert response_body["code"] == 0
    assert response_body["message"] == "decoded"
    assert response_body["meta"] == {
        "app_id": "barcode-result-display-app",
        "template_id": "barcode-result-display-template",
        "node_pack": "barcode.protocol-nodes",
    }

    response_data = response_body["data"]
    assert response_data["requested_format"] == "All Readable"
    assert response_data["count"] == 2
    assert set(response_data["matched_formats"]) == {"QR Code", "Code 128"}

    annotated_image = response_data["annotated_image"]
    assert annotated_image["type"] == "image-preview"
    assert annotated_image["title"] == "Detected Barcode Image"
    assert annotated_image["image"]["transport_kind"] == "inline-base64"
    assert annotated_image["image"]["image_base64_redacted"] is True

    result_table = response_data["result_table"]
    assert result_table["type"] == "table-preview"
    assert result_table["title"] == "Barcode Results"
    assert [column["key"] for column in result_table["columns"]] == ["index", "format", "text", "valid"]
    assert result_table["row_count"] == 2
    assert {row["text"] for row in result_table["rows"]} == {"qr-multi", "code128-multi"}
    assert {row["format"] for row in result_table["rows"]} == {"QR Code", "Code 128"}
    assert {row["valid"] for row in result_table["rows"]} == {True}


def _build_barcode_example_runtime_service(tmp_path: Path) -> tuple[WorkflowRuntimeService, object]:
    """构造带仓库 custom nodes 的 workflow runtime service。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-barcode-result-display.db",
    )
    custom_nodes_root_dir = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    service = WorkflowRuntimeService(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(custom_nodes_root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
        worker_manager=SimpleNamespace(),
    )
    return service, dataset_storage


def _load_barcode_example_documents() -> tuple[WorkflowGraphTemplate, FlowApplication]:
    """加载 barcode 结果展示示例 template 与 application。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template = WorkflowGraphTemplate.model_validate(
        json.loads((example_dir / "barcode_result_display.template.json").read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads((example_dir / "barcode_result_display.application.json").read_text(encoding="utf-8"))
    )
    return template, application