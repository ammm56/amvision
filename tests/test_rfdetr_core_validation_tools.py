"""RF-DETR core 验收工具测试。"""

from __future__ import annotations

import pytest
import torch

from backend.service.application.models.model_core_validation import (
    analyze_state_dict_coverage,
    build_model_core_snapshot,
)
from backend.service.application.models.rfdetr_model import build_rfdetr_model
from backend.service.application.models.rfdetr_segmentation_model import (
    build_rfdetr_segmentation_model,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


@pytest.mark.parametrize(
    ("task_type", "builder", "expected_extra_keys"),
    (
        (DETECTION_TASK_TYPE, build_rfdetr_model, ()),
        (SEGMENTATION_TASK_TYPE, build_rfdetr_segmentation_model, ("pred_masks",)),
    ),
)
def test_rfdetr_core_snapshot_records_forward_output_shapes(
    task_type: str,
    builder,
    expected_extra_keys: tuple[str, ...],
) -> None:
    """验证 RF-DETR detection/segmentation 可以生成结构和输出形状快照。"""

    model = builder(model_scale="nano", num_classes=3)

    snapshot = build_model_core_snapshot(
        model=model,
        model_type="rfdetr",
        task_type=task_type,
        model_scale="nano",
        num_classes=3,
        example_input=torch.randn(1, 3, 56, 56),
    )

    assert snapshot.model_type == "rfdetr"
    assert snapshot.task_type == task_type
    assert snapshot.parameters.total_parameter_count > 0
    assert snapshot.parameters.trainable_parameter_count == snapshot.parameters.total_parameter_count
    assert snapshot.parameters.state_dict_key_count == len(model.state_dict())
    assert snapshot.parameters.leaf_module_counts["Linear"] > 0
    assert snapshot.output_summary is not None
    assert snapshot.output_summary["kind"] == "dict"

    output_items = snapshot.output_summary["items"]
    assert output_items["pred_logits"] == {
        "kind": "tensor",
        "shape": (1, 300, 4),
        "dtype": "torch.float32",
    }
    assert output_items["pred_boxes"] == {
        "kind": "tensor",
        "shape": (1, 300, 4),
        "dtype": "torch.float32",
    }
    assert output_items["hs"]["kind"] == "list"
    assert output_items["hs"]["items"][0] == {
        "kind": "tensor",
        "shape": (1, 300, 256),
        "dtype": "torch.float32",
    }
    for key in expected_extra_keys:
        assert key in output_items


@pytest.mark.parametrize(
    ("task_type", "builder"),
    (
        (DETECTION_TASK_TYPE, build_rfdetr_model),
        (SEGMENTATION_TASK_TYPE, build_rfdetr_segmentation_model),
    ),
)
def test_rfdetr_state_dict_coverage_accepts_project_state_dict(task_type: str, builder) -> None:
    """验证 RF-DETR 项目内 detection/segmentation state_dict 可以完整覆盖。"""

    model = builder(model_scale="nano", num_classes=3)

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


def test_rfdetr_state_dict_coverage_strips_outer_checkpoint_prefixes() -> None:
    """验证 RF-DETR checkpoint 外层 model/module 前缀不会影响覆盖率判断。"""

    model = build_rfdetr_model(model_scale="nano", num_classes=3)
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


def test_rfdetr_state_dict_coverage_reports_shape_mismatch() -> None:
    """验证 RF-DETR 权重 shape 不一致时会给出明确覆盖率结果。"""

    model = build_rfdetr_segmentation_model(model_scale="nano", num_classes=3)
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
