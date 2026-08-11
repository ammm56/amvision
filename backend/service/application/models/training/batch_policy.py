"""训练 batch size 运行时解析和 CUDA AutoBatch 探针。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class TrainingBatchResolution:
    """描述训练实际采用的 batch size 和解析来源。"""

    batch_size: int
    mode: str
    target_memory_fraction: float
    probed_batch_sizes: tuple[int, ...] = ()


def resolve_training_batch_size(
    *,
    torch_module: Any,
    model: Any,
    device_name: str,
    input_size: tuple[int, int],
    dataset_size: int,
    requested_batch_size: int | None,
    default_batch_size: int,
    runtime_precision: str,
    extra_options: dict[str, object] | None,
    resume_batch_size: int | None = None,
) -> TrainingBatchResolution:
    """解析固定 batch 或通过 CUDA 实测选择安全 AutoBatch。"""

    def resolved(value: TrainingBatchResolution) -> TrainingBatchResolution:
        """登记共享 TrainingEngine 运行时后返回解析结果。"""

        from backend.service.application.models.training.training_engine import (
            record_active_training_batch_resolution,
        )

        record_active_training_batch_resolution(
            batch_size=value.batch_size,
            mode=value.mode,
            device_name=device_name,
            target_memory_fraction=value.target_memory_fraction,
        )
        return value

    options = dict(extra_options or {})
    mode = str(options.get("batch_mode", "auto")).strip().lower()
    if "batch_mode" not in options and requested_batch_size is not None:
        mode = "fixed"
    if mode not in {"auto", "fixed"}:
        raise InvalidRequestError(
            "batch_mode 必须是 auto 或 fixed",
            details={"batch_mode": mode},
        )

    minimum = _read_positive_int(options, "batch_minimum_size", default=1)
    configured_maximum = _read_optional_positive_int(options, "batch_maximum_size")
    dataset_limit = max(1, int(dataset_size))
    maximum = min(dataset_limit, configured_maximum or 256)
    if maximum < minimum:
        raise InvalidRequestError("AutoBatch maximum 不能小于 minimum")
    fraction = _read_memory_fraction(options)

    if mode == "fixed":
        if requested_batch_size is None:
            raise InvalidRequestError("batch_mode=fixed 时缺少 batch_size")
        fixed = int(requested_batch_size)
        if fixed < minimum or fixed > maximum:
            raise InvalidRequestError(
                "固定 batch_size 超出执行策略范围",
                details={"batch_size": fixed, "minimum": minimum, "maximum": maximum},
            )
        return resolved(TrainingBatchResolution(fixed, "fixed", fraction))

    if resume_batch_size is not None:
        resumed = int(resume_batch_size)
        if resumed < 1:
            raise InvalidRequestError("resume checkpoint 的 batch_size 不合法")
        return resolved(TrainingBatchResolution(resumed, "resume", fraction))

    fallback = min(maximum, max(minimum, int(default_batch_size)))
    if not str(device_name).startswith("cuda"):
        return resolved(
            TrainingBatchResolution(fallback, "auto-cpu-fallback", fraction)
        )

    cuda = getattr(torch_module, "cuda", None)
    if cuda is None or not callable(getattr(cuda, "mem_get_info", None)):
        return resolved(
            TrainingBatchResolution(fallback, "auto-runtime-fallback", fraction)
        )

    free_bytes, _total_bytes = cuda.mem_get_info(device_name)
    allocated_bytes = int(cuda.memory_allocated(device_name))
    parameter_bytes = sum(
        int(parameter.numel()) * int(parameter.element_size())
        for parameter in model.parameters()
    )
    # AdamW 的两个 FP32 moment 在首次 optimizer step 才分配，探针时必须预留。
    optimizer_reserve_bytes = parameter_bytes * 2
    target_peak_bytes = int(
        allocated_bytes + int(free_bytes) * fraction - optimizer_reserve_bytes
    )
    if target_peak_bytes <= allocated_bytes:
        return resolved(
            TrainingBatchResolution(fallback, "auto-memory-fallback", fraction)
        )

    probed: list[int] = []

    def probe(batch_size: int) -> int | None:
        probed.append(int(batch_size))
        return _profile_cuda_training_batch(
            torch_module=torch_module,
            model=model,
            device_name=device_name,
            input_size=input_size,
            batch_size=batch_size,
            runtime_precision=runtime_precision,
        )

    selected = select_largest_safe_batch_size(
        minimum_size=minimum,
        maximum_size=maximum,
        target_peak_bytes=target_peak_bytes,
        probe=probe,
    )
    if selected is None:
        raise InvalidRequestError(
            "AutoBatch 在最小 batch 下仍超出目标显存",
            details={
                "minimum_size": minimum,
                "target_memory_fraction": fraction,
                "probed_batch_sizes": probed,
            },
        )
    return resolved(
        TrainingBatchResolution(
            selected,
            "auto-cuda-profile",
            fraction,
            tuple(probed),
        )
    )


def select_largest_safe_batch_size(
    *,
    minimum_size: int,
    maximum_size: int,
    target_peak_bytes: int,
    probe: Callable[[int], int | None],
) -> int | None:
    """通过倍增和二分探针选择不超过显存目标的最大 batch。"""

    minimum = max(1, int(minimum_size))
    maximum = max(minimum, int(maximum_size))
    best: int | None = None
    low = minimum
    high = maximum + 1
    candidate = minimum

    while candidate <= maximum:
        peak = probe(candidate)
        if peak is None or int(peak) > int(target_peak_bytes):
            high = candidate
            break
        best = candidate
        low = candidate + 1
        if candidate == maximum:
            return candidate
        candidate = min(maximum, candidate * 2)

    while low < high:
        candidate = (low + high) // 2
        peak = probe(candidate)
        if peak is not None and int(peak) <= int(target_peak_bytes):
            best = candidate
            low = candidate + 1
        else:
            high = candidate
    return best


def read_resume_checkpoint_batch_size(
    *,
    torch_module: Any,
    checkpoint_path: Any | None,
) -> int | None:
    """只读取可信内部 checkpoint 的 batch_size，供 AutoBatch resume 复用。"""

    if checkpoint_path is None or not checkpoint_path.is_file():
        return None
    payload = torch_module.load(
        str(checkpoint_path),
        map_location="cpu",
        weights_only=False,
    )
    if not isinstance(payload, dict):
        return None
    value = payload.get("batch_size")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return int(value)


def _profile_cuda_training_batch(
    *,
    torch_module: Any,
    model: Any,
    device_name: str,
    input_size: tuple[int, int],
    batch_size: int,
    runtime_precision: str,
) -> int | None:
    """执行一次无 optimizer step 的 forward/backward 并返回显存峰值。"""

    cuda = torch_module.cuda
    was_training = bool(model.training)
    batch_norm_states: list[tuple[Any, bool]] = []
    try:
        model.train()
        batch_norm_base = getattr(
            getattr(torch_module.nn, "modules", None),
            "batchnorm",
            None,
        )
        batch_norm_type = getattr(batch_norm_base, "_BatchNorm", ())
        for module in model.modules():
            if batch_norm_type and isinstance(module, batch_norm_type):
                batch_norm_states.append((module, bool(module.training)))
                module.eval()
        model.zero_grad(set_to_none=True)
        cuda.empty_cache()
        cuda.reset_peak_memory_stats(device_name)
        height, width = (int(input_size[0]), int(input_size[1]))
        images = torch_module.zeros(
            (int(batch_size), 3, height, width),
            device=device_name,
            dtype=torch_module.float32,
        )
        autocast_context: Any = nullcontext()
        if runtime_precision in {"fp16", "bf16"}:
            autocast_context = torch_module.amp.autocast(
                "cuda",
                dtype=(
                    torch_module.float16
                    if runtime_precision == "fp16"
                    else torch_module.bfloat16
                ),
            )
        with autocast_context:
            outputs = model(images)
            objective = _sum_differentiable_tensors(
                torch_module=torch_module,
                value=outputs,
            )
        if objective is None:
            raise InvalidRequestError("AutoBatch 无法从模型输出构建反向探针")
        objective.backward()
        cuda.synchronize(device_name)
        return int(cuda.max_memory_allocated(device_name))
    except Exception as error:
        if _is_cuda_out_of_memory(torch_module=torch_module, error=error):
            return None
        raise
    finally:
        model.zero_grad(set_to_none=True)
        for module, training in batch_norm_states:
            module.train(training)
        model.train(was_training)
        cuda.empty_cache()


def _sum_differentiable_tensors(*, torch_module: Any, value: Any) -> Any | None:
    """递归汇总模型输出中参与梯度的 tensor。"""

    if isinstance(value, torch_module.Tensor):
        return value.float().mean() if value.requires_grad else None
    if isinstance(value, dict):
        items = value.values()
    elif isinstance(value, list | tuple):
        items = value
    else:
        return None
    result = None
    for item in items:
        tensor_sum = _sum_differentiable_tensors(torch_module=torch_module, value=item)
        if tensor_sum is not None:
            result = tensor_sum if result is None else result + tensor_sum
    return result


def _is_cuda_out_of_memory(*, torch_module: Any, error: Exception) -> bool:
    """判断异常是否为 CUDA OOM。"""

    out_of_memory_error = getattr(getattr(torch_module, "cuda", None), "OutOfMemoryError", ())
    return bool(
        (out_of_memory_error and isinstance(error, out_of_memory_error))
        or "out of memory" in str(error).lower()
    )


def _read_positive_int(options: dict[str, object], key: str, *, default: int) -> int:
    value = options.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidRequestError(f"{key} 必须是大于 0 的整数")
    return int(value)


def _read_optional_positive_int(options: dict[str, object], key: str) -> int | None:
    value = options.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidRequestError(f"{key} 必须是大于 0 的整数或 null")
    return int(value)


def _read_memory_fraction(options: dict[str, object]) -> float:
    value = options.get("batch_target_memory_fraction", 0.6)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidRequestError("batch_target_memory_fraction 必须是数值")
    fraction = float(value)
    if not 0.1 <= fraction <= 0.95:
        raise InvalidRequestError("batch_target_memory_fraction 必须在 0.1 到 0.95 之间")
    return fraction


__all__ = [
    "TrainingBatchResolution",
    "read_resume_checkpoint_batch_size",
    "resolve_training_batch_size",
    "select_largest_safe_batch_size",
]
