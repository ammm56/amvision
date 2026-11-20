"""Detection-like 独立测试报告测试。"""

from types import SimpleNamespace

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.detection_evaluation import (
    _compute_ap,
    _detection_confusion,
    _detection_matches,
    _interpolated_precision,
    run_detection_evaluation,
)
from backend.service.application.models.training.detection_evaluation_report import (
    build_detection_test_metrics_report,
)


def test_detection_test_report_preserves_task_and_per_class_metrics() -> None:
    """报告应标记 best checkpoint，并原样保留逐类指标。"""

    per_class_metrics = [
        {
            "class_index": 0,
            "class_name": "empty",
            "ap50": 0.9,
            "ap50_95": 0.7,
        }
    ]
    report = build_detection_test_metrics_report(
        available=True,
        sample_count=12,
        category_names=("empty", "full"),
        task_type="segmentation",
        metrics={
            "map50": 0.88,
            "map50_95": 0.66,
            "per_class_metrics": per_class_metrics,
        },
    )

    assert report["available"] is True
    assert report["split_name"] == "test"
    assert report["checkpoint_role"] == "best"
    assert report["task_type"] == "segmentation"
    assert report["sample_count"] == 12
    assert report["category_names"] == ["empty", "full"]
    assert report["metrics"]["per_class_metrics"] == per_class_metrics


def test_detection_test_report_marks_missing_test_as_unavailable() -> None:
    """缺少 test split 时必须明确 unavailable，不复用 validation。"""

    report = build_detection_test_metrics_report(
        available=False,
        sample_count=0,
        category_names=("part",),
        reason="missing test",
    )

    assert report["available"] is False
    assert report["split_name"] == "test"
    assert report["checkpoint_role"] == "best"
    assert report["metrics"] == {}
    assert report["reason"] == "missing test"


def test_detection_curves_use_greedy_matches_and_keep_missed_objects() -> None:
    """重复预测、未召回标注和类别错分须反映在真实曲线与矩阵中。"""
    gt = [
        {"image_id": 0, "category_id": 1, "bbox_xyxy": (0, 0, 10, 10)},
        {"image_id": 0, "category_id": 1, "bbox_xyxy": (11, 11, 18, 18)},
    ]
    duplicate = {**gt[0], "score": 0.71}
    predictions = [{**gt[0], "score": 0.9}, duplicate]

    matches = _detection_matches(gt, predictions, iou_threshold=0.5)
    assert matches == [1, 1]
    curve = _interpolated_precision(matches, len(gt))
    assert curve == [1.0] * 51 + [0.0] * 50
    assert _compute_ap(gt, predictions) == pytest.approx(51 / 101)
    assert _detection_confusion(gt, [{**predictions[0], "category_id": 2}, duplicate]) == [
        (1, 2), (None, 1), (1, None),
    ]


@pytest.fixture
def partial_evaluation(tmp_path, monkeypatch):
    """构造可逐项检查的图片与标注，替换模型但保留真实解码器。"""
    import cv2
    import numpy as np

    from backend.service.application.images.image_matrix import (
        decode_image_bytes_to_matrix,
    )
    from backend.service.application.models.evaluation import (
        detection_evaluation as evaluation,
    )
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        DatasetStorageSettings,
        LocalDatasetStorage,
    )

    class Session:
        """返回单个正确预测，也可模拟整次推理的故障。"""

        failure = None
        closed = False

        def predict(self, request):
            """解码真实 PNG 后，返回和标注一致的预测框。"""
            if self.failure is not None:
                raise self.failure
            decode_image_bytes_to_matrix(cv2_module=cv2, np_module=np, image_bytes=request.input_image_bytes, image_payload=None)
            return SimpleNamespace(detections=[SimpleNamespace(score=0.9, class_id=0, bbox_xyxy=(1, 2, 6, 9))], latency_ms=1)

        def close(self):
            """记录会话释放，即使任务失败也应执行。"""
            self.closed = True

    session = Session()
    monkeypatch.setattr(evaluation, "DefaultDetectionModelRuntime", lambda: SimpleNamespace(load_session=lambda **_: session))
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    valid_png = cv2.imencode(".png", np.zeros((12, 12, 3), dtype=np.uint8))[1].tobytes()
    storage.write_bytes("images/valid.png", valid_png)
    storage.write_bytes("images/broken.png", b"broken")
    storage.write_bytes("images/bad-label.png", valid_png)
    split = {
        "name": "test",
        "image_root": "images",
        "images": [{"id": i, "file_name": name} for i, name in enumerate(("valid.png", "missing.png", "broken.png", "bad-label.png"))],
        "annotations": [{"image_id": i, "category_id": 1, "bbox": [1, 2, 0 if i == 3 else 5, 7]} for i in range(4)],
    }
    request = evaluation.DetectionEvaluationRequest(
        dataset_storage=storage,
        runtime_target=SimpleNamespace(model_type="yolo11", labels=("part",), input_size=(12, 12)),
        manifest_payload={"categories": [{"id": 1, "name": "part"}], "splits": [split]},
    )
    return request, split, session


def test_partial_detection_only_scores_successful_samples(partial_evaluation) -> None:
    """缺图、坏图和无效标注独立记录，不能作为漏检计入指标。"""
    request, _, session = partial_evaluation
    from dataclasses import replace

    snapshots = []
    result = run_detection_evaluation(replace(request, on_progress=snapshots.append))
    assert result.sample_count == 1
    assert result.map50_95 == pytest.approx(1)
    assert result.report_payload["coverage"] == {"requested": 4, "succeeded": 1, "failed": 3, "unprocessed": 0}
    assert [(item["name"], item["reason"], item["classes"]) for item in result.report_payload["failed_samples"]] == [
        ("missing.png", "missing_image", ["part"]),
        ("broken.png", "unreadable_image", ["part"]),
        ("bad-label.png", "invalid_annotation", ["part"]),
    ]
    assert [item["image_index"] for item in result.detections_payload] == [0]
    assert result.failed_image_paths == {1: "images/missing.png", 2: "images/broken.png", 3: "images/bad-label.png"}
    assert all("image_path" not in item for item in result.report_payload["failed_samples"])
    assert snapshots[0]["coverage"] == {"requested": 4, "succeeded": 0, "failed": 0, "unprocessed": 4}
    assert snapshots[-1]["coverage"] == result.report_payload["coverage"]
    assert snapshots[-1]["stage"] == "summarizing"
    assert [item["name"] for item in snapshots[-1]["recent_samples"]] == ["bad-label.png", "broken.png", "missing.png"]
    assert all("image_path" not in item and item["processed_at"] for item in snapshots[-1]["recent_samples"])
    assert session.closed


def test_detection_fails_when_no_scored_samples_remain(partial_evaluation) -> None:
    """所有样本失败时不应生成空的成功报告。"""
    request, split, session = partial_evaluation
    split["images"].pop(0)
    with pytest.raises(InvalidRequestError, match="没有可用于计算指标的评估样本"):
        run_detection_evaluation(request)
    assert session.closed


def test_detection_runtime_failure_is_not_a_sample_warning(partial_evaluation) -> None:
    """模型或运行时故障必须仍然让任务失败。"""
    request, _, session = partial_evaluation
    session.failure = RuntimeError("runtime failure")
    with pytest.raises(RuntimeError, match="runtime failure"):
        run_detection_evaluation(request)
    assert session.closed
