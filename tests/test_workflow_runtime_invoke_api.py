"""workflow runtime 通用 invoke 输入边界 API 测试。"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.service.api.app import create_app
from backend.service.api.rest.v1.routes.workflow_runtime import _build_workflow_runtime_service
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.settings import (
    BackendServiceCustomNodesConfig,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)
from tests.api_test_support import build_test_headers, build_valid_test_png_bytes, create_test_runtime
from tests.test_workflow_barcode_protocol_nodes import _build_mixed_barcode_test_png_bytes


def test_workflow_app_runtime_invoke_api_accepts_image_base64_for_barcode_result_display(
    tmp_path: Path,
) -> None:
    """验证通用 invoke 路由可以按 image-base64.v1 执行条码展示 app。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-runtime-invoke-barcode.db",
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="barcode_result_display",
            )

            workflow_runtime_id = _create_and_start_runtime(
                client=client,
                headers=headers,
                application_id="barcode-result-display-app",
                display_name="Barcode Result Display Runtime",
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                headers=headers,
                json={
                    "input_bindings": {
                        "request_image": _build_image_base64_payload(_build_mixed_barcode_test_png_bytes())
                    },
                    "execution_metadata": {
                        "scenario": "barcode-result-display-api",
                        "trigger_source": "sync-api",
                    },
                },
            )
            health_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                headers=headers,
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=headers,
            )
    finally:
        session_factory.engine.dispose()

    assert invoke_response.status_code == 200
    assert health_response.status_code == 200
    assert stop_response.status_code == 200

    run_payload = invoke_response.json()
    response_payload = run_payload["outputs"]["http_response"]
    response_body = response_payload["body"]
    response_data = response_body["data"]

    assert run_payload["state"] == "succeeded"
    assert response_payload["status_code"] == 200
    assert response_body["code"] == 0
    assert response_body["message"] == "decoded"
    assert response_data["count"] == 2
    assert set(response_data["matched_formats"]) == {"QR Code", "Code 128"}
    assert response_data["annotated_image"]["image"]["transport_kind"] == "inline-base64"

    health_summary = health_response.json()["health_summary"]
    assert health_summary["local_buffer_broker"]["connected"] is True
    assert health_summary["parent_local_buffer_broker_channel"]["configured"] is True


def test_workflow_app_runtime_invoke_api_accepts_image_base64_for_opencv_process_save_image(
    tmp_path: Path,
) -> None:
    """验证通用 invoke 路由可以按 image-base64.v1 读取 base64 图片输入。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-runtime-invoke-opencv.db",
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="opencv_process_save_image",
            )
            workflow_runtime_id = _create_and_start_runtime(
                client=client,
                headers=headers,
                application_id="opencv-process-save-image-app",
                display_name="OpenCV Process Save Image Runtime",
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                headers=headers,
                json={
                    "input_bindings": {
                        "request_image": _build_image_base64_payload(build_valid_test_png_bytes())
                    },
                    "execution_metadata": {
                        "scenario": "opencv-process-save-image-api",
                        "trigger_source": "sync-api",
                    },
                },
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=headers,
            )
    finally:
        session_factory.engine.dispose()

    assert invoke_response.status_code == 200
    assert stop_response.status_code == 200

    run_payload = invoke_response.json()
    response_payload = run_payload["outputs"]["http_response"]
    response_body = response_payload["body"]
    image_payload = response_body["image"]

    assert run_payload["state"] == "succeeded"
    assert response_payload["status_code"] == 200
    assert response_body["type"] == "image-preview"
    assert response_body["title"] == "Saved Edge Image"
    assert image_payload["transport_kind"] == "storage-ref"
    assert dataset_storage.resolve(image_payload["object_key"]).is_file()


def test_workflow_app_runtime_invoke_api_accepts_image_base64_for_dual_input_opencv_process_save_image(
    tmp_path: Path,
) -> None:
    """验证双输入 OpenCV app 可以只通过 HTTP base64 binding 调用。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-runtime-invoke-opencv-dual-input.db",
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="opencv_process_save_image_zeromq",
            )
            workflow_runtime_id = _create_and_start_runtime(
                client=client,
                headers=headers,
                application_id="opencv-process-save-image-zeromq-app",
                display_name="OpenCV Process Save Image ZeroMQ Runtime",
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                headers=headers,
                json={
                    "input_bindings": {
                        "request_image_base64": _build_image_base64_payload(build_valid_test_png_bytes())
                    },
                    "execution_metadata": {
                        "scenario": "opencv-process-save-image-zeromq",
                        "trigger_source": "sync-api",
                    },
                },
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=headers,
            )
    finally:
        session_factory.engine.dispose()

    assert invoke_response.status_code == 200
    assert stop_response.status_code == 200

    run_payload = invoke_response.json()
    response_payload = run_payload["outputs"]["http_response"]
    response_body = response_payload["body"]
    image_payload = response_body["image"]

    assert run_payload["state"] == "succeeded"
    assert response_payload["status_code"] == 200
    assert response_body["type"] == "image-preview"
    assert response_body["title"] == "Saved Edge Image"
    assert image_payload["transport_kind"] == "storage-ref"
    assert dataset_storage.resolve(image_payload["object_key"]).is_file()


