"""样本追加和移除通过真实导入、任务和文件路径验证。"""

import json
from io import BytesIO
from zipfile import ZipFile
from uuid import uuid4

from backend.service.application.tasks.queue_outbox import QueueOutboxDispatcher
from backend.workers.datasets.workspace_queue_worker import DatasetWorkspaceQueueWorker
from tests.test_dataset_import_api import (
    _create_test_client,
    _build_coco_zip_bytes,
    _build_dataset_read_headers,
    _build_dataset_write_headers,
    _run_import_worker_once,
)


def test_append_remove_and_directory_browsing(tmp_path, monkeypatch):
    """同名文件不覆盖、增删更新当前版本，只有手动创建才新增版本。"""
    client, factory, storage, queue = _create_test_client(
        tmp_path, enable_queue_outbox_dispatcher=False
    )
    read, write = _build_dataset_read_headers(), _build_dataset_write_headers()
    worker = DatasetWorkspaceQueueWorker(
        session_factory=factory,
        dataset_storage=storage,
        queue_backend=queue,
        worker_id="revision-test",
    )
    root = "/api/v1/datasets/sample-revision/versions/"
    try:
        with client:

            def upload(base=None, remove=None, revision=None):
                """通过真实 ZIP 解析与 worker 创建版本。"""
                data = {
                    "project_id": "project-1",
                    "dataset_id": "sample-revision",
                    "task_type": "detection",
                }
                if base:
                    data["base_version_id"] = base
                if revision is not None:
                    data["expected_content_revision"] = revision
                if remove:
                    data["exclude_selection_json"] = json.dumps(remove)
                response = client.post(
                    "/api/v1/datasets/imports",
                    headers=write,
                    data=data,
                    files={
                        "package": (
                            "coco.zip",
                            _build_coco_zip_bytes(),
                            "application/zip",
                        )
                    },
                )
                assert response.status_code == 202, response.text
                _run_import_worker_once(
                    session_factory=factory,
                    dataset_storage=storage,
                    queue_backend=queue,
                )
                result = client.get(
                    "/api/v1/datasets/imports/" + response.json()["dataset_import_id"],
                    headers=read,
                ).json()
                assert result["status"] == "completed", result
                return result["dataset_version_id"]

            first = upload()
            original = client.get(root + first + "/samples", headers=read).json()
            second = upload(first, revision="")
            combined = client.get(root + second + "/samples", headers=read).json()
            assert combined["total"] == original["total"] * 2
            assert second == first
            assert (
                combined["items"][0]["sample_id"] == original["items"][0]["sample_id"]
            )
            info = client.get(root + second + "/workspace", headers=read).json()
            assert info["version_number"] == 1 and info["parent_version_number"] is None
            assert info["category_count"] == 1
            # 空标识也必须校验：首次修改前打开的旧页面不能绕过过期检查。
            stale_upload = client.post(
                "/api/v1/datasets/imports", headers=write,
                data={"project_id": "project-1", "dataset_id": "sample-revision",
                      "task_type": "detection", "base_version_id": first,
                      "expected_content_revision": ""},
                files={"package": ("coco.zip", _build_coco_zip_bytes(), "application/zip")},
            )
            assert stale_upload.status_code == 409, stale_upload.text
            assert len({s["image_id"] for s in combined["items"]}) == combined["total"]
            assert len({s["sample_id"] for s in combined["items"]}) == combined["total"]
            for sample in combined["items"]:
                assert (
                    client.get(
                        root + second + f"/samples/{sample['sample_id']}/image",
                        headers=read,
                    ).status_code
                    == 200
                )
            remove = {"mode": "ids", "sample_ids": [combined["items"][0]["sample_id"]]}
            # 合并后的完整版本仍可导出；图片与标注必须一一关联，文件名不能覆盖。
            from backend.contracts.datasets.exports.coco_detection_export import (
                COCO_DETECTION_DATASET_FORMAT,
            )
            from tests.test_dataset_export_api import _run_export_worker_once

            exported = client.post(
                "/api/v1/datasets/exports",
                headers=write,
                json={
                    "project_id": "project-1",
                    "dataset_id": "sample-revision",
                    "dataset_version_id": second,
                    "format_id": COCO_DETECTION_DATASET_FORMAT,
                },
            )
            assert exported.status_code == 202, exported.text
            assert _run_export_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            export_id = exported.json()["dataset_export_id"]
            assert (
                client.post(
                    f"/api/v1/datasets/exports/{export_id}/package", headers=write
                ).status_code
                == 200
            )
            archive = client.get(
                f"/api/v1/datasets/exports/{export_id}/download", headers=read
            )
            assert archive.status_code == 200
            with ZipFile(BytesIO(archive.content)) as bundle:
                payloads = [
                    json.loads(bundle.read(name))
                    for name in bundle.namelist()
                    if name.endswith(".json") and "/annotations/" in "/" + name
                ]
            populated = [p for p in payloads if p.get("images")]
            assert populated
            for payload in populated:
                identities = {image["id"] for image in payload["images"]}
                assert len(identities) == len(payload["images"])
                assert len({image["file_name"] for image in payload["images"]}) == len(
                    payload["images"]
                )
                assert all(a["image_id"] in identities for a in payload["annotations"])

            # 明确点击创建新版本时才生成快照和 v2。
            def run_job(operation, **values):
                body = {"request_id": str(uuid4()), "operation": operation, **values}
                posted = client.post(root + first + "/jobs", headers=write, json=body)
                assert posted.status_code == 202, posted.text
                QueueOutboxDispatcher(
                    session_factory=factory, queue_backend=queue
                ).dispatch_once()
                assert worker.run_once()
                detail = client.get(
                    root + first + "/jobs/" + posted.json()["task_id"], headers=read
                ).json()
                assert detail["state"] == "succeeded", detail
                return detail

            checked = run_job("derive-check")
            snapshot = run_job("derive", checked_task_id=checked["task_id"])["result"][
                "created_version_id"
            ]
            assert (
                client.get(root + snapshot + "/workspace", headers=read).json()[
                    "version_number"
                ]
                == 2
            )
            third = upload(second, remove)
            assert third == first
            remove = {
                "mode": "ids",
                "sample_ids": [
                    client.get(root + first + "/samples", headers=read).json()["items"][
                        0
                    ]["sample_id"]
                ],
            }
            assert (
                client.get(root + third + "/workspace", headers=read).json()[
                    "sample_count"
                ]
                == combined["total"]
            )

            body = {
                "request_id": str(uuid4()),
                "operation": "revise",
                "config": {"exclude_selection": remove},
            }
            response = client.post(root + second + "/jobs", headers=write, json=body)
            assert response.status_code == 202, response.text
            assert (
                client.post(root + second + "/jobs", headers=write, json=body).json()
                == response.json()
            )
            QueueOutboxDispatcher(
                session_factory=factory, queue_backend=queue
            ).dispatch_once()
            assert worker.run_once()
            result = client.get(
                root + second + "/jobs/" + response.json()["task_id"], headers=read
            ).json()
            assert result["state"] == "succeeded", result
            fourth = result["result"]["updated_version_id"]
            assert fourth == first
            assert (
                client.get(root + fourth + "/workspace", headers=read).json()[
                    "sample_count"
                ]
                == combined["total"] - 1
            )
            assert (
                client.get(root + snapshot + "/workspace", headers=read).json()[
                    "sample_count"
                ]
                == combined["total"]
            )

            # 旧页面修改不能覆盖新内容。
            stale = {
                "request_id": str(uuid4()),
                "operation": "revise",
                "config": {"exclude_selection": {"mode": "filter"}},
                "expected_content_revision": "",
            }
            assert (
                client.post(
                    root + first + "/jobs", headers=write, json=stale
                ).status_code
                == 409
            )
            assert (
                client.get(root + first + "/workspace", headers=read).json()[
                    "version_number"
                ]
                == 1
            )
            # 两个在同一内容上排队的修改，第二个不能覆盖第一个。
            current_rows = client.get(root + first + "/samples", headers=read).json()
            if current_rows["total"] < 2:
                upload(first)
            revision = client.get(root + first + "/workspace", headers=read).json()[
                "metadata"
            ]["content_revision"]
            selected = client.get(root + first + "/samples", headers=read).json()[
                "items"
            ][0]["sample_id"]
            pending = []
            for _ in range(2):
                body = {
                    "request_id": str(uuid4()),
                    "operation": "revise",
                    "expected_content_revision": revision,
                    "config": {
                        "exclude_selection": {"mode": "ids", "sample_ids": [selected]}
                    },
                }
                submitted = client.post(
                    root + first + "/jobs", headers=write, json=body
                )
                assert submitted.status_code == 202
                pending.append(submitted.json()["task_id"])
            QueueOutboxDispatcher(
                session_factory=factory, queue_backend=queue
            ).dispatch_once()
            worker.run_once()
            worker.run_once()
            outcomes = [client.get(root + first + "/jobs/" + task_id, headers=read).json() for task_id in pending]
            assert sorted(item["state"] for item in outcomes) == ["failed", "succeeded"], outcomes
            assert "样本已变化" in next(item for item in outcomes if item["state"] == "failed")["error_message"]
            before_failure = client.get(root + first + "/samples", headers=read).json()
            # 磁盘写入失败不能改变数据库内容，也不能移除当前图片。
            from backend.service.application.datasets.imports.service import (
                SqlAlchemyDatasetImportService,
            )
            from backend.service.application.errors import InvalidRequestError

            original_writer = SqlAlchemyDatasetImportService._write_version_files

            def fail_write(*args, **kwargs):
                raise InvalidRequestError("测试写入失败")

            monkeypatch.setattr(
                SqlAlchemyDatasetImportService, "_write_version_files", fail_write
            )
            failed = client.post(
                "/api/v1/datasets/imports",
                headers=write,
                data={
                    "project_id": "project-1",
                    "dataset_id": "sample-revision",
                    "task_type": "detection",
                    "base_version_id": first,
                },
                files={
                    "package": ("coco.zip", _build_coco_zip_bytes(), "application/zip")
                },
            )
            _run_import_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            assert (
                client.get(
                    "/api/v1/datasets/imports/" + failed.json()["dataset_import_id"],
                    headers=read,
                ).json()["status"]
                == "failed"
            )
            assert (
                client.get(root + first + "/samples", headers=read).json()
                == before_failure
            )
            monkeypatch.setattr(
                SqlAlchemyDatasetImportService, "_write_version_files", original_writer
            )
            # 空版本和越界选择都不得发布。
            body.pop("expected_content_revision", None)
            body["request_id"] = str(uuid4())
            body["config"]["exclude_selection"] = {"mode": "filter"}
            response = client.post(root + fourth + "/jobs", headers=write, json=body)
            assert response.status_code == 202
            QueueOutboxDispatcher(
                session_factory=factory, queue_backend=queue
            ).dispatch_once()
            worker.run_once()
            assert (
                client.get(
                    root + fourth + "/jobs/" + response.json()["task_id"], headers=read
                ).json()["state"]
                == "failed"
            )
            body["request_id"] = str(uuid4())
            body["config"]["exclude_selection"] = {
                "mode": "ids",
                "sample_ids": ["missing"],
            }
            assert (
                client.post(
                    root + fourth + "/jobs", headers=write, json=body
                ).status_code
                == 400
            )

            folders = client.get(
                root + second + "/files",
                headers=read,
                params={"directories_only": True},
            ).json()
            assert folders["items"] and all(f["directory"] for f in folders["items"])
            assert (
                next(f for f in folders["items"] if f["name"] == "manifests")[
                    "has_directories"
                ]
                is False
            )
            assert (
                next(f for f in folders["items"] if f["name"] == "images")[
                    "has_directories"
                ]
                is True
            )
            from backend.service.application.datasets.content import content_access

            with content_access(storage, first, write=True):
                assert (
                    client.get(root + first + "/files", headers=read).status_code == 409
                )
            images = client.get(
                root + second + "/files", headers=read, params={"path": "images/train"}
            ).json()["items"]
            image_files = client.get(
                root + second + "/files",
                headers=read,
                params={"path": images[0]["path"]},
            ).json()["items"]
            media = client.get(
                root + second + "/file-image",
                headers=read,
                params={"path": image_files[0]["path"]},
            )
            assert media.status_code == 200 and media.headers[
                "content-type"
            ].startswith("image/")
            assert (
                client.get(
                    root + second + "/file-image",
                    headers=read,
                    params={"path": "../secret.png"},
                ).status_code
                == 400
            )
            assert client.get(
                root + second + "/file-image",
                headers=read,
                params={"path": "dataset-version.json"},
            ).status_code in {400, 404}
            assert (
                client.get(
                    root + second + "/file-image",
                    params={"path": image_files[0]["path"]},
                ).status_code
                == 401
            )
    finally:
        factory.engine.dispose()


def test_append_rejects_wrong_source_before_staging(tmp_path):
    """无来源的删除请求和错误来源不能接受上传任务。"""
    client, factory, _, _ = _create_test_client(
        tmp_path, enable_queue_outbox_dispatcher=False
    )
    try:
        with client:
            for extra in (
                {"exclude_selection_json": '{"mode":"filter"}'},
                {"base_version_id": "missing"},
                {"exclude_selection_json": "not-json"},
            ):
                response = client.post(
                    "/api/v1/datasets/imports",
                    headers=_build_dataset_write_headers(),
                    data={
                        "project_id": "project-1",
                        "dataset_id": "sample-revision",
                        "task_type": "detection",
                        **extra,
                    },
                    files={
                        "package": (
                            "test.zip",
                            _build_coco_zip_bytes(),
                            "application/zip",
                        )
                    },
                )
                assert response.status_code in {400, 404}, response.text
    finally:
        factory.engine.dispose()
