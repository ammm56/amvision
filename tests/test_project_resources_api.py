"""项目目录与对象读取接口测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.settings import (
    BackendServiceProjectCatalogItemConfig,
    BackendServiceProjectsConfig,
    BackendServiceSettings,
)
from tests.api_test_support import build_test_headers, build_valid_test_png_bytes, create_test_runtime


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
    assert list_payload[0]["registered_in_catalog"] is True
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
        with client:
            list_response = client.get(
                "/api/v1/projects",
                headers=_build_project_headers(project_ids="project-2,project-1"),
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
    assert metadata_payload["object_key"] == object_key
    assert metadata_payload["media_type"] == "image/png"
    assert metadata_payload["content_url"].startswith("/api/v1/projects/project-1/files/content")

    assert content_response.status_code == 200
    assert content_response.headers["content-type"] == "image/png"
    assert content_response.content == build_valid_test_png_bytes()


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


def _build_project_headers(*, project_ids: str = "project-1") -> dict[str, str]:
    """构建当前测试需要的 Project 读取请求头。"""

    return build_test_headers(
        scopes="workflows:read,models:read",
        project_ids=project_ids,
    )


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