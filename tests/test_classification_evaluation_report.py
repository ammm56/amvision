"""Classification 独立评估报告测试。"""

from backend.service.application.models.training.classification_evaluation_report import (
    build_classification_evaluation_report,
    build_unavailable_test_metrics_report,
)


def test_classification_evaluation_report_contains_confusion_and_per_class_accuracy() -> None:
    """报告应保留混淆矩阵、support 和每类准确率。"""

    report = build_classification_evaluation_report(
        split_name="test",
        checkpoint_role="best",
        labels=("empty", "full"),
        targets=(0, 0, 1, 1),
        predictions=(0, 1, 1, 1),
        top5_correct=4,
    )

    assert report["top1_accuracy"] == 0.75
    assert report["top5_accuracy"] == 1.0
    assert report["confusion_matrix"] == {
        "labels": ["empty", "full"],
        "rows": [[1, 1], [0, 2]],
    }
    assert report["per_class_metrics"] == [
        {
            "class_index": 0,
            "class_name": "empty",
            "support": 2,
            "predicted_count": 1,
            "correct": 1,
            "accuracy": 0.5,
        },
        {
            "class_index": 1,
            "class_name": "full",
            "support": 2,
            "predicted_count": 3,
            "correct": 2,
            "accuracy": 1.0,
        },
    ]


def test_unavailable_test_report_does_not_reuse_validation_metrics() -> None:
    """缺少 test split 时必须明确 unavailable，不能复用 validation。"""

    report = build_unavailable_test_metrics_report(reason="missing test")

    assert report["available"] is False
    assert report["split_name"] == "test"
    assert report["checkpoint_role"] == "best"
    assert report["reason"] == "missing test"
