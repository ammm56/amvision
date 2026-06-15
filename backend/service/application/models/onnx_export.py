"""PyTorch 模型 ONNX 导出公共工具。"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Any, Sequence

from backend.service.application.errors import ServiceConfigurationError


TORCH_ONNX_DYNAMO_EXPORTER_MODE = "torch-onnx-dynamo-export"
TORCH_ONNX_DYNAMO_EXPORTER_OPSET_VERSION = 18


def export_torch_model_to_onnx(
    *,
    torch_module: Any,
    model: Any,
    model_args: tuple[Any, ...],
    output_path: Path,
    opset_version: int,
    input_names: Sequence[str],
    output_names: Sequence[str],
) -> None:
    """使用 PyTorch 2.8 dynamo ONNX exporter 导出模型。"""

    ensure_torch_onnx_dynamo_exporter_dependencies()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    progress_stdout = io.StringIO()
    progress_stderr = io.StringIO()
    with contextlib.redirect_stdout(progress_stdout), contextlib.redirect_stderr(progress_stderr):
        torch_module.onnx.export(
            model,
            args=model_args,
            f=str(output_path),
            export_params=True,
            opset_version=opset_version,
            input_names=list(input_names),
            output_names=list(output_names),
            dynamo=True,
            fallback=False,
            optimize=True,
            verify=False,
            report=False,
            external_data=False,
        )


def ensure_torch_onnx_dynamo_exporter_dependencies() -> None:
    """确认 PyTorch 新 ONNX exporter 需要的运行依赖已安装。"""

    try:
        import onnxscript  # noqa: F401
    except ImportError as error:
        raise ServiceConfigurationError(
            "当前环境缺少 PyTorch ONNX 新导出器依赖 onnxscript，请重新安装 requirements.txt"
        ) from error
