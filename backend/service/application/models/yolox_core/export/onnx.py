"""YOLOX ONNX 导出和校验。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.export.onnx_export import (
    TORCH_ONNX_DYNAMO_EXPORTER_MODE,
    TORCH_ONNX_DYNAMO_EXPORTER_OPSET_VERSION,
    export_torch_model_to_onnx,
)


YOLOX_EXPORT_INPUT_NAMES = ("images",)
YOLOX_EXPORT_OUTPUT_NAMES = ("predictions",)
YOLOX_ONNX_EXPORTER_MODE = TORCH_ONNX_DYNAMO_EXPORTER_MODE
YOLOX_ONNX_EXPORT_OPSET_VERSION = TORCH_ONNX_DYNAMO_EXPORTER_OPSET_VERSION


def export_yolox_onnx(
    *,
    session: object,
    output_path: Path,
    output_object_key: str,
) -> dict[str, object]:
    """把 YOLOX PyTorch checkpoint 导出为 ONNX。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dummy_input = _build_yolox_dummy_input(session=session)
    with session.imports.torch.no_grad():
        export_torch_model_to_onnx(
            torch_module=session.imports.torch,
            model=session.model,
            model_args=(dummy_input,),
            output_path=output_path,
            opset_version=YOLOX_ONNX_EXPORT_OPSET_VERSION,
            input_names=YOLOX_EXPORT_INPUT_NAMES,
            output_names=YOLOX_EXPORT_OUTPUT_NAMES,
        )
    return {
        "stage": "export-onnx",
        "object_uri": output_object_key,
        "opset_version": YOLOX_ONNX_EXPORT_OPSET_VERSION,
        "input_size": list(session.runtime_target.input_size),
        "exporter_mode": YOLOX_ONNX_EXPORTER_MODE,
        "input_names": list(YOLOX_EXPORT_INPUT_NAMES),
        "output_names": list(YOLOX_EXPORT_OUTPUT_NAMES),
    }


def validate_yolox_onnx(
    *,
    session: object,
    onnx_path: Path,
    onnx_module: object,
    onnxruntime_module: object,
) -> dict[str, object]:
    """校验 YOLOX ONNX 文件合法性并和 PyTorch 输出做数值对比。"""

    onnx_model = onnx_module.load(str(onnx_path))
    onnx_module.checker.check_model(onnx_model)

    dummy_input = _build_yolox_dummy_input(session=session)
    with session.imports.torch.no_grad():
        torch_outputs = normalize_yolox_export_model_outputs(session.model(dummy_input))
    ort_session = onnxruntime_module.InferenceSession(
        str(onnx_path),
        providers=["CPUExecutionProvider"],
    )
    ort_outputs = ort_session.run(
        None,
        {ort_session.get_inputs()[0].name: dummy_input.detach().cpu().numpy()},
    )
    summary = summarize_yolox_onnx_numeric_validation(
        np_module=session.imports.np,
        torch_outputs=torch_outputs,
        ort_outputs=ort_outputs,
    )
    if not bool(summary["allclose"]):
        raise ServiceConfigurationError(
            "ONNX 数值校验失败",
            details=dict(summary),
        )
    return summary


def optimize_yolox_onnx(
    *,
    source_path: Path,
    optimized_path: Path,
    source_object_key: str,
    output_object_key: str,
    onnx_module: object,
    onnx_simplify: object,
) -> dict[str, object]:
    """执行 YOLOX ONNX simplify 优化并写回独立输出。"""

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


def normalize_yolox_export_model_outputs(model_outputs: object) -> list[object]:
    """把 YOLOX PyTorch 输出规整为 numpy 数组列表。"""

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


def summarize_yolox_onnx_numeric_validation(
    *,
    np_module: object,
    torch_outputs: list[object],
    ort_outputs: list[object],
) -> dict[str, object]:
    """计算 YOLOX PyTorch 与 ONNX 输出的数值差异摘要。"""

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


def _build_yolox_dummy_input(*, session: object) -> object:
    """按 runtime target 尺寸创建 YOLOX ONNX 导出输入。"""

    return session.imports.torch.randn(
        1,
        3,
        session.runtime_target.input_size[0],
        session.runtime_target.input_size[1],
        device=session.device_name,
        dtype=session.imports.torch.float32,
    )
