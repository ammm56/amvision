"""跨模型共享的训练执行引擎。"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import wraps
import gc
import math
import os
from typing import Any, Callable, ParamSpec, TypeVar, cast

from backend.service.application.errors import InvalidRequestError


_Request = TypeVar("_Request")
_Result = TypeVar("_Result")
_Params = ParamSpec("_Params")


@dataclass(frozen=True)
class TrainingBatchRuntimeResolution:
    """记录一次训练尝试最终使用的 batch 和设备。"""

    batch_size: int
    mode: str
    device_name: str
    target_memory_fraction: float


@dataclass(frozen=True)
class TrainingAmpRuntimeResolution:
    """记录一次训练尝试实际使用的 AMP 配置。"""

    enabled: bool
    precision: str
    device_name: str
    scaler_enabled: bool


@dataclass(frozen=True)
class TrainingOomRecoveryRecord:
    """记录一次首轮 CUDA OOM 降批恢复。"""

    attempt_no: int
    previous_batch_size: int
    next_maximum_batch_size: int


_ACTIVE_TRAINING_ENGINE: ContextVar[TrainingEngine | None] = ContextVar(
    "amvision_active_training_engine",
    default=None,
)


class TrainingEngine:
    """统一管理训练入口、首轮 OOM 恢复和运行时上下文。

    恢复只允许发生在 auto batch、非 resume 且第一个 epoch 尚未完成时。发生
    OOM 后不会继续使用已被部分修改的 model/optimizer，而是重新调用完整训练入口，
    由模型工厂从干净状态重建全部运行时对象。
    """

    def __init__(self, request: Any) -> None:
        """读取公共 batch 恢复策略。"""

        self.original_request = request
        self.original_options = dict(getattr(request, "extra_options", None) or {})
        requested_batch_size = getattr(request, "batch_size", None)
        self.batch_mode = (
            str(
                self.original_options.get(
                    "batch_mode",
                    "fixed" if requested_batch_size is not None else "auto",
                )
            )
            .strip()
            .lower()
        )
        self.recovery_enabled = _read_bool_option(
            self.original_options,
            "batch_recover_on_oom",
            default=True,
        )
        self.maximum_retries = _read_non_negative_int_option(
            self.original_options,
            "batch_oom_max_retries",
            default=3,
        )
        self.minimum_batch_size = _read_positive_int_option(
            self.original_options,
            "batch_minimum_size",
            default=1,
        )
        self.completed_epochs = 0
        self.current_attempt_no = 0
        self.batch_resolution: TrainingBatchRuntimeResolution | None = None
        self.amp_resolution: TrainingAmpRuntimeResolution | None = None
        self.batch_stage_runtime: dict[str, float] = {}
        self.recoveries: list[TrainingOomRecoveryRecord] = []

    def execute(
        self,
        execute_once: Callable[[Any], _Result],
    ) -> _Result:
        """执行训练，并在安全边界内从首轮 CUDA OOM 自动恢复。"""

        current_request = self.original_request
        while True:
            self.current_attempt_no = len(self.recoveries) + 1
            self.completed_epochs = 0
            self.batch_resolution = None
            self.amp_resolution = None
            self.batch_stage_runtime = {}
            tracked_request = self._wrap_epoch_callback(current_request)
            token = _ACTIVE_TRAINING_ENGINE.set(self)
            try:
                result = execute_once(tracked_request)
                return self.attach_runtime_to_result(result)
            except Exception as error:
                if not self._can_recover(error):
                    raise
                resolution = cast(TrainingBatchRuntimeResolution, self.batch_resolution)
                next_maximum = max(
                    self.minimum_batch_size,
                    int(resolution.batch_size) // 2,
                )
                if next_maximum >= resolution.batch_size:
                    raise InvalidRequestError(
                        "AutoBatch 在最小 batch 下仍发生 CUDA OOM",
                        details={
                            "batch_size": resolution.batch_size,
                            "minimum_size": self.minimum_batch_size,
                            "oom_recovery_count": len(self.recoveries),
                        },
                    ) from error
                self.recoveries.append(
                    TrainingOomRecoveryRecord(
                        attempt_no=self.current_attempt_no,
                        previous_batch_size=resolution.batch_size,
                        next_maximum_batch_size=next_maximum,
                    )
                )
                # OOM traceback 会持有完整训练 frame（model、optimizer、batch tensor）。
                # 先断开引用再执行 gc/empty_cache，否则下一次尝试仍会占用失败显存。
                error.__traceback__ = None
                _release_cuda_after_oom()
                current_request = self._build_retry_request(next_maximum)
            finally:
                _ACTIVE_TRAINING_ENGINE.reset(token)
                release_training_runtime_resources()

    def record_batch_resolution(
        self,
        *,
        batch_size: int,
        mode: str,
        device_name: str,
        target_memory_fraction: float,
    ) -> None:
        """记录当前尝试的实际 batch 解析结果。"""

        self.batch_resolution = TrainingBatchRuntimeResolution(
            batch_size=max(1, int(batch_size)),
            mode=str(mode),
            device_name=str(device_name),
            target_memory_fraction=float(target_memory_fraction),
        )

    def runtime_snapshot(self) -> dict[str, object]:
        """返回可直接写入 training.telemetry.v1 的运行时字段。"""

        resolution = self.batch_resolution
        payload: dict[str, object] = {
            "training_engine": "shared-v1",
            "training_attempt": self.current_attempt_no,
            "batch_mode": self.batch_mode,
            "oom_recovery_count": len(self.recoveries),
        }
        if resolution is not None:
            payload.update(
                {
                    "batch_size": resolution.batch_size,
                    "batch_resolution_mode": resolution.mode,
                    "device": resolution.device_name,
                    "batch_target_memory_fraction": (resolution.target_memory_fraction),
                }
            )
        amp_resolution = self.amp_resolution
        if amp_resolution is not None:
            payload.update(
                {
                    "amp_enabled": amp_resolution.enabled,
                    "precision": amp_resolution.precision,
                    "amp_dtype": (
                        amp_resolution.precision if amp_resolution.enabled else None
                    ),
                    "amp_scaler_enabled": amp_resolution.scaler_enabled,
                    "amp_device": amp_resolution.device_name,
                }
            )
        if self.recoveries:
            latest = self.recoveries[-1]
            payload.update(
                {
                    "oom_previous_batch_size": latest.previous_batch_size,
                    "oom_retry_maximum_batch_size": (latest.next_maximum_batch_size),
                }
            )
        payload.update(self.batch_stage_runtime)
        return payload

    def record_amp_resolution(
        self,
        *,
        enabled: bool,
        precision: str,
        device_name: str,
        scaler_enabled: bool,
    ) -> None:
        """记录当前尝试实际采用的 AMP precision。"""

        self.amp_resolution = TrainingAmpRuntimeResolution(
            enabled=bool(enabled),
            precision=str(precision),
            device_name=str(device_name),
            scaler_enabled=bool(scaler_enabled),
        )

    def attach_runtime_to_result(self, result: _Result) -> _Result:
        """把最终实际运行配置附加到统一结果的 metrics payload。"""

        metrics_payload = getattr(result, "metrics_payload", None)
        if not isinstance(metrics_payload, dict):
            return result
        enriched_payload = dict(metrics_payload)
        enriched_payload["training_runtime"] = self.runtime_snapshot()
        try:
            return replace(result, metrics_payload=enriched_payload)
        except TypeError:
            metrics_payload["training_runtime"] = self.runtime_snapshot()
            return result

    def record_batch_stage_metrics(self, metrics: dict[str, float]) -> None:
        """记录当前 batch 的有限、非负阶段耗时。"""

        self.batch_stage_runtime = {
            str(name): round(float(value), 4)
            for name, value in metrics.items()
            if isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) >= 0.0
        }

    def _can_recover(self, error: Exception) -> bool:
        """判断当前失败是否满足首轮自动恢复的全部边界。"""

        resolution = self.batch_resolution
        return bool(
            self.recovery_enabled
            and self.batch_mode == "auto"
            and getattr(self.original_request, "resume_checkpoint_path", None) is None
            and self.completed_epochs == 0
            and len(self.recoveries) < self.maximum_retries
            and resolution is not None
            and resolution.device_name.startswith("cuda")
            and _is_cuda_out_of_memory(error)
        )

    def _wrap_epoch_callback(self, request: Any) -> Any:
        """安装内部 epoch 边界观察器，同时保留原控制 callback。"""

        if not hasattr(request, "epoch_callback"):
            return request
        original_callback = getattr(self.original_request, "epoch_callback", None)

        def tracked_epoch_callback(progress: Any) -> Any:
            self.completed_epochs = max(
                self.completed_epochs,
                _read_completed_epoch(progress),
            )
            return (
                original_callback(progress) if original_callback is not None else None
            )

        return replace(request, epoch_callback=tracked_epoch_callback)

    def _build_retry_request(self, next_maximum: int) -> Any:
        """从原请求构造一次干净重试，避免 callback 包装和内部状态叠加。"""

        options = dict(self.original_options)
        configured_maximum = options.get("batch_maximum_size")
        if isinstance(configured_maximum, int) and not isinstance(
            configured_maximum,
            bool,
        ):
            next_maximum = min(next_maximum, configured_maximum)
        options["batch_maximum_size"] = next_maximum
        options["batch_oom_recovery_attempt"] = len(self.recoveries)
        return replace(self.original_request, extra_options=options)


def training_engine_entrypoint(
    function: Callable[[_Request], _Result],
) -> Callable[[_Request], _Result]:
    """把单 request 训练入口接入共享 TrainingEngine。"""

    @wraps(function)
    def wrapped(request: _Request) -> _Result:
        active = _ACTIVE_TRAINING_ENGINE.get()
        if active is not None:
            return function(request)
        return TrainingEngine(request).execute(function)

    return wrapped


def record_active_training_batch_resolution(
    *,
    batch_size: int,
    mode: str,
    device_name: str,
    target_memory_fraction: float,
) -> None:
    """供各模型 batch resolver 登记实际执行值。"""

    engine = _ACTIVE_TRAINING_ENGINE.get()
    if engine is not None:
        engine.record_batch_resolution(
            batch_size=batch_size,
            mode=mode,
            device_name=device_name,
            target_memory_fraction=target_memory_fraction,
        )


def record_active_training_amp_resolution(
    *,
    enabled: bool,
    precision: str,
    device_name: str,
    scaler_enabled: bool,
) -> None:
    """供 AMP resolver 登记实际执行 precision。"""

    engine = _ACTIVE_TRAINING_ENGINE.get()
    if engine is not None:
        engine.record_amp_resolution(
            enabled=enabled,
            precision=precision,
            device_name=device_name,
            scaler_enabled=scaler_enabled,
        )


def build_execution_training_config_runtime(
    *,
    execution_result: Any,
    requested_batch_size: object,
    requested_precision: object,
    default_batch_size: int,
) -> dict[str, object]:
    """从 TrainingEngine 结果构建训练摘要中的真实运行配置。"""

    metrics_payload = getattr(execution_result, "metrics_payload", None)
    runtime = (
        metrics_payload.get("training_runtime", {})
        if isinstance(metrics_payload, dict)
        else {}
    )
    if not isinstance(runtime, dict):
        runtime = {}
    batch_size = runtime.get("batch_size")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int):
        batch_size = requested_batch_size
    if isinstance(batch_size, bool) or not isinstance(batch_size, int):
        batch_size = int(default_batch_size)
    precision = runtime.get("precision")
    if not isinstance(precision, str) or not precision:
        precision = requested_precision
    if not isinstance(precision, str) or not precision:
        precision = "fp32"
    return {
        "batch_size": max(1, int(batch_size)),
        "precision": precision,
        "batch_resolution_mode": runtime.get("batch_resolution_mode"),
        "amp_enabled": bool(runtime.get("amp_enabled", False)),
        "amp_dtype": runtime.get("amp_dtype"),
        "device": runtime.get("device") or runtime.get("amp_device"),
        "oom_recovery_count": max(0, int(runtime.get("oom_recovery_count", 0))),
    }


def read_active_training_runtime() -> dict[str, object]:
    """供遥测层读取当前训练引擎状态；非训练上下文返回空。"""

    engine = _ACTIVE_TRAINING_ENGINE.get()
    return engine.runtime_snapshot() if engine is not None else {}


def record_active_training_batch_stage_metrics(
    metrics: dict[str, float],
) -> None:
    """供模型训练循环登记低开销 batch 阶段耗时。"""

    engine = _ACTIVE_TRAINING_ENGINE.get()
    if engine is not None:
        engine.record_batch_stage_metrics(metrics)


def _read_completed_epoch(progress: Any) -> int:
    """兼容一基和零基 progress，只需判断是否已有完整 epoch。"""

    value = getattr(progress, "epoch", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return max(1, int(value))
    return 1


def _is_cuda_out_of_memory(error: Exception) -> bool:
    """严格识别 CUDA OOM，避免把主机内存错误误当成可恢复训练错误。"""

    try:
        import torch

        oom_type = getattr(torch.cuda, "OutOfMemoryError", ())
        if oom_type and isinstance(error, oom_type):
            return True
    except ImportError:
        pass
    message = str(error).lower()
    return "out of memory" in message and (
        "cuda" in message or "cublas" in message or "cudnn" in message
    )


def _release_cuda_after_oom() -> None:
    """清理失败尝试的 Python/CUDA 缓存，随后由完整入口重建运行时。"""

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            reset = getattr(torch.cuda, "reset_peak_memory_stats", None)
            if callable(reset):
                reset()
    except (ImportError, RuntimeError):
        return


def release_training_runtime_resources() -> None:
    """在每个训练尝试结束后释放 CUDA、IPC 和 Python 高水位资源。

    训练 worker 是常驻进程。模型、optimizer、DataLoader 或异常 traceback 即使
    已离开业务作用域，也需要显式触发回收；Windows 额外清理当前进程 working
    set，避免多次训练把已释放但仍驻留的页长期计入物理内存。
    """

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            ipc_collect = getattr(torch.cuda, "ipc_collect", None)
            if callable(ipc_collect):
                ipc_collect()
    except (ImportError, RuntimeError):
        pass
    gc.collect()
    if os.name != "nt":
        return
    try:
        import ctypes

        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.argtypes = []
        get_current_process.restype = ctypes.c_void_p
        empty_working_set = ctypes.windll.psapi.EmptyWorkingSet
        empty_working_set.argtypes = [ctypes.c_void_p]
        empty_working_set.restype = ctypes.c_bool
        empty_working_set(get_current_process())
    except (AttributeError, OSError, TypeError, ValueError):
        return


def _read_bool_option(
    options: dict[str, object],
    key: str,
    *,
    default: bool,
) -> bool:
    value = options.get(key, default)
    if not isinstance(value, bool):
        raise InvalidRequestError(f"{key} 必须是布尔值")
    return value


def _read_positive_int_option(
    options: dict[str, object],
    key: str,
    *,
    default: int,
) -> int:
    value = options.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidRequestError(f"{key} 必须是大于 0 的整数")
    return int(value)


def _read_non_negative_int_option(
    options: dict[str, object],
    key: str,
    *,
    default: int,
) -> int:
    value = options.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{key} 必须是大于等于 0 的整数")
    return int(value)


__all__ = [
    "TrainingAmpRuntimeResolution",
    "TrainingBatchRuntimeResolution",
    "TrainingEngine",
    "TrainingOomRecoveryRecord",
    "build_execution_training_config_runtime",
    "read_active_training_runtime",
    "release_training_runtime_resources",
    "record_active_training_amp_resolution",
    "record_active_training_batch_stage_metrics",
    "record_active_training_batch_resolution",
    "training_engine_entrypoint",
]
