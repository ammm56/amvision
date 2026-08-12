"""YOLO11/YOLO26 非 detection task execution callback 合同测试。"""

from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace

import pytest


_TASK_EXECUTION_CASES = (
    ("yolo11", "classification"),
    ("yolo11", "segmentation"),
    ("yolo11", "pose"),
    ("yolo11", "obb"),
    ("yolo26", "classification"),
    ("yolo26", "segmentation"),
    ("yolo26", "pose"),
    ("yolo26", "obb"),
)


@pytest.mark.parametrize(("model_type", "task_type"), _TASK_EXECUTION_CASES)
def test_task_execution_preserves_batch_and_control_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    model_type: str,
    task_type: str,
) -> None:
    """验证平台 request 进入模型执行层时不会丢失批次遥测和即时控制。"""

    module = import_module(
        "backend.service.application.models.training."
        f"{model_type}_{task_type}_task_execution"
    )
    runner_name = f"run_{model_type}_{task_type}_training"
    adapter_name = f"run_{model_type}_{task_type}_training_from_task_request"
    captured: dict[str, object] = {}
    expected_result = object()

    def capture_request(request: object) -> object:
        captured["request"] = request
        return expected_result

    monkeypatch.setattr(module, runner_name, capture_request)
    batch_callback = object()
    control_callback = object()
    platform_request = SimpleNamespace(
        dataset_storage=object(),
        manifest_payload={},
        model_type=model_type,
        model_scale="s",
        batch_size=4,
        max_epochs=2,
        evaluation_interval=1,
        input_size=(640, 640),
        precision="fp16",
        warm_start_checkpoint_path=None,
        warm_start_source_summary=None,
        resume_checkpoint_path=None,
        previous_best_checkpoint_path=None,
        extra_options={},
        epoch_callback=None,
        batch_callback=batch_callback,
        control_callback=control_callback,
        savepoint_callback=None,
    )

    result = getattr(module, adapter_name)(platform_request)

    assert result is expected_result
    model_request = captured["request"]
    assert getattr(model_request, "batch_callback") is batch_callback
    assert getattr(model_request, "control_callback") is control_callback
