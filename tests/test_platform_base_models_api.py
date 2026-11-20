"""平台基础模型查询 API 行为测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.service.application.models.registry.model_service import (
    ModelBuildRegistration,
    PretrainedRegistrationRequest,
    SqlAlchemyModelService,
    TrainingOutputRegistration,
)
from backend.service.application.models.registry.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
    Yolo11TrainingOutputRegistration,
)
from backend.service.application.models.catalog.yolo_model_pretrained_catalog import (
    _load_yolo_model_catalog_entry,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.domain.models.model_records import Model
from backend.service.domain.deployments.deployment_instance import DeploymentInstance
from backend.service.domain.deployments.deployment_runtime_state import DeploymentRuntimeState
from backend.service.infrastructure.persistence.model_repository import SqlAlchemyModelRepository
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
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


def test_project_model_catalog_filters_and_paginates_without_losing_empty_models(tmp_path: Path) -> None:
    """目录只包含当前项目，统计全部结果并保留没有版本的模型。"""

    client, session_factory = _create_test_client(tmp_path)
    platform_ids, _ = _seed_platform_and_project_models(session_factory, include_project_model=True)
    with session_factory.create_session() as session:
        repository = SqlAlchemyModelRepository(session)
        for model_id, project_id, name, task in (
            ("empty-1", "project-1", "Alpha_100%", "detection"),
            ("empty-2", "project-1", "Beta", "classification"),
            ("other-project", "project-2", "Alpha_other", "detection"),
        ):
            repository.save_model(Model(model_id=model_id, project_id=project_id, model_name=name,
                                        model_type="yolox", task_type=task, model_scale="s"))
        session.commit()
    restricted_token = issue_test_user_token(
        session_factory, username="catalog-reader", scopes=("models:read",), project_ids=("project-1",)
    )
    try:
        with client:
            response = client.get("/api/v1/models/catalog", params={"project_id": "project-1", "limit": 1}, headers=build_bearer_headers(restricted_token))
            assert response.status_code == 200
            assert response.json()["total"] == 3
            assert response.json()["items"][0]["model_id"] == "empty-1"
            assert response.json()["items"][0]["version_count"] == 0
            assert response.json()["items"][0]["build_formats"] == []
            page = client.get("/api/v1/models/catalog", params={"project_id": "project-1", "limit": 1, "offset": 1}, headers=build_bearer_headers(restricted_token))
            assert page.json()["total"] == 3
            assert page.json()["items"][0]["model_id"] == "empty-2"
            filtered = client.get("/api/v1/models/catalog", params={"project_id": "project-1", "query": "_100%", "task_type": "detection"}, headers=build_bearer_headers(restricted_token))
            assert [item["model_id"] for item in filtered.json()["items"]] == ["empty-1"]
            denied = client.get("/api/v1/models/catalog", params={"project_id": "project-2"}, headers=build_bearer_headers(restricted_token))
            assert denied.status_code == 403
            detail = client.get("/api/v1/models/catalog/empty-1", params={"project_id": "project-1"}, headers=build_bearer_headers(restricted_token))
            assert detail.status_code == 200
            assert detail.json()["versions"] == []
            hidden = client.get(f"/api/v1/models/catalog/{platform_ids[0]}", params={"project_id": "project-1"}, headers=build_bearer_headers(restricted_token))
            assert hidden.status_code == 404
    finally:
        session_factory.engine.dispose()


def test_project_model_references_are_direct_scoped_and_paginated(tmp_path: Path) -> None:
    """版本引用只包含当前项目的直接部署，分页及运行模式状态独立。"""

    client, session_factory = _create_test_client(tmp_path)
    platform_ids, model_id = _seed_platform_and_project_models(session_factory, include_project_model=True)
    with session_factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        version_id = unit.models.list_model_versions(model_id)[0].model_version_id
        for index in range(8):
            deployment_id = f"deployment-{index}"
            unit.deployments.save_deployment_instance(DeploymentInstance(
                deployment_instance_id=deployment_id, project_id="project-1", model_id=model_id,
                model_version_id=version_id, display_name=f"Line_{index}%", created_at=f"2026-11-{index + 1:02}",
            ))
        unit.deployments.save_deployment_instance(DeploymentInstance(
            deployment_instance_id="other-project", project_id="project-2", model_id=model_id,
            model_version_id=version_id, display_name="Hidden", created_at="2026-11-11",
        ))
        unit.deployment_runtime_states.save_deployment_runtime_state(DeploymentRuntimeState(
            deployment_instance_id="deployment-7", runtime_mode="sync", observed_state="running",
        ))
        unit.deployment_runtime_states.save_deployment_runtime_state(DeploymentRuntimeState(
            deployment_instance_id="deployment-7", runtime_mode="async", observed_state="stopped",
        ))
        unit.commit()
    token = issue_test_user_token(session_factory, username="references-reader", scopes=("models:read",), project_ids=("project-1",))
    headers = build_bearer_headers(token)
    path = f"/api/v1/models/catalog/{model_id}/versions/{version_id}/references"
    try:
        with client:
            first = client.get(path, params={"project_id": "project-1", "limit": 6}, headers=headers)
            assert first.status_code == 200
            assert first.json()["total"] == 8
            assert len(first.json()["items"]) == 6
            assert first.json()["items"][0]["runtime_states"] == {"sync": "running", "async": "stopped"}
            second = client.get(path, params={"project_id": "project-1", "limit": 6, "offset": 6}, headers=headers)
            assert len(second.json()["items"]) == 2
            filtered = client.get(path, params={"project_id": "project-1", "query": "_7%"}, headers=headers)
            assert filtered.json()["total"] == 1
            assert filtered.json()["items"][0]["deployment_id"] == "deployment-7"
            denied = client.get(path, params={"project_id": "project-2"}, headers=headers)
            assert denied.status_code == 403
            hidden = client.get(f"/api/v1/models/catalog/{platform_ids[0]}/versions/{version_id}/references", params={"project_id": "project-1"}, headers=headers)
            assert hidden.status_code == 404
    finally:
        session_factory.engine.dispose()


def test_project_model_file_status_checks_existence_without_cross_project_access(tmp_path: Path) -> None:
    """只检查属于目标项目版本的登记文件，区分缺失和存在。"""

    context = create_api_test_context(tmp_path, database_name="model-file-status.db")
    client, session_factory, storage = context.client, context.session_factory, context.dataset_storage
    platform_ids, model_id = _seed_platform_and_project_models(session_factory, include_project_model=True)
    with session_factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        version = unit.models.list_model_versions(model_id)[0]
        model_file = next(file for file in unit.model_files.list_model_files(model_version_id=version.model_version_id) if file.file_type.endswith("checkpoint"))
    token = issue_test_user_token(session_factory, username="file-reader", scopes=("models:read",), project_ids=("project-1",))
    headers = build_bearer_headers(token)
    path = f"/api/v1/models/catalog/{model_id}/versions/{version.model_version_id}/files/{model_file.file_id}/status"
    try:
        with client:
            missing = client.get(path, params={"project_id": "project-1"}, headers=headers)
            assert missing.status_code == 200
            assert missing.json()["state"] == "missing"
            download_path = path.removesuffix("/status") + "/download"
            assert client.get(download_path, params={"project_id": "project-1"}, headers=headers).status_code == 404
            storage.write_bytes(model_file.storage_uri, b"test model")
            present = client.get(path, params={"project_id": "project-1"}, headers=headers)
            assert present.json() == {"file_id": model_file.file_id, "state": "present", "size_bytes": 10}
            digest = client.get(path, params={"project_id": "project-1", "include_sha256": "true"}, headers=headers)
            assert digest.json()["sha256"] == sha256(b"test model").hexdigest()
            assert client.get(path, params={"project_id": "project-1", "part": "weights"}, headers=headers).status_code == 404
            download = client.get(download_path, params={"project_id": "project-1"}, headers=headers)
            assert download.status_code == 200
            assert download.content == b"test model"
            assert download.headers["cache-control"] == "no-store"
            assert Path(model_file.storage_uri).name in download.headers["content-disposition"]
            assert client.get(path, params={"project_id": "project-2"}, headers=headers).status_code == 403
            assert client.get(download_path, params={"project_id": "project-2"}, headers=headers).status_code == 403
            wrong_model = f"/api/v1/models/catalog/{platform_ids[0]}/versions/{version.model_version_id}/files/{model_file.file_id}/status"
            assert client.get(wrong_model, params={"project_id": "project-1"}, headers=headers).status_code == 404
    finally:
        session_factory.engine.dispose()


def test_project_model_file_legacy_openvino_weights_are_scoped_to_the_registered_xml(tmp_path: Path) -> None:
    """旧 OpenVINO 产物只允许读取其登记的同目录、同名权重。"""

    context = create_api_test_context(tmp_path, database_name="openvino-file-status.db")
    client, session_factory, storage = context.client, context.session_factory, context.dataset_storage
    _, model_id = _seed_platform_and_project_models(session_factory, include_project_model=True)
    with session_factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        version_id = unit.models.list_model_versions(model_id)[0].model_version_id
    service = SqlAlchemyModelService(session_factory=session_factory)
    for name, weights in (
        ("valid", "projects/project-1/models/valid.bin"),
        ("unrelated", "projects/project-1/models/valid.bin"),
    ):
        service.register_build(ModelBuildRegistration(
            project_id="project-1", source_model_version_id=version_id, build_format="openvino-ir",
            runtime_backend="openvino", runtime_precision="fp32", build_file_id=f"{name}-xml",
            build_file_uri=f"projects/project-1/models/{name}.xml", conversion_task_id=f"convert-{name}",
            metadata={"weights_object_uri": weights},
        ))
    storage.write_bytes("projects/project-1/models/valid.xml", b"<net/>")
    token = issue_test_user_token(session_factory, username="weights-reader", scopes=("models:read",), project_ids=("project-1",))
    endpoint = f"/api/v1/models/catalog/{model_id}/versions/{version_id}/files"
    headers = build_bearer_headers(token)
    try:
        with client:
            params = {"project_id": "project-1", "part": "weights"}
            assert client.get(f"{endpoint}/valid-xml/status", params=params, headers=headers).json()["state"] == "missing"
            storage.write_bytes("projects/project-1/models/valid.bin", b"weights")
            status = client.get(f"{endpoint}/valid-xml/status", params={**params, "include_sha256": "true"}, headers=headers)
            assert status.json() == {
                "file_id": "valid-xml", "state": "present", "size_bytes": 7, "part": "weights",
                "sha256": sha256(b"weights").hexdigest(),
            }
            download = client.get(f"{endpoint}/valid-xml/download", params=params, headers=headers)
            assert download.content == b"weights"
            assert "valid.bin" in download.headers["content-disposition"]
            assert client.get(f"{endpoint}/unrelated-xml/download", params=params, headers=headers).status_code == 404
            denied = client.get(f"{endpoint}/valid-xml/download", params={**params, "project_id": "project-2"}, headers=headers)
            assert denied.status_code == 403
    finally:
        session_factory.engine.dispose()


def test_project_model_presentation_preserves_identity_and_rejects_stale_edits(tmp_path: Path) -> None:
    """展示信息不改登记自然键，过期编辑和跨项目访问被拒绝。"""
    client, session_factory = _create_test_client(tmp_path)
    _, model_id = _seed_platform_and_project_models(session_factory, include_project_model=True)
    token = issue_test_user_token(session_factory, username="presentation-editor", scopes=("models:read", "models:write"), project_ids=("project-1",))
    headers = build_bearer_headers(token)
    endpoint = f"/api/v1/models/catalog/{model_id}/presentation"
    try:
        with client:
            before = client.get(f"/api/v1/models/catalog/{model_id}", params={"project_id": "project-1"}, headers=headers).json()
            request = {"display_name": "新的展示名", "description": "说明", "expected_revision": 0}
            saved = client.put(endpoint, params={"project_id": "project-1"}, headers=headers, json=request)
            assert saved.status_code == 200
            assert saved.json()["revision"] == 1
            stale = client.put(endpoint, params={"project_id": "project-1"}, headers=headers, json=request)
            assert stale.status_code == 409
            denied = client.put(endpoint, params={"project_id": "project-2"}, headers=headers, json=request)
            assert denied.status_code == 403
            after = client.get(f"/api/v1/models/catalog/{model_id}", params={"project_id": "project-1"}, headers=headers).json()
            assert after["model_name"] == before["model_name"]
            assert after["metadata"]["display_name"] == "新的展示名"
            assert after["metadata"]["description"] == "说明"
            assert after["metadata"]["presentation_updated_at"].endswith("+00:00")
            assert [item["model_version_id"] for item in after["versions"]] == [item["model_version_id"] for item in before["versions"]]
            found = client.get("/api/v1/models/catalog", params={"project_id": "project-1", "query": "新的展示名"}, headers=headers).json()
            assert found["total"] == 1
    finally:
        session_factory.engine.dispose()


def test_platform_base_checkpoint_state_tracks_the_registered_file(tmp_path: Path) -> None:
    """基础模型状态只表示已登记 checkpoint 是否实际存在。"""

    context = create_api_test_context(tmp_path, database_name="base-checkpoint-state.db")
    client, session_factory, storage = context.client, context.session_factory, context.dataset_storage
    model_ids = _seed_platform_and_project_models(session_factory)
    with session_factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        version = unit.models.list_model_versions(model_ids[0])[0]
        model_file = next(file for file in unit.model_files.list_model_files(model_version_id=version.model_version_id) if file.file_type.endswith("checkpoint"))
    try:
        with client:
            response = client.get("/api/v1/models/platform-base", headers=_build_model_headers())
            item = next(item for item in response.json() if item["model_id"] == model_ids[0])
            assert item["available_versions"][0]["checkpoint_state"] == "missing"
            storage.write_bytes(model_file.storage_uri, b"checkpoint")
            response = client.get("/api/v1/models/platform-base", headers=_build_model_headers())
            item = next(item for item in response.json() if item["model_id"] == model_ids[0])
            assert item["available_versions"][0]["checkpoint_state"] == "present"
    finally:
        session_factory.engine.dispose()


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
        assert (
            payload[0]["available_versions"][0]["model_version_id"]
            == "model-version-pretrained-yolox-nano"
        )
        assert payload[1]["available_versions"][0]["checkpoint_storage_uri"] == (
            "models/pretrained/yolox/detection/s/default/checkpoints/yolox_s.pth"
        )
    finally:
        session_factory.engine.dispose()


def test_get_platform_base_model_detail_returns_versions_and_files(
    tmp_path: Path,
) -> None:
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
        assert (
            payload["versions"][0]["model_version_id"]
            == "model-version-pretrained-yolox-nano"
        )
        assert payload["versions"][0]["catalog_manifest_object_key"] == (
            "models/pretrained/yolox/detection/nano/default/manifest.json"
        )
        assert payload["versions"][0]["files"][0]["project_id"] is None
        assert payload["versions"][0]["files"][0]["file_type"] == "yolox-checkpoint"
    finally:
        session_factory.engine.dispose()


def test_get_platform_base_model_detail_rejects_project_model_id(
    tmp_path: Path,
) -> None:
    """验证平台基础模型详情接口不会暴露 Project 内模型。"""

    client, session_factory = _create_test_client(tmp_path)
    _platform_model_ids, project_model_id = _seed_platform_and_project_models(
        session_factory, include_project_model=True
    )
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


def test_deployment_source_models_include_project_training_builds(
    tmp_path: Path,
) -> None:
    """验证部署来源接口会返回当前 Project 的训练版本和转换 build。"""

    context = create_api_test_context(tmp_path, database_name="deployment-source-checkpoint.db")
    client, session_factory, storage = context.client, context.session_factory, context.dataset_storage
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
            metadata={
                "dataset_export_id": "dataset-export-deployable",
                "input_size": {"width": 640, "height": 640},
            },
        )
    )
    project_model = service.get_model(
        service.get_model_version(project_version_id).model_id
    )
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
            assert list_payload[0]["available_versions"][0]["checkpoint_state"] == "missing"
            storage.write_bytes("task-runs/training/task-2/artifacts/checkpoints/best_ckpt.pth", b"checkpoint")
            refreshed = client.get(
                "/api/v1/models/deployment-sources?project_id=project-1&task_type=detection",
                headers=_build_model_headers(),
            )
            assert refreshed.json()[0]["available_versions"][0]["checkpoint_state"] == "present"

            detail_response = client.get(
                f"/api/v1/models/deployment-sources/{project_model.model_id}?project_id=project-1",
                headers=_build_model_headers(),
            )

            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert (
                detail_payload["versions"][0]["model_version_id"] == project_version_id
            )
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


def test_deployment_source_models_preserve_multi_generation_training_versions(
    tmp_path: Path,
) -> None:
    """验证通用部署来源接口保留 YOLO11 多代训练版本及 checkpoint。"""

    client, session_factory = _create_test_client(tmp_path)
    _seed_platform_and_project_models(session_factory)
    service = SqlAlchemyYolo11ModelService(session_factory=session_factory)
    service.register_pretrained(
        PretrainedRegistrationRequest(
            model_name="yolo11",
            storage_uri=(
                "models/pretrained/yolo11/classification/s/default/"
                "checkpoints/yolo11s-cls.pt"
            ),
            model_scale="s",
            model_version_id="mv-pretrained-yolo11-classification-s",
            checkpoint_file_id="mf-pretrained-yolo11-classification-s",
            task_type="classification",
            metadata={"input_size": {"width": 224, "height": 224}},
        )
    )
    first_version_id = service.register_training_output(
        Yolo11TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-task-generation-1",
            model_name="yolo11-lineage-generation-1",
            model_scale="s",
            task_type="classification",
            dataset_version_id="dataset-version-generation-1",
            parent_version_id="mv-pretrained-yolo11-classification-s",
            checkpoint_file_id="model-file-generation-1-checkpoint",
            checkpoint_file_uri="task-runs/training-task-generation-1/best.pth",
            metadata={"input_size": {"width": 640, "height": 640}},
        )
    )
    second_version_id = service.register_training_output(
        Yolo11TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-task-generation-2",
            model_name="yolo11-lineage-generation-2",
            model_scale="s",
            task_type="classification",
            dataset_version_id="dataset-version-generation-2",
            parent_version_id=first_version_id,
            checkpoint_file_id="model-file-generation-2-checkpoint",
            checkpoint_file_uri="task-runs/training-task-generation-2/best.pth",
            metadata={"input_size": {"width": 640, "height": 640}},
        )
    )

    try:
        with client:
            response = client.get(
                "/api/v1/models/deployment-sources?project_id=project-1&task_type=classification",
                headers=_build_model_headers(),
            )

        assert response.status_code == 200
        models_by_name = {item["model_name"]: item for item in response.json()}
        second_model = models_by_name["yolo11-lineage-generation-2"]
        assert len(second_model["available_versions"]) == 1
        second_version = second_model["available_versions"][0]
        assert second_version["model_version_id"] == second_version_id
        assert second_version["parent_version_id"] == first_version_id
        assert second_version["checkpoint_file_id"] == (
            "model-file-generation-2-checkpoint"
        )
        assert second_version["checkpoint_storage_uri"] == (
            "task-runs/training-task-generation-2/best.pth"
        )
    finally:
        session_factory.engine.dispose()


def test_yolo_model_pretrained_manifest_rejects_inconsistent_model_version_id(
    tmp_path: Path,
) -> None:
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


def test_yolo_model_pretrained_manifest_accepts_variant_model_version_id(
    tmp_path: Path,
) -> None:
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


def test_yolo_model_pretrained_manifest_concurrent_load_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证并发 catalog 扫描只读 manifest，不会把源文件写回自身。"""

    manifest_path, dataset_storage = _write_yolo_model_manifest(
        tmp_path,
        model_version_id="mv-pretrained-yolov8-detection-nano",
    )
    original_content = manifest_path.read_bytes()

    def reject_catalog_write(_relative_path: str, _content: str) -> None:
        raise AssertionError("catalog 扫描不得写回预训练 manifest")

    monkeypatch.setattr(dataset_storage, "write_text", reject_catalog_write)

    def load_entry(_index: int) -> str:
        entry = _load_yolo_model_catalog_entry(
            manifest_path=manifest_path,
            dataset_storage=dataset_storage,
            model_type="yolov8",
        )
        return entry.model_version_id

    with ThreadPoolExecutor(max_workers=16) as executor:
        model_version_ids = list(executor.map(load_entry, range(256)))

    assert set(model_version_ids) == {"mv-pretrained-yolov8-detection-nano"}
    assert manifest_path.read_bytes() == original_content


