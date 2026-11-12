"""质量检查、衍生及比较经真实 Task/Outbox/worker 的契约回归。"""

from uuid import uuid4
from io import BytesIO
from zipfile import ZipFile
import json

from backend.service.application.tasks.queue_outbox import QueueOutboxDispatcher
from backend.workers.datasets.workspace_queue_worker import DatasetWorkspaceQueueWorker
from tests.test_dataset_import_api import (
    _create_test_client,
    _build_coco_zip_bytes,
    _build_dataset_read_headers,
    _build_dataset_write_headers,
    _run_import_worker_once,
)


def test_quality_derivation_compare_and_cancel(tmp_path, monkeypatch):
    """检查—创建—比较闭环不改变来源，并保留取消和权限边界。"""
    client, factory, storage, queue = _create_test_client(
        tmp_path, enable_queue_outbox_dispatcher=False
    )
    read, write = _build_dataset_read_headers(), _build_dataset_write_headers()
    worker = DatasetWorkspaceQueueWorker(
        session_factory=factory,
        dataset_storage=storage,
        queue_backend=queue,
        worker_id="workspace-test",
    )
    try:
        with client:
            imported = client.post(
                "/api/v1/datasets/imports",
                headers=write,
                data={
                    "project_id": "project-1",
                    "dataset_id": "workspace-jobs",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco.zip", _build_coco_zip_bytes(), "application/zip")
                },
            ).json()
            _run_import_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            version = client.get(
                "/api/v1/datasets/imports/" + imported["dataset_import_id"],
                headers=read,
            ).json()["dataset_version_id"]
            base = f"/api/v1/datasets/workspace-jobs/versions/{version}"
            original = client.get(base + "/samples", headers=read).json()

            def submit(operation, **values):
                """重复提交同一请求只能得到同一 Task。"""
                body = {"request_id": str(uuid4()), "operation": operation, **values}
                response = client.post(base + "/jobs", headers=write, json=body)
                assert response.status_code == 202, response.text
                assert (
                    client.post(base + "/jobs", headers=write, json=body).json()
                    == response.json()
                )
                QueueOutboxDispatcher(
                    session_factory=factory, queue_backend=queue
                ).dispatch_once()
                assert worker.run_once()
                report = client.get(
                    base + "/jobs/" + response.json()["task_id"], headers=read
                ).json()
                assert report["state"] == "succeeded", report
                return report

            quality = submit("quality")
            assert quality["result"]["sample_count"] == original["total"]
            assert "unchecked" in quality["result"]
            config = {"category_names": {"0": "new-name"}, "split_ratios": [100, 0, 0], "description": "手动确认的训练版本"}
            checked = submit("derive-check", config=config)
            assert checked["result"]["object_count"] == sum(len(s["annotations"]) for s in original["items"])
            assert checked["result"]["category_count"] > 0
            assert sum(checked["result"]["source_split_counts"].values()) == original["total"]
            assert checked["result"]["category_changes"][0]["after"] == "new-name"
            derived = submit(
                "derive", config=config, checked_task_id=checked["task_id"]
            )
            new_version = derived["result"]["created_version_id"]
            new_base = f"/api/v1/datasets/workspace-jobs/versions/{new_version}"
            info = client.get(new_base + "/workspace", headers=read).json()
            assert info["metadata"]["parent_version_id"] == version
            assert info["categories"][0]["name"] == "new-name"
            assert info["metadata"]["description"] == "手动确认的训练版本"
            assert client.get(base + "/samples", headers=read).json() == original
            comparison = submit("compare", compare_version_id=new_version)
            # 即使最新任务是比较，质量标签页也必须读取该版本最近的质量检查。
            filtered = client.get(base + "/jobs", headers=read, params={"operation":"quality", "limit":1}).json()
            assert [row["task_id"] for row in filtered["items"]] == [quality["task_id"]]
            assert "content_revision" in quality
            assert comparison["result"]["counts"].get("added", 0) == 0
            assert comparison["result"]["counts"].get("removed", 0) == 0
            assert comparison["result"]["counts"]["categories"] > 0
            mismatch = client.post(
                base + "/jobs",
                headers=write,
                json={
                    "request_id": str(uuid4()),
                    "operation": "derive",
                    "checked_task_id": checked["task_id"],
                    "config": {"split_ratios": [50, 50, 0]},
                },
            )
            assert mismatch.status_code == 400
            # 取消在磁盘复制完成、版本发布之前抢先成功，不能留下可见版本或暂存目录。
            racing = client.post(
                base + "/jobs",
                headers=write,
                json={
                    "request_id": str(uuid4()),
                    "operation": "derive",
                    "config": config,
                    "checked_task_id": checked["task_id"],
                },
            ).json()
            original_writer = worker.service.write_version
            created_paths = []

            def cancel_before_publish(*args, **kwargs):
                """在明确的发布边界注入取消，验证真实事务而非模拟状态。"""
                version_result = original_writer(*args, **kwargs)
                created_paths.append(
                    storage.resolve(
                        f"projects/project-1/datasets/workspace-jobs/versions/{version_result.dataset_version_id}"
                    )
                )
                assert (
                    client.post(
                        base + "/jobs/" + racing["task_id"] + "/cancel", headers=write
                    ).json()["state"]
                    == "cancelled"
                )
                return version_result

            monkeypatch.setattr(worker.service, "write_version", cancel_before_publish)
            QueueOutboxDispatcher(
                session_factory=factory, queue_backend=queue
            ).dispatch_once()
            assert worker.run_once()
            assert (
                client.get(base + "/jobs/" + racing["task_id"], headers=read).json()[
                    "state"
                ]
                == "cancelled"
            )
            assert created_paths and all(not path.exists() for path in created_paths)
            monkeypatch.setattr(worker.service, "write_version", original_writer)
            cancel = client.post(
                base + "/jobs",
                headers=write,
                json={"request_id": str(uuid4()), "operation": "quality"},
            ).json()
            assert (
                client.post(
                    base + "/jobs/" + cancel["task_id"] + "/cancel", headers=write
                ).json()["state"]
                == "cancelled"
            )
            QueueOutboxDispatcher(
                session_factory=factory, queue_backend=queue
            ).dispatch_once()
            assert not worker.run_once()
            assert (
                client.get(
                    new_base + "/jobs/" + quality["task_id"], headers=read
                ).status_code
                == 404
            )
    finally:
        factory.engine.dispose()


