"""Detection-like 独立测试报告测试。"""

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
