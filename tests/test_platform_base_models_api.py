"""平台基础模型查询 API 行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.application.models.registry.model_service import (
    ModelBuildRegistration,
    PretrainedRegistrationRequest,
    SqlAlchemyModelService,
    TrainingOutputRegistration,
)
from backend.service.application.models.catalog.yolo_model_pretrained_catalog import (
    _load_yolo_model_catalog_entry,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.db.session import SessionFactory
from tests.api_test_support import (
    build_bearer_headers,
    build_test_headers,
    create_api_test_context,
    issue_test_user_token,
)


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
            "models/pretrained/yolox/detection/s/default/checkpoints/yolox_s.pth"
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
            "models/pretrained/yolox/detection/nano/default/manifest.json"
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
    denied_token = issue_test_user_token(
        session_factory,
        username="platform-model-reader",
        scopes=("tasks:read",),
    )
    try:
        with client:
            response = client.get(
                "/api/v1/models/platform-base",
                headers=build_bearer_headers(denied_token),
            )

        assert response.status_code == 403
        payload = response.json()
        assert payload["error"]["code"] == "permission_denied"
    finally:
        session_factory.engine.dispose()


def test_deployment_source_models_include_project_training_builds(tmp_path: Path) -> None:
    """验证部署来源接口会返回当前 Project 的训练版本和转换 build。"""

    client, session_factory = _create_test_client(tmp_path)
    _seed_platform_and_project_models(session_factory)
    service = SqlAlchemyModelService(session_factory=session_factory)
    project_version_id = service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-task-deployable",
            model_name="yolox",
            model_scale="m",
            dataset_version_id="dataset-version-deployable",
            checkpoint_file_id="model-file-project-yolox-m-checkpoint",
            checkpoint_file_uri="task-runs/training/task-2/artifacts/checkpoints/best_ckpt.pth",
            metadata={"dataset_export_id": "dataset-export-deployable"},
        )
    )
    project_model = service.get_model(service.get_model_version(project_version_id).model_id)
    project_build_id = service.register_build(
        ModelBuildRegistration(
            project_id="project-1",
            source_model_version_id=project_version_id,
            build_format="onnx",
            runtime_backend="onnxruntime",
            runtime_precision="fp32",
            build_file_id="model-file-project-yolox-m-onnx",
            build_file_uri="projects/project-1/models/builds/yolox-m.onnx",
            conversion_task_id="conversion-task-deployable",
            metadata={},
        )
    )
    try:
        with client:
            list_response = client.get(
                "/api/v1/models/deployment-sources?project_id=project-1&task_type=detection",
                headers=_build_model_headers(),
            )

            assert list_response.status_code == 200
            list_payload = list_response.json()
            assert list_payload[0]["model_id"] == project_model.model_id
            assert list_payload[0]["scope_kind"] == "project"
            assert list_payload[0]["project_id"] == "project-1"
            assert list_payload[0]["version_count"] == 1
            assert list_payload[0]["build_count"] == 1

            detail_response = client.get(
                f"/api/v1/models/deployment-sources/{project_model.model_id}?project_id=project-1",
                headers=_build_model_headers(),
            )

            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["versions"][0]["model_version_id"] == project_version_id
            assert detail_payload["builds"][0]["model_build_id"] == project_build_id
            assert detail_payload["builds"][0]["build_format"] == "onnx"
            assert detail_payload["builds"][0]["runtime_backend"] == "onnxruntime"
            assert detail_payload["builds"][0]["runtime_precision"] == "fp32"
            assert "runtime_backend" not in detail_payload["builds"][0]["metadata"]
            assert "runtime_precision" not in detail_payload["builds"][0]["metadata"]

            hidden_response = client.get(
                f"/api/v1/models/deployment-sources/{project_model.model_id}?project_id=project-2",
                headers=_build_model_headers(),
            )

            assert hidden_response.status_code == 404
    finally:
        session_factory.engine.dispose()


def test_yolo_model_pretrained_manifest_rejects_inconsistent_model_version_id(tmp_path: Path) -> None:
    """验证 YOLO 主线预训练 manifest 不会静默接受错误版本 id。"""

    manifest_path, dataset_storage = _write_yolo_model_manifest(
        tmp_path,
        model_version_id="mv-pretrainanoed-yolov8-detectionano-nano",
    )

    try:
        _load_yolo_model_catalog_entry(
            manifest_path=manifest_path,
            dataset_storage=dataset_storage,
            model_type="yolov8",
        )
    except ServiceConfigurationError as exc:
        assert exc.details["expected_prefix"] == "mv-pretrained-yolov8-detection-nano"
    else:
        raise AssertionError("错误的 model_version_id 应该被拒绝")


def test_yolo_model_pretrained_manifest_accepts_variant_model_version_id(tmp_path: Path) -> None:
    """验证 YOLO 主线预训练 manifest 允许使用 variant 后缀区分版本。"""

    manifest_path, dataset_storage = _write_yolo_model_manifest(
        tmp_path,
        model_version_id="mv-pretrained-yolov8-detection-nano-openimagev7",
    )

    entry = _load_yolo_model_catalog_entry(
        manifest_path=manifest_path,
        dataset_storage=dataset_storage,
        model_type="yolov8",
    )

    assert entry.model_version_id == "mv-pretrained-yolov8-detection-nano-openimagev7"


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

    service = SqlAlchemyModelService(session_factory=session_factory)
    nano_version_id = service.register_pretrained(
        PretrainedRegistrationRequest(
            model_name="yolox",
            storage_uri="models/pretrained/yolox/detection/nano/default/checkpoints/yolox_nano.pth",
            model_scale="nano",
            model_version_id="model-version-pretrained-yolox-nano",
            checkpoint_file_id="model-file-pretrained-yolox-nano-checkpoint",
            metadata={
                "catalog_manifest_object_key": "models/pretrained/yolox/detection/nano/default/manifest.json",
                "catalog_name": "default",
            },
        )
    )
    s_version_id = service.register_pretrained(
        PretrainedRegistrationRequest(
            model_name="yolox",
            storage_uri="models/pretrained/yolox/detection/s/default/checkpoints/yolox_s.pth",
            model_scale="s",
            model_version_id="model-version-pretrained-yolox-s",
            checkpoint_file_id="model-file-pretrained-yolox-s-checkpoint",
            metadata={
                "catalog_manifest_object_key": "models/pretrained/yolox/detection/s/default/manifest.json",
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
        TrainingOutputRegistration(
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

    context = create_api_test_context(
        tmp_path,
        database_name="amvision-platform-base-models.db",
    )
    return context.client, context.session_factory


def _build_model_headers(*, scopes: str = "models:read") -> dict[str, str]:
    """构建平台基础模型 API 测试请求头。"""

    return build_test_headers(scopes=scopes)


def _write_yolo_model_manifest(
    tmp_path: Path,
    *,
    model_version_id: str,
) -> tuple[Path, LocalDatasetStorage]:
    """写入一个最小 YOLO 主线预训练 manifest。"""

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")))
    manifest_dir = dataset_storage.root_dir / "models" / "pretrained" / "yolov8" / "detection" / "nano" / "default"
    checkpoint_path = manifest_dir / "checkpoints" / "yolov8n.pt"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_bytes(b"fake-checkpoint")
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(
        "\n".join(
            [
                "{",
                '  "model_name": "yolov8",',
                '  "model_scale": "nano",',
                '  "task_type": "detection",',
                f'  "model_version_id": "{model_version_id}",',
                '  "checkpoint_file_id": "mf-pretrained-yolov8-detection-nano-checkpoint",',
                '  "checkpoint_path": "checkpoints/yolov8n.pt",',
                '  "metadata": {"catalog_name": "default", "entry_name": "default"}',
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return manifest_path, dataset_storage
