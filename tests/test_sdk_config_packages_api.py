"""SDK 配置包生成接口测试。"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.application.local_buffers.broker_settings import LocalBufferBrokerSettings
from backend.service.application.workflows.trigger_sources.output_delivery import (
    TRIGGER_RESPONSE_PLAN_METADATA_KEY,
    build_trigger_response_plan,
)
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
    workflow_config_name = "Config/config_workflow-app-sdk-config.json"
    assert workflow_config_name in names
    model_config_name = next(name for name in names if name.startswith("Config/config_model_deployment_"))

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["format_id"] == "amvision.sdk-config-package.v1"
    assert manifest["contains_access_token"] is True
    assert manifest["workflow_runtime_count"] == 1
    assert manifest["model_deployment_count"] == 1

    workflow_config = json.loads(archive.read(workflow_config_name))
    assert workflow_config["backend"]["access_token"] == "amvision-default-user-token"
    assert workflow_config["backend"]["http_timeout_seconds"] == 300
    assert workflow_config["runtime"]["name"] == "新建应用yolo11m_barqrcode"
    assert workflow_config["runtime"]["workflow_runtime_id"] == "workflow-runtime-sdk-config"
    assert workflow_config["runtime"]["public_contract"]["format_id"] == (
        "amvision.workflow-app-contract.v2"
    )
    assert workflow_config["runtime"]["public_contract"]["inputs"][0]["binding_id"] == (
        "request_json"
    )
    assert workflow_config_name == "Config/config_workflow-app-sdk-config.json"
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
    workflow_config_name = "Config/config_workflow-app-sdk-config.json"
    workflow_config = json.loads(archive.read(workflow_config_name))
    assert manifest["contains_access_token"] is True
    assert workflow_config["backend"]["access_token"] == token


def test_sdk_config_current_snapshot_supports_etag_and_file_checksums(
    tmp_path: Path,
) -> None:
    """自动同步快照使用稳定 revision、ETag 和逐文件 checksum。"""

    client, session_factory, dataset_storage = _create_sdk_config_package_test_client(
        tmp_path
    )
    _seed_workflow_runtime_and_trigger_source(session_factory, dataset_storage)
    try:
        with client:
            first = client.get(
                "/api/v1/projects/project-1/sdk-config-packages/current",
                headers=_build_headers(),
            )
            second = client.get(
                "/api/v1/projects/project-1/sdk-config-packages/current",
                headers={
                    **_build_headers(),
                    "If-None-Match": first.headers["etag"],
                },
            )
    finally:
        session_factory.engine.dispose()

    assert first.status_code == 200
    assert first.headers["content-type"] == "application/zip"
    revision = first.headers["x-amvision-config-revision"]
    assert first.headers["etag"] == f'"{revision}"'
    assert second.status_code == 304
    assert second.content == b""

    archive = zipfile.ZipFile(BytesIO(first.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["configuration_revision"] == revision
    files = {item["path"]: item for item in manifest["files"]}
    assert "Config/sdk-bootstrap.json" in files
    for path, item in files.items():
        assert item["sha256"] == sha256(archive.read(path)).hexdigest()

    bootstrap = json.loads(archive.read("Config/sdk-bootstrap.json"))
    assert bootstrap["configuration_sync"] == {
        "enabled": False,
        "use_last_known_good": True,
    }
    assert bootstrap["backend"]["configuration_path"].endswith(
        "/projects/project-1/sdk-config-packages/current"
    )


def test_sdk_config_package_includes_local_shared_memory_trigger(tmp_path: Path) -> None:
    """验证配置包为同机 SDK 固定 buffers root、route generation 和容量。"""

    client, session_factory, dataset_storage = _create_sdk_config_package_test_client(tmp_path)
    _seed_workflow_runtime_and_trigger_source(session_factory, dataset_storage)
    _seed_local_shared_memory_trigger_source(session_factory)

    try:
        with client:
            response = client.post(
                "/api/v1/projects/project-1/sdk-config-packages/download",
                headers=_build_headers(),
                json={},
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    workflow_config = json.loads(
        archive.read("Config/config_workflow-app-sdk-config.json")
    )
    sources = {
        item["trigger_source_id"]: item
        for item in workflow_config["trigger_sources"]
    }
    local_source = sources["local-shared-sdk-config"]
    assert local_source["trigger_kind"] == "local-shared-memory"
    assert "zero_mq" not in local_source
    config = local_source["local_shared_memory"]
    assert Path(config["buffers_root"]).is_absolute()
    assert Path(config["buffers_root"]).name == "buffers"
    assert config["route_generation"] == 1
    assert config["default_input_binding"] == "request_image_ref"
    assert config["timeout_seconds"] == 7
    assert set(config) == {
        "buffers_root",
        "route_generation",
        "default_input_binding",
        "timeout_seconds",
    }


def test_sdk_config_package_uses_resource_ids_for_workflow_file_names(tmp_path: Path) -> None:
    """验证中文展示名称不会再生成重复的 project 文件名。"""

    client, session_factory, dataset_storage = _create_sdk_config_package_test_client(tmp_path)
    _seed_workflow_runtime(
        session_factory,
        dataset_storage,
        application_id="workflow-app-20260718114943",
        application_display_name="摆盘分拣塑盒满盘检测应用",
        workflow_runtime_id="workflow-runtime-sdk-config-first",
    )
    _seed_workflow_runtime(
        session_factory,
        dataset_storage,
        application_id="workflow-app-20260718122522",
        application_display_name="摆盘分拣来料空盘检测应用",
        workflow_runtime_id="workflow-runtime-sdk-config-second",
    )

    try:
        with client:
            response = client.post(
                "/api/v1/projects/project-1/sdk-config-packages/download",
                headers=_build_headers(),
                json={},
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    workflow_names = sorted(
        name
        for name in archive.namelist()
        if name.startswith("Config/config_workflow-app-")
    )
    assert workflow_names == [
        "Config/config_workflow-app-20260718114943.json",
        "Config/config_workflow-app-20260718122522.json",
    ]
    assert len(archive.namelist()) == len(set(archive.namelist()))


def test_sdk_config_package_disambiguates_multiple_runtimes_for_one_application(
    tmp_path: Path,
) -> None:
    """验证同一 application 的多个 runtime 会使用真实 runtime id 消歧。"""

    client, session_factory, dataset_storage = _create_sdk_config_package_test_client(tmp_path)
    application_id = "workflow-app-20260718114943"
    _seed_workflow_runtime(
        session_factory,
        dataset_storage,
        application_id=application_id,
        application_display_name="摆盘分拣塑盒满盘检测应用",
        workflow_runtime_id="workflow-runtime-primary",
    )
    _seed_workflow_runtime(
        session_factory,
        dataset_storage,
        application_id=application_id,
        application_display_name="摆盘分拣塑盒满盘检测应用",
        workflow_runtime_id="workflow-runtime-backup",
    )

    try:
        with client:
            response = client.post(
                "/api/v1/projects/project-1/sdk-config-packages/download",
                headers=_build_headers(),
                json={},
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    workflow_names = sorted(
        name
        for name in archive.namelist()
        if name.startswith(f"Config/config_{application_id}_")
    )
    assert workflow_names == [
        f"Config/config_{application_id}_workflow-runtime-backup.json",
        f"Config/config_{application_id}_workflow-runtime-primary.json",
    ]
    assert len(archive.namelist()) == len(set(archive.namelist()))


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
    workflow_config_name = "Config/config_workflow-app-sdk-config.json"
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
    contract_object_key = (
        "projects/project-1/workflows/apps/workflow-app-sdk-config/contract.json"
    )
    dataset_storage.write_json(
        contract_object_key,
        {
            "format_id": "amvision.workflow-app-contract.v2",
            "application_id": "workflow-app-sdk-config",
            "inputs": [
                {
                    "binding_id": "request_json",
                    "payload_type_id": "value.v1",
                    "required": True,
                    "transports": ["json"],
                    "payload_schema": {
                        "type": "object",
                        "properties": {"value": {}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                }
            ],
            "outputs": [],
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
                metadata={"contract_snapshot_object_key": contract_object_key},
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


def _seed_local_shared_memory_trigger_source(session_factory: object) -> None:
    """写入带固定 response plan 的同机共享内存 TriggerSource。"""

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    response_plan = build_trigger_response_plan(
        trigger_source_id="local-shared-sdk-config",
        trigger_kind="local-shared-memory",
        workflow_runtime_id="workflow-runtime-sdk-config",
        workflow_runtime_revision_id="workflow-runtime-revision-sdk-config",
        workflow_app_version_id="workflow-app-version-sdk-config",
        workflow_runtime_generation=1,
        expected_snapshot_fingerprint="snapshot-sdk-config",
        contract_fingerprint="contract-sdk-config",
        submit_mode="sync",
        result_mode="sync-reply",
        ack_policy="ack-after-run-finished",
        reply_timeout_seconds=7,
        response_ack_timeout_seconds=30.0,
        selected_output_payload_types={},
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_trigger_sources.save_trigger_source(
            WorkflowTriggerSource(
                trigger_source_id="local-shared-sdk-config",
                project_id="project-1",
                display_name="Local shared memory runtime",
                trigger_kind="local-shared-memory",
                workflow_runtime_id="workflow-runtime-sdk-config",
                enabled=True,
                desired_state="running",
                observed_state="running",
                transport_config={
                    "default_input_binding": "request_image_ref",
                },
                input_binding_mapping={
                    "request_image_ref": {
                        "source": "payload.request_image_ref",
                    }
                },
                reply_timeout_seconds=7,
                metadata={
                    TRIGGER_RESPONSE_PLAN_METADATA_KEY: response_plan.model_dump(
                        mode="json"
                    )
                },
                created_at=now,
                updated_at=now,
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()


def _seed_workflow_runtime(
    session_factory: object,
    dataset_storage: object,
    *,
    application_id: str,
    application_display_name: str,
    workflow_runtime_id: str,
) -> None:
    """写入一个独立 Workflow app runtime，供文件名回归测试使用。"""

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    application_object_key = f"projects/project-1/workflows/apps/{application_id}/app.json"
    dataset_storage.write_json(
        application_object_key,
        {
            "application_id": application_id,
            "display_name": application_display_name,
        },
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_runtime.save_workflow_app_runtime(
            WorkflowAppRuntime(
                workflow_runtime_id=workflow_runtime_id,
                project_id="project-1",
                application_id=application_id,
                display_name=f"{application_display_name} runtime",
                application_snapshot_object_key=application_object_key,
                template_snapshot_object_key=(
                    f"projects/project-1/workflows/templates/{application_id}/template.json"
                ),
                desired_state="running",
                observed_state="running",
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
