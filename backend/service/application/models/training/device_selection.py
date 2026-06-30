"""训练任务单卡设备选择工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class SingleTrainingDeviceSelection:
    """描述一次单进程训练实际绑定的设备。"""

    device_name: str
    device_index: int | None

    @property
    def is_cuda(self) -> bool:
        """判断当前选择是否为 CUDA 设备。"""

        return self.device_name.startswith("cuda:")

    @property
    def device_ids(self) -> tuple[int, ...]:
        """返回 PyTorch 单进程训练使用的 CUDA id 列表。"""

        if self.device_index is None:
            return ()
        return (self.device_index,)

    @property
    def gpu_count(self) -> int:
        """返回当前单进程训练实际使用的 GPU 数量。"""

        return 1 if self.device_index is not None else 0

    @property
    def lightning_accelerator(self) -> str:
        """返回 PyTorch Lightning accelerator 名称。"""

        return "gpu" if self.is_cuda else "cpu"

    @property
    def lightning_devices(self) -> int | list[int]:
        """返回 PyTorch Lightning devices 参数。"""

        if self.device_index is None:
            return 1
        return [self.device_index]


def resolve_single_training_device(
    *,
    torch_module: Any,
    extra_options: dict[str, object] | None = None,
    requested_device_name: str | None = None,
) -> SingleTrainingDeviceSelection:
    """解析 `cpu`、`cuda`、`cuda:<index>` 或空值对应的单卡训练设备。"""

    raw_value = (
        requested_device_name
        if requested_device_name is not None
        else (extra_options or {}).get("device")
    )
    requested = str(raw_value or "auto").strip().lower()
    if requested in {"", "auto"}:
        if _cuda_is_available(torch_module):
            return _resolve_cuda_training_device(torch_module=torch_module, requested="cuda:0")
        return SingleTrainingDeviceSelection(device_name="cpu", device_index=None)

    if requested == "cpu":
        return SingleTrainingDeviceSelection(device_name="cpu", device_index=None)

    if requested in {"cuda", "gpu"}:
        return _resolve_cuda_training_device(torch_module=torch_module, requested="cuda:0")

    if requested.startswith("cuda:"):
        return _resolve_cuda_training_device(torch_module=torch_module, requested=requested)

    raise InvalidRequestError(
        "训练 device 必须是 auto、cpu、cuda、gpu 或 cuda:<index>",
        details={"device": requested},
    )


def resolve_single_training_device_name(
    *,
    torch_module: Any,
    extra_options: dict[str, object] | None = None,
    requested_device_name: str | None = None,
) -> str:
    """解析并返回单卡训练设备名称。"""

    return resolve_single_training_device(
        torch_module=torch_module,
        extra_options=extra_options,
        requested_device_name=requested_device_name,
    ).device_name


def resolve_torch_amp_device_type(device_name: str) -> str:
    """把 `cuda:<index>` 规整为 PyTorch AMP 需要的 device type。"""

    return "cuda" if str(device_name).startswith("cuda") else "cpu"


def _resolve_cuda_training_device(
    *,
    torch_module: Any,
    requested: str,
) -> SingleTrainingDeviceSelection:
    """校验并返回 CUDA 单卡训练设备。"""

    if not _cuda_is_available(torch_module):
        raise InvalidRequestError(
            "当前运行环境没有可用 CUDA 设备，不能选择 CUDA 训练设备",
            details={"device": requested},
        )

    raw_index = requested.split(":", 1)[1]
    if not raw_index.isdigit():
        raise InvalidRequestError(
            "训练 device 必须是 cuda:<index> 格式",
            details={"device": requested},
        )
    device_index = int(raw_index)
    available_count = int(torch_module.cuda.device_count())
    if device_index >= available_count:
        raise InvalidRequestError(
            "指定的训练 device 超出了本机可用 GPU 范围",
            details={
                "device": requested,
                "available_gpu_count": available_count,
            },
        )
    return SingleTrainingDeviceSelection(
        device_name=f"cuda:{device_index}",
        device_index=device_index,
    )


def _cuda_is_available(torch_module: Any) -> bool:
    """判断当前 torch 模块是否可使用 CUDA。"""

    cuda = getattr(torch_module, "cuda", None)
    return bool(cuda is not None and cuda.is_available())


__all__ = [
    "SingleTrainingDeviceSelection",
    "resolve_single_training_device",
    "resolve_single_training_device_name",
    "resolve_torch_amp_device_type",
]
