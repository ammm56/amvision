"""真实受限凭据通过原 Runtime 执行链路的授权回归。"""

from tests.api_test_support import (
    build_test_headers,
    build_bearer_headers,
    issue_test_user_token,
)
from tests.test_workflow_runtime_invoke_api import (
    _create_runtime_api_client,
    _save_example_documents,
    _create_and_start_runtime,
    _build_image_base64_payload,
    _build_mixed_barcode_test_png_bytes,
    _build_file_metadata_application,
    _wait_for_workflow_run,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService


def test_read_invoke_user_runs_without_management(tmp_path):
    """独立非管理员 Token 能检测和读取，但无法改变 Runtime。"""
    client, factory, storage = _create_runtime_api_client(
        tmp_path, database_name="invoke-access.db", enable_local_buffer_broker=False
    )
    admin = build_test_headers(scopes="*")
    try:
        with client:
            _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="barcode_result_display",
            )
            runtime_id = _create_and_start_runtime(
                client=client,
                headers=admin,
                application_id="barcode-result-display-app",
                display_name="Permission test",
            )
            invoke = build_bearer_headers(
                issue_test_user_token(
                    factory,
                    username="runner",
                    scopes=("workflows:read", "workflows:invoke"),
                )
            )
            read = build_bearer_headers(
                issue_test_user_token(
                    factory, username="reader", scopes=("workflows:read",)
                )
            )
            root = f"/api/v1/workflows/app-runtimes/{runtime_id}"
            payload = {
                "input_bindings": {
                    "request_image_base64": _build_image_base64_payload(
                        _build_mixed_barcode_test_png_bytes()
                    )
                }
            }
            assert (
                client.post(root + "/invoke", headers=read, json=payload).status_code
                == 403
            )
            assert (
                client.post(
                    root + "/invoke/upload",
                    headers=read,
                    files={"image": ("image.png", b"bad", "image/png")},
                ).status_code
                == 403
            )
            assert (
                client.post(
                    root + "/invoke",
                    headers=invoke,
                    params={"response_mode": "invalid"},
                    json=payload,
                ).status_code
                == 400
            )
            response = client.post(
                root + "/invoke",
                headers=invoke,
                params={"response_mode": "run"},
                json=payload,
            )
            assert response.status_code == 200, response.text
            assert response.json()["state"] == "succeeded"
            assert client.post(root + "/runs", headers=read, json=payload).status_code == 403
            queued = client.post(root + "/runs", headers=invoke, json=payload)
            assert queued.status_code == 201, queued.text
            completed = _wait_for_workflow_run(client=client, headers=invoke, workflow_run_id=queued.json()["workflow_run_id"])
            assert completed["state"] == "succeeded"
            assert (
                response.json()["outputs"]["http_response"]["body"]["data"]["count"]
                == 2
            )
            assert (
                client.get(root + "/preview-snapshot", headers=read).status_code == 200
            )
            for action in ("start", "stop", "restart"):
                assert (
                    client.post(root + "/" + action, headers=invoke).status_code == 403
                )
            assert client.delete(root, headers=invoke).status_code == 403
            assert client.get(root, headers=read).json()["observed_state"] == "running"
            assert client.post(root + "/stop", headers=admin).status_code == 200
    finally:
        factory.engine.dispose()


def test_invoke_scope_accepts_sync_and_async_multipart_files(tmp_path):
    """无管理权限时仍可上传正式文件绑定，不能借上传入口配置节点。"""
    client, factory, storage = _create_runtime_api_client(tmp_path, database_name="invoke-file-access.db", enable_local_buffer_broker=False)
    admin = build_test_headers(scopes="*")
    service = LocalWorkflowJsonService(dataset_storage=storage, node_catalog_registry=client.app.state.node_catalog_registry)
    template, app = _build_file_metadata_application(multiple=False)
    service.save_template(project_id="project-1", template=template)
    service.save_application(project_id="project-1", application=app)
    try:
        with client:
            runtime_id = _create_and_start_runtime(client=client, headers=admin, application_id=app.application_id, display_name="Upload access")
            root = f"/api/v1/workflows/app-runtimes/{runtime_id}"
            invoke = build_bearer_headers(issue_test_user_token(factory, username="upload-runner", scopes=("workflows:read", "workflows:invoke")))
            read = build_bearer_headers(issue_test_user_token(factory, username="upload-reader", scopes=("workflows:read",)))
            files = {"request_file": ("recipe.json", b'{"threshold":0.7}', "application/json")}
            for suffix in ("/invoke/upload", "/runs/upload"):
                assert client.post(root + suffix, headers=read, files=files).status_code == 403
                response = client.post(root + suffix, headers=invoke, files=files, params={"response_mode": "run"})
                assert response.status_code == (200 if suffix.startswith('/invoke') else 201), response.text
                result = response.json() if suffix.startswith('/invoke') else _wait_for_workflow_run(client=client, headers=invoke, workflow_run_id=response.json()["workflow_run_id"])
                assert result["state"] == "succeeded"
            assert client.post(root + '/stop', headers=admin).status_code == 200
    finally:
        factory.engine.dispose()
