"""模型 core 验收工具测试。"""

from __future__ import annotations

import pytest
import torch

from backend.service.application.models.model_core_validation import (
    analyze_state_dict_coverage,
    build_model_core_snapshot,
)
from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


YOLO_MODEL_TYPES = ("yolov8", "yolo11", "yolo26")


@pytest.mark.parametrize("model_type", YOLO_MODEL_TYPES)
@pytest.mark.parametrize(
    ("task_type", "num_classes", "expected_output_shape"),
    (
        (DETECTION_TASK_TYPE, 2, (1, 84, 6)),
        (POSE_TASK_TYPE, 2, (1, 84, 57)),
        (OBB_TASK_TYPE, 2, (1, 84, 7)),
    ),
)
def test_yolo_primary_core_snapshot_records_tensor_output_shape(
    model_type: str,
    task_type: str,
    num_classes: int,
    expected_output_shape: tuple[int, ...],
) -> None:
    """验证 YOLO 主线 tensor 输出任务可以生成结构与输出形状快照。"""

    model = build_yolo_primary_model(
        model_type=model_type,
        task_type=task_type,
        model_scale="nano",
        num_classes=num_classes,
    )

    snapshot = build_model_core_snapshot(
        model=model,
        model_type=model_type,
        task_type=task_type,
        model_scale="nano",
        num_classes=num_classes,
        example_input=torch.randn(1, 3, 64, 64),
    )

    assert snapshot.model_type == model_type
    assert snapshot.task_type == task_type
    assert snapshot.parameters.total_parameter_count > 0
    assert snapshot.parameters.trainable_parameter_count == snapshot.parameters.total_parameter_count
    assert snapshot.parameters.state_dict_key_count == len(model.state_dict())
    assert snapshot.parameters.leaf_module_counts["Conv2d"] > 0
    assert snapshot.output_summary == {
        "kind": "tensor",
        "shape": expected_output_shape,
        "dtype": "torch.float32",
    }


@pytest.mark.parametrize("model_type", YOLO_MODEL_TYPES)
def test_yolo_primary_core_snapshot_records_classification_tuple_shape(model_type: str) -> None:
    """验证 classification 输出的概率和 logits 形状会一起记录。"""

    model = build_yolo_primary_model(
        model_type=model_type,
        task_type=CLASSIFICATION_TASK_TYPE,
        model_scale="nano",
        num_classes=3,
    )

    snapshot = build_model_core_snapshot(
        model=model,
        model_type=model_type,
        task_type=CLASSIFICATION_TASK_TYPE,
        model_scale="nano",
        num_classes=3,
        example_input=torch.randn(1, 3, 64, 64),
    )

    assert snapshot.output_summary == {
        "kind": "tuple",
        "items": (
            {"kind": "tensor", "shape": (1, 3), "dtype": "torch.float32"},
            {"kind": "tensor", "shape": (1, 3), "dtype": "torch.float32"},
        ),
    }


@pytest.mark.parametrize("model_type", YOLO_MODEL_TYPES)
def test_yolo_primary_core_snapshot_records_segmentation_tuple_shape(model_type: str) -> None:
    """验证 segmentation 输出的预测和 proto 形状会一起记录。"""

    model = build_yolo_primary_model(
        model_type=model_type,
        task_type=SEGMENTATION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )

    snapshot = build_model_core_snapshot(
        model=model,
        model_type=model_type,
        task_type=SEGMENTATION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
        example_input=torch.randn(1, 3, 64, 64),
    )

    assert snapshot.output_summary == {
        "kind": "tuple",
        "items": (
            {"kind": "tensor", "shape": (1, 84, 38), "dtype": "torch.float32"},
            {"kind": "tensor", "shape": (1, 32, 16, 16), "dtype": "torch.float32"},
        ),
    }


def test_state_dict_coverage_accepts_exact_project_state_dict() -> None:
    """验证自身 state_dict 可以达到完整覆盖。"""

    model = build_yolo_primary_model(
        model_type="yolo26",
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
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


def test_state_dict_coverage_strips_common_prefixes() -> None:
    """验证常见 model/module 前缀不会影响覆盖率判断。"""

    model = build_yolo_primary_model(
        model_type="yolo11",
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )
    prefixed_state_dict = {
        f"module.model.{key}": value for key, value in model.state_dict().items()
    }

    coverage = analyze_state_dict_coverage(
        model=model,
        source_state_dict=prefixed_state_dict,
    )

    assert coverage.loadable_key_count == coverage.model_key_count
    assert coverage.loadable_ratio == 1.0
    assert coverage.missing_keys == ()
    assert coverage.unexpected_keys == ()


def test_state_dict_coverage_reports_shape_mismatch() -> None:
    """验证 shape 不一致的 key 会被单独标记出来。"""

    model = build_yolo_primary_model(
        model_type="yolov8",
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=2,
    )
    source_state_dict = dict(model.state_dict())
    mismatch_key = next(iter(source_state_dict))
    source_state_dict[mismatch_key] = torch.zeros(1)

    coverage = analyze_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
    )

    assert coverage.shape_mismatch_keys == (mismatch_key,)
    assert mismatch_key not in coverage.missing_keys
    assert coverage.loadable_key_count == coverage.model_key_count - 1
    assert coverage.loadable_ratio < 1.0
