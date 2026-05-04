"""YOLOX DeploymentInstance API 行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.api.app import create_app
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXBuildRegistration,
    YoloXTrainingOutputRegistration,
)
from backend.service.domain.files.yolox_file_types import YOLOX_ONNX_FILE
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.service.infrastructure.persistence.deployment_repository import SqlAlchemyDeploymentInstanceRepository
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig


def test_create_list_and_get_yolox_deployment_instance(tmp_path: Path) -> None:
    """验证 DeploymentInstance create、list 和 detail 可以闭环。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "runtime_backend": "pytorch",
                    "device_name": "cpu",
                    "display_name": "yolox bolt deployment",
                },
            )

            assert create_response.status_code == 201
            payload = create_response.json()
            deployment_instance_id = payload["deployment_instance_id"]
            assert payload["project_id"] == "project-1"
            assert payload["model_version_id"] == model_version_id
            assert payload["model_build_id"] is None
            assert payload["runtime_backend"] == "pytorch"
            assert payload["device_name"] == "cpu"
            assert payload["input_size"] == [64, 64]
            assert payload["labels"] == ["bolt"]

            list_response = client.get(
                "/api/v1/models/yolox/deployment-instances?project_id=project-1",
                headers=_build_headers(),
            )
            assert list_response.status_code == 200
            list_payload = list_response.json()
            assert len(list_payload) == 1
            assert list_payload[0]["deployment_instance_id"] == deployment_instance_id

            detail_response = client.get(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}",
                headers=_build_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["display_name"] == "yolox bolt deployment"
            assert detail_payload["model_name"] == "yolox-nano-deployment"
            assert detail_payload["status"] == "active"
            assert detail_payload["metadata"] == {}

        session = session_factory.create_session()
        try:
            saved_instance = SqlAlchemyDeploymentInstanceRepository(session).get_deployment_instance(
                deployment_instance_id
            )
        finally:
            session.close()

        assert saved_instance is not None
        snapshot = saved_instance.metadata.get("runtime_target_snapshot")
        assert isinstance(snapshot, dict)
        assert snapshot["model_version_id"] == model_version_id
        assert snapshot["checkpoint_storage_uri"] == (
            "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth"
        )
    finally:
        session_factory.engine.dispose()


def test_create_yolox_deployment_instance_uses_model_build_snapshot(tmp_path: Path) -> None:
    """验证 DeploymentInstance 绑定 ModelBuild 时会固化 build 文件快照。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    model_build_id = _seed_model_build(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        model_version_id=model_version_id,
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_build_id": model_build_id,
                    "display_name": "yolox onnx deployment",
                },
            )

            assert create_response.status_code == 201
            payload = create_response.json()
            deployment_instance_id = payload["deployment_instance_id"]
            assert payload["model_version_id"] == model_version_id
            assert payload["model_build_id"] == model_build_id
            assert payload["runtime_backend"] == "onnxruntime"

        session = session_factory.create_session()
        try:
            saved_instance = SqlAlchemyDeploymentInstanceRepository(session).get_deployment_instance(
                deployment_instance_id
            )
        finally:
            session.close()

        assert saved_instance is not None
        snapshot = saved_instance.metadata.get("runtime_target_snapshot")
        assert isinstance(snapshot, dict)
        assert snapshot["model_build_id"] == model_build_id
        assert snapshot["runtime_backend"] == "onnxruntime"
        assert snapshot["runtime_artifact_file_type"] == YOLOX_ONNX_FILE
        assert snapshot["runtime_artifact_storage_uri"] == "projects/project-1/models/builds/build-1/yolox.onnx"
        assert snapshot["checkpoint_storage_uri"] == (
            "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth"
        )
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage]:
    """创建绑定测试数据库和本地文件存储的 API 客户端。"""

    database_path = tmp_path / "amvision-deployments-api.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    settings = BackendServiceSettings(
        task_manager=BackendServiceTaskManagerConfig(
            enabled=False,
            max_concurrent_tasks=2,
            poll_interval_seconds=0.05,
        )
    )
    client = TestClient(
        create_app(
            settings=settings,
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        )
    )
    return client, session_factory, dataset_storage


def _seed_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    checkpoint_uri = "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = "projects/project-1/models/deployment-source-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, b"fake-checkpoint")
    dataset_storage.write_text(labels_uri, "bolt\n")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-deployment-source-1",
            model_name="yolox-nano-deployment",
            model_scale="nano",
            dataset_version_id="dataset-version-deployment-source-1",
            checkpoint_file_id="checkpoint-file-deployment-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-deployment-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


def _seed_model_build(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    model_version_id: str,
) -> str:
    """写入一个与 ModelVersion 绑定的最小 ONNX ModelBuild。"""

    build_uri = "projects/project-1/models/builds/build-1/yolox.onnx"
    dataset_storage.write_bytes(build_uri, b"fake-onnx-build")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_build(
        YoloXBuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            build_file_id="build-file-onnx-1",
            build_file_uri=build_uri,
            conversion_task_id="conversion-task-1",
        )
    )


def _build_headers() -> dict[str, str]:
    """构建具备 deployment API 所需 scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read,models:write",
    }