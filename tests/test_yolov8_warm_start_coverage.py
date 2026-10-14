"""YOLOv8 detection warm start 必须遵守正式权重覆盖率门禁。"""

from types import SimpleNamespace

import pytest
import torch

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolov8_core.model import build_yolov8_model
from backend.service.application.models.yolov8_core.training.detection_execution import (
    _load_warm_start_checkpoint,
)


def test_warm_start_rejects_shape_mismatches_across_model(tmp_path) -> None:
    """所有 key 存在但绝大部分 shape 不匹配时，不能报告 warm start 成功。"""

    model = build_yolov8_model(task_type="detection", model_scale="nano", num_classes=2)
    checkpoint = tmp_path / "incompatible.pt"
    torch.save(
        {"model_state_dict": {key: value.new_zeros(1) for key, value in model.state_dict().items()}},
        checkpoint,
    )
    with pytest.raises(ServiceConfigurationError, match="覆盖率"):
        _load_warm_start_checkpoint(
            imports=SimpleNamespace(torch=torch),
            model=model,
            checkpoint_path=checkpoint,
            source_summary={},
        )


def test_warm_start_allows_class_head_change_and_reports_coverage(tmp_path) -> None:
    """允许新类别数改变 head，同时记录实际覆盖率并保留当前训练配方。"""

    source = build_yolov8_model(task_type="detection", model_scale="nano", num_classes=3)
    target = build_yolov8_model(task_type="detection", model_scale="nano", num_classes=2)
    checkpoint = tmp_path / "warm-start.pt"
    torch.save({"model_state_dict": source.state_dict()}, checkpoint)
    summary = _load_warm_start_checkpoint(
        imports=SimpleNamespace(torch=torch),
        model=target,
        checkpoint_path=checkpoint,
        source_summary={"source_model_version_id": "version-1"},
    )
    assert summary["enabled"] is True
    assert summary["source_model_version_id"] == "version-1"
    assert summary["load_summary"]["coverage"]["loadable_ratio"] > 0.8
    assert summary["load_summary"]["shape_mismatch_keys"]
    torch.testing.assert_close(target.model[0].conv.weight, source.model[0].conv.weight)
