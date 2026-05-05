"""YOLOX conversion planner 测试。"""

from __future__ import annotations

from backend.service.application.conversions.yolox_conversion_planner import (
    DefaultYoloXConversionPlanner,
    YoloXConversionPlanningRequest,
)


def test_conversion_planner_builds_stable_graph_for_future_targets() -> None:
    """验证 planner 会为未来下游目标保留稳定的 ONNX 中间层图谱。"""

    planner = DefaultYoloXConversionPlanner()

    plan = planner.build_plan(
        YoloXConversionPlanningRequest(
            project_id="project-1",
            source_model_version_id="model-version-1",
            target_formats=("onnx-optimized", "rknn"),
        )
    )

    assert plan.target_formats == ("onnx-optimized", "rknn")
    assert [step.kind for step in plan.steps] == [
        "export-onnx",
        "validate-onnx",
        "optimize-onnx",
        "build-rknn",
    ]
    assert plan.steps[0].source_format == "pytorch-checkpoint"
    assert plan.steps[0].target_format == "onnx"
    assert plan.steps[1].produced_file_type is None
    assert plan.steps[2].target_format == "onnx-optimized"
    assert plan.steps[3].source_format == "onnx-optimized"
    assert plan.steps[3].target_format == "rknn"