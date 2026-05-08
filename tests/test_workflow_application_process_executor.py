"""workflow application 隔离进程执行测试。"""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.app import create_app
from backend.service.application.workflows.process_executor import (
    WorkflowApplicationExecutionRequest,
    WorkflowApplicationProcessExecutor,
    WorkflowApplicationRuntimeExecutor,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.settings import (
    BackendServiceCustomNodesConfig,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)
from tests.api_test_support import build_test_headers, create_test_runtime


def test_workflow_application_process_executor_runs_application_in_child_process(
    tmp_path: Path,
) -> None:
    """验证 workflow application 会在独立子进程中执行并按 binding 返回结果。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-process-executor.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )
    executor = WorkflowApplicationProcessExecutor(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(custom_nodes_root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        )
    )

    try:
        execution_result = executor.execute(
            WorkflowApplicationExecutionRequest(
                project_id="project-1",
                application_id="process-echo-app",
                input_bindings={"request_text": {"value": "hello workflow app"}},
                execution_metadata={"marker": "isolated-run"},
            )
        )
    finally:
        session_factory.engine.dispose()

    response_payload = execution_result.outputs["http_response"]
    assert execution_result.project_id == "project-1"
    assert execution_result.application_id == "process-echo-app"
    assert response_payload["status_code"] == 200
    assert response_payload["body"]["message"] == "hello workflow app"
    assert response_payload["body"]["marker"] == "isolated-run"
    assert response_payload["body"]["pid"] != os.getpid()
    assert response_payload["body"]["is_daemon"] is False
    assert isinstance(response_payload["body"]["workflow_run_id"], str)
    assert execution_result.node_records[0].node_type_id == "custom.test.process-echo"


def test_workflow_application_runtime_executor_runs_application_in_current_process(
    tmp_path: Path,
) -> None:
    """验证当前运行时执行器会复用 backend-service 主进程运行时。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-executor.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
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
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )

    try:
        with TestClient(application):
            execution_result = WorkflowApplicationRuntimeExecutor(
                dataset_storage=dataset_storage,
                node_catalog_registry=node_catalog_registry,
                runtime_registry=application.state.workflow_node_runtime_registry,
                runtime_context=application.state.workflow_service_node_runtime_context,
            ).execute(
                WorkflowApplicationExecutionRequest(
                    project_id="project-1",
                    application_id="process-echo-app",
                    input_bindings={"request_text": {"value": "hello workflow runtime"}},
                    execution_metadata={"marker": "runtime-run"},
                )
            )
    finally:
        session_factory.engine.dispose()

    response_payload = execution_result.outputs["http_response"]
    assert response_payload["status_code"] == 200
    assert response_payload["body"]["message"] == "hello workflow runtime"
    assert response_payload["body"]["marker"] == "runtime-run"
    assert response_payload["body"]["pid"] == os.getpid()
    assert response_payload["body"]["is_daemon"] is False
    assert isinstance(response_payload["body"]["workflow_run_id"], str)


