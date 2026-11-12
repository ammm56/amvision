"""真实 HTTP/Task/worker 的草稿、严格点云导入、导出重读和附件比较链路。"""

from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZipFile

import pytest

from backend.service.application.datasets.imports.contracts import DatasetImportRequest
from backend.service.application.datasets.imports.formats.sample_media import (
    parse_sample_media,
)
from backend.service.application.datasets.workspace_analysis import image_path
from backend.service.application.datasets.imports.formats.sample_media import asset_path
from backend.service.application.tasks.queue_outbox import QueueOutboxDispatcher
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.workers.datasets.workspace_queue_worker import DatasetWorkspaceQueueWorker
from tests.test_dataset_import_api import (
    _create_test_client,
    _build_dataset_read_headers,
    _build_dataset_write_headers,
    _run_import_worker_once,
)
from tests.test_dataset_export_api import _run_export_worker_once
from tests.test_dataset_sample_media import ply_bytes


@pytest.mark.parametrize("malformed", [False, True])
def test_draft_import_export_and_compare_chain(tmp_path, malformed):
    """坏文件不发布版本；正常文件经过正式导出重读，原云变更由比较任务报告。"""
    client, factory, storage, queue = _create_test_client(
        tmp_path, enable_queue_outbox_dispatcher=False
    )
    read, write = _build_dataset_read_headers(), _build_dataset_write_headers()
    source = ply_bytes(b"1 2 3\n4 5 6\n" if malformed else b"1 2 3\n")
    manifest = {
        "format_id": "amvision.sample-media.v1",
        "task_type": "point-cloud",
        "samples": [
            {
                "id": "part",
                "split": "test",
                "cloud": "part.ply",
                "unit": "mm",
                "frame": "sensor",
            },
        ],
    }
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr("samples.json", json.dumps(manifest))
        archive.writestr("part.ply", source)
    try:
        with client:
            upload = client.post(
                "/api/v1/datasets/upload-drafts",
                headers=write,
                data={"project_id": "project-1"},
                files={"package": ("part.zip", package.getvalue(), "application/zip")},
            )
            assert upload.status_code == 201, upload.text
            token = upload.json()["draft_id"]
            response = client.post(
                "/api/v1/datasets/imports",
                headers=write,
                data={
                    "project_id": "project-1",
                    "dataset_id": "cloud-chain",
                    "task_type": "point-cloud",
                    "draft_id": token,
                },
            )
            assert response.status_code == 202, response.text
            assert not list(
                storage.resolve("projects/project-1/dataset-upload-drafts").rglob(
                    token + "*"
                )
            )
            assert _run_import_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            detail = client.get(
                "/api/v1/datasets/imports/" + response.json()["dataset_import_id"],
                headers=read,
            ).json()
            if malformed:
                assert detail["status"] == "failed", detail
                assert detail["dataset_version_id"] is None
                return
            assert detail["status"] == "completed", detail
            version_id = detail["dataset_version_id"]
            export = client.post(
                "/api/v1/datasets/exports",
                headers=write,
                json={
                    "project_id": "project-1",
                    "dataset_id": "cloud-chain",
                    "dataset_version_id": version_id,
                    "format_id": "amvision-point-cloud-v1",
                    "include_test_split": True,
                },
            )
            assert export.status_code == 202, export.text
            assert _run_export_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            exported = client.get(
                "/api/v1/datasets/exports/" + export.json()["dataset_export_id"],
                headers=read,
            ).json()
            assert exported["status"] == "completed", exported
            parsed = parse_sample_media(
                storage.resolve(exported["export_path"]),
                DatasetImportRequest(
                    "project-1", "cloud-chain", "again.zip", "point-cloud"
                ),
            )
            assert (
                asset_path(parsed.samples[0].source_image_path, "cloud").read_bytes()
                == source
            )

            worker = DatasetWorkspaceQueueWorker(
                session_factory=factory,
                dataset_storage=storage,
                queue_backend=queue,
                worker_id="media-chain",
            )
            base = f"/api/v1/datasets/cloud-chain/versions/{version_id}"

            def job(operation, **values):
                """经公开队列提交并读取终态，禁止直接调用被测比较函数。"""
                response = client.post(
                    base + "/jobs",
                    headers=write,
                    json={"request_id": str(uuid4()), "operation": operation, **values},
                )
                assert response.status_code == 202, response.text
                QueueOutboxDispatcher(
                    session_factory=factory, queue_backend=queue
                ).dispatch_once()
                assert worker.run_once()
                result = client.get(
                    base + "/jobs/" + response.json()["task_id"], headers=read
                ).json()
                assert result["state"] == "succeeded", result
                return result

            checked = job("derive-check")
            cloned = job("derive", checked_task_id=checked["task_id"])["result"][
                "created_version_id"
            ]
            assert not job("compare", compare_version_id=cloned)["result"]["changes"]
            with factory.create_session() as session:
                version = SqlAlchemyUnitOfWork(session).datasets.get_dataset_version(
                    cloned
                )
            # 只替换派生版本的原云；缩略图不变，验证比较不能依赖预览摘要。
            path = image_path(storage, version, version.samples[0])
            asset_path(path, "cloud").write_bytes(ply_bytes(b"10 20 30\n"))
            assert job("compare", compare_version_id=cloned)["result"]["counts"] == {
                "cloud": 1,
                "changed_samples": 1,
            }
    finally:
        factory.engine.dispose()
