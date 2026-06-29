"""普通 YOLO 训练设备资源解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class YoloTrainingRuntimeResources:
    """描述单机普通 YOLO 训练实际使用的设备资源。"""

    device: str
    gpu_count: int
    device_ids: tuple[int, ...]
    distributed_mode: str
    precision: str


def resolve_yolo_training_runtime_resources(
    *,
    torch_module: Any,
    requested_gpu_count: int | None,
    requested_precision: str | None,
    extra_options: dict[str, object] | None = None,
) -> YoloTrainingRuntimeResources:
    """解析普通 YOLO 训练的 CUDA 设备、GPU 数量和 precision。"""

    options = dict(extra_options or {})
    requested_device = _read_requested_device(options)
    if requested_device == "cpu":
        if requested_gpu_count is not None or "gpu_count" in options:
            raise InvalidRequestError("CPU 训练不能同时指定 gpu_count")
        return YoloTrainingRuntimeResources(
            device="cpu",
            gpu_count=0,
            device_ids=(),
            distributed_mode="single-device",
            precision="fp32",
        )

    cuda_available = bool(torch_module.cuda.is_available())
    if not cuda_available:
        if requested_gpu_count is not None or requested_device in {"cuda"} or str(
            requested_device or ""
        ).startswith("cuda:"):
            raise InvalidRequestError("当前运行环境没有可用 GPU，不能指定 CUDA 训练")
        return YoloTrainingRuntimeResources(
            device="cpu",
            gpu_count=0,
            device_ids=(),
            distributed_mode="single-device",
            precision="fp32",
        )

    available_gpu_count = int(torch_module.cuda.device_count())
    gpu_count = _resolve_gpu_count(
        requested_gpu_count=requested_gpu_count,
        extra_options=options,
    )
    if gpu_count > available_gpu_count:
        raise InvalidRequestError(
            "指定的 gpu_count 超过了本机可用 GPU 数量",
            details={
                "requested_gpu_count": gpu_count,
                "available_gpu_count": available_gpu_count,
            },
        )

    start_device_index = _resolve_start_device_index(requested_device)
    if start_device_index + gpu_count > available_gpu_count:
        raise InvalidRequestError(
            "指定的 device 和 gpu_count 超出了本机可用 GPU 范围",
            details={
                "device": requested_device,
                "requested_gpu_count": gpu_count,
                "available_gpu_count": available_gpu_count,
            },
        )

    if gpu_count > 1:
        raise InvalidRequestError(
            "普通 YOLO 多 GPU 训练必须使用 DDP TrainingBackend，"
            "不再支持单进程 DataParallel",
            details={
                "requested_gpu_count": gpu_count,
                "available_gpu_count": available_gpu_count,
            },
        )

    device_ids = tuple(range(start_device_index, start_device_index + gpu_count))
    runtime_precision = "fp16" if requested_precision == "fp16" else "fp32"
    return YoloTrainingRuntimeResources(
        device=f"cuda:{device_ids[0]}",
        gpu_count=gpu_count,
        device_ids=device_ids,
        distributed_mode="single-device",
        precision=runtime_precision,
    )


def build_yolo_data_parallel_model(
    *,
    torch_module: Any,
    model: Any,
    device_ids: tuple[int, ...],
) -> Any:
    """保留单设备模型返回，禁止继续构建单进程 DataParallel。"""

    if len(device_ids) <= 1:
        return model
    raise InvalidRequestError(
        "普通 YOLO 多 GPU 训练必须通过 DDP 子进程入口执行，"
        "不能再构建 torch.nn.DataParallel",
        details={"device_ids": list(device_ids)},
    )


def _read_requested_device(extra_options: dict[str, object]) -> str | None:
    """读取并校验 extra_options.device。"""

    raw_device = extra_options.get("device")
    if raw_device is None:
        return None
    device = str(raw_device).strip().lower()
    if not device:
        return None
    if device == "cpu" or device == "cuda" or device.startswith("cuda:"):
        return device
    raise InvalidRequestError(
        "device 必须是 cpu、cuda 或 cuda:<index>",
        details={"device": raw_device},
    )


def _resolve_gpu_count(
    *,
    requested_gpu_count: int | None,
    extra_options: dict[str, object],
) -> int:
    """按顶层 gpu_count 优先、extra_options 兜底的规则解析 GPU 数量。"""

    raw_gpu_count = (
        requested_gpu_count
        if requested_gpu_count is not None
        else extra_options.get("gpu_count", 1)
    )
    try:
        gpu_count = int(raw_gpu_count)
    except (TypeError, ValueError) as error:
        raise InvalidRequestError(
            "gpu_count 必须是正整数",
            details={"gpu_count": raw_gpu_count},
        ) from error
    if gpu_count < 1:
        raise InvalidRequestError(
            "gpu_count 必须大于 0",
            details={"gpu_count": raw_gpu_count},
        )
    return gpu_count


def _resolve_start_device_index(requested_device: str | None) -> int:
    """解析 cuda:<index> 的起始设备编号。"""

    if requested_device is None or requested_device == "cuda":
        return 0
    if not requested_device.startswith("cuda:"):
        return 0
    raw_device_index = requested_device.split(":", 1)[1]
    if not raw_device_index.isdigit():
        raise InvalidRequestError(
            "device 必须是 cpu、cuda 或 cuda:<index>",
            details={"device": requested_device},
        )
    return int(raw_device_index)


__all__ = [
    "YoloTrainingRuntimeResources",
    "build_yolo_data_parallel_model",
    "resolve_yolo_training_runtime_resources",
]
