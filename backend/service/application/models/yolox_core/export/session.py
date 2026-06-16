"""YOLOX 导出源模型加载入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_core.dependencies import (
    require_yolox_core_dependencies,
)
from backend.service.application.models.yolox_core.models import build_yolox_detection_model
from backend.service.application.models.yolox_core.utils import (
    enable_yolox_cuda_inference_fast_path,
    resolve_yolox_torch_device_name,
)
from backend.service.application.models.yolox_core.weights import load_yolox_warm_start_checkpoint
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot


@dataclass(frozen=True)
class YoloXExportSession:
    """描述一次 YOLOX PyTorch 导出源模型会话。

    字段：
    - runtime_target：导出来源的运行时快照。
    - imports：YOLOX core 依赖集合。
    - model：已经加载 checkpoint 的 YOLOX 模型。
    - device_name：导出时使用的 PyTorch device。
    - runtime_precision：导出来源请求的 precision。
    """

    runtime_target: RuntimeTargetSnapshot
    imports: Any
    model: Any
    device_name: str
    runtime_precision: str


def load_yolox_export_session(*, runtime_target: RuntimeTargetSnapshot) -> YoloXExportSession:
    """加载 YOLOX conversion 使用的 PyTorch 导出源模型。

    参数：
    - runtime_target：转换任务解析出的来源运行时快照。

    返回：
    - YoloXExportSession：已加载 checkpoint 并切到 eval 状态的导出源模型。
    """

    if runtime_target.runtime_backend != "pytorch":
        raise InvalidRequestError(
            "YOLOX 导出源当前只支持 pytorch runtime_backend",
            details={
                "runtime_backend": runtime_target.runtime_backend,
                "model_build_id": runtime_target.model_build_id,
            },
        )

    imports = require_yolox_core_dependencies()
    model = build_yolox_detection_model(
        torch_module=imports.torch,
        model_scale=runtime_target.model_scale,
        num_classes=len(runtime_target.labels),
    )
    load_yolox_warm_start_checkpoint(
        torch_module=imports.torch,
        model=model,
        checkpoint_path=runtime_target.runtime_artifact_path,
        source_summary={
            "source_model_version_id": runtime_target.model_version_id,
            "runtime_artifact_file_id": runtime_target.runtime_artifact_file_id,
            "runtime_artifact_file_type": runtime_target.runtime_artifact_file_type,
            "source_model_build_id": runtime_target.model_build_id,
        },
    )
    device_name = resolve_yolox_torch_device_name(
        torch_module=imports.torch,
        requested_device_name=runtime_target.device_name,
    )
    enable_yolox_cuda_inference_fast_path(
        torch_module=imports.torch,
        device_name=device_name,
    )
    model.to(device_name)
    if runtime_target.runtime_precision == "fp16":
        model.half()
    model.eval()
    return YoloXExportSession(
        runtime_target=runtime_target,
        imports=imports,
        model=model,
        device_name=device_name,
        runtime_precision=runtime_target.runtime_precision,
    )
