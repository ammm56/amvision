"""YOLOE runtime 环境准备 helper。"""

from __future__ import annotations

import types
from typing import Any

import numpy as np
import torch

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.support.detection import (
    enable_pytorch_cuda_inference_fast_path,
    resolve_execution_device_name,
)


def prepare_runtime_environment(
    *,
    requested_device_name: str,
    precision: str,
    mode_name: str,
) -> tuple[Any, str]:
    """准备 YOLOE runtime 依赖和执行设备。"""

    import cv2

    imports = types.SimpleNamespace(cv2=cv2, np=np, torch=torch)
    resolved_device_name = resolve_execution_device_name(
        torch_module=torch,
        requested_device_name=requested_device_name,
    )
    if precision == "fp16" and not resolved_device_name.startswith("cuda"):
        raise InvalidRequestError(
            f"YOLOE {mode_name} 仅在 CUDA 设备上支持 fp16",
            details={"device": resolved_device_name, "precision": precision},
        )
    enable_pytorch_cuda_inference_fast_path(
        torch_module=torch,
        device_name=resolved_device_name,
    )
    return imports, resolved_device_name


__all__ = ["prepare_runtime_environment"]
