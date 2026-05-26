"""项目目录与对象读取接口测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.infrastructure.object_store.object_key_layout import build_public_project_file_id
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.datasets.dataset_import import DatasetImport
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.settings import (
    BackendServiceProjectCatalogItemConfig,
    BackendServiceProjectsConfig,
    BackendServiceSettings,
)
from tests.api_test_support import (
    build_bearer_headers,
    build_test_headers,
    build_valid_test_png_bytes,
    create_test_runtime,
    issue_test_user_token,
)


def test_list_and_get_project_detail_expose_catalog_and_summary(tmp_path: Path) -> None:
    """验证项目列表和详情会返回目录信息，并支持内联 summary。"""

    client, session_factory = _create_project_resources_test_client(
        tmp_path,
        database_name="project-resources-projects.db",
    )

    try:
        with client:
            list_response = client.get(
                "/api/v1/projects",
                headers=_build_project_headers(),
                params={"include_summary": True},
            )
            detail_response = client.get(
                "/api/v1/projects/project-1",
                headers=_build_project_headers(),
            )
    finally:
        session_factory.engine.dispose()

    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload) == 1
    assert list_payload[0]["project_id"] == "project-1"
    assert list_payload[0]["display_name"] == "Project One"
    assert list_payload[0]["project_source"] == "configured"
    assert list_payload[0]["summary"]["project_id"] == "project-1"

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["project_id"] == "project-1"
    assert detail_payload["display_name"] == "Project One"
    assert detail_payload["summary"]["project_id"] == "project-1"


def test_project_list_supports_offset_limit_and_pagination_headers(tmp_path: Path) -> None:
    """验证项目列表接口支持统一分页参数与响应头。"""

    client, session_factory = _create_project_resources_test_client(
        tmp_path,
        database_name="project-resources-pagination.db",
        project_items=[
            BackendServiceProjectCatalogItemConfig(
                project_id="project-1",
                display_name="Project One",
                description="测试项目一",
            ),
            BackendServiceProjectCatalogItemConfig(
                project_id="project-2",
                display_name="Project Two",
                description="测试项目二",
            ),
        ],
    )

    try:
        visible_token = issue_test_user_token(
            session_factory,
            username="project-resources-viewer",
            scopes=("workflows:read", "models:read"),
            project_ids=("project-2", "project-1"),
        )
        with client:
            list_response = client.get(
                "/api/v1/projects",
                headers=build_bearer_headers(visible_token),
                params={"offset": 0, "limit": 1},
            )
    finally:
        session_factory.engine.dispose()

    assert list_response.status_code == 200
    assert list_response.headers["x-offset"] == "0"
    assert list_response.headers["x-limit"] == "1"
    assert list_response.headers["x-total-count"] == "2"
    assert list_response.headers["x-has-more"] == "true"
    assert list_response.headers["x-next-offset"] == "1"
    assert [item["project_id"] for item in list_response.json()] == ["project-2"]


def test_project_object_metadata_and_content_support_image_preview(tmp_path: Path) -> None:
    """验证项目对象接口可以返回图片元数据并直接输出图片内容。"""

    object_key = (
        "projects/project-1/results/workflow-applications/"
        "opencv-process-save-image-app/runs/workflow-run-1/preview.png"
    )
    client, session_factory, dataset_storage = _create_project_resources_test_client(
        tmp_path,
        database_name="project-resources-objects.db",
        include_storage=True,
    )
    dataset_storage.write_bytes(object_key, build_valid_test_png_bytes())

    try:
        with client:
            metadata_response = client.get(
                "/api/v1/projects/project-1/files/metadata",
                headers=_build_project_headers(),
                params={"object_key": object_key},
            )
            content_response = client.get(
                "/api/v1/projects/project-1/files/content",
                headers=_build_project_headers(),
                params={"object_key": object_key},
            )
    finally:
        session_factory.engine.dispose()

    assert metadata_response.status_code == 200
    metadata_payload = metadata_response.json()
    assert metadata_payload["file_id"] == build_public_project_file_id(
        project_id="project-1",
        object_key=object_key,
    )
    assert metadata_payload["object_key"] == object_key
    assert metadata_payload["media_type"] == "image/png"
    assert metadata_payload["content_url"].startswith("/api/v1/projects/project-1/files/content")

    assert content_response.status_code == 200
    assert content_response.headers["content-type"] == "image/png"
    assert content_response.content == build_valid_test_png_bytes()


def test_project_file_list_returns_public_files_with_file_ids(tmp_path: Path) -> None:
    """验证项目公开文件列表会直接返回 file_id，并过滤非公开命名空间。"""

    input_object_key = "projects/project-1/inputs/gallery/input-1.jpg"
    result_object_key = "projects/project-1/results/workflow-runs/run-1/result.json"
    version_object_key = "projects/project-1/datasets/dataset-1/versions/version-1/images/sample-1.jpg"
    private_object_key = "projects/project-1/datasets/dataset-1/imports/import-1/package.zip"

    client, session_factory, dataset_storage = _create_project_resources_test_client(
        tmp_path,
        database_name="project-resources-file-list.db",
        include_storage=True,
    )
    dataset_storage.write_bytes(input_object_key, build_valid_test_png_bytes())
    dataset_storage.write_text(result_object_key, '{"ok": true}')
    dataset_storage.write_bytes(version_object_key, build_valid_test_png_bytes())
    dataset_storage.write_bytes(private_object_key, b"fake-package")

    try:
        with client:
            list_response = client.get(
                "/api/v1/projects/project-1/files",
                headers=_build_project_headers(),
                params={"offset": 0, "limit": 10},
            )
            prefix_response = client.get(
                "/api/v1/projects/project-1/files",
                headers=_build_project_headers(),
                params={"object_prefix": "projects/project-1/inputs"},
            )
    finally:
        session_factory.engine.dispose()

    assert list_response.status_code == 200
    assert list_response.headers["x-total-count"] == "3"
    payload = list_response.json()
    object_keys = [item["object_key"] for item in payload]
    assert object_keys == sorted([input_object_key, version_object_key, result_object_key])
    item_by_object_key = {item["object_key"]: item for item in payload}
    assert item_by_object_key[input_object_key]["file_id"] == build_public_project_file_id(
        project_id="project-1",
        object_key=input_object_key,
    )
    assert private_object_key not in item_by_object_key

    assert prefix_response.status_code == 200
    prefix_payload = prefix_response.json()
    assert [item["object_key"] for item in prefix_payload] == [input_object_key]


def test_project_file_list_rejects_non_public_prefix(tmp_path: Path) -> None:
    """验证项目公开文件列表会拒绝非公开命名空间前缀。"""

    client, session_factory = _create_project_resources_test_client(
        tmp_path,
        database_name="project-resources-file-list-reject.db",
    )

    try:
        with client:
            response = client.get(
                "/api/v1/projects/project-1/files",
                headers=_build_project_headers(),
                params={
                    "object_prefix": "projects/project-1/datasets/dataset-1/imports/import-1",
                },
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_project_object_interface_rejects_non_public_namespace(tmp_path: Path) -> None:
    """验证项目对象接口会拒绝 imports 等非公开命名空间。"""

    object_key = "projects/project-1/datasets/dataset-1/imports/dataset-import-1/package.zip"
    client, session_factory, dataset_storage = _create_project_resources_test_client(
        tmp_path,
        database_name="project-resources-imports.db",
        include_storage=True,
    )
    dataset_storage.write_bytes(object_key, b"fake-package")

    try:
        with client:
            metadata_response = client.get(
                "/api/v1/projects/project-1/files/metadata",
                headers=_build_project_headers(),
                params={"object_key": object_key},
            )
    finally:
        session_factory.engine.dispose()

    assert metadata_response.status_code == 400
    error_payload = metadata_response.json()["error"]
    assert error_payload["code"] == "invalid_request"
    assert "allowed_namespaces" in error_payload["details"]


def test_project_bootstrap_creates_manifest_workspace_and_catalog_entry(tmp_path: Path) -> None:
    """验证 Project bootstrap 会创建目录骨架、manifest，并立即出现在目录列表中。"""

    client, session_factory, dataset_storage = _create_project_resources_test_client(
        tmp_path,
        database_name="project-resources-bootstrap.db",
        include_storage=True,
        project_items=[],
    )

    try:
        with client:
            bootstrap_response = client.post(
                "/api/v1/projects/bootstrap",
                headers=build_test_headers(scopes="datasets:write"),
                json={
                    "project_id": "project-bootstrap",
                    "display_name": "Bootstrap Project",
                    "description": "初始化项目",
                    "metadata": {"site": "line-b"},
                },
            )
            list_response = client.get(
                "/api/v1/projects",
                headers=_build_project_headers(),
            )
    finally:
        session_factory.engine.dispose()

    assert bootstrap_response.status_code == 201
    bootstrap_payload = bootstrap_response.json()
    assert bootstrap_payload["project_id"] == "project-bootstrap"
    assert bootstrap_payload["display_name"] == "Bootstrap Project"
    assert bootstrap_payload["description"] == "初始化项目"
    assert bootstrap_payload["metadata"] == {"site": "line-b"}
    assert bootstrap_payload["project_source"] == "local_disk"
    assert bootstrap_payload["summary"]["project_id"] == "project-bootstrap"

    assert dataset_storage.resolve("projects/project-bootstrap/project.json").is_file()
    assert dataset_storage.resolve("projects/project-bootstrap/inputs").is_dir()
    assert dataset_storage.resolve("projects/project-bootstrap/results").is_dir()
    assert dataset_storage.resolve("projects/project-bootstrap/datasets").is_dir()
    assert dataset_storage.resolve("projects/project-bootstrap/workflow/templates").is_dir()
    assert dataset_storage.resolve("projects/project-bootstrap/workflow/applications").is_dir()

    assert list_response.status_code == 200
    assert [item["project_id"] for item in list_response.json()] == ["project-bootstrap"]


def test_project_detail_summary_aggregates_dataset_io_and_model_runtime_slices(tmp_path: Path) -> None:
    """验证 Project detail summary 会聚合数据集、导入导出、任务和 validation session 统计。"""

    client, session_factory, dataset_storage = _create_project_resources_test_client(
        tmp_path,
        database_name="project-resources-summary-slices.db",
        include_storage=True,
    )
    dataset_storage.resolve("projects/project-1/datasets/dataset-1").mkdir(parents=True, exist_ok=True)
    dataset_storage.resolve("projects/project-1/datasets/dataset-2").mkdir(parents=True, exist_ok=True)
    dataset_storage.write_json(
        "runtime/validation-sessions/validation-session-1/session.json",
        _build_validation_session_payload(project_id="project-1", status="ready"),
    )
    dataset_storage.write_json(
        "runtime/validation-sessions/validation-session-2/session.json",
        _build_validation_session_payload(project_id="project-2", status="ready"),
    )

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_imports.save_dataset_import(
            DatasetImport(
                dataset_import_id="dataset-import-1",
                dataset_id="dataset-1",
                project_id="project-1",
                format_type="coco",
                task_type="detection",
                status="completed",
                created_at=_now_isoformat(),
                dataset_version_id="dataset-version-1",
                package_path="projects/project-1/datasets/dataset-1/imports/dataset-import-1/package.zip",
                staging_path="projects/project-1/datasets/dataset-1/imports/dataset-import-1/staging/extracted",
            )
        )
        unit_of_work.dataset_exports.save_dataset_export(
            DatasetExport(
                dataset_export_id="dataset-export-1",
                dataset_id="dataset-1",
                project_id="project-1",
                dataset_version_id="dataset-version-1",
                format_id="coco-detection-v1",
                status="running",
                created_at=_now_isoformat(),
                task_id="task-export-1",
            )
        )
        unit_of_work.tasks.save_task(
            TaskRecord(
                task_id="task-training-1",
                task_kind="yolox-training",
                project_id="project-1",
                display_name="train yolox-s",
                created_at=_now_isoformat(),
                state="running",
            )
        )
        unit_of_work.tasks.save_task(
            TaskRecord(
                task_id="task-evaluation-1",
                task_kind="yolox-evaluation",
                project_id="project-1",
                display_name="evaluate yolox-s",
                created_at=_now_isoformat(),
                state="succeeded",
            )
        )
        unit_of_work.tasks.save_task(
            TaskRecord(
                task_id="task-conversion-1",
                task_kind="yolox-conversion",
                project_id="project-1",
                display_name="convert yolox-s",
                created_at=_now_isoformat(),
                state="queued",
            )
        )
        unit_of_work.tasks.save_task(
            TaskRecord(
                task_id="task-inference-1",
                task_kind="yolox-inference",
                project_id="project-1",
                display_name="infer yolox-s",
                created_at=_now_isoformat(),
                state="failed",
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    try:
        with client:
            detail_response = client.get(
                "/api/v1/projects/project-1",
                headers=_build_project_headers(),
            )
    finally:
        session_factory.engine.dispose()

    assert detail_response.status_code == 200
    summary = detail_response.json()["summary"]
    assert summary["datasets"]["dataset_total"] == 2
    assert summary["imports"]["total"] == 1
    assert summary["imports"]["status_counts"] == {"completed": 1}
    assert summary["exports"]["total"] == 1
    assert summary["exports"]["status_counts"] == {"running": 1}
    assert summary["training"]["total"] == 1
    assert summary["training"]["status_counts"] == {"running": 1}
    assert summary["validation"]["total"] == 1
    assert summary["validation"]["status_counts"] == {"ready": 1}
    assert summary["evaluation"]["status_counts"] == {"succeeded": 1}
    assert summary["conversion"]["status_counts"] == {"queued": 1}
    assert summary["inference"]["status_counts"] == {"failed": 1}


def _build_project_headers() -> dict[str, str]:
    """构建当前测试需要的 Project 读取请求头。"""

    return build_test_headers(scopes="workflows:read,models:read")


def _create_project_resources_test_client(
    tmp_path: Path,
    *,
    database_name: str,
    include_storage: bool = False,
    project_items: list[BackendServiceProjectCatalogItemConfig] | None = None,
) -> tuple[TestClient, object] | tuple[TestClient, object, object]:
    """创建带 Project 目录配置的测试客户端。

    参数：
    - tmp_path：pytest 临时目录。
    - database_name：SQLite 数据库文件名。
    - include_storage：是否同时返回 LocalDatasetStorage。

    返回：
    - tuple[TestClient, object] 或 tuple[TestClient, object, object]：测试客户端和运行时资源。
    """

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name=database_name,
    )
    application = create_app(
        settings=BackendServiceSettings(
            projects=BackendServiceProjectsConfig(
                items=(
                    project_items
                    if project_items is not None
                    else [
                        BackendServiceProjectCatalogItemConfig(
                            project_id="project-1",
                            display_name="Project One",
                            description="测试项目",
                            metadata={"site": "line-a"},
                        )
                    ]
                )
            )
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    client = TestClient(application)
    if include_storage:
        return client, session_factory, dataset_storage
    return client, session_factory


def _build_validation_session_payload(*, project_id: str, status: str) -> dict[str, object]:
    """构造最小可读的 validation session JSON。"""

    now = _now_isoformat()
    return {
        "session_id": f"validation-session-{project_id}",
        "project_id": project_id,
        "model_id": "model-1",
        "model_version_id": "model-version-1",
        "model_name": "yolox",
        "model_scale": "s",
        "source_kind": "training-output",
        "status": status,
        "runtime_profile_id": None,
        "runtime_backend": "pytorch",
        "device_name": "cpu",
        "runtime_precision": "fp32",
        "score_threshold": 0.3,
        "save_result_image": True,
        "input_size": [640, 640],
        "labels": ["bolt"],
        "checkpoint_file_id": "checkpoint-1",
        "checkpoint_storage_uri": "projects/project-1/models/checkpoint.pt",
        "labels_storage_uri": None,
        "extra_options": {},
        "created_at": now,
        "updated_at": now,
        "created_by": "amvar",
        "last_prediction": None,
    }


def _now_isoformat() -> str:
    """返回当前 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")