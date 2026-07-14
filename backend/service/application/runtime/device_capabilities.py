"""运行时目标与当前设备环境的可用性检查。"""

from __future__ import annotations

from importlib import import_module, util
import shutil
import subprocess
from typing import Any

from backend.service.application.errors import InvalidRequestError


def validate_runtime_target_available(runtime_target: Any) -> None:
    """校验 runtime target 是否能在当前机器上启动。

    参数：
    - runtime_target：包含 runtime_backend、device_name 等字段的运行时目标快照。

    异常：
    - InvalidRequestError：当前机器缺少目标运行时所需的 NVIDIA CUDA 设备或 TensorRT Python 包。
    """

    runtime_backend = _normalize(getattr(runtime_target, "runtime_backend", ""))
    device_name = _normalize(getattr(runtime_target, "device_name", ""))
    if runtime_backend == "tensorrt":
        _require_nvidia_cuda_device(runtime_backend=runtime_backend, device_name=device_name)
        _require_importable_module(
            package_name="tensorrt",
            message="当前环境未安装 TensorRT Python 运行时，不能启动 TensorRT deployment",
            details={
                "runtime_backend": runtime_backend,
                "device_name": device_name,
            },
        )
    if _is_cuda_device_name(device_name):
        _require_nvidia_cuda_device(runtime_backend=runtime_backend, device_name=device_name)


def _require_nvidia_cuda_device(*, runtime_backend: str, device_name: str) -> None:
    """要求当前机器具备真实 NVIDIA CUDA 设备。"""

    if _has_nvidia_cuda_device():
        return
    raise InvalidRequestError(
        "当前环境未检测到 NVIDIA CUDA 设备，不能启动 CUDA / TensorRT deployment",
        details={
            "runtime_backend": runtime_backend,
            "device_name": device_name,
        },
    )


def _require_importable_module(
    *,
    package_name: str,
    message: str,
    details: dict[str, object],
) -> None:
    """要求指定 Python module 可以正常 import。"""

    available, error_message = _probe_importable_module(package_name)
    if available:
        return
    error_details = dict(details)
    if error_message:
        error_details["import_error"] = error_message
    raise InvalidRequestError(message, details=error_details)


def _probe_importable_module(package_name: str) -> tuple[bool, str | None]:
    """检查 Python module 是否存在且能导入。"""

    if util.find_spec(package_name) is None:
        return False, None
    try:
        import_module(package_name)
    except Exception as error:  # pragma: no cover - 依赖环境异常时才进入
        return False, str(error)
    return True, None


def _has_nvidia_cuda_device() -> bool:
    """返回当前环境是否能看到实际 NVIDIA CUDA 设备。"""

    return _probe_torch_cuda_device_count() > 0 or _probe_nvidia_smi_device_count() > 0


def _probe_torch_cuda_device_count() -> int:
    """通过 torch 探测 CUDA 设备数量；CPU wheel 或导入失败时返回 0。"""

    if util.find_spec("torch") is None:
        return 0
    try:
        torch_module = import_module("torch")
        cuda_module = getattr(torch_module, "cuda", None)
        if cuda_module is None or not bool(cuda_module.is_available()):
            return 0
        return max(0, int(cuda_module.device_count()))
    except Exception:
        return 0


def _probe_nvidia_smi_device_count() -> int:
    """通过 nvidia-smi 探测 NVIDIA GPU 数量。"""

    executable = shutil.which("nvidia-smi")
    if not executable:
        return 0
    try:
        result = subprocess.run(
            [executable, "-L"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return 0
    if result.returncode != 0:
        return 0
    return len([line for line in result.stdout.splitlines() if line.strip()])


def _is_cuda_device_name(device_name: str) -> bool:
    """判断 device_name 是否指向 CUDA。"""

    return device_name == "cuda" or device_name.startswith("cuda:")


def _normalize(value: object) -> str:
    """把输入值归一为小写字符串。"""

    return str(value or "").strip().lower()
