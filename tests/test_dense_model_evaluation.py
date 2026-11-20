"""验证独立像素评估  API、正式 Worker 和样本预览的闭环。"""

from io import BytesIO
import json
from zipfile import ZipFile

import numpy as np
from PIL import Image
import pytest

from backend.service.application.models.evaluation.dense_evaluation import _auc
from backend.service.application.models.evaluation.sample_diagnostics import explain_geometry_errors
from backend.workers.evaluation.dense_evaluation_worker import DenseEvaluationQueueWorker
from backend.workers.task_execution_claim import TaskAttemptClaimingQueueBackend
from tests.api_test_support import build_test_headers, create_api_test_context, dispatch_queue_outbox


def _bundle(kind: str) -> bytes:
    """构造像素数量可手工复核的语义和异常评估包。"""
    output = BytesIO()
    with ZipFile(output, "w") as bundle:
        manifest = {
            "format": "amvision.dense-evaluation.v1", "kind": kind, "model": "test",
            "dataset": "test", "split": "val", "classes": ["background", "object"],
            "samples": [],
        }
        for i in range(2):
            mask = [[0, 0], [1, 255]] if kind == "semantic" else [[0, 0], [i, i]]
            prediction = [[0, 1], [1, 1]] if kind == "semantic" else [[0, 0], [i * 255, i * 255]]
            for filename, values in (("image", [[10, 20], [30, 40]]), ("truth", mask), ("prediction", prediction)):
                stream = BytesIO()
                Image.fromarray(np.array(values, dtype=np.uint8)).save(stream, "PNG")
                bundle.writestr(f"{i}/{filename}.png", stream.getvalue())
            row = {"id": str(i), "image": f"{i}/image.png", "truth": f"{i}/truth.png", "prediction": f"{i}/prediction.png"}
            if kind == "anomaly":
                row.update(label="anomaly" if i else "normal", score=0.7 if i else 0.1)
            manifest["samples"].append(row)
        bundle.writestr("manifest.json", json.dumps(manifest))
    return output.getvalue()


@pytest.mark.parametrize("kind", ["semantic", "anomaly"])
def test_submitted_evaluation_writes_report_and_preview(tmp_path, kind):
    """提交包、投递队列、读取指标和受项目权限保护的 PNG。"""
    ctx = create_api_test_context(tmp_path, database_name="dense.db", enable_local_buffer_broker=False, enable_queue_outbox_dispatcher=False)
    factory, storage = ctx.session_factory, ctx.dataset_storage
    queue = TaskAttemptClaimingQueueBackend(queue_backend=ctx.queue_backend, session_factory=factory)
    worker = DenseEvaluationQueueWorker(session_factory=factory, dataset_storage=storage, queue_backend=queue)
    auth = build_test_headers(scopes="models:read,datasets:read,tasks:read,tasks:write")
    base = f"/api/v1/models/{kind}/evaluation-tasks"
    try:
        with ctx.client as client:
            submission = client.post(base, data={"project_id": "project-1"}, files={"file": ("evaluation.zip", _bundle(kind), "application/zip")}, headers=auth)
            assert submission.status_code == 202, submission.text
            task_path = f"{base}/{submission.json()['task_id']}"
            dispatch_queue_outbox(session_factory=factory, queue_backend=ctx.queue_backend)
            assert worker.run_once()
            task = client.get(task_path, headers=auth).json()
            assert task["state"] == "succeeded", task
            payload = client.get(f"{task_path}/report", headers=auth).json()["payload"]
            assert payload["sample_count"] == 2 and len(payload["input_sha256"]) == 64
            if kind == "semantic":
                assert payload["valid_pixels"] == 6
                assert payload["miou"] == 0.5
                assert payload["background_index"] == 0
            else:
                assert payload["image_auroc"] == payload["pixel_auroc"] == 1.0
                assert payload["pixel_normal_count"] == payload["pixel_anomaly_count"] == 1
                both = client.get(f"{task_path}/samples?limit=2", headers=auth).json()["items"]
                assert [row["label_index"] for row in both] == [0, 0]
                anomalies = client.get(f"{task_path}/samples?sample_filter=anomaly", headers=auth).json()
                assert anomalies["total"] == 1
                assert anomalies["items"][0]["index"] == 1
                assert anomalies["items"][0]["label_index"] == 0
            preview = client.get(f"{task_path}/samples/0/image?layer=prediction", headers=auth)
            assert preview.status_code == 200
            assert preview.content.startswith(b"\x89PNG")
            assert client.get(f"{task_path}/samples/3/image", headers=auth).status_code == 404
    finally:
        factory.engine.dispose()


def test_auc_ties_and_undefined_cases():
    """同分给半分，无正负任一类时指标留空。"""
    assert _auc(np.array([1]), np.array([2])) == 0.5
    assert _auc(np.array([1]), np.array([0])) is None


def test_specialized_geometry_errors():
    """关键点偏差和角度偏差不能误归类为漏检和误检。"""
    truth = {"category_id": 0, "bbox_xyxy": [0, 0, 20, 20], "keypoints": [5, 5, 2], "area": 400}
    predicted = {**truth, "keypoints": [16, 15, 1], "score": 0.9}
    assert explain_geometry_errors({"ground_truth": [truth], "predictions": [predicted]}, "pose", sigmas=(0.05,)) == {
        "keypoints": 1, "missed": 0, "extra": 0,
    }
    truth = {"category_id": 0, "polygon": [[0, 8], [20, 8], [20, 12], [0, 12]]}
    predicted = {"category_id": 0, "polygon": [[8, 0], [12, 0], [12, 20], [8, 20]], "score": 0.9}
    assert explain_geometry_errors({"ground_truth": [truth], "predictions": [predicted]}, "obb") == {
        "angle": 1, "missed": 0, "extra": 0,
    }
