"""YOLOX 评估任务 API 行为测试。"""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.service.application.models.evaluation.detection_evaluation_task_service as detection_evaluation_task_service_module
from backend.contracts.datasets.exports.coco_detection_export import (
    COCO_DETECTION_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.voc_detection_export import (
    VOC_DETECTION_DATASET_FORMAT,
)
from backend.service.application.models.evaluation.detection_evaluation import (
    DetectionEvaluationResult,
)
from backend.service.application.tasks.queue_outbox import QueueOutboxDispatcher
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend
from backend.workers.evaluation.model_evaluation_queue_worker import (
    DetectionEvaluationQueueWorker,
)
from backend.workers.task_execution_claim import TaskAttemptClaimingQueueBackend
from tests.api_test_support import build_test_headers, build_test_jpeg_bytes, create_api_test_context
from tests.yolox_test_support import (
    seed_yolox_model_version,
)


@pytest.mark.parametrize("phase", ["evaluating", "publishing"])
def test_cancel_running_detection_preserves_progress_without_publishing(tmp_path, monkeypatch, phase) -> None:
    """运行时和写文件时取消都应保留最新进度，且不发布结果。"""
    client, session_factory, storage, queue = _create_test_client(tmp_path)
    export = _seed_completed_dataset_export(
        session_factory=session_factory, dataset_storage=storage,
        dataset_export_id="cancel-export", manifest_object_key="exports/cancel/manifest.json",
    )
    version_id = _seed_model_version(session_factory=session_factory, dataset_storage=storage)
    worker = DetectionEvaluationQueueWorker(
        session_factory=session_factory,
        dataset_storage=storage,
        queue_backend=TaskAttemptClaimingQueueBackend(queue_backend=queue, session_factory=session_factory),
    )
    base = "/api/v1/models/detection/evaluation-tasks"
    coverage = {"requested": 3, "succeeded": 1, "failed": 0, "unprocessed": 2}
    progress = {
        "stage": "evaluating", "percent": 35, "split_name": "val", "coverage": coverage,
        "recent_samples": [{"image_index": 0, "name": "bolt.jpg", "classes": ["bolt"], "status": "succeeded"}],
    }
    try:
        with client:
            created = client.post(base, headers=_build_headers(), json={
                "project_id": "project-1", "model_type": "yolox", "model_version_id": version_id,
                "dataset_export_id": export.dataset_export_id,
            })
            assert created.status_code == 202, created.text
            task_id = created.json()["task_id"]

            def cancel() -> None:
                """通过公开接口取消 Worker 正在执行的任务。"""
                response = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=_build_headers())
                assert response.status_code == 200, response.text

            def run(request):
                """提供确定的首个进度和后续阶段边界。"""
                request.on_progress(progress)
                if phase == "evaluating":
                    cancel()
                request.on_progress({**progress, "stage": "summarizing"})
                return DetectionEvaluationResult(split_name="val", sample_count=1, duration_seconds=1, map50=0.7, map50_95=0.6)

            write_json = storage.write_json

            def write_and_cancel(path, payload):
                """模拟报告文件已落盘但成功状态尚未提交时取消。"""
                result = write_json(path, payload)
                if phase == "publishing" and path.endswith("/detections.json"):
                    cancel()
                return result

            monkeypatch.setattr(detection_evaluation_task_service_module, "run_detection_evaluation", run)
            monkeypatch.setattr(storage, "write_json", write_and_cancel)
            assert QueueOutboxDispatcher(session_factory=session_factory, queue_backend=queue).dispatch_once() == 1
            assert worker.run_once()
            detail = client.get(f"{base}/{task_id}", headers=_build_headers(), params={"include_events": True}).json()
            assert detail["state"] == "cancelled"
            assert detail["report_object_key"] is None and detail["map50_95"] is None
            assert detail["progress"]["coverage"] == coverage
            assert detail["progress"]["recent_samples"][0]["name"] == "bolt.jpg"
            assert not storage.resolve(f"task-runs/evaluation/{task_id}").exists()
            assert client.get(f"{base}/{task_id}/report", headers=_build_headers()).status_code == 404
            message = queue.get_task(queue_name=created.json()["queue_name"], task_id=created.json()["queue_task_id"])
            assert message and message.metadata["status"] == "cancelled"
    finally:
        session_factory.engine.dispose()


