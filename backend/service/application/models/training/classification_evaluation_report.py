"""Classification 独立评估报告构建。"""

from __future__ import annotations

from collections.abc import Sequence


def build_classification_evaluation_report(
    *,
    split_name: str,
    checkpoint_role: str,
    labels: Sequence[str],
    targets: Sequence[int],
    predictions: Sequence[int],
    top5_correct: int,
) -> dict[str, object]:
    """构建包含混淆矩阵和每类准确率的 classification 评估报告。"""

    if len(targets) != len(predictions):
        raise ValueError("classification targets 与 predictions 数量不一致")
    class_count = len(labels)
    confusion_matrix = [
        [0 for _ in range(class_count)]
        for _ in range(class_count)
    ]
    for target, prediction in zip(targets, predictions, strict=True):
        target_index = int(target)
        prediction_index = int(prediction)
        if not 0 <= target_index < class_count:
            raise ValueError("classification target 超出类别范围")
        if not 0 <= prediction_index < class_count:
            raise ValueError("classification prediction 超出类别范围")
        confusion_matrix[target_index][prediction_index] += 1

    sample_count = len(targets)
    correct_top1 = sum(
        confusion_matrix[index][index] for index in range(class_count)
    )
    per_class_metrics: list[dict[str, object]] = []
    for class_index, class_name in enumerate(labels):
        support = sum(confusion_matrix[class_index])
        correct = confusion_matrix[class_index][class_index]
        predicted_count = sum(
            confusion_matrix[row_index][class_index]
            for row_index in range(class_count)
        )
        per_class_metrics.append(
            {
                "class_index": class_index,
                "class_name": str(class_name),
                "support": support,
                "predicted_count": predicted_count,
                "correct": correct,
                "accuracy": (
                    round(correct / support, 6) if support > 0 else None
                ),
            }
        )

    return {
        "available": sample_count > 0,
        "split_name": str(split_name),
        "checkpoint_role": str(checkpoint_role),
        "sample_count": sample_count,
        "top1_accuracy": (
            round(correct_top1 / sample_count, 6) if sample_count > 0 else None
        ),
        "top5_accuracy": (
            round(int(top5_correct) / sample_count, 6)
            if sample_count > 0
            else None
        ),
        "confusion_matrix": {
            "labels": [str(label) for label in labels],
            "rows": confusion_matrix,
        },
        "per_class_metrics": per_class_metrics,
    }


def build_unavailable_test_metrics_report(*, reason: str) -> dict[str, object]:
    """构建没有独立 test split 时的明确报告。"""

    return {
        "available": False,
        "split_name": "test",
        "checkpoint_role": "best",
        "sample_count": 0,
        "reason": str(reason),
        "top1_accuracy": None,
        "top5_accuracy": None,
        "confusion_matrix": {"labels": [], "rows": []},
        "per_class_metrics": [],
    }


__all__ = [
    "build_classification_evaluation_report",
    "build_unavailable_test_metrics_report",
]
