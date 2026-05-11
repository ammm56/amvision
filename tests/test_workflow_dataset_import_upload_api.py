"""workflow runtime 数据集上传节点 API 测试。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.service.api.app import create_app
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.settings import (
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)
from tests.api_test_support import build_test_headers, create_test_runtime
from tests.test_dataset_import_api import _build_coco_zip_bytes


def test_workflow_app_runtime_invoke_upload_submits_dataset_import_package(tmp_path: Path) -> None:
    """验证 workflow app runtime 可以通过 multipart 上传 zip 并提交 DatasetImport 节点。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-dataset-import-upload.db",
    )
    application = create_app(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    client = TestClient(application)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=client.app.state.node_catalog_registry,
    )
    template, flow_application = _load_dataset_import_example_documents()
    workflow_service.save_template(
        project_id="project-1",
        template=template,
    )
    workflow_service.save_application(
        project_id="project-1",
        application=flow_application,
    )

    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "application_id": "dataset-import-upload-app",
                    "display_name": "Dataset Import Upload Runtime",
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=headers,
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload",
                headers=headers,
                data={
                    "input_bindings_json": json.dumps(
                        {
                            "request_payload": {
                                "value": {
                                    "project_id": "project-1",
                                    "dataset_id": "dataset-1",
                                    "format_type": "coco-detection",
                                    "task_type": "detection",
                                }
                            }
                        }
                    )
                },
                files={
                    "request_package": (
                        "coco-dataset.zip",
                        _build_coco_zip_bytes(),
                        "application/zip",
                    )
                },
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=headers,
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert invoke_response.status_code == 200
    assert stop_response.status_code == 200

    run_payload = invoke_response.json()
    import_body = run_payload["outputs"]["submission_body"]
    request_payload = run_payload["input_payload"]["request_payload"]["value"]
    request_package_payload = run_payload["input_payload"]["request_package"]
    assert run_payload["state"] == "succeeded"
    assert import_body["status"] == "received"
    assert import_body["processing_state"] == "queued"
    assert import_body["queue_name"] == "dataset-imports"
    assert import_body["queue_task_id"]
    assert import_body["task_id"]
    assert import_body["package_path"].endswith("package.zip")
    assert request_payload["project_id"] == "project-1"
    assert request_payload["dataset_id"] == "dataset-1"
    assert request_payload["format_type"] == "coco-detection"
    assert request_package_payload["package_file_name"] == "coco-dataset.zip"
    assert request_package_payload["package_bytes"]["binary_redacted"] is True
    assert request_package_payload["package_bytes"]["byte_length"] > 0


def test_workflow_preview_run_accepts_dataset_package_base64_payload(tmp_path: Path) -> None:
    """验证 preview run 可以通过 JSON base64 字符串提交 dataset-package.v1 输入。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-dataset-import-preview-upload.db",
    )
    application = create_app(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    client = TestClient(application)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=client.app.state.node_catalog_registry,
    )
    template, flow_application = _load_dataset_import_example_documents()
    workflow_service.save_template(project_id="project-1", template=template)
    workflow_service.save_application(project_id="project-1", application=flow_application)
    headers = build_test_headers(scopes="workflows:read,workflows:write")

    try:
        with client:
            preview_response = client.post(
                "/api/v1/workflows/preview-runs",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "application_ref": {"application_id": "dataset-import-upload-app"},
                    "input_bindings": {
                        "request_payload": {
                            "value": {
                                "project_id": "project-1",
                                "dataset_id": "dataset-1",
                                "format_type": "coco-detection",
                                "task_type": "detection",
                            }
                        },
                        "request_package": {
                            "package_file_name": "coco-dataset.zip",
                            "package_bytes": base64.b64encode(_build_coco_zip_bytes()).decode("ascii"),
                            "media_type": "application/zip",
                        },
                    },
                    "execution_metadata": {
                        "scenario": "dataset-import-upload-preview",
                        "trigger_source": "editor-preview",
                    },
                    "timeout_seconds": 30,
                },
            )
    finally:
        session_factory.engine.dispose()

    assert preview_response.status_code == 201

    preview_payload = preview_response.json()
    import_body = preview_payload["outputs"]["submission_body"]
    assert preview_payload["state"] == "succeeded"
    assert import_body["status"] == "received"
    assert import_body["processing_state"] == "queued"
    assert import_body["package_size"] == len(_build_coco_zip_bytes())


def _load_dataset_import_example_documents() -> tuple[WorkflowGraphTemplate, FlowApplication]:
    """加载 DatasetImport 上传正式示例 template 与 application。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template = WorkflowGraphTemplate.model_validate(
        json.loads((example_dir / "dataset_import_upload.template.json").read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads((example_dir / "dataset_import_upload.application.json").read_text(encoding="utf-8"))
    )
    return template, application