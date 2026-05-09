"""workflow runtime 数据集上传节点 API 测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
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
    workflow_service.save_template(
        project_id="project-1",
        template=_build_dataset_import_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_dataset_import_application(),
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
    import_body = run_payload["outputs"]["import_body"]
    request_package_payload = run_payload["input_payload"]["request_package"]
    assert run_payload["state"] == "succeeded"
    assert import_body["status"] == "received"
    assert import_body["processing_state"] == "queued"
    assert import_body["queue_name"] == "dataset-imports"
    assert import_body["queue_task_id"]
    assert import_body["task_id"]
    assert import_body["package_path"].endswith("package.zip")
    assert request_package_payload["package_file_name"] == "coco-dataset.zip"
    assert request_package_payload["package_bytes"]["binary_redacted"] is True
    assert request_package_payload["package_bytes"]["byte_length"] > 0


def _build_dataset_import_template() -> WorkflowGraphTemplate:
    """构造 DatasetImport 上传提交模板。"""

    return WorkflowGraphTemplate(
        template_id="dataset-import-upload-template",
        template_version="1.0.0",
        display_name="Dataset Import Upload Template",
        nodes=(
            WorkflowGraphNode(
                node_id="submit_import",
                node_type_id="core.service.dataset-import.submit",
                parameters={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                },
            ),
        ),
        edges=(),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_package",
                display_name="Request Package",
                payload_type_id="dataset-package.v1",
                target_node_id="submit_import",
                target_port="package",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="import_body",
                display_name="Import Body",
                payload_type_id="response-body.v1",
                source_node_id="submit_import",
                source_port="body",
            ),
        ),
    )


def _build_dataset_import_application() -> FlowApplication:
    """构造 DatasetImport 上传提交流程应用。"""

    return FlowApplication(
        application_id="dataset-import-upload-app",
        display_name="Dataset Import Upload App",
        runtime_mode="python-json-workflow",
        template_ref=FlowTemplateReference(
            template_id="dataset-import-upload-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
            metadata={},
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_package",
                direction="input",
                template_port_id="request_package",
                binding_kind="workflow-execute-input",
                config={
                    "payload_type_id": "dataset-package.v1",
                    "content_type": "application/zip",
                },
                metadata={},
            ),
            FlowApplicationBinding(
                binding_id="import_body",
                direction="output",
                template_port_id="import_body",
                binding_kind="workflow-execute-output",
                config={"payload_type_id": "response-body.v1"},
                metadata={},
            ),
        ),
        metadata={},
    )