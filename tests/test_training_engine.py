"""共享 TrainingEngine 和首轮 CUDA OOM 恢复测试。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training import training_engine as engine_module
from backend.service.application.models.training.training_engine import (
    build_execution_training_config_runtime,
    read_active_training_runtime,
    record_active_training_amp_resolution,
    record_active_training_batch_stage_metrics,
    record_active_training_batch_resolution,
    training_engine_entrypoint,
)


@dataclass(frozen=True)
class _Request:
    """构造训练引擎所需的最小 request 合同。"""

    batch_size: int | None = None
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: Callable[[Any], Any] | None = None


@dataclass(frozen=True)
class _Result:
    """构造包含统一 metrics payload 的最小执行结果。"""

    metrics_payload: dict[str, object]


def _record_cuda_batch(request: _Request) -> int:
    """模拟模型 resolver 按当前 maximum 选择实际 batch。"""

    options = dict(request.extra_options or {})
    batch_size = int(options.get("batch_maximum_size") or 16)
    record_active_training_batch_resolution(
        batch_size=batch_size,
        mode="auto-cuda-profile",
        device_name="cuda:0",
        target_memory_fraction=0.6,
    )
    return batch_size


def test_training_engine_rebuilds_and_halves_auto_batch_after_first_epoch_oom() -> None:
    """首轮 OOM 必须从原 request 干净重建并按半降低 maximum。"""

    attempts: list[int] = []

    @training_engine_entrypoint
    def execute(request: _Request) -> dict[str, object]:
        attempts.append(_record_cuda_batch(request))
        if len(attempts) < 3:
            raise RuntimeError("CUDA out of memory while allocating tensor")
        return read_active_training_runtime()

    runtime = execute(
        _Request(
            extra_options={
                "batch_mode": "auto",
                "batch_maximum_size": 16,
                "batch_minimum_size": 1,
                "batch_oom_max_retries": 3,
            }
        )
    )

    assert attempts == [16, 8, 4]
    assert runtime["training_engine"] == "shared-v1"
    assert runtime["batch_size"] == 4
    assert runtime["oom_recovery_count"] == 2
    assert runtime["oom_previous_batch_size"] == 8


def test_training_engine_does_not_retry_after_completed_epoch() -> None:
    """完整 epoch 后的 OOM 不能静默重启并改变训练轨迹。"""

    attempts = 0

    @training_engine_entrypoint
    def execute(request: _Request) -> None:
        nonlocal attempts
        attempts += 1
        _record_cuda_batch(request)
        assert request.epoch_callback is not None
        request.epoch_callback(SimpleNamespace(epoch=1))
        raise RuntimeError("CUDA out of memory during validation")

    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        execute(_Request(extra_options={"batch_mode": "auto"}))
    assert attempts == 1


@pytest.mark.parametrize(
    ("training_request", "expected_message"),
    [
        (
            _Request(batch_size=8, extra_options={"batch_mode": "fixed"}),
            "CUDA out of memory",
        ),
        (
            _Request(
                resume_checkpoint_path=Path("resume.pt"),
                extra_options={"batch_mode": "auto"},
            ),
            "CUDA out of memory",
        ),
    ],
)
def test_training_engine_never_changes_fixed_or_resume_batch(
    training_request: _Request,
    expected_message: str,
) -> None:
    """固定 batch 与 resume 必须保持可复现语义。"""

    @training_engine_entrypoint
    def execute(current: _Request) -> None:
        _record_cuda_batch(current)
        raise RuntimeError("CUDA out of memory")

    with pytest.raises(RuntimeError, match=expected_message):
        execute(training_request)


def test_training_engine_reports_oom_at_minimum_batch() -> None:
    """batch=1 仍 OOM 时返回明确配置错误。"""

    @training_engine_entrypoint
    def execute(request: _Request) -> None:
        record_active_training_batch_resolution(
            batch_size=1,
            mode="auto-cuda-profile",
            device_name="cuda:0",
            target_memory_fraction=0.6,
        )
        raise RuntimeError("CUDA out of memory")

    with pytest.raises(InvalidRequestError, match="最小 batch"):
        execute(
            _Request(
                extra_options={
                    "batch_mode": "auto",
                    "batch_minimum_size": 1,
                }
            )
        )


def test_training_engine_exposes_only_finite_non_negative_stage_metrics() -> None:
    """阶段遥测不得把负数、NaN 或 Inf 带入 WebSocket payload。"""

    @training_engine_entrypoint
    def execute(_request: _Request) -> dict[str, object]:
        record_active_training_batch_stage_metrics(
            {
                "forward_loss_host_time_ms": 12.34567,
                "negative": -1.0,
                "nan": float("nan"),
                "inf": float("inf"),
            }
        )
        return read_active_training_runtime()

    runtime = execute(_Request())

    assert runtime["forward_loss_host_time_ms"] == 12.3457
    assert "negative" not in runtime
    assert "nan" not in runtime
    assert "inf" not in runtime


def test_training_engine_persists_resolved_batch_and_amp_in_result() -> None:
    """训练结果和摘要必须记录真实 batch/AMP，不能回退为请求默认值。"""

    @training_engine_entrypoint
    def execute(_request: _Request) -> _Result:
        record_active_training_batch_resolution(
            batch_size=46,
            mode="auto-cuda-profile",
            device_name="cuda:0",
            target_memory_fraction=0.75,
        )
        record_active_training_amp_resolution(
            enabled=True,
            precision="fp16",
            device_name="cuda:0",
            scaler_enabled=True,
        )
        return _Result(metrics_payload={"epoch_history": []})

    result = execute(_Request(extra_options={"batch_mode": "auto"}))
    runtime = result.metrics_payload["training_runtime"]
    config = build_execution_training_config_runtime(
        execution_result=result,
        requested_batch_size=None,
        requested_precision=None,
        default_batch_size=4,
    )

    assert runtime["batch_size"] == 46
    assert runtime["precision"] == "fp16"
    assert runtime["amp_enabled"] is True
    assert runtime["amp_scaler_enabled"] is True
    assert config == {
        "batch_size": 46,
        "precision": "fp16",
        "batch_resolution_mode": "auto-cuda-profile",
        "amp_enabled": True,
        "amp_dtype": "fp16",
        "device": "cuda:0",
        "oom_recovery_count": 0,
    }


@pytest.mark.parametrize("should_fail", [False, True])
def test_training_engine_releases_runtime_resources_after_every_exit(
    monkeypatch: pytest.MonkeyPatch,
    should_fail: bool,
) -> None:
    """成功或异常退出都必须清理常驻 worker 的训练高水位资源。"""

    release_count = 0

    def release() -> None:
        nonlocal release_count
        release_count += 1

    monkeypatch.setattr(engine_module, "release_training_runtime_resources", release)

    @training_engine_entrypoint
    def execute(_request: _Request) -> _Result:
        if should_fail:
            raise RuntimeError("training stopped")
        return _Result(metrics_payload={})

    if should_fail:
        with pytest.raises(RuntimeError, match="training stopped"):
            execute(_Request(extra_options={"batch_mode": "fixed"}))
    else:
        execute(_Request(extra_options={"batch_mode": "fixed"}))

    assert release_count == 1
