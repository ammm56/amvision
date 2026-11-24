"""Classification 独立评估报告测试。"""

from dataclasses import replace

from backend.service.api.rest.v1.routes.classification_evaluation_tasks.responses import (
    build_classification_evaluation_detail_response,
    build_classification_evaluation_summary_response,
)
from backend.service.application.models.training.classification_evaluation_report import (
    build_classification_evaluation_report,
    build_unavailable_test_metrics_report,
)
from backend.service.domain.tasks.task_records import TaskRecord


def test_classification_evaluation_responses_include_title_fields() -> None:
    """列表和详情返回命名来源，历史记录可从已保存结果取得输入引用。"""

    task = TaskRecord(
        task_id="task-1",
        task_kind="classification-evaluation",
        project_id="project-1",
        display_name="classification evaluation dataset-export-1",
        state="succeeded",
        result={
            "model_version_id": "model-version-1",
            "dataset_export_id": "dataset-export-1",
            "sample_count": 96,
        },
    )
    summary = build_classification_evaluation_summary_response(task)
    assert summary.model_version_id == "model-version-1"
    assert summary.dataset_export_id == "dataset-export-1"
    assert summary.uses_default_name is None
    assert summary.sample_count == 96

    named_task = replace(task, metadata={"uses_default_name": False})
    assert build_classification_evaluation_summary_response(named_task).uses_default_name is False
    detail = build_classification_evaluation_detail_response(named_task)
    assert detail.display_name == task.display_name
    assert detail.model_version_id == summary.model_version_id
    assert detail.uses_default_name is False


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
