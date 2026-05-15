"""项目级 summary REST 与 WebSocket 聚合流测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.app import create_app
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import (
    BackendServiceCustomNodesConfig,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)
from tests.api_test_support import build_test_headers, create_test_runtime
from tests.test_workflow_application_process_executor import (
    _build_process_echo_application,
    _build_process_echo_template,
    _create_process_test_node_pack_fixture,
    _receive_websocket_json_with_timeout,
    _wait_for_workflow_run_state,
)
from tests.yolox_test_support import FakeDeploymentProcessSupervisor, seed_yolox_model_version


def test_project_summary_api_aggregates_workflow_and_deployment_counts(tmp_path: Path) -> None:
    """验证项目级 summary REST 会聚合 workflow 与 deployment 资源计数。"""

    client, session_factory, dataset_storage = _create_project_summary_test_client(
        tmp_path,
        database_name="project-summary-api.db",
    )
    model_version_id = seed_yolox_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        source_prefix="project-summary-api",
        training_task_id="training-task-project-summary-api",
        model_name="project-summary-model",
        dataset_version_id="dataset-version-project-summary-api",
        checkpoint_file_id="checkpoint-project-summary-api",
        labels_file_id="labels-project-summary-api",
    )

    try:
        with client:
            preview_run_response = client.post(
                "/api/v1/workflows/preview-runs",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "application_ref": {"application_id": "process-echo-app"},
                    "input_bindings": {"request_text": {"value": "project summary preview"}},
                    "wait_mode": "sync",
                    "timeout_seconds": 5,
                },
            )
            assert preview_run_response.status_code == 201
            assert preview_run_response.json()["state"] == "succeeded"

            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "application_id": "process-echo-app",
                    "display_name": "Project Summary Runtime",
                },
            )
            assert create_runtime_response.status_code == 201
            workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]

            start_runtime_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/start",
                headers=_build_headers(),
            )
            assert start_runtime_response.status_code == 200

            create_run_response = client.post(
                f"/api/v1/workflows/app-runtimes/{workflow_runtime_id}/runs",
                headers=_build_headers(),
                json={
                    "input_bindings": {"request_text": {"value": "project summary run"}},
                    "execution_metadata": {"marker": "project-summary"},
                },
            )
            assert create_run_response.status_code == 201
            workflow_run_id = create_run_response.json()["workflow_run_id"]
            _wait_for_workflow_run_state(
                client,
                workflow_run_id,
                expected_states={"succeeded"},
            )

            create_deployment_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "display_name": "Project Summary Deployment",
                },
            )
            assert create_deployment_response.status_code == 201

            summary_response = client.get(
                "/api/v1/projects/project-1/summary",
                headers=_build_headers(),
            )
    finally:
        session_factory.engine.dispose()

    assert summary_response.status_code == 200
    payload = summary_response.json()
    assert payload["project_id"] == "project-1"
    assert payload["workflows"]["template_total"] == 1
    assert payload["workflows"]["application_total"] == 1
    assert payload["workflows"]["preview_run_total"] == 1
    assert payload["workflows"]["preview_run_state_counts"] == {"succeeded": 1}
    assert payload["workflows"]["workflow_run_total"] == 1
    assert payload["workflows"]["workflow_run_state_counts"] == {"succeeded": 1}
    assert payload["workflows"]["app_runtime_total"] == 1
    assert payload["workflows"]["app_runtime_observed_state_counts"] == {"running": 1}
    assert payload["deployments"]["deployment_instance_total"] == 1
    assert payload["deployments"]["deployment_status_counts"] == {"active": 1}


def test_projects_events_websocket_streams_summary_snapshot_and_live_updates(tmp_path: Path) -> None:
    """验证 projects.events 会先返回快照，再推送 workflow 与 deployment 聚合更新。"""

    client, session_factory, dataset_storage = _create_project_summary_test_client(
        tmp_path,
        database_name="project-summary-events.db",
    )
    model_version_id = seed_yolox_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        source_prefix="project-summary-events",
        training_task_id="training-task-project-summary-events",
        model_name="project-summary-events-model",
        dataset_version_id="dataset-version-project-summary-events",
        checkpoint_file_id="checkpoint-project-summary-events",
        labels_file_id="labels-project-summary-events",
    )

    try:
        with client:
            with client.websocket_connect(
                "/ws/v1/projects/events?project_id=project-1",
                headers=_build_headers(),
            ) as websocket:
                connected_message = websocket.receive_json()
                snapshot_message = websocket.receive_json()

                create_runtime_response = client.post(
                    "/api/v1/workflows/app-runtimes",
                    headers=_build_headers(),
                    json={
                        "project_id": "project-1",
                        "application_id": "process-echo-app",
                        "display_name": "Project Events Runtime",
                    },
                )
                assert create_runtime_response.status_code == 201
                workflow_runtime_id = create_runtime_response.json()["workflow_runtime_id"]

                runtime_update_message = _receive_websocket_json_with_timeout(websocket)

                create_deployment_response = client.post(
                    "/api/v1/models/yolox/deployment-instances",
                    headers=_build_headers(),
                    json={
                        "project_id": "project-1",
                        "model_version_id": model_version_id,
                        "display_name": "Project Events Deployment",
                    },
                )
                assert create_deployment_response.status_code == 201
                deployment_instance_id = create_deployment_response.json()["deployment_instance_id"]

                start_deployment_response = client.post(
                    f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/sync/start",
                    headers=_build_headers(),
                )
                assert start_deployment_response.status_code == 200

                deployment_update_message = _receive_websocket_json_with_timeout(websocket)
    finally:
        session_factory.engine.dispose()

    assert connected_message["event_type"] == "projects.connected"
    assert connected_message["resource_id"] == "project-1"
    assert snapshot_message["event_type"] == "projects.summary.snapshot"
    assert snapshot_message["payload"]["workflows"]["template_total"] == 1
    assert snapshot_message["payload"]["workflows"]["application_total"] == 1
    assert snapshot_message["payload"]["workflows"]["app_runtime_total"] == 0
    assert snapshot_message["payload"]["deployments"]["deployment_instance_total"] == 0

    assert runtime_update_message["stream"] == "projects.events"
    assert runtime_update_message["event_type"] == "projects.summary.updated"
    assert runtime_update_message["resource_id"] == "project-1"
    assert runtime_update_message["payload"]["topic"] == "workflows.app-runtimes"
    assert runtime_update_message["payload"]["source_resource_kind"] == "workflow_app_runtime"
    assert runtime_update_message["payload"]["source_resource_id"] == workflow_runtime_id
    assert runtime_update_message["payload"]["workflows"]["app_runtime_total"] == 1

    assert deployment_update_message["stream"] == "projects.events"
    assert deployment_update_message["event_type"] == "projects.summary.updated"
    assert deployment_update_message["resource_id"] == "project-1"
    assert deployment_update_message["payload"]["topic"] == "deployments"
    assert deployment_update_message["payload"]["source_resource_kind"] == "deployment_instance"
    assert deployment_update_message["payload"]["source_resource_id"] == deployment_instance_id
    assert deployment_update_message["payload"]["deployments"]["deployment_instance_total"] == 1


def _create_project_summary_test_client(
    tmp_path: Path,
    *,
    database_name: str,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage]:
    """创建带 workflow 自定义节点和 fake deployment supervisor 的测试客户端。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name=database_name,
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

    service_event_bus = getattr(application.state, "service_event_bus", None)
    application.state.yolox_sync_deployment_process_supervisor = FakeDeploymentProcessSupervisor(
        runtime_mode="sync",
        dataset_storage_root_dir=str(dataset_storage.root_dir),
        service_event_bus=service_event_bus,
    )
    application.state.yolox_async_deployment_process_supervisor = FakeDeploymentProcessSupervisor(
        runtime_mode="async",
        dataset_storage_root_dir=str(dataset_storage.root_dir),
        service_event_bus=service_event_bus,
    )
    application.state.yolox_sync_deployment_process_supervisor.session_factory = session_factory
    application.state.yolox_sync_deployment_process_supervisor.dataset_storage = dataset_storage
    application.state.yolox_async_deployment_process_supervisor.session_factory = session_factory
    application.state.yolox_async_deployment_process_supervisor.dataset_storage = dataset_storage
    return TestClient(application), session_factory, dataset_storage


def _build_headers() -> dict[str, str]:
    """构建项目级 summary 读写测试使用的请求头。"""

    return build_test_headers(
        scopes="workflows:read,workflows:write,models:read,models:write",
    )