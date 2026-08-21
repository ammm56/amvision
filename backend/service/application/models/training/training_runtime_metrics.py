"""训练吞吐量、阶段耗时和 CUDA 资源采样。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Any, Callable


@dataclass
class _TaskRuntimeState:
    """保存一个训练任务的有界运行时计算状态。"""

    started_at: float
    last_observed_at: float
    last_global_step: int
    current_epoch: int | None
    epoch_started_at: float
    last_gpu_sample_at: float = float("-inf")
    cached_gpu_metrics: dict[str, object] = field(default_factory=dict)


class TrainingRuntimeMetricsSampler:
    """根据 batch heartbeat 计算实时性能指标。

    该 sampler 只保存每个活跃 task 的常数级状态。CUDA utilization 最多每秒读取
    一次，显存标量随发布点读取，避免高频调用 NVML 对训练造成明显干扰。
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_tasks: int = 256,
        gpu_sample_interval_seconds: float = 1.0,
        torch_module: Any | None = None,
    ) -> None:
        """初始化有界 sampler。"""

        if max_tasks < 1:
            raise ValueError("max_tasks 必须大于 0")
        if gpu_sample_interval_seconds <= 0:
            raise ValueError("gpu_sample_interval_seconds 必须大于 0")
        self._clock = clock
        self._max_tasks = int(max_tasks)
        self._gpu_sample_interval_seconds = float(gpu_sample_interval_seconds)
        self._torch_module = torch_module
        self._lock = threading.Lock()
        self._states: OrderedDict[str, _TaskRuntimeState] = OrderedDict()

    def sample(
        self,
        *,
        task_id: str,
        epoch: int,
        global_step: int,
        total_steps: int,
        batch_size: int | None,
        device_name: str | None,
    ) -> dict[str, object]:
        """采样一个 batch 完成点并返回有限运行时字段。"""

        now = self._clock()
        with self._lock:
            state = self._states.get(task_id)
            if state is None or global_step <= 1 or global_step < state.last_global_step:
                state = _TaskRuntimeState(
                    started_at=now,
                    last_observed_at=now,
                    last_global_step=max(0, int(global_step) - 1),
                    current_epoch=epoch,
                    epoch_started_at=now,
                )
                self._states[task_id] = state
            self._states.move_to_end(task_id)
            while len(self._states) > self._max_tasks:
                self._states.popitem(last=False)

            if state.current_epoch != epoch:
                state.current_epoch = epoch
                state.epoch_started_at = now

            elapsed = max(0.0, now - state.started_at)
            interval = max(0.0, now - state.last_observed_at)
            step_delta = max(0, int(global_step) - state.last_global_step)
            steps_per_second = (
                float(step_delta) / interval if interval > 0.0 and step_delta > 0 else 0.0
            )
            runtime: dict[str, object] = {
                "elapsed_seconds": round(elapsed, 4),
                "epoch_elapsed_seconds": round(
                    max(0.0, now - state.epoch_started_at),
                    4,
                ),
            }
            if interval > 0.0 and step_delta > 0:
                runtime.update(
                    {
                        "step_time_ms": round(interval * 1000.0 / step_delta, 4),
                        "steps_per_second": round(steps_per_second, 4),
                    }
                )
                if batch_size is not None and batch_size > 0:
                    runtime["samples_per_second"] = round(
                        steps_per_second * int(batch_size),
                        4,
                    )
                remaining_steps = max(0, int(total_steps) - int(global_step))
                if steps_per_second > 0.0:
                    runtime["estimated_remaining_seconds"] = round(
                        remaining_steps / steps_per_second,
                        4,
                    )

            runtime.update(
                self._sample_cuda_metrics(
                    state=state,
                    now=now,
                    device_name=device_name,
                )
            )
            state.last_observed_at = now
            state.last_global_step = int(global_step)
            return _finite_runtime_values(runtime)

    def discard(self, task_id: str) -> None:
        """训练结束后主动释放任务采样状态。"""

        with self._lock:
            self._states.pop(task_id, None)

    def _sample_cuda_metrics(
        self,
        *,
        state: _TaskRuntimeState,
        now: float,
        device_name: str | None,
    ) -> dict[str, object]:
        """读取当前进程 CUDA 显存，并低频读取 utilization。"""

        if not str(device_name or "").startswith("cuda"):
            return {}
        torch_module = self._resolve_torch_module()
        cuda = getattr(torch_module, "cuda", None) if torch_module is not None else None
        if cuda is None:
            return {}
        try:
            cuda_available = bool(getattr(cuda, "is_available", lambda: False)())
        except Exception:
            # CUDA/NVML 是可选遥测源；厂商运行时错误不得丢掉吞吐与耗时字段。
            cuda_available = False
        if not cuda_available:
            return {}
        device = str(device_name)
        metrics: dict[str, object] = {}
        for output_name, reader_name in (
            ("gpu_memory_allocated_bytes", "memory_allocated"),
            ("gpu_memory_reserved_bytes", "memory_reserved"),
            ("gpu_memory_peak_allocated_bytes", "max_memory_allocated"),
        ):
            reader = getattr(cuda, reader_name, None)
            if callable(reader):
                try:
                    metrics[output_name] = int(reader(device))
                except Exception:
                    # 不同 torch/CUDA/NVML 版本会抛出不同 vendor exception。
                    pass
        memory_info = getattr(cuda, "mem_get_info", None)
        if callable(memory_info):
            try:
                free_bytes, total_bytes = memory_info(device)
                total = int(total_bytes)
                free = int(free_bytes)
                metrics["gpu_memory_free_bytes"] = free
                metrics["gpu_memory_total_bytes"] = total
                if total > 0:
                    metrics["gpu_memory_used_percent"] = round(
                        100.0 * max(0, total - free) / total,
                        4,
                    )
            except Exception:
                pass

        if now - state.last_gpu_sample_at >= self._gpu_sample_interval_seconds:
            for output_name, reader_name, transform in (
                ("gpu_utilization_percent", "utilization", float),
                ("gpu_temperature_celsius", "temperature", float),
                ("gpu_power_draw_watts", "power_draw", lambda value: float(value) / 1000.0),
                ("gpu_sm_clock_mhz", "clock_rate", float),
            ):
                reader = getattr(cuda, reader_name, None)
                if not callable(reader):
                    continue
                try:
                    state.cached_gpu_metrics[output_name] = transform(reader(device))
                except Exception:
                    state.cached_gpu_metrics.pop(output_name, None)
            state.last_gpu_sample_at = now
        metrics.update(state.cached_gpu_metrics)
        return metrics

    def _resolve_torch_module(self) -> Any | None:
        """延迟加载 torch，保证 API-only 进程无需为导入付出启动成本。"""

        if self._torch_module is not None:
            return self._torch_module
        try:
            import torch
        except ImportError:
            return None
        self._torch_module = torch
        return torch


def _finite_runtime_values(values: dict[str, object]) -> dict[str, object]:
    """过滤非有限数，维持 telemetry JSON 合同。"""

    result: dict[str, object] = {}
    for name, value in values.items():
        if isinstance(value, bool | str | int) or value is None:
            result[name] = value
        elif isinstance(value, float) and math.isfinite(value):
            result[name] = value
    return result


__all__ = ["TrainingRuntimeMetricsSampler"]