def test_preview_detection_evaluation_counts_only_the_selected_split(tmp_path: Path) -> None:
    """预检读取所选 COCO 标注文件，并分别返回图像数和标注对象数。"""
    client, session_factory, storage, _ = _create_test_client(tmp_path)
    export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=storage,
        dataset_export_id="preview-export",
        manifest_object_key="exports/preview/manifest.json",
    )
    version_id = _seed_model_version(session_factory=session_factory, dataset_storage=storage)
    annotation_key = f"{export.export_path}/annotations/instances_val.json"
    payload = storage.read_json(annotation_key)
    payload["annotations"].append({**payload["annotations"][0], "id": 3})
    storage.write_json(annotation_key, payload)
    base = "/api/v1/models/detection/evaluation-tasks"
    body = {
        "project_id": "project-1",
        "model_type": "yolox",
        "model_version_id": version_id,
        "dataset_export_id": export.dataset_export_id,
        "extra_options": {"split": "val"},
    }
    try:
        with client:
            response = client.post(f"{base}/preview", headers=_build_headers(), json=body)
            assert response.status_code == 200, response.text
            result = response.json()
            assert (result["split"], result["sample_count"], result["annotation_count"]) == ("val", 1, 2)
            assert result["runtime_precision"] == "fp32"

            body["extra_options"]["split"] = "test"
            assert client.post(f"{base}/preview", headers=_build_headers(), json=body).status_code == 400
            body["extra_options"]["split"] = "val"

            payload["annotations"] = []
            storage.write_json(annotation_key, payload)
            response = client.post(f"{base}/preview", headers=_build_headers(), json=body)
            assert response.status_code == 200, response.text
            assert response.json()["annotation_count"] == 0

            storage.resolve(annotation_key).unlink()
            assert client.post(f"{base}/preview", headers=_build_headers(), json=body).status_code == 400
            listed = client.get(base, headers=_build_headers(), params={"project_id": "project-1"})
            assert listed.status_code == 200, listed.text
            assert listed.json() == []
    finally:
        session_factory.engine.dispose()