def test_annotation_handoff_return_preserves_source(tmp_path, monkeypatch):
    """真实 COCO 导出交接、修改标注、回传导入与新版本发布。"""
    from backend.contracts.datasets.exports.coco_detection_export import (
        COCO_DETECTION_DATASET_FORMAT,
    )
    from tests.test_dataset_export_api import _run_export_worker_once

    client, factory, storage, queue = _create_test_client(
        tmp_path, enable_queue_outbox_dispatcher=False
    )
    read, write = _build_dataset_read_headers(), _build_dataset_write_headers()
    worker = DatasetWorkspaceQueueWorker(
        session_factory=factory,
        dataset_storage=storage,
        queue_backend=queue,
        worker_id="handoff-test",
    )
    try:
        with client:

            def import_zip(content):
                """回传沿用已有 zip 导入器，不绕过格式和几何校验。"""
                created = client.post(
                    "/api/v1/datasets/imports",
                    headers=write,
                    data={
                        "project_id": "project-1",
                        "dataset_id": "handoff",
                        "task_type": "detection",
                    },
                    files={"package": ("coco.zip", content, "application/zip")},
                ).json()
                _run_import_worker_once(
                    session_factory=factory,
                    dataset_storage=storage,
                    queue_backend=queue,
                )
                result = client.get(
                    "/api/v1/datasets/imports/" + created["dataset_import_id"],
                    headers=read,
                ).json()
                assert result["status"] == "completed", result
                return result["dataset_version_id"]

            source = import_zip(_build_coco_zip_bytes())
            base = f"/api/v1/datasets/handoff/versions/{source}"
            before = client.get(base + "/samples", headers=read).json()
            created = client.post(
                "/api/v1/datasets/exports",
                headers=write,
                json={
                    "project_id": "project-1",
                    "dataset_id": "handoff",
                    "dataset_version_id": source,
                    "format_id": COCO_DETECTION_DATASET_FORMAT,
                    "annotation_handoff": True,
                },
            ).json()
            assert _run_export_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            export_id = created["dataset_export_id"]
            response = client.post(
                "/api/v1/datasets/exports/" + export_id + "/package", headers=write
            )
            assert response.status_code == 200, response.text
            archive = client.get(
                "/api/v1/datasets/exports/" + export_id + "/download", headers=read
            )
            assert archive.status_code == 200, archive.text
            output = BytesIO()
            with (
                ZipFile(BytesIO(archive.content)) as original,
                ZipFile(output, "w") as returned,
            ):
                for name in original.namelist():
                    content = original.read(name)
                    if name.startswith("annotations/") and name.endswith(".json"):
                        payload = json.loads(content)
                        assert all(
                            image.get("amvision_handoff_id") == export_id
                            for image in payload["images"]
                        )
                        for annotation in payload["annotations"]:
                            annotation["bbox"] = [0, 0, 2, 2]
                            annotation["area"] = 4
                        content = json.dumps(payload).encode()
                    returned.writestr(name, content)
            returned_version = import_zip(output.getvalue())
            config = {
                "handoff_export_id": export_id,
                "returned_version_id": returned_version,
            }

            def operation(name, **extra):
                submission = client.post(
                    base + "/jobs",
                    headers=write,
                    json={
                        "request_id": str(uuid4()),
                        "operation": name,
                        "config": config,
                        **extra,
                    },
                )
                assert submission.status_code == 202, submission.text
                QueueOutboxDispatcher(
                    session_factory=factory, queue_backend=queue
                ).dispatch_once()
                assert worker.run_once()
                report = client.get(
                    base + "/jobs/" + submission.json()["task_id"], headers=read
                ).json()
                assert report["state"] == "succeeded", report
                return report

            checked = operation("return-check")
            assert checked["result"]["can_create"] is True, checked
            result = operation("return-apply", checked_task_id=checked["task_id"])
            after = client.get(
                "/api/v1/datasets/handoff/versions/"
                + result["result"]["created_version_id"]
                + "/samples",
                headers=read,
            ).json()
            assert after["items"][0]["annotations"][0]["bbox_xywh"] == [0, 0, 2, 2]
            assert client.get(base + "/samples", headers=read).json() == before
            # 同一真实交接数据验证防呆分支，不用文件名猜测或静默吞掉回传缺项。
            from dataclasses import replace
            from backend.contracts.datasets.workspace_jobs import DatasetDerivation
            from backend.service.application.datasets import annotation_handoff
            from backend.service.infrastructure.db.unit_of_work import (
                SqlAlchemyUnitOfWork,
            )

            unit = SqlAlchemyUnitOfWork(factory.create_session())
            try:
                source_data = unit.datasets.get_dataset_version(source)
                returned_data = unit.datasets.get_dataset_version(returned_version)
                exported = unit.dataset_exports.get_dataset_export(export_id)
            finally:
                unit.close()

            def check(data, **options):
                """在已验证导入的数据结构上变更一项，检查恢复选项边界。"""
                return annotation_handoff.check_return(
                    storage,
                    source_data,
                    data,
                    exported,
                    DatasetDerivation(**config, **options),
                    lambda *args: None,
                )[1]

            missing = replace(returned_data, samples=())
            assert check(missing)["can_create"] is False
            assert check(missing, keep_missing=True)["can_create"] is True
            duplicate = replace(returned_data, samples=returned_data.samples * 2)
            assert (
                check(duplicate, keep_missing=True, accept_image_changes=True)[
                    "can_create"
                ]
                is False
            )
            unknown = replace(
                returned_data, samples=(replace(returned_data.samples[0], metadata={}),)
            )
            assert check(unknown, keep_missing=True)["can_create"] is False
            monkeypatch.setattr(
                annotation_handoff, "file_digest", lambda *args: "changed"
            )
            assert check(returned_data)["can_create"] is False
            assert check(returned_data, accept_image_changes=True)["can_create"] is True
    finally:
        factory.engine.dispose()
