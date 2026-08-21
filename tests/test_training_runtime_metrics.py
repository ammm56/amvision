"""训练运行时吞吐量和 GPU 资源采样测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.service.application.models.training.training_runtime_metrics import (
    TrainingRuntimeMetricsSampler,
)


class _FakeCuda:
    """提供 sampler 使用的最小 CUDA API。"""

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def memory_allocated(_device: str) -> int:
        return 2 * 1024**3

    @staticmethod
    def memory_reserved(_device: str) -> int:
        return 3 * 1024**3

    @staticmethod
    def max_memory_allocated(_device: str) -> int:
        return 4 * 1024**3

    @staticmethod
    def mem_get_info(_device: str) -> tuple[int, int]:
        return 4 * 1024**3, 8 * 1024**3

    @staticmethod
    def utilization(_device: str) -> float:
        return 72.0

    @staticmethod
    def temperature(_device: str) -> int:
        return 67

    @staticmethod
    def power_draw(_device: str) -> int:
        return 321_500

    @staticmethod
    def clock_rate(_device: str) -> int:
        return 2_625


class _UnavailableNvmlCuda(_FakeCuda):
    """模拟显存 API 可用但 NVML utilization 不可用的 CUDA 环境。"""

    @staticmethod
    def utilization(_device: str) -> float:
        raise OSError("NVML unavailable")


def test_runtime_sampler_calculates_throughput_timing_and_gpu_metrics() -> None:
    """连续 heartbeat 应计算 samples/s、耗时、ETA 和显存。"""

    ticks = iter((10.0, 10.5))
    sampler = TrainingRuntimeMetricsSampler(
        clock=lambda: next(ticks),
        torch_module=SimpleNamespace(cuda=_FakeCuda()),
    )

    first = sampler.sample(
        task_id="task-1",
        epoch=1,
        global_step=1,
        total_steps=10,
        batch_size=4,
        device_name="cuda:0",
    )
    second = sampler.sample(
        task_id="task-1",
        epoch=1,
        global_step=2,
        total_steps=10,
        batch_size=4,
        device_name="cuda:0",
    )

    assert first["gpu_utilization_percent"] == 72.0
    assert first["gpu_temperature_celsius"] == 67.0
    assert first["gpu_power_draw_watts"] == 321.5
    assert first["gpu_sm_clock_mhz"] == 2625.0
    assert second["step_time_ms"] == 500.0
    assert second["steps_per_second"] == 2.0
    assert second["samples_per_second"] == 8.0
    assert second["estimated_remaining_seconds"] == 4.0
    assert second["gpu_memory_allocated_bytes"] == 2 * 1024**3
    assert second["gpu_memory_used_percent"] == 50.0


def test_runtime_sampler_resets_timing_when_global_step_restarts() -> None:
    """OOM 完整重建导致 step 回退时不能沿用旧尝试的吞吐量。"""

    ticks = iter((1.0, 2.0, 3.0))
    sampler = TrainingRuntimeMetricsSampler(
        clock=lambda: next(ticks),
        torch_module=SimpleNamespace(cuda=_FakeCuda()),
    )
    sampler.sample(
        task_id="task-1",
        epoch=1,
        global_step=1,
        total_steps=10,
        batch_size=8,
        device_name="cuda:0",
    )
    sampler.sample(
        task_id="task-1",
        epoch=1,
        global_step=2,
        total_steps=10,
        batch_size=8,
        device_name="cuda:0",
    )
    restarted = sampler.sample(
        task_id="task-1",
        epoch=1,
        global_step=1,
        total_steps=20,
        batch_size=4,
        device_name="cuda:0",
    )

    assert restarted["elapsed_seconds"] == 0.0
    assert "samples_per_second" not in restarted


def test_runtime_sampler_keeps_timing_and_memory_when_nvml_is_unavailable() -> None:
    """可选 GPU utilization 失败时不得清空吞吐和显存遥测。"""

    ticks = iter((1.0, 1.25))
    sampler = TrainingRuntimeMetricsSampler(
        clock=lambda: next(ticks),
        torch_module=SimpleNamespace(cuda=_UnavailableNvmlCuda()),
    )
    sampler.sample(
        task_id="task-1",
        epoch=1,
        global_step=1,
        total_steps=10,
        batch_size=8,
        device_name="cuda:0",
    )
    runtime = sampler.sample(
        task_id="task-1",
        epoch=1,
        global_step=2,
        total_steps=10,
        batch_size=8,
        device_name="cuda:0",
    )

    assert runtime["step_time_ms"] == 250.0
    assert runtime["samples_per_second"] == 32.0
    assert runtime["gpu_memory_allocated_bytes"] == 2 * 1024**3
    assert "gpu_utilization_percent" not in runtime
