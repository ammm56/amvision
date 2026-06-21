"""YOLOX runtime 耗时统计工具。"""

from __future__ import annotations

import sys
from time import perf_counter
from typing import Any

from backend.service.application.runtime.predictors.yolox.backend import ensure_yolox_cuda_success


def measure_yolox_stage_elapsed_ms(*, imports: Any, device_name: str, started_at: float) -> float:
    """测量单个推理阶段的耗时，并在 CUDA 设备上补齐同步边界。

    参数：
    - imports：YOLOX 运行时依赖集合。
    - device_name：当前执行 device 名称。
    - started_at：阶段开始时的 perf_counter 值。

    返回：
    - float：阶段耗时，单位毫秒。
    """

    synchronize_yolox_device_for_timing(imports=imports, device_name=device_name)
    return round((perf_counter() - started_at) * 1000, 3)


def measure_yolox_elapsed_ms(started_at: float) -> float:
    """返回从 started_at 到当前时刻的毫秒耗时。"""

    return round((perf_counter() - started_at) * 1000, 3)


def measure_yolox_cuda_event_elapsed_ms(
    *,
    cudart_module: Any,
    start_event: Any,
    end_event: Any,
    device_name: str,
) -> float | None:
    """返回两个 CUDA event 之间的纯 GPU 执行时间。"""

    try:
        elapsed_ms = ensure_yolox_cuda_success(
            cudart_module.cudaEventElapsedTime(start_event, end_event),
            operation_name="TensorRT runtime 读取执行 event 耗时",
            details={"device_name": device_name},
        )[0]
    except Exception:
        return None
    return round(float(elapsed_ms), 3)


def synchronize_yolox_device_for_timing(*, imports: Any, device_name: str) -> None:
    """在 CUDA 设备上执行同步，确保阶段耗时统计不会被异步 kernel 扰乱。

    参数：
    - imports：YOLOX 运行时依赖集合。
    - device_name：当前执行 device 名称。
    """

    if not device_name.startswith("cuda"):
        return
    torch_module = getattr(imports, "torch", None)
    if torch_module is None or not hasattr(torch_module, "cuda"):
        return
    try:
        torch_module.cuda.synchronize(device_name)
    except Exception:
        return


def is_yolox_debugger_attached() -> bool:
    """返回当前 Python 进程是否挂着调试跟踪器。"""

    try:
        return sys.gettrace() is not None
    except Exception:
        return False
