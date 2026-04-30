"""平台基础模型查询 API 行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.api.app import create_app
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXPretrainedRegistrationRequest,
    YoloXTrainingOutputRegistration,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig


def test_list_platform_base_models_returns_only_platform_models(tmp_path: Path) -> None:
    """验证平台基础模型列表接口只返回 platform-base 模型。"""

    client, session_factory = _create_test_client(tmp_path)
    platform_model_ids = _seed_platform_and_project_models(session_factory)
    try:
        with client:
            response = client.get(
                "/api/v1/models/platform-base",
                headers=_build_model_headers(),
            )

        assert response.status_code == 200
        payload = response.json()
        assert [item["model_id"] for item in payload] == platform_model_ids
        assert all(item["scope_kind"] == "platform-base" for item in payload)
        assert all(item["project_id"] is None for item in payload)
        assert payload[0]["available_versions"][0]["model_version_id"] == "model-version-pretrained-yolox-nano"
        assert payload[1]["available_versions"][0]["checkpoint_storage_uri"] == (
            "models/pretrained/yolox/s/default/checkpoints/yolox_s.pth"
        )
    finally:
        session_factory.engine.dispose()


def test_get_platform_base_model_detail_returns_versions_and_files(tmp_path: Path) -> None:
    """验证平台基础模型详情接口会返回版本和文件明细。"""

    client, session_factory = _create_test_client(tmp_path)
    platform_model_ids = _seed_platform_and_project_models(session_factory)
    try:
        with client:
            response = client.get(
                f"/api/v1/models/platform-base/{platform_model_ids[0]}",
                headers=_build_model_headers(),
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["model_id"] == platform_model_ids[0]
        assert payload["project_id"] is None
        assert payload["version_count"] == 1
        assert payload["build_count"] == 0
        assert payload["versions"][0]["model_version_id"] == "model-version-pretrained-yolox-nano"
        assert payload["versions"][0]["catalog_manifest_object_key"] == (
            "models/pretrained/yolox/nano/default/manifest.json"
        )
        assert payload["versions"][0]["files"][0]["project_id"] is None
        assert payload["versions"][0]["files"][0]["file_type"] == "yolox-checkpoint"
    finally:
        session_factory.engine.dispose()


def test_get_platform_base_model_detail_rejects_project_model_id(tmp_path: Path) -> None:
    """验证平台基础模型详情接口不会暴露 Project 内模型。"""

    client, session_factory = _create_test_client(tmp_path)
    _platform_model_ids, project_model_id = _seed_platform_and_project_models(session_factory, include_project_model=True)
    try:
        with client:
            response = client.get(
                f"/api/v1/models/platform-base/{project_model_id}",
                headers=_build_model_headers(),
            )

        assert response.status_code == 404
        payload = response.json()
        assert payload["error"]["code"] == "resource_not_found"
        assert payload["error"]["message"] == "找不到指定的平台基础模型"
    finally:
        session_factory.engine.dispose()


def test_list_platform_base_models_requires_models_read_scope(tmp_path: Path) -> None:
    """验证平台基础模型列表接口要求 models:read scope。"""

    client, session_factory = _create_test_client(tmp_path)
    _seed_platform_and_project_models(session_factory)
    try:
        with client:
            response = client.get(
                "/api/v1/models/platform-base",
                headers=_build_model_headers(scopes="tasks:read"),
            )

        assert response.status_code == 403
        payload = response.json()
        assert payload["error"]["code"] == "permission_denied"
    finally:
        session_factory.engine.dispose()


def _seed_platform_and_project_models(
    session_factory: SessionFactory,
    *,
    include_project_model: bool = False,
) -> tuple[list[str], str] | list[str]:
    """向测试数据库写入平台基础模型和可选的 Project 模型。

    参数：
    - session_factory：测试数据库会话工厂。
    - include_project_model：是否同时返回一个 Project 模型 id。

    返回：
    - 平台基础模型 id 列表；当 include_project_model 为 True 时额外返回 Project 模型 id。
    """

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    nano_version_id = service.register_pretrained(
        YoloXPretrainedRegistrationRequest(
            model_name="yolox",
            storage_uri="models/pretrained/yolox/nano/default/checkpoints/yolox_nano.pth",
            model_scale="nano",
            model_version_id="model-version-pretrained-yolox-nano",
            checkpoint_file_id="model-file-pretrained-yolox-nano-checkpoint",
            metadata={
                "catalog_manifest_object_key": "models/pretrained/yolox/nano/default/manifest.json",
                "catalog_name": "default",
            },
        )
    )
    s_version_id = service.register_pretrained(
        YoloXPretrainedRegistrationRequest(
            model_name="yolox",
            storage_uri="models/pretrained/yolox/s/default/checkpoints/yolox_s.pth",
            model_scale="s",
            model_version_id="model-version-pretrained-yolox-s",
            checkpoint_file_id="model-file-pretrained-yolox-s-checkpoint",
            metadata={
                "catalog_manifest_object_key": "models/pretrained/yolox/s/default/manifest.json",
                "catalog_name": "default",
            },
        )
    )

    nano_model = service.get_model(service.get_model_version(nano_version_id).model_id)
    s_model = service.get_model(service.get_model_version(s_version_id).model_id)
    platform_model_ids = [nano_model.model_id, s_model.model_id]

    if not include_project_model:
        return platform_model_ids

    project_version_id = service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-task-1",
            model_name="yolox",
            model_scale="nano",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="model-file-project-yolox-nano-checkpoint",
            checkpoint_file_uri="task-runs/training/task-1/artifacts/checkpoints/best_ckpt.pth",
            metadata={"dataset_export_id": "dataset-export-1"},
        )
    )
    project_model = service.get_model(service.get_model_version(project_version_id).model_id)
    return platform_model_ids, project_model.model_id


def _create_test_client(tmp_path: Path) -> tuple[TestClient, SessionFactory]:
    """创建平台基础模型 API 测试客户端。"""

    database_path = tmp_path / "amvision-platform-base-models.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    settings = BackendServiceSettings(
        task_manager=BackendServiceTaskManagerConfig(enabled=False),
    )
    client = TestClient(
        create_app(
            settings=settings,
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        )
    )
    return client, session_factory


def _build_model_headers(*, scopes: str = "models:read") -> dict[str, str]:
    """构建平台基础模型 API 测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": scopes,
    }