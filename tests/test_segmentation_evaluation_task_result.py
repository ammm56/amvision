"""segmentation evaluation 任务结果持久化契约测试。"""

from __future__ import annotations

from backend.service.application.models.evaluation.segmentation_evaluation_service import (
    SegmentationEvaluationTaskResult,
)


def test_segmentation_evaluation_task_payload_preserves_all_metrics_and_files() -> None:
    """验证任务事件、详情 API 与恢复执行共享完整结果字段。"""

    task_result = SegmentationEvaluationTaskResult(
        task_id="task-1",
        status="succeeded",
        dataset_export_id="dataset-export-1",
        dataset_version_id="dataset-version-1",
        model_version_id="model-version-1",
        output_object_prefix="task-runs/evaluation/task-1",
        report_object_key="task-runs/evaluation/task-1/report.json",
        predictions_object_key="task-runs/evaluation/task-1/predictions.json",
        result_package_object_key="task-runs/evaluation/task-1/result.zip",
        bbox_map50=0.71,
        bbox_map50_95=0.52,
        map50=0.71,
        map50_95=0.52,
        mask_map50=0.68,
        mask_map50_95=0.47,
        sample_count=12,
        report_summary={"split_name": "test"},
    )

    payload = task_result.to_task_result_payload()

    assert payload["map50"] == 0.71
    assert payload["map50_95"] == 0.52
    assert payload["bbox_map50"] == 0.71
    assert payload["bbox_map50_95"] == 0.52
    assert payload["mask_map50"] == 0.68
    assert payload["mask_map50_95"] == 0.47
    assert payload["predictions_object_key"].endswith("predictions.json")
    assert payload["result_package_object_key"].endswith("result.zip")
    assert payload["report_summary"] == {"split_name": "test"}