def test_workflow_app_runtime_invoke_api_invalid_image_base64_keeps_runtime_running(
    tmp_path: Path,
) -> None:
    """验证坏 base64 只会让当前 run 失败，不会把 runtime 打成 failed。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-runtime-invoke-invalid-base64.db",
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="opencv_process_save_image",
            )
            workflow_runtime_id = _create_and_start_runtime(
                client=client,
                headers=headers,
                application_id="opencv-process-save-image-app",
                display_name="OpenCV Process Save Image Runtime",
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                headers=headers,
                json={
                    "input_bindings": {
                        "request_image": {
                            "image_base64": "not-base64@@@",
                            "media_type": "image/png",
                        }
                    },
                    "execution_metadata": {
                        "scenario": "opencv-process-save-image-invalid-base64-api",
                        "trigger_source": "sync-api",
                    },
                },
            )
            health_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                headers=headers,
            )
            second_start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=headers,
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=headers,
            )
    finally:
        session_factory.engine.dispose()

    assert invoke_response.status_code == 200
    assert health_response.status_code == 200
    assert second_start_response.status_code == 200
    assert stop_response.status_code == 200

    run_payload = invoke_response.json()
    assert run_payload["state"] == "failed"
    assert run_payload["error_message"] == "image-base64 payload 不是有效的 base64 图片"
    assert run_payload["metadata"]["error_details"]["error_code"] == "invalid_request"
    assert run_payload["metadata"]["error_details"]["node_id"] == "decode_request_image"

    health_payload = health_response.json()
    assert health_payload["observed_state"] == "running"
    assert health_payload["last_error"] is None

    second_start_payload = second_start_response.json()
    assert second_start_payload["observed_state"] == "running"
    assert second_start_payload["worker_process_id"] == health_payload["worker_process_id"]


def test_workflow_runtime_service_builder_reads_local_buffer_channel_only_when_requested(
    tmp_path: Path,
) -> None:
    """验证 workflow runtime 路由只在显式需要时才读取 broker event channel。"""

    client, session_factory, _ = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-runtime-invoke-route-channel.db",
    )
    try:
        request = SimpleNamespace(app=client.app)
        supervisor = client.app.state.local_buffer_broker_supervisor
        original_get_event_channel = supervisor.get_event_channel
        channel_read_count = 0

        def counting_get_event_channel() -> object:
            nonlocal channel_read_count
            channel_read_count += 1
            return None

        supervisor.get_event_channel = counting_get_event_channel
        try:
            default_service = _build_workflow_runtime_service(request)
            preview_service = _build_workflow_runtime_service(
                request,
                include_local_buffer_broker_event_channel=True,
            )
        finally:
            supervisor.get_event_channel = original_get_event_channel
    finally:
        session_factory.engine.dispose()

    assert default_service.local_buffer_broker_event_channel is None
    assert preview_service.local_buffer_broker_event_channel is None
    assert channel_read_count == 1


def test_workflow_app_runtime_invoke_upload_rejects_image_file_for_non_dataset_package_binding(
    tmp_path: Path,
) -> None:
    """验证 multipart invoke/upload 当前不会把图片文件直接映射为 request_image 输入。"""

    client, session_factory, _ = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-runtime-invoke-upload-image.db",
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _save_example_documents(
                client=client,
                dataset_storage=client.app.state.dataset_storage,
                example_name="opencv_process_save_image",
            )
            workflow_runtime_id = _create_and_start_runtime(
                client=client,
                headers=headers,
                application_id="opencv-process-save-image-app",
                display_name="OpenCV Process Save Image Runtime",
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke/upload",
                headers=headers,
                files={
                    "request_image": (
                        "input.png",
                        build_valid_test_png_bytes(),
                        "image/png",
                    )
                },
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=headers,
            )
    finally:
        session_factory.engine.dispose()

    assert invoke_response.status_code == 400
    assert stop_response.status_code == 200

    error_payload = invoke_response.json()["error"]
    assert error_payload["code"] == "invalid_request"
    assert error_payload["message"] == "当前 multipart 上传入口仅支持 dataset-package.v1 输入绑定"
    assert error_payload["details"] == {
        "binding_id": "request_image",
        "payload_type_id": "image-base64.v1",
    }


def _create_runtime_api_client(
    tmp_path: Path,
    *,
    database_name: str,
) -> tuple[TestClient, object, object]:
    """创建加载仓库 custom_nodes 的 workflow runtime API 测试客户端。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name=database_name,
    )
    custom_nodes_root_dir = Path(__file__).resolve().parents[1] / "custom_nodes"
    application = create_app(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(custom_nodes_root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    return TestClient(application), session_factory, dataset_storage


def _save_example_documents(
    *,
    client: TestClient,
    dataset_storage: object,
    example_name: str,
) -> tuple[WorkflowGraphTemplate, FlowApplication]:
    """把 docs/examples/workflows 中的一组示例保存到当前测试环境。"""

    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=client.app.state.node_catalog_registry,
    )
    template, application = _load_example_documents(example_name)
    workflow_service.save_template(project_id="project-1", template=template)
    workflow_service.save_application(project_id="project-1", application=application)
    return template, application


def _load_example_documents(example_name: str) -> tuple[WorkflowGraphTemplate, FlowApplication]:
    """加载指定 workflow 示例的 template 与 application 文档。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template = WorkflowGraphTemplate.model_validate(
        json.loads((example_dir / f"{example_name}.template.json").read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads((example_dir / f"{example_name}.application.json").read_text(encoding="utf-8"))
    )
    return template, application


def _create_and_start_runtime(
    *,
    client: TestClient,
    headers: dict[str, str],
    application_id: str,
    display_name: str,
) -> str:
    """创建并启动一个 workflow app runtime。"""

    create_runtime_response = client.post(
        "/api/v1/workflows/app-runtimes",
        headers=headers,
        json={
            "project_id": "project-1",
            "application_id": application_id,
            "display_name": display_name,
        },
    )
    assert create_runtime_response.status_code == 201
    workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
    start_response = client.post(
        f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
        headers=headers,
    )
    assert start_response.status_code == 200
    return workflow_runtime_id


def _build_image_base64_payload(image_bytes: bytes) -> dict[str, object]:
    """构造 image-base64.v1 输入 payload。"""

    return {
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
        "media_type": "image/png",
    }