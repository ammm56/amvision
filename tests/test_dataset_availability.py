"""版本可用性：真实资源变化、筛选分页及更新占用回归。"""

import pytest

from backend.service.application.datasets.availability import check_version_resources
from backend.service.application.datasets.content import content_access, content_key
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings, LocalDatasetStorage,
)
from tests.test_dataset_import_api import (
    _create_test_client, _build_coco_zip_bytes, _build_dataset_read_headers,
    _build_dataset_write_headers, _run_import_worker_once,
)


@pytest.fixture
def resource(tmp_path):
    """仅创建当前测试自己的版本基础资源。"""
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    version = {"project_id": "p", "dataset_id": "d", "dataset_version_id": "v",
               "sample_count": 1, "metadata": {"content_revision": "a" * 32}}
    root = storage.resolve(content_key("p", "d", "v", version["metadata"]))
    for name in ("images", "samples", "indexes", "manifests"):
        (root / name).mkdir(parents=True)
    for name in ("dataset-version.json", "categories.json"):
        (root / "manifests" / name).write_text("{}")
    return storage, version, root


def test_resource_revision_missing_restore_and_empty(resource):
    """使用当前 content_revision，资源恢复立即生效，不依赖历史缓存。"""
    storage, version, root = resource
    assert check_version_resources(storage, version)["state"] == "available"
    manifest = root / "manifests/categories.json"
    manifest.unlink()
    assert check_version_resources(storage, version)["state"] == "missing"
    manifest.write_text("")
    assert check_version_resources(storage, version)["reason"] == "empty_manifest"
    manifest.write_text("[]")
    assert check_version_resources(storage, version)["state"] == "available"
    version["sample_count"] = 0
    assert check_version_resources(storage, version)["state"] == "empty"


def test_resource_busy_and_invalid_revision(resource):
    """更新中的版本不能误报资源缺失，非法内容标识不能逃逸路径。"""
    storage, version, _ = resource
    with content_access(storage, "v", write=True):
        assert check_version_resources(storage, version)["state"] == "updating"
    version["metadata"]["content_revision"] = "../elsewhere"
    assert check_version_resources(storage, version)["reason"] == "invalid_path"


@pytest.mark.parametrize("error, reason", [(PermissionError, "access_denied"), (OSError, "storage_error")])
def test_resource_access_errors(resource, monkeypatch, error, reason):
    """访问失败单独返回原因，不能误报不存在或让整页 500。"""
    storage, version, _ = resource
    def denied(_):
        raise error("test")
    monkeypatch.setattr("backend.service.application.datasets.availability.os.scandir", denied)
    result = check_version_resources(storage, version)
    assert result["state"] == "unavailable"
    assert result["reason"] == reason


def test_real_import_version_state_filter_pagination_and_restore(tmp_path):
    """真实导入两版本；状态筛选先于分页，恢复文件后总数随实际资源改变。"""
    client, factory, storage, queue = _create_test_client(tmp_path, enable_queue_outbox_dispatcher=False)
    read, write = _build_dataset_read_headers(), _build_dataset_write_headers()
    try:
        with client:
            for dataset in ("dataset-one", "dataset-two"):
                submitted = client.post("/api/v1/datasets/imports", headers=write,
                    data={"project_id": "project-1", "dataset_id": dataset, "task_type": "detection"},
                    files={"package": ("coco.zip", _build_coco_zip_bytes(), "application/zip")})
                assert submitted.status_code == 202, submitted.text
                assert _run_import_worker_once(session_factory=factory, dataset_storage=storage, queue_backend=queue)
            url = "/api/v1/datasets/catalog/versions"
            def page(**params):
                response = client.get(url, headers=read, params={"project_id": "project-1", **params})
                assert response.status_code == 200, response.text
                return response.json()
            all_versions = page()
            assert all_versions["total"] == 2
            assert all(item["availability"]["state"] == "available" for item in all_versions["items"])
            first = all_versions["items"][0]
            root = storage.resolve(content_key("project-1", first["dataset_id"], first["dataset_version_id"], first["metadata"]))
            target = root / "manifests/dataset-version.json"
            saved = target.read_bytes()
            target.unlink()
            missing = page(state="missing", limit=1)
            assert missing["total"] == 1
            assert missing["items"][0]["dataset_version_id"] == first["dataset_version_id"]
            available = page(state="available", limit=1)
            assert available["total"] == 1 and len(available["items"]) == 1
            assert available["items"][0]["dataset_version_id"] != first["dataset_version_id"]
            assert page(state="available", offset=1)["items"] == []
            assert page(state="available", q=first["dataset_id"])["total"] == 0
            assert page(state="missing", task_type="classification")["total"] == 0
            assert page(project_id="other-project")["total"] == 0
            assert client.get(url, headers=read, params={"project_id": "project-1", "state": "wrong"}).status_code == 422
            target.write_bytes(saved)
            assert page(state="missing")["total"] == 0
            assert page(state="available")["total"] == 2
    finally:
        factory.engine.dispose()
