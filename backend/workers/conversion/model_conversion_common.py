"""YOLO 系列转换 worker 共享工具。"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot


OPENVINO_IR_PRECISION_OPTION_KEY = "openvino_ir_precision"
TENSORRT_ENGINE_PRECISION_OPTION_KEY = "tensorrt_engine_precision"
SUPPORTED_OPENVINO_IR_BUILD_PRECISIONS = frozenset({"fp32", "fp16"})
SUPPORTED_TENSORRT_ENGINE_BUILD_PRECISIONS = frozenset({"fp32", "fp16"})
_CONVERSION_RUNTIME_BACKEND_BY_TARGET_FORMAT = {
    "onnx": "onnxruntime",
    "onnx-optimized": "onnxruntime",
    "openvino-ir": "openvino",
    "tensorrt-engine": "tensorrt",
    "rknn": "rknn",
}
_CONVERSION_RUNTIME_PRECISIONS_BY_TARGET_FORMAT = {
    "onnx": frozenset({"fp32"}),
    "onnx-optimized": frozenset({"fp32"}),
    "openvino-ir": SUPPORTED_OPENVINO_IR_BUILD_PRECISIONS,
    "tensorrt-engine": SUPPORTED_TENSORRT_ENGINE_BUILD_PRECISIONS,
    "rknn": frozenset({"fp32"}),
}


def resolve_openvino_ir_build_precision(metadata: dict[str, object]) -> str:
    """从 worker metadata 中解析 OpenVINO IR 构建精度策略。"""

    raw_precision = metadata.get(OPENVINO_IR_PRECISION_OPTION_KEY)
    if raw_precision is None:
        return "fp32"
    if isinstance(raw_precision, str):
        normalized_precision = raw_precision.strip().lower()
        if normalized_precision in SUPPORTED_OPENVINO_IR_BUILD_PRECISIONS:
            return normalized_precision
    raise InvalidRequestError(
        "openvino_ir_precision 必须是 fp32 或 fp16",
        details={OPENVINO_IR_PRECISION_OPTION_KEY: raw_precision},
    )


def resolve_tensorrt_engine_build_precision(metadata: dict[str, object]) -> str:
    """从 worker metadata 中解析 TensorRT engine 构建精度策略。"""

    raw_precision = metadata.get(TENSORRT_ENGINE_PRECISION_OPTION_KEY)
    if raw_precision is None:
        return "fp32"
    if isinstance(raw_precision, str):
        normalized_precision = raw_precision.strip().lower()
        if normalized_precision in SUPPORTED_TENSORRT_ENGINE_BUILD_PRECISIONS:
            return normalized_precision
    raise InvalidRequestError(
        "tensorrt_engine_precision 必须是 fp32 或 fp16",
        details={TENSORRT_ENGINE_PRECISION_OPTION_KEY: raw_precision},
    )


def build_conversion_options_metadata(
    *,
    target_formats: tuple[str, ...],
    openvino_ir_build_precision: str,
    tensorrt_engine_build_precision: str,
) -> dict[str, object]:
    """根据目标格式生成转换报告中的附加策略摘要。"""

    metadata: dict[str, object] = {}
    if "openvino-ir" in target_formats:
        metadata[OPENVINO_IR_PRECISION_OPTION_KEY] = openvino_ir_build_precision
    if "tensorrt-engine" in target_formats:
        metadata[TENSORRT_ENGINE_PRECISION_OPTION_KEY] = tensorrt_engine_build_precision
    return metadata


def build_conversion_output_runtime_fields(
    *,
    target_format: str,
    build_precision: str | None = None,
) -> dict[str, str]:
    """生成单个转换输出的明确部署 runtime 字段。"""

    normalized_format = target_format.strip().lower()
    runtime_backend = _CONVERSION_RUNTIME_BACKEND_BY_TARGET_FORMAT.get(normalized_format)
    if runtime_backend is None:
        raise InvalidRequestError(
            "不支持的转换输出格式",
            details={"target_format": target_format},
        )

    supported_precisions = _CONVERSION_RUNTIME_PRECISIONS_BY_TARGET_FORMAT[normalized_format]
    normalized_precision = (build_precision or "fp32").strip().lower()
    if normalized_precision not in supported_precisions:
        raise InvalidRequestError(
            "转换输出 runtime_precision 与目标格式不匹配",
            details={
                "target_format": normalized_format,
                "runtime_precision": normalized_precision,
                "supported_precisions": sorted(supported_precisions),
            },
        )

    return {
        "runtime_backend": runtime_backend,
        "runtime_precision": normalized_precision,
    }


def import_onnx_conversion_dependencies() -> tuple[object, object, object]:
    """导入 ONNX 转换链所需依赖。"""

    try:
        import onnx
        import onnxruntime
        from onnxsim import simplify
    except ImportError as error:
        raise ServiceConfigurationError("当前环境缺少 ONNX phase-1 所需依赖") from error
    return onnx, onnxruntime, simplify


def build_output_base_name(runtime_target: RuntimeTargetSnapshot) -> str:
    """根据来源模型信息构建稳定输出文件名前缀。"""

    model_name = runtime_target.model_name.replace(" ", "-").lower() or "model"
    model_scale = runtime_target.model_scale.strip().lower() or "unknown"
    return f"{model_name}-{model_scale}"


def resolve_conversion_phase(target_formats: tuple[str, ...]) -> str:
    """根据目标格式集合返回当前转换阶段标识。"""

    if "tensorrt-engine" in target_formats:
        return "phase-2-tensorrt-engine"
    if "openvino-ir" in target_formats:
        return "phase-2-openvino-ir"
    return "phase-1-onnx"


def optimize_onnx_model(
    *,
    source_path: Path,
    optimized_path: Path,
    source_object_key: str,
    output_object_key: str,
    onnx_module: object,
    onnx_simplify: object,
) -> dict[str, object]:
    """执行 ONNX simplify 优化并写回独立输出。"""

    optimized_path.parent.mkdir(parents=True, exist_ok=True)
    source_model = onnx_module.load(str(source_path))
    simplified_model, check_passed = onnx_simplify(source_model)
    if not check_passed:
        raise ServiceConfigurationError("ONNX simplify 校验失败")
    onnx_module.checker.check_model(simplified_model)
    onnx_module.save(simplified_model, str(optimized_path))
    return {
        "stage": "optimize-onnx",
        "object_uri": output_object_key,
        "source_object_uri": source_object_key,
        "optimizer": "onnxsim",
    }


def run_conversion_script(
    *,
    script_file_name: str,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """执行 conversion 隔离子进程脚本。"""

    script_path = resolve_conversion_script_path(script_file_name)
    project_root = resolve_conversion_project_root()
    process_env = dict(os.environ)
    python_path_parts = [str(project_root)]
    current_python_path = process_env.get("PYTHONPATH")
    if current_python_path:
        python_path_parts.append(current_python_path)
    process_env["PYTHONPATH"] = os.pathsep.join(python_path_parts)
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(project_root),
        env=process_env,
    )


def resolve_conversion_script_path(script_file_name: str) -> Path:
    """返回 conversion 子进程脚本文件路径。"""

    script_path = Path(__file__).resolve().parent / "scripts" / script_file_name
    if script_path.is_file():
        return script_path
    raise ServiceConfigurationError(
        "conversion 子进程脚本不存在",
        details={"script_path": str(script_path)},
    )


def resolve_conversion_project_root() -> Path:
    """返回 conversion 子进程应使用的项目根目录。"""

    return Path(__file__).resolve().parents[3]


def normalize_model_outputs(model_outputs: object) -> list[object]:
    """把模型输出规整为 numpy 数组列表。"""

    if hasattr(model_outputs, "detach"):
        return [model_outputs.detach().cpu().numpy()]
    if isinstance(model_outputs, (list, tuple)):
        normalized_outputs: list[object] = []
        for item in model_outputs:
            if hasattr(item, "detach"):
                normalized_outputs.append(item.detach().cpu().numpy())
        if normalized_outputs:
            return normalized_outputs
    raise ServiceConfigurationError(
        "当前模型输出格式不受支持",
        details={"output_type": model_outputs.__class__.__name__},
    )


def summarize_numeric_validation(
    *,
    np_module: object,
    torch_outputs: list[object],
    ort_outputs: list[object],
) -> dict[str, object]:
    """计算 PyTorch 与 ONNX 输出的数值差异摘要。"""

    if len(torch_outputs) != len(ort_outputs):
        raise ServiceConfigurationError(
            "ONNX 输出数量与 PyTorch 不一致",
            details={
                "torch_output_count": len(torch_outputs),
                "ort_output_count": len(ort_outputs),
            },
        )
    max_abs_diff = 0.0
    mean_abs_diff = 0.0
    compared_output_count = 0
    for torch_output, ort_output in zip(torch_outputs, ort_outputs, strict=True):
        if tuple(torch_output.shape) != tuple(ort_output.shape):
            raise ServiceConfigurationError(
                "ONNX 输出形状与 PyTorch 不一致",
                details={
                    "torch_shape": list(torch_output.shape),
                    "ort_shape": list(ort_output.shape),
                },
            )
        abs_diff = np_module.abs(torch_output - ort_output)
        max_abs_diff = max(max_abs_diff, float(np_module.max(abs_diff)))
        mean_abs_diff += float(np_module.mean(abs_diff))
        compared_output_count += 1
    mean_abs_diff = mean_abs_diff / max(1, compared_output_count)
    allclose = all(
        bool(np_module.allclose(torch_output, ort_output, rtol=1e-3, atol=1e-4))
        for torch_output, ort_output in zip(torch_outputs, ort_outputs, strict=True)
    )
    return {
        "stage": "validate-onnx",
        "allclose": allclose,
        "max_abs_diff": max_abs_diff,
        "mean_abs_diff": mean_abs_diff,
        "output_count": compared_output_count,
    }
