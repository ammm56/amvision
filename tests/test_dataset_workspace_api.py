"""数据集工作区：分页、版本选择、修改冲突、图片权限和现有导入兼容。"""

from dataclasses import replace

from tests.test_dataset_import_api import (
    _create_test_client,
    _build_coco_zip_bytes,
    _build_dataset_read_headers,
    _build_dataset_write_headers,
    _run_import_worker_once,
    _load_dataset_objects,
)
from tests.api_test_support import build_bearer_headers, issue_test_user_token
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


def test_import_response_preserves_current_version_change_counts():
    """新增、删除与保留数量不能在 API 序列化时丢失。"""
    from backend.service.api.rest.v1.routes.datasets.responses import _build_validation_report_response
    result = _build_validation_report_response({"sample_count": 7, "added_count": 2, "removed_count": 1, "retained_count": 5, "split_counts": {"train": 6, "val": 1}})
    assert result.added_count == 2
    assert result.removed_count == 1
    assert result.retained_count == 5
    assert sum(result.split_counts.values()) == result.sample_count


def test_workspace_import_browse_edit_and_preserve_after_record_deletion(tmp_path):
    """同一个实际导入形成目录、真实样本/标注和受权限保护的图片。"""
    client, factory, storage, queue = _create_test_client(tmp_path, enable_queue_outbox_dispatcher=False)
    read, write = _build_dataset_read_headers(), _build_dataset_write_headers()
    try:
        with client:
            submitted = client.post(
                "/api/v1/datasets/imports",
                headers=write,
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-test",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco.zip", _build_coco_zip_bytes(), "application/zip")
                },
            )
            assert submitted.status_code == 202
            assert _run_import_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            catalog = client.get(
                "/api/v1/datasets/catalog",
                headers=read,
                params={"project_id": "project-1", "limit": 1},
            ).json()
            assert catalog["total"] == 1
            item = catalog["items"][0]
            version_id = item["latest_version"]["dataset_version_id"]
            records = client.get(
                "/api/v1/datasets/catalog/records/imports",
                headers=read,
                params={"project_id": "project-1"},
            ).json()["items"]
            assert records[0]["source_file_name"] == "coco.zip"
            assert records[0]["version_number"] == 1
            assert records[0]["sample_count"] == item["latest_version"]["sample_count"]
            assert records[0]["category_count"] == item["latest_version"]["category_count"]
            # 文件名检索和时间范围必须在分页前过滤；未知参数不能静默忽略。
            record_url = "/api/v1/datasets/catalog/records/imports"
            assert client.get(record_url, headers=read, params={"project_id": "project-1", "q": "coco.zip", "days": 7}).json()["total"] == 1
            assert client.get(record_url, headers=read, params={"project_id": "project-1", "q": "missing.zip"}).json()["total"] == 0
            assert client.get(record_url, headers=read, params={"project_id": "project-1", "days": 1}).status_code == 422
            base = f"/api/v1/datasets/dataset-test/versions/{version_id}"
            workspace = client.get(base + "/workspace", headers=read).json()
            assert workspace["sample_count"] == item["latest_version"]["sample_count"]
            assert workspace["categories"][0]["name"]
            samples = client.get(
                base + "/samples", headers=read, params={"limit": 1, "category_id": 0}
            ).json()
            assert len(samples["items"]) == 1
            sample = samples["items"][0]
            ordered = client.get(base + "/samples", headers=read, params={"sort": "filename"}).json()
            descending = client.get(base + "/samples", headers=read, params={"sort": "filename_desc"}).json()
            names = [row["file_name"].lower() for row in ordered["items"]]
            assert names == sorted(names)
            assert [row["file_name"].lower() for row in descending["items"]] == sorted(names, reverse=True)
            assert client.get(base + "/samples", headers=read, params={"sort": "unknown"}).status_code == 422
            assert sample["annotations"][0]["bbox_xywh"] == [1.0, 2.0, 3.0, 4.0]
            categories = client.get(base + "/category-statistics", headers=read).json()[
                "items"
            ]
            assert categories[0]["sample_count"] > 0
            listing = client.get(
                base + "/files", headers=read, params={"path": "manifests"}
            ).json()
            assert any(item["name"] == "categories.json" for item in listing["items"])
            assert (
                client.get(
                    base + "/file-text", headers=read, params={"path": "../secret.txt"}
                ).status_code
                == 400
            )
            assert (
                client.get(
                    base + "/file-text",
                    headers=read,
                    params={"path": "manifests/categories.json"},
                ).status_code
                == 200
            )
            associated = client.get(
                base + "/file-samples",
                headers=read,
                params={
                    "path": f"samples/{sample['split']}/{sample['sample_id']}.json"
                },
            ).json()
            assert associated["total"] == 1
            assert associated["items"][0]["sample_id"] == sample["sample_id"]
            assert (
                client.get(
                    base + "/file-samples",
                    headers=read,
                    params={"path": "../secret.txt"},
                ).status_code
                == 400
            )
            image = client.get(
                base + f"/samples/{sample['sample_id']}/image",
                headers=read,
                params={"thumbnail": True},
            )
            assert (
                image.status_code == 200
                and image.headers["content-type"] == "image/jpeg"
            )
            restricted = build_bearer_headers(
                issue_test_user_token(
                    factory,
                    username="restricted-reader",
                    scopes=("datasets:read",),
                    project_ids=("other-project",),
                )
            )
            assert (
                client.get(base + "/workspace", headers=restricted).status_code == 404
            )
            assert (
                client.get(
                    base + f"/samples/{sample['sample_id']}/image", headers=restricted
                ).status_code
                == 404
            )
            assert (
                client.get(
                    base + "/samples", headers=read, params={"limit": 100000}
                ).status_code
                == 422
            )
            edit = {
                "display_name": "真实测试数据集",
                "description": "保留版本",
                "revision": item["revision"],
            }
            saved = client.patch(
                "/api/v1/datasets/catalog/dataset-test",
                headers=write,
                params={"project_id": "project-1"},
                json=edit,
            )
            assert saved.status_code == 200
            assert (
                client.patch(
                    "/api/v1/datasets/catalog/dataset-test",
                    headers=write,
                    params={"project_id": "project-1"},
                    json=edit,
                ).status_code
                == 409
            )
            readonly = build_bearer_headers(
                issue_test_user_token(
                    factory,
                    username="dataset-reader",
                    scopes=("datasets:read",),
                    project_ids=("project-1",),
                )
            )
            assert (
                client.patch(
                    "/api/v1/datasets/catalog/dataset-test",
                    headers=readonly,
                    params={"project_id": "project-1"},
                    json=edit,
                ).status_code
                == 403
            )
            deleted = client.delete(
                "/api/v1/datasets/imports/" + submitted.json()["dataset_import_id"],
                headers=write,
            )
            assert deleted.status_code == 204, deleted.text
            assert (
                client.get(base + "/workspace", headers=read).json()["dataset"][
                    "display_name"
                ]
                == "真实测试数据集"
            )
            assert (
                client.get(base + "/import-report", headers=read).json()["available"]
                is True
            )
    finally:
        factory.engine.dispose()


