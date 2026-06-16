"""YOLOX torch device 解析和 CUDA 推理设置。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError


def resolve_yolox_torch_device_name(*, torch_module: Any, requested_device_name: str) -> str:
    """解析 YOLOX PyTorch 执行使用的 device 名称。

    参数：
    - torch_module：当前导入的 torch 模块。
    - requested_device_name：外部请求的 device 名称。

    返回：
    - str：规范化后的 device 名称。
    """

    if requested_device_name == "cpu":
        return "cpu"
    if requested_device_name == "cuda":
        requested_device_name = "cuda:0"
    if requested_device_name.startswith("cuda:"):
        if not torch_module.cuda.is_available():
            raise InvalidRequestError(
                "当前环境没有可用 CUDA device",
                details={"device_name": requested_device_name},
            )
        raw_index = requested_device_name.split(":", 1)[1]
        if not raw_index.isdigit():
            raise InvalidRequestError(
                "device_name 必须是 cpu、cuda 或 cuda:<index>",
                details={"device_name": requested_device_name},
            )
        device_index = int(raw_index)
        available_count = int(torch_module.cuda.device_count())
        if device_index >= available_count:
            raise InvalidRequestError(
                "请求的 CUDA device 不存在",
                details={
                    "device_name": requested_device_name,
                    "available_gpu_count": available_count,
                },
            )
        return requested_device_name
    raise InvalidRequestError(
        "device_name 必须是 cpu、cuda 或 cuda:<index>",
        details={"device_name": requested_device_name},
    )


def enable_yolox_cuda_inference_fast_path(*, torch_module: Any, device_name: str) -> None:
    """按需打开 YOLOX CUDA 推理常用加速设置。"""

    if not device_name.startswith("cuda"):
        return
    cudnn_module = getattr(torch_module.backends, "cudnn", None)
    if cudnn_module is not None:
        cudnn_module.benchmark = True
    if hasattr(torch_module, "set_float32_matmul_precision"):
        torch_module.set_float32_matmul_precision("high")
