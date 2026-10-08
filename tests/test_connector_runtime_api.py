"""隔离 API 与真实 Runtime 进程验证，不使用开发环境的客户 App。"""

import shutil

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.settings import (
    BackendServiceSettings,
    BackendServiceCustomNodesConfig,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
)
from backend.service.application.local_buffers import LocalBufferBrokerSettings
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from scripts.connector_assets.workflow import build_example
from tests.api_test_support import build_test_headers, create_test_runtime
from tests.test_connector_nodes import ROOT, ASSETS
from tests.test_workflow_runtime_invoke_api import _create_and_start_runtime


def test_isolated_pack_enable_publish_runtime_invoke_and_stop(tmp_path):
    """实际包启用、发布冻结、独立进程执行和停止；资源/图像留在隔离目录。"""
    factory, storage, queue = create_test_runtime(
        tmp_path, database_name="connector-runtime.db"
    )
    packs = tmp_path / "custom_nodes"
    for name in ("opencv_nodes", "connector_nodes"):
        shutil.copytree(
            ROOT / "custom_nodes" / name,
            packs / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    settings = BackendServiceSettings(
        database=BackendServiceDatabaseConfig(url=factory.settings.url),
        dataset_storage=BackendServiceDatasetStorageConfig(
            root_dir=str(storage.root_dir)
        ),
        queue=BackendServiceQueueConfig(root_dir=str(queue.root_dir)),
        custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(packs)),
        local_buffer_broker=LocalBufferBrokerSettings(enabled=False),
    )
    app = create_app(
        settings=settings,
        session_factory=factory,
        dataset_storage=storage,
        queue_backend=queue,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    runtime_id = None
    try:
        with TestClient(app) as client:
            enabled = client.post(
                "/api/v1/workflows/node-packs/connector.nodes/enable", headers=headers
            )
            assert enabled.status_code == 200, enabled.text
            graph, application, resources = build_example(
                MeasurementResourceService(storage),
                ASSETS,
                project_id="project-1",
                family="single10_front",
            )
            documents = LocalWorkflowJsonService(
                dataset_storage=storage,
                node_catalog_registry=app.state.node_catalog_registry,
            )
            documents.save_template(project_id="project-1", template=graph)
            documents.save_application(project_id="project-1", application=application)
            runtime_id = _create_and_start_runtime(
                client=client,
                headers=headers,
                application_id=application.application_id,
                display_name="Connector isolated validation",
            )
            try:
                for condition, passed in [
                    ("reference", True),
                    ("missing_middle", False),
                    ("no_part", False),
                ]:
                    receipt = storage.write_immutable_object(
                        object_prefix="projects/project-1/inputs",
                        content=(
                            ASSETS / "images" / f"single10_front__{condition}.png"
                        ).read_bytes(),
                        media_type="image/png",
                        extension=".png",
                    )
                    response = client.post(
                        f"/api/v1/workflows/app-runtimes/{runtime_id}/invoke",
                        params={"response_mode": "run"},
                        headers=headers,
                        json={
                            "input_bindings": {
                                "image": {
                                    "transport_kind": "storage",
                                    "object_key": receipt.metadata.object_key,
                                    "media_type": "image/png",
                                }
                            }
                        },
                    )
                    assert response.status_code == 200, response.text
                    run = response.json()
                    assert run["state"] == "succeeded", run.get("error_message", run)
                    assert run["outputs"]["output_result"]["value"]["passed"] is passed
                    assert run["outputs"]["output_image"]
                # 真实草稿/发布快照必须保护两个不可变资源版本。
                for item in resources:
                    r = item.reference
                    deleted = client.delete(
                        f"/api/v1/workflows/projects/project-1/measurement-resources/{r.resource_id}/versions/{r.version}",
                        headers=headers,
                    )
                    assert deleted.status_code == 409, deleted.text
            finally:
                if runtime_id:
                    stopped = client.post(
                        f"/api/v1/workflows/app-runtimes/{runtime_id}/stop",
                        headers=headers,
                    )
                    assert stopped.status_code == 200, stopped.text
    finally:
        factory.engine.dispose()