def test_workflow_preview_run_api_executes_saved_application_in_child_process(
    tmp_path: Path,
) -> None:
    """验证 preview run API 会在独立子进程中执行已保存 application。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-process-execute-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_response = client.post(
                "/api/v1/workflows/preview-runs",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_ref": {"application_id": "process-echo-app"},
                    "input_bindings": {"request_text": {"value": "hello execute api"}},
                    "execution_metadata": {"marker": "api-execute"},
                },
            )
            preview_run_id = create_response.json()["preview_run_id"]
            get_response = client.get(
                f"/api/v1/workflows/preview-runs/{preview_run_id}",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_response.status_code == 201
    assert get_response.status_code == 200
    preview_payload = create_response.json()
    body = preview_payload["outputs"]["http_response"]["body"]
    assert preview_payload["state"] == "succeeded"
    assert preview_payload["source_kind"] == "saved-application"
    assert body["message"] == "hello execute api"
    assert body["marker"] == "api-execute"
    assert body["pid"] != os.getpid()
    assert body["is_daemon"] is False
    assert isinstance(body["workflow_run_id"], str)
    assert get_response.json()["preview_run_id"] == preview_payload["preview_run_id"]
    assert get_response.json()["state"] == "succeeded"


def test_workflow_preview_run_api_marks_timed_out_when_child_process_exceeds_timeout(
    tmp_path: Path,
) -> None:
    """验证 preview run API 在子进程超时时会把记录落成 timed_out。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-preview-timeout-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_slow_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_slow_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_response = client.post(
                "/api/v1/workflows/preview-runs",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_ref": {"application_id": "process-slow-app"},
                    "input_bindings": {"request_text": {"value": "hello preview timeout"}},
                    "execution_metadata": {"marker": "preview-timeout"},
                    "timeout_seconds": 1,
                },
            )
            preview_run_id = create_response.json()["preview_run_id"]
            get_response = client.get(
                f"/api/v1/workflows/preview-runs/{preview_run_id}",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_response.status_code == 201
    assert get_response.status_code == 200
    preview_payload = create_response.json()
    assert preview_payload["state"] == "timed_out"
    assert preview_payload["error_message"] == "等待 workflow snapshot 子进程响应超时"
    assert preview_payload["outputs"] == {}
    assert preview_payload["template_outputs"] == {}
    assert get_response.json()["state"] == "timed_out"
    assert get_response.json()["error_message"] == "等待 workflow snapshot 子进程响应超时"


def test_workflow_execution_policy_api_creates_lists_and_applies_to_preview_and_runtime(
    tmp_path: Path,
) -> None:
    """验证 execution policy 接口可用，并会把默认 timeout 与保留策略应用到 preview 和 runtime。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-execution-policy-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_preview_policy_response = client.post(
                "/api/v1/workflows/execution-policies",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "execution_policy_id": "preview-default-policy",
                    "display_name": "Preview Default Policy",
                    "policy_kind": "preview-default",
                    "default_timeout_seconds": 9,
                    "max_run_timeout_seconds": 12,
                    "trace_level": "summary",
                    "retain_node_records_enabled": False,
                    "retain_trace_enabled": True,
                    "metadata": {"scope": "preview"},
                },
            )
            create_runtime_policy_response = client.post(
                "/api/v1/workflows/execution-policies",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "execution_policy_id": "runtime-default-policy",
                    "display_name": "Runtime Default Policy",
                    "policy_kind": "runtime-default",
                    "default_timeout_seconds": 7,
                    "max_run_timeout_seconds": 11,
                    "trace_level": "node-summary",
                    "retain_node_records_enabled": False,
                    "retain_trace_enabled": True,
                    "metadata": {"scope": "runtime"},
                },
            )
            list_policies_response = client.get(
                "/api/v1/workflows/execution-policies",
                params={"project_id": "project-1"},
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            get_runtime_policy_response = client.get(
                "/api/v1/workflows/execution-policies/runtime-default-policy",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            create_preview_response = client.post(
                "/api/v1/workflows/preview-runs",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "execution_policy_id": "preview-default-policy",
                    "application_ref": {"application_id": "process-echo-app"},
                    "input_bindings": {"request_text": {"value": "hello preview policy"}},
                    "execution_metadata": {"marker": "preview-policy"},
                },
            )
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-echo-app",
                    "execution_policy_id": "runtime-default-policy",
                    "display_name": "Policy Runtime",
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "hello runtime policy"}},
                    "execution_metadata": {"marker": "runtime-policy"},
                },
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_preview_policy_response.status_code == 201
    assert create_runtime_policy_response.status_code == 201
    assert list_policies_response.status_code == 200
    assert get_runtime_policy_response.status_code == 200
    assert create_preview_response.status_code == 201
    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert invoke_response.status_code == 200
    assert stop_response.status_code == 200

    preview_payload = create_preview_response.json()
    runtime_payload = create_runtime_response.json()
    invoke_payload = invoke_response.json()
    listed_policy_ids = {item["execution_policy_id"] for item in list_policies_response.json()}
    preview_policy_snapshot_object_key = preview_payload["metadata"]["execution_policy"]["snapshot_object_key"]
    runtime_policy_snapshot_object_key = runtime_payload["execution_policy_snapshot_object_key"]

    assert listed_policy_ids == {"preview-default-policy", "runtime-default-policy"}
    assert get_runtime_policy_response.json()["policy_kind"] == "runtime-default"
    assert preview_payload["timeout_seconds"] == 9
    assert preview_payload["node_records"] == []
    assert preview_payload["metadata"]["execution_policy"]["execution_policy_id"] == "preview-default-policy"
    assert runtime_payload["request_timeout_seconds"] == 7
    assert runtime_payload["execution_policy_snapshot_object_key"] is not None
    assert runtime_payload["metadata"]["execution_policy"]["execution_policy_id"] == "runtime-default-policy"
    assert invoke_payload["requested_timeout_seconds"] == 7
    assert invoke_payload["node_records"] == []
    assert invoke_payload["metadata"]["execution_policy"]["execution_policy_id"] == "runtime-default-policy"
    assert dataset_storage.read_json(preview_policy_snapshot_object_key)["execution_policy_id"] == "preview-default-policy"
    assert dataset_storage.read_json(runtime_policy_snapshot_object_key)["execution_policy_id"] == "runtime-default-policy"
    assert stop_response.json()["observed_state"] == "stopped"


def test_workflow_app_runtime_api_invokes_saved_application_in_worker_process(
    tmp_path: Path,
) -> None:
    """验证 app runtime API 会通过单实例 worker 执行同步 invoke。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-echo-app",
                    "display_name": "Process Echo Runtime",
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            health_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "hello runtime api"}},
                    "execution_metadata": {"marker": "runtime-api"},
                },
            )
            workflow_run_id = invoke_response.json()["workflow_run_id"]
            get_run_response = client.get(
                f"/api/v1/workflows/runs/{workflow_run_id}",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert health_response.status_code == 200
    assert invoke_response.status_code == 200
    assert get_run_response.status_code == 200
    assert stop_response.status_code == 200
    start_payload = start_response.json()
    health_payload = health_response.json()
    run_payload = invoke_response.json()
    run_body = run_payload["outputs"]["http_response"]["body"]
    assert start_payload["desired_state"] == "running"
    assert start_payload["observed_state"] == "running"
    assert isinstance(start_payload["worker_process_id"], int)
    assert health_payload["observed_state"] == "running"
    assert isinstance(health_payload["loaded_snapshot_fingerprint"], str)
    assert run_payload["state"] == "succeeded"
    assert run_payload["assigned_process_id"] == run_body["pid"]
    assert run_body["message"] == "hello runtime api"
    assert run_body["marker"] == "runtime-api"
    assert run_body["pid"] != os.getpid()
    assert run_body["is_daemon"] is False
    assert get_run_response.json()["workflow_run_id"] == run_payload["workflow_run_id"]
    assert get_run_response.json()["state"] == "succeeded"
    assert stop_response.json()["observed_state"] == "stopped"
    assert stop_response.json()["worker_process_id"] is None


def test_workflow_app_runtime_api_marks_run_timed_out_when_worker_exceeds_timeout(
    tmp_path: Path,
) -> None:
    """验证 runtime invoke 在 worker 超时后会把 WorkflowRun 落成 timed_out。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-timeout-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_slow_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_slow_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-slow-app",
                    "display_name": "Process Slow Runtime",
                    "request_timeout_seconds": 1,
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "hello runtime timeout"}},
                    "execution_metadata": {"marker": "runtime-timeout"},
                    "timeout_seconds": 1,
                },
            )
            workflow_run_id = invoke_response.json()["workflow_run_id"]
            get_run_response = client.get(
                f"/api/v1/workflows/runs/{workflow_run_id}",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            get_runtime_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            restart_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert invoke_response.status_code == 200
    assert get_run_response.status_code == 200
    assert get_runtime_response.status_code == 200
    assert restart_response.status_code == 200
    assert stop_response.status_code == 200
    run_payload = invoke_response.json()
    runtime_payload = get_runtime_response.json()
    assert run_payload["state"] == "timed_out"
    assert run_payload["error_message"] == "等待 workflow runtime worker 同步调用结果超时"
    assert run_payload["outputs"] == {}
    assert get_run_response.json()["state"] == "timed_out"
    assert runtime_payload["observed_state"] == "failed"
    assert runtime_payload["last_error"] == "等待 workflow runtime worker 同步调用结果超时"
    assert restart_response.json()["observed_state"] == "running"
    assert stop_response.json()["observed_state"] == "stopped"


def test_workflow_app_runtime_api_persists_failed_invoke_details(
    tmp_path: Path,
) -> None:
    """验证 app runtime invoke 失败时会持久化失败节点定位信息。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-process-execute-api-failure.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_fail_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_fail_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-fail-app",
                    "display_name": "Process Fail Runtime",
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "hello runtime failure"}},
                    "execution_metadata": {"marker": "api-runtime-failure"},
                },
            )
            workflow_run_id = invoke_response.json()["workflow_run_id"]
            get_run_response = client.get(
                f"/api/v1/workflows/runs/{workflow_run_id}",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            health_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert invoke_response.status_code == 200
    assert get_run_response.status_code == 200
    assert health_response.status_code == 200
    assert stop_response.status_code == 200
    run_payload = invoke_response.json()
    error_details = run_payload["metadata"]["error_details"]
    assert run_payload["state"] == "failed"
    assert run_payload["error_message"] == "workflow 节点执行失败"
    assert error_details["node_id"] == "explode"
    assert error_details["node_type_id"] == "custom.test.process-fail"
    assert error_details["runtime_kind"] == "python-callable"
    assert error_details["execution_index"] == 1
    assert error_details["sequence_index"] == 1
    assert error_details["error_type"] == "AssertionError"
    assert error_details["error_message"] == "process fail"
    assert get_run_response.json()["state"] == "failed"
    assert get_run_response.json()["metadata"]["error_details"]["node_id"] == "explode"
    assert health_response.json()["observed_state"] == "failed"
    assert health_response.json()["last_error"] == "workflow 节点执行失败"
    assert stop_response.json()["observed_state"] == "stopped"


def test_workflow_app_runtime_api_can_restart_after_failed_worker_state(
    tmp_path: Path,
) -> None:
    """验证 runtime worker 在 failed 后可以通过 restart 重新拉起。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-restart-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_fail_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_fail_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-fail-app",
                    "display_name": "Process Fail Runtime",
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            first_start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            invoke_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/invoke",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "hello runtime failure"}},
                    "execution_metadata": {"marker": "runtime-restart"},
                },
            )
            failed_health_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            second_start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            recovered_health_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert first_start_response.status_code == 200
    assert invoke_response.status_code == 200
    assert failed_health_response.status_code == 200
    assert second_start_response.status_code == 200
    assert recovered_health_response.status_code == 200
    assert stop_response.status_code == 200
    first_process_id = first_start_response.json()["worker_process_id"]
    failed_process_id = failed_health_response.json()["worker_process_id"]
    recovered_process_id = second_start_response.json()["worker_process_id"]
    assert invoke_response.json()["state"] == "failed"
    assert failed_health_response.json()["observed_state"] == "failed"
    assert failed_process_id == first_process_id
    assert second_start_response.json()["observed_state"] == "running"
    assert recovered_health_response.json()["observed_state"] == "running"
    assert recovered_process_id != first_process_id
    assert stop_response.json()["observed_state"] == "stopped"


def test_workflow_app_runtime_api_lists_instances_and_clears_them_after_stop(
    tmp_path: Path,
) -> None:
    """验证 app runtime instances 接口会返回当前单实例摘要，并在 stop 后清空。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-instances-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-echo-app",
                    "display_name": "Process Echo Runtime",
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            instances_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/instances",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            restart_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            restarted_instances_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/instances",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stopped_instances_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/instances",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert instances_response.status_code == 200
    assert restart_response.status_code == 200
    assert restarted_instances_response.status_code == 200
    assert stop_response.status_code == 200
    assert stopped_instances_response.status_code == 200
    first_instances_payload = instances_response.json()
    restarted_instances_payload = restarted_instances_response.json()
    assert len(first_instances_payload) == 1
    assert first_instances_payload[0]["workflow_runtime_id"] == create_runtime_response.json()["workflow_runtime_id"]
    assert first_instances_payload[0]["state"] == "running"
    assert first_instances_payload[0]["instance_id"].endswith("-primary")
    assert first_instances_payload[0]["process_id"] == start_response.json()["worker_process_id"]
    assert first_instances_payload[0]["current_run_id"] is None
    assert first_instances_payload[0]["started_at"] is not None
    assert len(restarted_instances_payload) == 1
    assert restarted_instances_payload[0]["state"] == "running"
    assert restarted_instances_payload[0]["instance_id"] == first_instances_payload[0]["instance_id"]
    assert restarted_instances_payload[0]["started_at"] != first_instances_payload[0]["started_at"]
    assert stop_response.json()["observed_state"] == "stopped"
    assert stopped_instances_response.json() == []


def test_workflow_app_runtime_async_run_api_persists_queued_then_succeeded(
    tmp_path: Path,
) -> None:
    """验证异步 WorkflowRun 创建后会先落成 queued，再由后台线程推进到 succeeded。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-async-run-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-echo-app",
                    "display_name": "Process Echo Async Runtime",
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            create_run_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "hello async runtime"}},
                    "execution_metadata": {"marker": "async-runtime-api"},
                },
            )
            workflow_run_id = create_run_response.json()["workflow_run_id"]
            final_run_response = _wait_for_workflow_run_state(
                client,
                workflow_run_id,
                expected_states={"succeeded"},
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert create_run_response.status_code == 201
    assert final_run_response.status_code == 200
    assert stop_response.status_code == 200
    create_run_payload = create_run_response.json()
    final_run_payload = final_run_response.json()
    assert create_run_payload["state"] == "queued"
    assert final_run_payload["state"] == "succeeded"
    assert final_run_payload["metadata"]["trigger_source"] == "async-invoke"
    assert final_run_payload["outputs"]["http_response"]["body"]["message"] == "hello async runtime"
    assert stop_response.json()["observed_state"] == "stopped"


def test_workflow_app_runtime_async_run_api_can_cancel_running_and_queued_runs(
    tmp_path: Path,
) -> None:
    """验证异步 WorkflowRun 支持取消 running 和 queued 两种状态。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-async-cancel-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_slow_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_slow_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-slow-app",
                    "display_name": "Process Slow Async Runtime",
                    "request_timeout_seconds": 5,
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            running_run_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "cancel running"}},
                    "execution_metadata": {"marker": "async-cancel-running"},
                },
            )
            running_run_id = running_run_response.json()["workflow_run_id"]
            _wait_for_workflow_run_state(
                client,
                running_run_id,
                expected_states={"running"},
            )
            queued_run_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "cancel queued"}},
                    "execution_metadata": {"marker": "async-cancel-queued"},
                },
            )
            queued_run_id = queued_run_response.json()["workflow_run_id"]
            cancel_queued_response = client.post(
                f"/api/v1/workflows/runs/{queued_run_id}/cancel",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            cancel_running_response = client.post(
                f"/api/v1/workflows/runs/{running_run_id}/cancel",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            queued_final_response = _wait_for_workflow_run_state(
                client,
                queued_run_id,
                expected_states={"cancelled"},
            )
            running_final_response = _wait_for_workflow_run_state(
                client,
                running_run_id,
                expected_states={"cancelled"},
            )
            health_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert running_run_response.status_code == 201
    assert queued_run_response.status_code == 201
    assert cancel_queued_response.status_code == 200
    assert cancel_running_response.status_code == 200
    assert queued_final_response.status_code == 200
    assert running_final_response.status_code == 200
    assert health_response.status_code == 200
    assert stop_response.status_code == 200
    assert queued_run_response.json()["state"] == "queued"
    assert queued_final_response.json()["state"] == "cancelled"
    assert queued_final_response.json()["error_message"] == "workflow run 已取消"
    assert running_final_response.json()["state"] == "cancelled"
    assert running_final_response.json()["error_message"] == "workflow run 已取消"
    assert running_final_response.json()["metadata"]["cancelled_by"] == "user-1"
    assert health_response.json()["observed_state"] == "running"
    assert stop_response.json()["observed_state"] == "stopped"


def test_workflow_app_runtime_async_run_api_persists_failed_state_and_error_details(
    tmp_path: Path,
) -> None:
    """验证异步 WorkflowRun 失败后会保留失败状态、节点定位信息，并把 runtime 置为 failed。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-async-fail-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_fail_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_fail_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-fail-app",
                    "display_name": "Process Fail Async Runtime",
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            create_run_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "async fail"}},
                    "execution_metadata": {"marker": "async-runtime-fail"},
                },
            )
            workflow_run_id = create_run_response.json()["workflow_run_id"]
            final_run_response = _wait_for_workflow_run_state(
                client,
                workflow_run_id,
                expected_states={"failed"},
            )
            health_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            restart_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert create_run_response.status_code == 201
    assert final_run_response.status_code == 200
    assert health_response.status_code == 200
    assert restart_response.status_code == 200
    assert stop_response.status_code == 200

    final_payload = final_run_response.json()
    error_details = final_payload["metadata"]["error_details"]
    assert create_run_response.json()["state"] == "queued"
    assert final_payload["state"] == "failed"
    assert final_payload["error_message"] == "workflow 节点执行失败"
    assert error_details["node_id"] == "explode"
    assert error_details["node_type_id"] == "custom.test.process-fail"
    assert error_details["runtime_kind"] == "python-callable"
    assert error_details["error_type"] == "AssertionError"
    assert error_details["error_message"] == "process fail"
    assert health_response.json()["observed_state"] == "failed"
    assert restart_response.json()["observed_state"] == "running"
    assert stop_response.json()["observed_state"] == "stopped"


def test_workflow_app_runtime_async_run_api_marks_timed_out_and_allows_restart(
    tmp_path: Path,
) -> None:
    """验证异步 WorkflowRun 超时后会把 run 落成 timed_out，并允许 runtime restart 恢复。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-async-timeout-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_slow_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_slow_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-slow-app",
                    "display_name": "Process Slow Async Runtime",
                    "request_timeout_seconds": 1,
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            create_run_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "async timeout"}},
                    "execution_metadata": {"marker": "async-runtime-timeout"},
                    "timeout_seconds": 1,
                },
            )
            workflow_run_id = create_run_response.json()["workflow_run_id"]
            final_run_response = _wait_for_workflow_run_state(
                client,
                workflow_run_id,
                expected_states={"timed_out"},
            )
            get_runtime_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            health_response = client.get(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/health",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            restart_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/restart",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert create_run_response.status_code == 201
    assert final_run_response.status_code == 200
    assert get_runtime_response.status_code == 200
    assert health_response.status_code == 200
    assert restart_response.status_code == 200
    assert stop_response.status_code == 200

    assert create_run_response.json()["state"] == "queued"
    assert final_run_response.json()["state"] == "timed_out"
    assert final_run_response.json()["error_message"] == "等待 workflow runtime worker 同步调用结果超时"
    assert get_runtime_response.json()["observed_state"] == "failed"
    assert get_runtime_response.json()["last_error"] == "等待 workflow runtime worker 同步调用结果超时"
    assert health_response.json()["observed_state"] == "stopped"
    assert restart_response.json()["observed_state"] == "running"
    assert stop_response.json()["observed_state"] == "stopped"


def test_workflow_app_runtime_async_run_api_cancel_ignores_terminal_succeeded_run(
    tmp_path: Path,
) -> None:
    """验证取消已进入 succeeded 的异步 WorkflowRun 时不会改写终态。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-async-terminal-cancel-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )
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
    client = TestClient(application)

    try:
        with client:
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "project_id": "project-1",
                    "application_id": "process-echo-app",
                    "display_name": "Process Echo Async Runtime",
                },
            )
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            start_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            create_run_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "terminal cancel"}},
                    "execution_metadata": {"marker": "async-terminal-cancel"},
                },
            )
            workflow_run_id = create_run_response.json()["workflow_run_id"]
            final_run_response = _wait_for_workflow_run_state(
                client,
                workflow_run_id,
                expected_states={"succeeded"},
            )
            cancel_response = client.post(
                f"/api/v1/workflows/runs/{workflow_run_id}/cancel",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            get_run_response = client.get(
                f"/api/v1/workflows/runs/{workflow_run_id}",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
            stop_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/stop",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
            )
    finally:
        session_factory.engine.dispose()

    assert create_runtime_response.status_code == 201
    assert start_response.status_code == 200
    assert create_run_response.status_code == 201
    assert final_run_response.status_code == 200
    assert cancel_response.status_code == 200
    assert get_run_response.status_code == 200
    assert stop_response.status_code == 200

    assert final_run_response.json()["state"] == "succeeded"
    assert cancel_response.json()["state"] == "succeeded"
    assert get_run_response.json()["state"] == "succeeded"
    assert "cancel_requested_at" not in cancel_response.json()["metadata"]
    assert "cancelled_by" not in cancel_response.json()["metadata"]
    assert stop_response.json()["observed_state"] == "stopped"


def _build_process_echo_template():
    """构造进程隔离测试使用的最小 workflow 模板。"""

    from backend.contracts.workflows.workflow_graph import (
        WorkflowGraphEdge,
        WorkflowGraphInput,
        WorkflowGraphNode,
        WorkflowGraphOutput,
        WorkflowGraphTemplate,
    )

    return WorkflowGraphTemplate(
        template_id="process-echo-template",
        template_version="1.0.0",
        display_name="Process Echo Template",
        nodes=(
            WorkflowGraphNode(
                node_id="echo",
                node_type_id="custom.test.process-echo",
            ),
            WorkflowGraphNode(
                node_id="response",
                node_type_id="core.output.http-response",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-echo-response",
                source_node_id="echo",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_text",
                display_name="Request Text",
                payload_type_id="text.v1",
                target_node_id="echo",
                target_port="text",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="http_response",
                display_name="HTTP Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )


def _build_process_echo_application():
    """构造进程隔离测试使用的最小流程应用。"""

    from backend.contracts.workflows.workflow_graph import (
        FlowApplication,
        FlowApplicationBinding,
        FlowTemplateReference,
    )

    return FlowApplication(
        application_id="process-echo-app",
        display_name="Process Echo App",
        template_ref=FlowTemplateReference(
            template_id="process-echo-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_text",
                direction="input",
                template_port_id="request_text",
                binding_kind="api-request",
                config={"route": "/execute/process-echo", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="http_response",
                direction="output",
                template_port_id="http_response",
                binding_kind="http-response",
                config={"status_code": 200},
            ),
        ),
    )


def _build_process_fail_template():
    """构造节点执行失败测试使用的最小 workflow 模板。"""

    from backend.contracts.workflows.workflow_graph import (
        WorkflowGraphInput,
        WorkflowGraphNode,
        WorkflowGraphOutput,
        WorkflowGraphTemplate,
    )

    return WorkflowGraphTemplate(
        template_id="process-fail-template",
        template_version="1.0.0",
        display_name="Process Fail Template",
        nodes=(
            WorkflowGraphNode(
                node_id="explode",
                node_type_id="custom.test.process-fail",
                metadata={"sequence_index": 1},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_text",
                display_name="Request Text",
                payload_type_id="text.v1",
                target_node_id="explode",
                target_port="text",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="body",
                display_name="Body",
                payload_type_id="response-body.v1",
                source_node_id="explode",
                source_port="body",
            ),
        ),
    )


def _build_process_fail_application():
    """构造节点执行失败测试使用的最小流程应用。"""

    from backend.contracts.workflows.workflow_graph import (
        FlowApplication,
        FlowApplicationBinding,
        FlowTemplateReference,
    )

    return FlowApplication(
        application_id="process-fail-app",
        display_name="Process Fail App",
        template_ref=FlowTemplateReference(
            template_id="process-fail-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_text",
                direction="input",
                template_port_id="request_text",
                binding_kind="api-request",
                config={"route": "/execute/process-fail", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="body",
                direction="output",
                template_port_id="body",
                binding_kind="workflow-execute-output",
                config={"status_code": 200},
            ),
        ),
    )


def _build_process_slow_template():
    """构造超时测试使用的最小 workflow 模板。"""

    from backend.contracts.workflows.workflow_graph import (
        WorkflowGraphInput,
        WorkflowGraphNode,
        WorkflowGraphOutput,
        WorkflowGraphTemplate,
    )

    return WorkflowGraphTemplate(
        template_id="process-slow-template",
        template_version="1.0.0",
        display_name="Process Slow Template",
        nodes=(
            WorkflowGraphNode(
                node_id="sleep",
                node_type_id="custom.test.process-slow",
                metadata={"sequence_index": 1},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_text",
                display_name="Request Text",
                payload_type_id="text.v1",
                target_node_id="sleep",
                target_port="text",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="body",
                display_name="Body",
                payload_type_id="response-body.v1",
                source_node_id="sleep",
                source_port="body",
            ),
        ),
    )


def _build_process_slow_application():
    """构造超时测试使用的最小流程应用。"""

    from backend.contracts.workflows.workflow_graph import (
        FlowApplication,
        FlowApplicationBinding,
        FlowTemplateReference,
    )

    return FlowApplication(
        application_id="process-slow-app",
        display_name="Process Slow App",
        template_ref=FlowTemplateReference(
            template_id="process-slow-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_text",
                direction="input",
                template_port_id="request_text",
                binding_kind="api-request",
                config={"route": "/execute/process-slow", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="body",
                direction="output",
                template_port_id="body",
                binding_kind="workflow-execute-output",
                config={"status_code": 200},
            ),
        ),
    )


def _create_process_test_node_pack_fixture(tmp_path: Path) -> Path:
    """创建进程隔离测试使用的最小 custom node pack。"""

    node_pack_dir = tmp_path / "custom_nodes" / "process_test_nodes"
    backend_dir = node_pack_dir / "backend"
    workflow_dir = node_pack_dir / "workflow"
    backend_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (node_pack_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "entry.py").write_text(
        """
import os
import multiprocessing
import time


def _process_echo_handler(request):
    text_payload = request.input_values.get("text")
    if isinstance(text_payload, dict):
        message = str(text_payload.get("value") or "")
    else:
        message = str(text_payload or "")
    return {
        "body": {
            "message": message,
            "marker": request.execution_metadata.get("marker"),
            "workflow_run_id": request.execution_metadata.get("workflow_run_id"),
            "pid": os.getpid(),
            "is_daemon": multiprocessing.current_process().daemon,
        }
    }


def _process_fail_handler(request):
    raise AssertionError("process fail")


def _process_slow_handler(request):
    time.sleep(2.0)
    return {
        "body": {
            "message": "slow done",
            "marker": request.execution_metadata.get("marker"),
            "workflow_run_id": request.execution_metadata.get("workflow_run_id"),
            "pid": os.getpid(),
            "is_daemon": multiprocessing.current_process().daemon,
        }
    }


def register(context):
    context.register_python_callable("custom.test.process-echo", _process_echo_handler)
    context.register_python_callable("custom.test.process-fail", _process_fail_handler)
    context.register_python_callable("custom.test.process-slow", _process_slow_handler)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest_payload = {
        "format_id": "amvision.node-pack-manifest.v1",
        "id": "test.process-nodes",
        "version": "0.1.0",
        "displayName": "Test Process Nodes",
        "description": "用于验证 workflow application 隔离子进程执行的测试节点包。",
        "category": "custom-node-pack",
        "capabilities": ["pipeline.node"],
        "entrypoints": {"backend": "custom_nodes.process_test_nodes.backend.entry:register"},
        "compatibility": {"api": ">=0.1 <1.0", "runtime": ">=3.12"},
        "timeout": {"defaultSeconds": 30},
        "enabledByDefault": True,
        "customNodeCatalogPath": "workflow/catalog.json",
    }
    workflow_catalog_payload = {
        "format_id": "amvision.custom-node-catalog.v1",
        "payload_contracts": [
            {
                "format_id": "amvision.workflow-payload-contract.v1",
                "payload_type_id": "text.v1",
                "display_name": "Text",
                "transport_kind": "inline-json",
                "json_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
                "artifact_kinds": [],
                "metadata": {},
            }
        ],
        "node_definitions": [
            {
                "format_id": "amvision.node-definition.v1",
                "node_type_id": "custom.test.process-echo",
                "display_name": "Process Echo",
                "category": "test.process",
                "description": "返回当前子进程 pid 与请求文本。",
                "implementation_kind": "custom-node",
                "runtime_kind": "python-callable",
                "input_ports": [
                    {
                        "name": "text",
                        "display_name": "Text",
                        "payload_type_id": "text.v1",
                    }
                ],
                "output_ports": [
                    {
                        "name": "body",
                        "display_name": "Body",
                        "payload_type_id": "response-body.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["test.process"],
                "runtime_requirements": {},
                "node_pack_id": "test.process-nodes",
                "node_pack_version": "0.1.0",
            },
            {
                "format_id": "amvision.node-definition.v1",
                "node_type_id": "custom.test.process-fail",
                "display_name": "Process Fail",
                "category": "test.process",
                "description": "主动抛出 AssertionError，用于验证失败节点定位。",
                "implementation_kind": "custom-node",
                "runtime_kind": "python-callable",
                "input_ports": [
                    {
                        "name": "text",
                        "display_name": "Text",
                        "payload_type_id": "text.v1",
                    }
                ],
                "output_ports": [
                    {
                        "name": "body",
                        "display_name": "Body",
                        "payload_type_id": "response-body.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["test.process"],
                "runtime_requirements": {},
                "node_pack_id": "test.process-nodes",
                "node_pack_version": "0.1.0",
            },
            {
                "format_id": "amvision.node-definition.v1",
                "node_type_id": "custom.test.process-slow",
                "display_name": "Process Slow",
                "category": "test.process",
                "description": "延迟返回结果，用于验证超时分支。",
                "implementation_kind": "custom-node",
                "runtime_kind": "python-callable",
                "input_ports": [
                    {
                        "name": "text",
                        "display_name": "Text",
                        "payload_type_id": "text.v1",
                    }
                ],
                "output_ports": [
                    {
                        "name": "body",
                        "display_name": "Body",
                        "payload_type_id": "response-body.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["test.process"],
                "runtime_requirements": {},
                "node_pack_id": "test.process-nodes",
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


def _wait_for_workflow_run_state(
    client: TestClient,
    workflow_run_id: str,
    *,
    expected_states: set[str],
    timeout_seconds: float = 10.0,
):
    """轮询 WorkflowRun，直到进入目标状态。"""

    deadline = time.monotonic() + timeout_seconds
    last_response = None
    while time.monotonic() < deadline:
        last_response = client.get(
            f"/api/v1/workflows/runs/{workflow_run_id}",
            headers=build_test_headers(scopes="workflows:read,workflows:write"),
        )
        if last_response.status_code == 200 and last_response.json().get("state") in expected_states:
            return last_response
        time.sleep(0.05)
    raise AssertionError(
        f"WorkflowRun {workflow_run_id} 未在 {timeout_seconds} 秒内进入目标状态 {sorted(expected_states)}；"
        f"最后一次响应：{None if last_response is None else last_response.json()}"
    )