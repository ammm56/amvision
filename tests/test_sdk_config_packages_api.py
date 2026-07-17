"""SDK 配置包生成接口测试。"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.application.local_buffers.broker_settings import LocalBufferBrokerSettings
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime
from backend.service.domain.workflows.workflow_trigger_source_records import WorkflowTriggerSource
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.settings import (
    BackendServiceProjectCatalogItemConfig,
    BackendServiceProjectsConfig,
    BackendServiceSettings,
)
from tests.api_test_support import build_test_headers, create_test_runtime
from tests.yolox_test_support import seed_yolox_model_version


def test_sdk_config_package_preview_and_download_include_project_resources(tmp_path: Path) -> None:
    """验证 Project 工作台配置包接口会导出 workflow、TriggerSource 和模型 deployment。"""

    client, session_factory, dataset_storage = _create_sdk_config_package_test_client(tmp_path)
    model_version_id = seed_yolox_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        source_prefix="sdk-config-package",
        training_task_id="training-task-sdk-config-package",
        model_name="sdk-config-model",
        dataset_version_id="dataset-version-sdk-config-package",
        checkpoint_file_id="checkpoint-sdk-config-package",
        labels_file_id="labels-sdk-config-package",
    )
    _seed_workflow_runtime_and_trigger_source(session_factory, dataset_storage)

    try:
        with client:
            create_deployment_response = client.post(
                "/api/v1/models/detection/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_type": "yolox",
                    "model_version_id": model_version_id,
                    "display_name": "Barcode Detector",
                },
            )
            assert create_deployment_response.status_code == 201

            preview_response = client.post(
                "/api/v1/projects/project-1/sdk-config-packages/preview",
                headers=_build_headers(),
                json={
                    "model_runtime_modes": ["sync"],
                    "include_disabled_trigger_sources": True,
                },
            )
            download_response = client.post(
                "/api/v1/projects/project-1/sdk-config-packages/download",
                headers=_build_headers(),
                json={
                    "model_runtime_modes": ["sync"],
                    "include_disabled_trigger_sources": True,
                },
            )
    finally:
        session_factory.engine.dispose()

    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["workflow_runtime_count"] == 1
    assert preview_payload["trigger_source_count"] == 1
    assert preview_payload["model_deployment_count"] == 1
    assert preview_payload["contains_access_token"] is True
    assert any(item["kind"] == "workflow-runtime" for item in preview_payload["files"])
    assert any(item["kind"] == "model-deployments" for item in preview_payload["files"])

    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"
    assert "amvision_sdk_configs_project-1_" in download_response.headers["content-disposition"]
    archive = zipfile.ZipFile(BytesIO(download_response.content))
    names = set(archive.namelist())
    assert "manifest.json" in names
    assert "README.md" in names
    workflow_config_name = next(name for name in names if name.startswith("Config/config_workflow_"))
    model_config_name = next(name for name in names if name.startswith("Config/config_model_deployment_"))

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["format_id"] == "amvision.sdk-config-package.v1"
    assert manifest["contains_access_token"] is True
    assert manifest["workflow_runtime_count"] == 1
    assert manifest["model_deployment_count"] == 1

    workflow_config = json.loads(archive.read(workflow_config_name))
    assert workflow_config["backend"]["access_token"] == "amvision-default-user-token"
    assert workflow_config["backend"]["http_timeout_seconds"] == 240
    assert workflow_config["runtime"]["name"] == "新建应用yolo11m_barqrcode"
    assert workflow_config["runtime"]["workflow_runtime_id"] == "workflow-runtime-sdk-config"
    assert workflow_config_name.startswith("Config/config_workflow_yolo11m_barqrcode_")
    assert workflow_config["trigger_sources"][0]["name"] == "zeromq yolo11m_barqrcode runtime"
    assert workflow_config["trigger_sources"][0]["trigger_source_id"] == "zeromq-sdk-config"
    assert workflow_config["trigger_sources"][0]["zero_mq"]["bind_endpoint"] == "tcp://127.0.0.1:5555"

    model_config = json.loads(archive.read(model_config_name))
    assert "runtime" not in model_config
    assert model_config["model_deployments"][0]["task_type"] == "detection"
    assert model_config["model_deployments"][0]["runtime_mode"] == "sync"
    assert model_config["model_deployments"][0]["name"] == "Barcode Detector"


def test_sdk_config_package_can_include_current_access_token(tmp_path: Path) -> None:
    """验证默认配置包会写入当前 Bearer token 并在 manifest 标记。"""

    client, session_factory, dataset_storage = _create_sdk_config_package_test_client(tmp_path)
    _seed_workflow_runtime_and_trigger_source(session_factory, dataset_storage)
    token = "amvision-default-user-token"

    try:
        with client:
            response = client.post(
                "/api/v1/projects/project-1/sdk-config-packages/download",
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    workflow_config_name = next(
        name for name in archive.namelist() if name.startswith("Config/config_workflow_")
    )
    workflow_config = json.loads(archive.read(workflow_config_name))
    assert manifest["contains_access_token"] is True
    assert workflow_config["backend"]["access_token"] == token


def test_sdk_config_package_can_skip_current_access_token(tmp_path: Path) -> None:
    """验证明确关闭 token 写入时仍使用占位符。"""

    client, session_factory, dataset_storage = _create_sdk_config_package_test_client(tmp_path)
    _seed_workflow_runtime_and_trigger_source(session_factory, dataset_storage)

    try:
        with client:
            response = client.post(
                "/api/v1/projects/project-1/sdk-config-packages/download",
                headers=_build_headers(),
                json={"include_access_token": False},
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    workflow_config_name = next(
        name for name in archive.namelist() if name.startswith("Config/config_workflow_")
    )
    workflow_config = json.loads(archive.read(workflow_config_name))
    assert manifest["contains_access_token"] is False
    assert workflow_config["backend"]["access_token"] == "<replace-with-user-token>"


def test_sdk_config_package_empty_project_does_not_download_empty_zip(tmp_path: Path) -> None:
    """验证空 Project 只返回 preview 提示，不下载空 zip。"""

    client, session_factory, _dataset_storage = _create_sdk_config_package_test_client(tmp_path)

    try:
        with client:
            preview_response = client.post(
                "/api/v1/projects/project-1/sdk-config-packages/preview",
                headers=_build_headers(),
                json={},
            )
            download_response = client.post(
                "/api/v1/projects/project-1/sdk-config-packages/download",
                headers=_build_headers(),
                json={},
            )
    finally:
        session_factory.engine.dispose()

    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["files"] == []
    assert preview_payload["warnings"] == ["当前 Project 没有可导出的 SDK 配置。"]
    assert download_response.status_code == 400


def _create_sdk_config_package_test_client(tmp_path: Path) -> tuple[TestClient, object, object]:
    """创建配置包接口测试客户端。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="sdk-config-packages.db",
    )
    application = create_app(
        settings=BackendServiceSettings(
            local_buffer_broker=LocalBufferBrokerSettings(enabled=False),
            projects=BackendServiceProjectsConfig(
                items=(
                    BackendServiceProjectCatalogItemConfig(
                        project_id="project-1",
                        display_name="Project One",
                    ),
                )
            )
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    return TestClient(application), session_factory, dataset_storage


def _seed_workflow_runtime_and_trigger_source(
    session_factory: object,
    dataset_storage: object,
) -> None:
    """直接写入一个已存在 runtime 和 ZeroMQ TriggerSource。"""

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    dataset_storage.write_json(
        "projects/project-1/workflows/apps/workflow-app-sdk-config/app.json",
        {
            "application_id": "workflow-app-sdk-config",
            "display_name": "新建应用yolo11m_barqrcode",
        },
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_runtime.save_workflow_app_runtime(
            WorkflowAppRuntime(
                workflow_runtime_id="workflow-runtime-sdk-config",
                project_id="project-1",
                application_id="workflow-app-sdk-config",
                display_name="yolo11m_barqrcode runtime",
                application_snapshot_object_key="projects/project-1/workflows/apps/workflow-app-sdk-config/app.json",
                template_snapshot_object_key="projects/project-1/workflows/templates/template-sdk-config/template.json",
                desired_state="running",
                observed_state="running",
                created_at=now,
                updated_at=now,
            )
        )
        unit_of_work.workflow_trigger_sources.save_trigger_source(
            WorkflowTriggerSource(
                trigger_source_id="zeromq-sdk-config",
                project_id="project-1",
                display_name="zeromq yolo11m_barqrcode runtime",
                trigger_kind="zeromq-topic",
                workflow_runtime_id="workflow-runtime-sdk-config",
                enabled=True,
                desired_state="running",
                observed_state="running",
                transport_config={
                    "bind_endpoint": "tcp://127.0.0.1:5555",
                    "default_input_binding": "request_image_ref",
                },
                input_binding_mapping={
                    "request_image_ref": {
                        "source": "payload.request_image_ref",
                    }
                },
                reply_timeout_seconds=5,
                created_at=now,
                updated_at=now,
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()


def _build_headers() -> dict[str, str]:
    """构建具备 Project 配置导出权限的请求头。"""

    return build_test_headers(scopes="workflows:read,models:read")
