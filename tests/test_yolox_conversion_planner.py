"""YOLOX conversion planner 测试。"""

from __future__ import annotations

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.conversions.yolox_conversion_planner import (
    DefaultYoloXConversionPlanner,
    YoloXConversionPlanningRequest,
)
from backend.service.application.conversions.yolo_model_conversion_planner import (
    DefaultYoloModelConversionPlanner,
    YoloModelConversionPlanningRequest,
)
from backend.service.domain.files.detection_model_file_types import YOLO11_DETECTION_FILE_TYPES


def test_conversion_planner_rejects_unimplemented_rknn_target() -> None:
    """验证 planner 不会把尚未实现的 RKNN 转换声明为可执行能力。"""

    planner = DefaultYoloXConversionPlanner()

    with pytest.raises(InvalidRequestError):
        planner.build_plan(
            YoloXConversionPlanningRequest(
                project_id="project-1",
                source_model_version_id="model-version-1",
                target_formats=("rknn",),  # type: ignore[arg-type]
            )
        )


def test_yolo_model_conversion_planner_rejects_unimplemented_rknn_target() -> None:
    """验证 YOLO 主线 planner 与公开 conversion service 的能力边界一致。"""

    planner = DefaultYoloModelConversionPlanner(
        file_types=YOLO11_DETECTION_FILE_TYPES,
        supported_task_types=("detection",),
    )

    with pytest.raises(InvalidRequestError):
        planner.build_plan(
            YoloModelConversionPlanningRequest(
                project_id="project-1",
                source_model_version_id="model-version-1",
                target_formats=("rknn",),  # type: ignore[arg-type]
            )
        )


def test_conversion_planner_builds_openvino_ir_chain() -> None:
    """验证 planner 会把 openvino-ir 规划为基于 optimized ONNX 的稳定链路。"""

    planner = DefaultYoloXConversionPlanner()

    plan = planner.build_plan(
        YoloXConversionPlanningRequest(
            project_id="project-1",
            source_model_version_id="model-version-1",
            target_formats=("openvino-ir",),
        )
    )

    assert plan.target_formats == ("openvino-ir",)
    assert [step.kind for step in plan.steps] == [
        "export-onnx",
        "validate-onnx",
        "optimize-onnx",
        "build-openvino-ir",
    ]
    assert plan.steps[-1].source_format == "onnx-optimized"
    assert plan.steps[-1].target_format == "openvino-ir"