def test_catalog_latest_uses_created_time_not_random_version_id(tmp_path):
    """随机 ID 字典序相反时仍选中最新创建的版本，类别过滤不重复样本。"""
    client, factory, storage, queue = _create_test_client(tmp_path, enable_queue_outbox_dispatcher=False)
    try:
        with client:
            submitted = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "test",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco.zip", _build_coco_zip_bytes(), "application/zip")
                },
            ).json()
            _run_import_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            _, version = _load_dataset_objects(
                session_factory=factory,
                dataset_import_id=submitted["dataset_import_id"],
            )
            with factory.create_session() as session:
                uow = SqlAlchemyUnitOfWork(session)
                uow.datasets.save_dataset_version(
                    replace(
                        version,
                        dataset_version_id="dataset-version-000",
                        samples=(),
                        metadata={"created_at": "2099-01-01T00:00:00+00:00"},
                    )
                )
                uow.commit()
            result = client.get(
                "/api/v1/datasets/catalog",
                headers=_build_dataset_read_headers(),
                params={"project_id": "project-1"},
            ).json()
            assert (
                result["items"][0]["latest_version"]["dataset_version_id"]
                == "dataset-version-000"
            )
            assert result["items"][0]["updated_at"] == "2099-01-01T00:00:00+00:00"
    finally:
        factory.engine.dispose()
