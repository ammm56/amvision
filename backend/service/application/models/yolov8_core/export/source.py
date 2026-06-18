"""YOLOv8 导出源模型会话。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolov8_core.model import build_yolov8_model
from backend.service.application.models.yolov8_core.weights import load_yolov8_checkpoint_file
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloV8ExportImports:
    """YOLOv8 导出源模型需要的 Python 依赖。"""

    np: Any
    torch: Any


class YoloV8ExportSourceSession:
    """供 ONNX/OpenVINO/TensorRT 转换使用的 YOLOv8 PyTorch 源模型会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        imports: YoloV8ExportImports,
        model: Any,
        device_name: str,
        runtime_precision: str,
    ) -> None:
        """初始化 YOLOv8 导出源模型会话。"""

        self.dataset_storage = dataset_storage
        self.runtime_target = runtime_target
        self.imports = imports
        self.model = model
        self.device_name = device_name
        self.runtime_precision = runtime_precision

    @classmethod
    def load(
        cls,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
    ) -> "YoloV8ExportSourceSession":
        """从 RuntimeTargetSnapshot 加载 YOLOv8 导出源模型。"""

        _require_yolov8_export_runtime_target(runtime_target)
        imports = require_yolov8_export_imports()
        model = build_yolov8_model(
            task_type=runtime_target.task_type,
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
            model_config_overrides=_resolve_yolov8_export_model_config(runtime_target),
        )
        load_yolov8_checkpoint_file(
            torch_module=imports.torch,
            model=model,
            checkpoint_path=runtime_target.runtime_artifact_path,
        )
        device_name = resolve_yolov8_export_torch_device_name(
            torch_module=imports.torch,
            requested_device_name=runtime_target.device_name,
        )
        enable_yolov8_export_cuda_fast_path(
            torch_module=imports.torch,
            device_name=device_name,
        )
        model.to(device_name)
        if runtime_target.runtime_precision == "fp16":
            model.half()
        model.eval()
        return cls(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            imports=imports,
            model=model,
            device_name=device_name,
            runtime_precision=runtime_target.runtime_precision,
        )


def require_yolov8_export_imports() -> YoloV8ExportImports:
    """加载 YOLOv8 导出源模型所需依赖。"""

    try:
        import numpy as np
        import torch
    except ImportError as error:
        raise ServiceConfigurationError(
            "当前运行环境缺少 YOLOv8 导出所需的 numpy 或 torch 依赖"
        ) from error
    return YoloV8ExportImports(np=np, torch=torch)


def resolve_yolov8_export_torch_device_name(
    *,
    torch_module: Any,
    requested_device_name: str,
) -> str:
    """解析 YOLOv8 导出源模型使用的 torch device。"""

    requested = requested_device_name.strip().lower()
    if requested in {"", "auto"}:
        return "cuda:0" if torch_module.cuda.is_available() else "cpu"
    if requested == "cuda":
        requested = "cuda:0"
    if requested == "gpu":
        requested = "cuda:0"

    if requested == "cpu":
        return requested
    if requested.startswith("cuda:"):
        if torch_module.cuda.is_available():
            return requested
        raise InvalidRequestError(
            "当前环境没有可用 CUDA，无法使用 YOLOv8 导出 CUDA device",
            details={"device_name": requested_device_name},
        )
    raise InvalidRequestError(
        "YOLOv8 导出 device_name 必须是 auto、cpu、cuda、cuda:<index> 或 gpu",
        details={"device_name": requested_device_name},
    )


def enable_yolov8_export_cuda_fast_path(*, torch_module: Any, device_name: str) -> None:
    """为 YOLOv8 导出源模型开启 CUDA 快路径。"""

    if not device_name.startswith("cuda"):
        return
    backends = getattr(torch_module, "backends", None)
    cudnn = getattr(backends, "cudnn", None)
    if cudnn is not None:
        cudnn.benchmark = True


def _require_yolov8_export_runtime_target(runtime_target: RuntimeTargetSnapshot) -> None:
    """校验 YOLOv8 导出源模型的 RuntimeTargetSnapshot。"""

    if runtime_target.model_type != "yolov8":
        raise InvalidRequestError(
            "YOLOv8 导出源模型只支持 yolov8 model_type",
            details={"model_type": runtime_target.model_type},
        )
    if runtime_target.runtime_backend != "pytorch":
        raise InvalidRequestError(
            "YOLOv8 导出源模型只支持 pytorch runtime_backend",
            details={"runtime_backend": runtime_target.runtime_backend},
        )


def _resolve_yolov8_export_model_config(
    runtime_target: RuntimeTargetSnapshot,
) -> dict[str, object] | None:
    """解析 YOLOv8 导出源模型需要的模型配置。"""

    if runtime_target.task_type != "pose":
        return None
    kpt_shape = runtime_target.model_config.get("kpt_shape")
    if isinstance(kpt_shape, list | tuple) and len(kpt_shape) == 2:
        return {"kpt_shape": (int(kpt_shape[0]), int(kpt_shape[1]))}
    return None


__all__ = [
    "YoloV8ExportImports",
    "YoloV8ExportSourceSession",
    "enable_yolov8_export_cuda_fast_path",
    "require_yolov8_export_imports",
    "resolve_yolov8_export_torch_device_name",
]