def test_create_yolox_evaluation_task_and_read_report_after_worker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证评估任务可以创建、执行，并返回 report、per-class metrics 和结果包。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-evaluation-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-evaluation-1/manifest.json"
        ),
    )
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    worker = DetectionEvaluationQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=TaskAttemptClaimingQueueBackend(
            queue_backend=queue_backend,
            session_factory=session_factory,
        ),
        worker_id="test-detection-evaluation-worker",
    )

    def fake_run(_request):
        return DetectionEvaluationResult(
            split_name="val",
            sample_count=1,
            duration_seconds=0.123,
            map50=0.88,
            map50_95=0.71,
            per_class_metrics=(
                {
                    "category_id": 0,
                    "class_index": 0,
                    "class_name": "bolt",
                    "ground_truth_count": 1,
                    "detection_count": 1,
                    "ap50": 0.88,
                    "ap50_95": 0.71,
                },
            ),
            report_payload={
                "implementation_mode": "yolox-evaluation-core",
                "model_version_id": model_version_id,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_version_id": dataset_export.dataset_version_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "split_name": "val",
                "sample_count": 1,
                "map50": 0.88,
                "map50_95": 0.71,
                "per_class_metrics": [
                    {
                        "category_id": 0,
                        "class_index": 0,
                        "class_name": "bolt",
                        "ground_truth_count": 1,
                        "detection_count": 1,
                        "ap50": 0.88,
                        "ap50_95": 0.71,
                    }
                ],
            },
            failed_image_paths={
                4: f"{dataset_export.export_path}/images/val/val-1.jpg",
                5: f"{dataset_export.export_path}/images/val/restored.jpg",
            },
            detections_payload=[
                {
                    "image_id": 2,
                    "category_id": 0,
                    "bbox": [12.0, 12.0, 20.0, 20.0],
                    "score": 0.91,
                }
            ],
        )

    monkeypatch.setattr(
        detection_evaluation_task_service_module,
        "run_detection_evaluation",
        fake_run,
    )

    try:
        with client:
            create_response = client.post(
                "/api/v1/models/detection/evaluation-tasks",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_type": "yolox",
                    "model_version_id": model_version_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "score_threshold": 0.2,
                    "nms_threshold": 0.6,
                    "save_result_package": True,
                },
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            task_id = submission["task_id"]

            pending_report_response = client.get(
                f"/api/v1/models/detection/evaluation-tasks/{task_id}/report",
                headers=_build_headers(),
            )
            assert pending_report_response.status_code == 200
            assert pending_report_response.json()["file_status"] == "pending"

            assert (
                QueueOutboxDispatcher(
                    session_factory=session_factory,
                    queue_backend=queue_backend,
                ).dispatch_once()
                == 1
            )
            assert worker.run_once() is True

            detail_response = client.get(
                f"/api/v1/models/detection/evaluation-tasks/{task_id}",
                headers=_build_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["state"] == "succeeded"
            assert detail_payload["map50"] == 0.88
            assert detail_payload["map50_95"] == 0.71
            assert detail_payload["report_summary"]["per_class_metrics"][0]["class_name"] == "bolt"

            report_response = client.get(
                f"/api/v1/models/detection/evaluation-tasks/{task_id}/report",
                headers=_build_headers(),
            )
            assert report_response.status_code == 200
            report_payload = report_response.json()
            assert report_payload["file_status"] == "ready"
            assert report_payload["payload"]["map50_95"] == 0.71
            assert report_payload["payload"]["per_class_metrics"][0]["ap50"] == 0.88
            execution = report_payload["payload"]["execution"]
            assert execution["device_name"] == "cpu"
            assert execution["batch_size"] == 1
            assert execution["runtime_artifact_file_id"]

            output_files_response = client.get(
                f"/api/v1/models/detection/evaluation-tasks/{task_id}/output-files",
                headers=_build_headers(),
            )
            assert output_files_response.status_code == 200
            output_files_payload = output_files_response.json()
            assert [item["file_name"] for item in output_files_payload] == [
                "report",
                "detections",
                "result-package",
            ]
            assert all(item["file_status"] == "ready" for item in output_files_payload)

            list_response = client.get(
                f"/api/v1/models/detection/evaluation-tasks?project_id=project-1&model_version_id={model_version_id}",
                headers=_build_headers(),
            )
            assert list_response.status_code == 200
            list_payload = list_response.json()
            assert len(list_payload) == 1
            assert list_payload[0]["map50"] == 0.88
            assert list_payload[0]["split_name"] == "val"
            assert list_payload[0]["report_object_key"].endswith("evaluation-report.json")
            next_page = client.get(
                "/api/v1/models/detection/evaluation-tasks",
                headers=_build_headers(),
                params={"project_id": "project-1", "model_version_id": model_version_id, "offset": 1, "limit": 1},
            )
            assert next_page.status_code == 200
            assert next_page.json() == []

            # 快照中含已匹配、两种错误和只存数量的旧记录，组合筛选仅返回符合条件的样本。
            dataset_storage.write_json(detail_payload["detections_object_key"], [
                {"image_index": 1, "image_path": "private/Part-A.JPG", "false_negatives": 1, "false_positives": 2,
                 "ground_truth": [{"class_name": "bolt", "matched": True},
                                  {"class_name": "nut", "matched": False, "bbox_xyxy": [0, 0, 12, 12]}],
                 "predictions": [{"class_name": "bolt", "matched": False, "bbox_xyxy": [8, 0, 20, 12]},
                                 {"class_name": "nut", "matched": False, "bbox_xyxy": [8, 0, 20, 12]}]},
                {"image_index": 2, "image_path": "private/Part-B.jpg", "false_negatives": 0, "false_positives": 0},
                {"image_index": 3, "image_path": "private/legacy.jpg", "gt_count": 1, "pred_count": 1},
            ])
            sample_url = f"/api/v1/models/detection/evaluation-tasks/{task_id}/samples"
            # 失败图片可独立预览或在恢复源文件后重试，不加入成功快照。
            preview = client.get(f"{sample_url}/4/image", headers=_build_headers())
            assert preview.status_code == 200
            assert preview.headers["content-type"] == "image/jpeg"
            assert preview.content == _build_test_jpeg_bytes()
            assert client.get(f"{sample_url}/5/image", headers=_build_headers()).status_code == 404
            dataset_storage.write_bytes(f"{dataset_export.export_path}/images/val/restored.jpg", preview.content)
            assert client.get(f"{sample_url}/5/image", headers=_build_headers()).content == preview.content
            items = client.get(sample_url, headers=_build_headers()).json()["items"]
            assert [item["image_index"] for item in items] == [1, 2, 3]
            assert client.get(
                f"/api/v1/models/detection/evaluation-tasks/{task_id}/report", headers=_build_headers(),
            ).json()["payload"] == report_payload["payload"]

            for params, expected in [
                ({"issue": "errors", "q": "  part-a.jpg ", "class_name": "nut"}, ["Part-A.JPG"]),
                ({"issue": "false_negatives", "class_name": "bolt"}, []),
                ({"issue": "false_positives", "class_name": "bolt"}, ["Part-A.JPG"]),
                ({"issue": "localization", "class_name": "bolt"}, []),
                ({"issue": "localization", "class_name": "nut", "q": "part-a"}, ["Part-A.JPG"]),
                ({"q": "legacy"}, ["legacy.jpg"]),
            ]:
                response = client.get(sample_url, params=params, headers=_build_headers())
                assert response.status_code == 200
                payload = response.json()
                assert payload["diagnostics_available"] is True
                assert payload["total"] == len(expected)
                assert [item["name"] for item in payload["items"]] == expected
                assert all("image_path" not in item for item in payload["items"])
                if params.get("issue") == "localization" and expected:
                    assert payload["items"][0]["localization_pair"] == {
                        "ground_truth_index": 1, "prediction_index": 1, "iou": pytest.approx(0.2),
                    }

            dataset_storage.write_json(detail_payload["detections_object_key"], [
                {"image_index": 3, "image_path": "private/legacy.jpg", "gt_count": 1, "pred_count": 1},
            ])
            response = client.get(sample_url, params={"issue": "errors"}, headers=_build_headers())
            assert response.json() == {"total": 0, "diagnostics_available": False, "items": []}

        task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=True)
        assert any(event.message == "detection evaluation started" for event in task_detail.events)
        assert any(event.message == "detection evaluation completed" for event in task_detail.events)
        assert dataset_storage.resolve(detail_payload["report_object_key"]).is_file()
        assert dataset_storage.resolve(detail_payload["detections_object_key"]).is_file()
        assert dataset_storage.resolve(detail_payload["result_package_object_key"]).is_file()
    finally:
        session_factory.engine.dispose()