def test_yolo_model_pretrained_manifest_reports_nul_corruption(
    tmp_path: Path,
) -> None:
    """验证损坏 manifest 的启动错误包含路径和 NUL 诊断信息。"""

    manifest_path, dataset_storage = _write_yolo_model_manifest(
        tmp_path,
        model_version_id="mv-pretrained-yolov8-detection-nano",
    )
    manifest_path.write_bytes(b"\x00" * 401)

    with pytest.raises(ServiceConfigurationError) as exc_info:
        _load_yolo_model_catalog_entry(
            manifest_path=manifest_path,
            dataset_storage=dataset_storage,
            model_type="yolov8",
        )

    assert manifest_path.as_posix() in exc_info.value.message
    assert exc_info.value.details == {
        "manifest_path": manifest_path.as_posix(),
        "file_size_bytes": 401,
        "contains_nul": True,
    }


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
            metadata={
                "dataset_export_id": "dataset-export-1",
                "input_size": {"width": 640, "height": 640},
            },
        )
    )
    project_model = service.get_model(
        service.get_model_version(project_version_id).model_id
    )
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

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    manifest_dir = (
        dataset_storage.root_dir
        / "models"
        / "pretrained"
        / "yolov8"
        / "detection"
        / "nano"
        / "default"
    )
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
