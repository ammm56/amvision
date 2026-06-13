"""YOLO core 独立入口测试。"""

from __future__ import annotations

import pytest
import torch

from backend.service.application.models.model_core_validation import analyze_state_dict_coverage
from backend.service.application.models.yolo11_core import (
    YOLO11_HEAD_MODULES,
    YOLO11_MODEL_CONFIGS,
    build_yolo11_model,
)
from backend.service.application.models.yolo26_core import (
    YOLO26_HEAD_MODULES,
    YOLO26_MODEL_CONFIGS,
    build_yolo26_model,
)
from backend.service.application.models.yolov8_core import (
    YOLOV8_HEAD_MODULES,
    YOLOV8_MODEL_CONFIGS,
    build_yolov8_model,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


@pytest.mark.parametrize(
    ("model_type", "builder", "model_configs"),
    (
        ("yolov8", build_yolov8_model, YOLOV8_MODEL_CONFIGS),
        ("yolo11", build_yolo11_model, YOLO11_MODEL_CONFIGS),
        ("yolo26", build_yolo26_model, YOLO26_MODEL_CONFIGS),
    ),
)
def test_yolo_core_entrypoint_builds_detection_model(
    model_type: str,
    builder,
    model_configs: dict[str, dict[str, object]],
) -> None:
    """验证每个 YOLO core 包都能独立构建 detection 模型。"""

    assert set(model_configs) == {
        DETECTION_TASK_TYPE,
        CLASSIFICATION_TASK_TYPE,
        SEGMENTATION_TASK_TYPE,
        POSE_TASK_TYPE,
        OBB_TASK_TYPE,
    }
    model = builder(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )
    model.eval()
    with torch.inference_mode():
        prediction = model(torch.randn(1, 3, 64, 64))

    assert model.model_name == f"{model_type}-detection"
    assert prediction.shape == (1, 84, 6)


def test_yolo_core_head_module_maps_are_model_specific() -> None:
    """验证 head/decode 入口已经由各自 YOLO core 显式登记。"""

    assert set(YOLOV8_HEAD_MODULES) == {"Detect", "Segment", "Pose", "OBB", "Classify"}
    assert set(YOLO11_HEAD_MODULES) == {"Detect", "Segment", "Pose", "OBB", "Classify"}
    assert set(YOLO26_HEAD_MODULES) == {
        "Detect",
        "Segment26",
        "Pose26",
        "OBB26",
        "Classify",
    }
    assert YOLOV8_HEAD_MODULES["Segment"].__name__ == "Segment"
    assert YOLO11_HEAD_MODULES["Pose"].__name__ == "Pose"
    assert YOLO26_HEAD_MODULES["Segment26"].__name__ == "Segment26"
    assert YOLO26_HEAD_MODULES["Pose26"].__name__ == "Pose26"
    assert YOLO26_HEAD_MODULES["OBB26"].__name__ == "OBB26"


@pytest.mark.parametrize(
    ("builder", "task_type", "num_classes"),
    (
        (build_yolov8_model, DETECTION_TASK_TYPE, 2),
        (build_yolov8_model, CLASSIFICATION_TASK_TYPE, 3),
        (build_yolov8_model, SEGMENTATION_TASK_TYPE, 2),
        (build_yolov8_model, POSE_TASK_TYPE, 2),
        (build_yolov8_model, OBB_TASK_TYPE, 2),
        (build_yolo11_model, DETECTION_TASK_TYPE, 2),
        (build_yolo11_model, CLASSIFICATION_TASK_TYPE, 3),
        (build_yolo11_model, SEGMENTATION_TASK_TYPE, 2),
        (build_yolo11_model, POSE_TASK_TYPE, 2),
        (build_yolo11_model, OBB_TASK_TYPE, 2),
        (build_yolo26_model, DETECTION_TASK_TYPE, 2),
        (build_yolo26_model, CLASSIFICATION_TASK_TYPE, 3),
        (build_yolo26_model, SEGMENTATION_TASK_TYPE, 2),
        (build_yolo26_model, POSE_TASK_TYPE, 2),
        (build_yolo26_model, OBB_TASK_TYPE, 2),
    ),
)
def test_yolo_core_entrypoint_state_dict_coverage_is_complete(
    builder,
    task_type: str,
    num_classes: int,
) -> None:
    """验证每个 YOLO core 入口都能完整覆盖自身 state_dict。"""

    model = builder(
        task_type=task_type,
        model_scale="nano",
        num_classes=num_classes,
    )

    coverage = analyze_state_dict_coverage(
        model=model,
        source_state_dict=dict(model.state_dict()),
    )

    assert coverage.model_key_count == len(model.state_dict())
    assert coverage.source_key_count == len(model.state_dict())
    assert coverage.loadable_key_count == coverage.model_key_count
    assert coverage.loadable_ratio == 1.0
    assert coverage.missing_keys == ()
    assert coverage.unexpected_keys == ()
    assert coverage.shape_mismatch_keys == ()