def test_package_yolox_evaluation_result_to_temporary_object_without_changing_task_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证评估结果包可以额外写到 workflow 临时路径，且不改变原任务结果中的 package 引用。"""

    _client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-evaluation-2",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-evaluation-2/manifest.json"
        ),
    )
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    worker = DetectionEvaluationQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-detection-evaluation-package-worker",
    )

    def fake_run(_request):
        return DetectionEvaluationResult(
            split_name="val",
            sample_count=1,
            duration_seconds=0.123,
            map50=0.88,
            map50_95=0.71,
            per_class_metrics=(
                {
                    "category_id": 0,
                    "class_index": 0,
                    "class_name": "bolt",
                    "ground_truth_count": 1,
                    "detection_count": 1,
                    "ap50": 0.88,
                    "ap50_95": 0.71,
                },
            ),
            report_payload={
                "implementation_mode": "yolox-evaluation-core",
                "model_version_id": model_version_id,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_version_id": dataset_export.dataset_version_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "split_name": "val",
                "sample_count": 1,
                "map50": 0.88,
                "map50_95": 0.71,
                "per_class_metrics": [
                    {
                        "category_id": 0,
                        "class_index": 0,
                        "class_name": "bolt",
                        "ground_truth_count": 1,
                        "detection_count": 1,
                        "ap50": 0.88,
                        "ap50_95": 0.71,
                    }
                ],
            },
            detections_payload=[
                {
                    "image_id": 2,
                    "category_id": 0,
                    "bbox": [12.0, 12.0, 20.0, 20.0],
                    "score": 0.91,
                }
            ],
        )

    monkeypatch.setattr(
        detection_evaluation_task_service_module,
        "run_detection_evaluation",
        fake_run,
    )

    service = detection_evaluation_task_service_module.SqlAlchemyDetectionEvaluationTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

    try:
        submission = service.submit_evaluation_task(
            detection_evaluation_task_service_module.DetectionEvaluationTaskRequest(
                project_id="project-1",
                model_type="yolox",
                model_version_id=model_version_id,
                dataset_export_id=dataset_export.dataset_export_id,
                save_result_package=False,
            ),
            created_by="workflow-user",
            display_name="evaluation package test",
        )
        assert (
            QueueOutboxDispatcher(
                session_factory=session_factory,
                queue_backend=queue_backend,
            ).dispatch_once()
            == 1
        )
        assert worker.run_once() is True

        package = service.package_evaluation_result(
            submission.task_id,
            package_object_key="workflows/runtime/run-1/package/detection-evaluation-package.zip",
        )

        package_path = dataset_storage.resolve(package.package_object_key)
        assert package_path.is_file()
        with zipfile.ZipFile(package_path) as archive:
            assert sorted(archive.namelist()) == ["detections.json", "report.json"]

        task_detail = SqlAlchemyTaskService(session_factory).get_task(submission.task_id, include_events=False)
        assert task_detail.task.result.get("result_package_object_key") is None
        assert not dataset_storage.resolve(
            f"task-runs/evaluation/{submission.task_id}/artifacts/packages/result-package.zip"
        ).is_file()
    finally:
        session_factory.engine.dispose()


def test_create_yolox_evaluation_task_accepts_voc_dataset_export(tmp_path: Path) -> None:
    """验证 YOLOX evaluation 应用层允许 VOC detection DatasetExport。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-evaluation-voc",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-evaluation-voc/manifest.json"
        ),
        format_id=VOC_DETECTION_DATASET_FORMAT,
    )
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

    try:
        with client:
            response = client.post(
                "/api/v1/models/detection/evaluation-tasks",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_type": "yolox",
                    "model_version_id": model_version_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                },
            )

        assert response.status_code == 202
        assert response.json()["format_id"] == VOC_DETECTION_DATASET_FORMAT
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定测试数据库、本地文件存储和队列的评估 API 测试客户端。"""

    context = create_api_test_context(
        tmp_path,
        database_name="amvision-evaluation-api.db",
        enable_local_buffer_broker=False,
        enable_queue_outbox_dispatcher=False,
    )
    return context.client, context.session_factory, context.dataset_storage, context.queue_backend


def _seed_completed_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    dataset_export_id: str,
    manifest_object_key: str,
    format_id: str = COCO_DETECTION_DATASET_FORMAT,
) -> DatasetExport:
    """写入一个已完成的 DatasetExport 资源和最小 manifest 文件。"""

    export_path = manifest_object_key.rsplit("/manifest.json", 1)[0]
    dataset_export = DatasetExport(
        dataset_export_id=dataset_export_id,
        dataset_id="dataset-1",
        project_id="project-1",
        dataset_version_id=f"dataset-version-{dataset_export_id}",
        format_id=format_id,
        task_type="detection",
        status="completed",
        created_at=datetime.now(timezone.utc).isoformat(),
        task_id=f"task-{dataset_export_id}",
        export_path=export_path,
        manifest_object_key=manifest_object_key,
        split_names=("train", "val"),
        sample_count=2,
        category_names=("bolt",),
    )

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(dataset_export)
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    dataset_storage.write_json(
        manifest_object_key,
        {
            "format_id": format_id,
            "dataset_version_id": dataset_export.dataset_version_id,
            "category_names": ["bolt"],
            "splits": [
                {
                    "name": "train",
                    "image_root": f"{export_path}/images/train",
                    "annotation_file": f"{export_path}/annotations/instances_train.json",
                    "sample_count": 1,
                },
                {
                    "name": "val",
                    "image_root": f"{export_path}/images/val",
                    "annotation_file": f"{export_path}/annotations/instances_val.json",
                    "sample_count": 1,
                },
            ],
            "metadata": {"source_dataset_id": "dataset-1"},
        },
    )
    dataset_storage.write_json(
        f"{export_path}/annotations/instances_train.json",
        {
            "images": [
                {"id": 1, "file_name": "train-1.jpg", "width": 64, "height": 64}
            ],
            "annotations": [
                {
                    "id": 1,
                    "image_id": 1,
                    "category_id": 0,
                    "bbox": [8, 8, 24, 24],
                    "area": 576,
                    "iscrowd": 0,
                }
            ],
            "categories": [{"id": 0, "name": "bolt"}],
        },
    )
    dataset_storage.write_json(
        f"{export_path}/annotations/instances_val.json",
        {
            "images": [
                {"id": 2, "file_name": "val-1.jpg", "width": 64, "height": 64}
            ],
            "annotations": [
                {
                    "id": 2,
                    "image_id": 2,
                    "category_id": 0,
                    "bbox": [12, 12, 20, 20],
                    "area": 400,
                    "iscrowd": 0,
                }
            ],
            "categories": [{"id": 0, "name": "bolt"}],
        },
    )
    dataset_storage.write_bytes(f"{export_path}/images/train/train-1.jpg", _build_test_jpeg_bytes())
    dataset_storage.write_bytes(f"{export_path}/images/val/val-1.jpg", _build_test_jpeg_bytes())
    return dataset_export


def _seed_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    return seed_yolox_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        source_prefix="evaluation-source-1",
        training_task_id="training-evaluation-source-1",
        model_name="yolox-nano-evaluation",
        dataset_version_id="dataset-version-evaluation-source-1",
        checkpoint_file_id="checkpoint-file-evaluation-1",
        labels_file_id="labels-file-evaluation-1",
    )


def _build_test_jpeg_bytes() -> bytes:
    """构建一个可被 cv2 正常读取的最小 JPEG 图片。"""

    return build_test_jpeg_bytes()


def _build_headers() -> dict[str, str]:
    """构建具备评估任务所需 scope 的测试请求头。"""

    return build_test_headers(scopes="datasets:read,models:read,tasks:read,tasks:write")

