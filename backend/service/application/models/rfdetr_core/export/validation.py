"""RF-DETR core 导出处理模块：`export.validation`。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from backend.service.application.errors import ServiceConfigurationError


RFDETR_ONNX_VALIDATION_TOLERANCES: dict[str, tuple[float, float]] = {
    "pred_masks": (1e-2, 1e-1),
}
RFDETR_SEGMENTATION_MEAN_ABS_TOLERANCES: dict[str, float] = {
    "pred_boxes": 1e-1,
    "pred_logits": 5e-2,
    "pred_masks": 5e-1,
}
RFDETR_SEGMENTATION_MEAN_RATIO_TOLERANCES: dict[str, float] = {
    "pred_boxes": 4.5e-1,
    "pred_logits": 2e-1,
    "pred_masks": 3e-1,
}
RFDETR_DETECTION_MEAN_ABS_TOLERANCES: dict[str, float] = {
    "pred_boxes": 1e-1,
    "pred_logits": 1e-1,
}
RFDETR_DETECTION_MEAN_RATIO_TOLERANCES: dict[str, float] = {
    "pred_boxes": 3.5e-1,
    "pred_logits": 5e-2,
}


def build_rfdetr_dummy_input(*, input_height: int, input_width: int) -> torch.Tensor:
    """执行 `build_rfdetr_dummy_input`。
    
    参数：
    - `input_height`：传入的 `input_height` 参数。
    - `input_width`：传入的 `input_width` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    total_values = 3 * input_height * input_width
    return torch.linspace(
        0.0,
        1.0,
        steps=total_values,
        dtype=torch.float32,
    ).reshape(1, 3, input_height, input_width)


def validate_rfdetr_onnx(
    *,
    model: Any,
    dummy_input: torch.Tensor,
    onnx_path: Path,
    onnx_module: object,
    onnxruntime_module: object,
    output_names: tuple[str, ...],
) -> dict[str, object]:
    """执行 `validate_rfdetr_onnx`。
    
    参数：
    - `model`：传入的 `model` 参数。
    - `dummy_input`：传入的 `dummy_input` 参数。
    - `onnx_path`：传入的 `onnx_path` 参数。
    - `onnx_module`：传入的 `onnx_module` 参数。
    - `onnxruntime_module`：传入的 `onnxruntime_module` 参数。
    - `output_names`：传入的 `output_names` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    onnx_model = onnx_module.load(str(onnx_path))
    onnx_module.checker.check_model(onnx_model)

    if not bool(getattr(model, "_export", False)):
        model.export()
    with torch.no_grad():
        torch_outputs = _extract_torch_outputs(
            model_outputs=model(dummy_input),
            output_names=output_names,
        )
    ort_session = onnxruntime_module.InferenceSession(
        str(onnx_path),
        providers=["CPUExecutionProvider"],
    )
    actual_output_names = tuple(output.name for output in ort_session.get_outputs())
    if actual_output_names != output_names:
        raise ServiceConfigurationError(
            "RF-DETR ONNX 输出名与任务要求不一致",
            details={
                "expected_output_names": list(output_names),
                "actual_output_names": list(actual_output_names),
            },
        )
    ort_outputs = ort_session.run(
        list(output_names),
        {ort_session.get_inputs()[0].name: dummy_input.detach().cpu().numpy()},
    )
    summary = summarize_rfdetr_onnx_validation(
        output_names=output_names,
        np_module=__import__("numpy"),
        torch_outputs=torch_outputs,
        ort_outputs=ort_outputs,
    )
    if not bool(summary["accepted"]):
        raise ServiceConfigurationError(
            "RF-DETR ONNX 数值校验失败",
            details=dict(summary),
        )
    return summary


def summarize_rfdetr_onnx_validation(
    *,
    output_names: tuple[str, ...],
    np_module: object,
    torch_outputs: list[object],
    ort_outputs: list[object],
) -> dict[str, object]:
    """执行 `summarize_rfdetr_onnx_validation`。
    
    参数：
    - `output_names`：传入的 `output_names` 参数。
    - `np_module`：传入的 `np_module` 参数。
    - `torch_outputs`：传入的 `torch_outputs` 参数。
    - `ort_outputs`：传入的 `ort_outputs` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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
    strict_allclose = True
    accepted = True
    output_summaries: list[dict[str, object]] = []
    has_mask_output = "pred_masks" in output_names
    for output_name, torch_output, ort_output in zip(
        output_names,
        torch_outputs,
        ort_outputs,
        strict=True,
    ):
        if tuple(torch_output.shape) != tuple(ort_output.shape):
            raise ServiceConfigurationError(
                "ONNX 输出形状与 PyTorch 不一致",
                details={
                    "output_name": output_name,
                    "torch_shape": list(torch_output.shape),
                    "ort_shape": list(ort_output.shape),
                },
            )
        abs_diff = np_module.abs(torch_output - ort_output)
        output_max_abs_diff = float(np_module.max(abs_diff))
        output_mean_abs_diff = float(np_module.mean(abs_diff))
        reference_mean_abs = float(np_module.mean(np_module.abs(torch_output)))
        mean_abs_ratio = output_mean_abs_diff / max(reference_mean_abs, 1e-6)
        rtol, atol = RFDETR_ONNX_VALIDATION_TOLERANCES.get(
            output_name,
            (1e-3, 1e-4),
        )
        output_allclose = bool(
            np_module.allclose(torch_output, ort_output, rtol=rtol, atol=atol)
        )
        mean_abs_tolerance = (
            RFDETR_SEGMENTATION_MEAN_ABS_TOLERANCES.get(output_name)
            if has_mask_output
            else RFDETR_DETECTION_MEAN_ABS_TOLERANCES.get(output_name)
        )
        mean_abs_ratio_tolerance = (
            RFDETR_SEGMENTATION_MEAN_RATIO_TOLERANCES.get(output_name)
            if has_mask_output
            else RFDETR_DETECTION_MEAN_RATIO_TOLERANCES.get(output_name)
        )
        output_accepted = output_allclose or (
            mean_abs_tolerance is not None
            and output_mean_abs_diff <= mean_abs_tolerance
        ) or (
            mean_abs_ratio_tolerance is not None
            and mean_abs_ratio <= mean_abs_ratio_tolerance
        )
        max_abs_diff = max(max_abs_diff, output_max_abs_diff)
        mean_abs_diff += output_mean_abs_diff
        strict_allclose = strict_allclose and output_allclose
        accepted = accepted and output_accepted
        output_summaries.append(
            {
                "output_name": output_name,
                "shape": list(torch_output.shape),
                "allclose": output_allclose,
                "accepted": output_accepted,
                "max_abs_diff": output_max_abs_diff,
                "mean_abs_diff": output_mean_abs_diff,
                "reference_mean_abs": reference_mean_abs,
                "mean_abs_ratio": mean_abs_ratio,
                "rtol": rtol,
                "atol": atol,
                "mean_abs_tolerance": mean_abs_tolerance,
                "mean_abs_ratio_tolerance": mean_abs_ratio_tolerance,
            }
        )

    output_count = len(output_summaries)
    return {
        "stage": "validate-onnx",
        "validation_mode": (
            "segmentation-mean-bound" if has_mask_output else "detection-mean-bound"
        ),
        "allclose": strict_allclose,
        "strict_allclose": strict_allclose,
        "accepted": accepted,
        "max_abs_diff": max_abs_diff,
        "mean_abs_diff": mean_abs_diff / max(1, output_count),
        "output_count": output_count,
        "outputs": output_summaries,
    }


def _extract_torch_outputs(
    *,
    model_outputs: object,
    output_names: tuple[str, ...],
) -> list[object]:
    """执行 `_extract_torch_outputs`。
    
    参数：
    - `model_outputs`：传入的 `model_outputs` 参数。
    - `output_names`：传入的 `output_names` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if isinstance(model_outputs, dict):
        normalized_outputs: list[object] = []
        for output_name in output_names:
            output_tensor = model_outputs.get(output_name)
            if output_tensor is None or not hasattr(output_tensor, "detach"):
                raise ServiceConfigurationError(
                    "RF-DETR 模型输出缺少 ONNX 校验所需字段",
                    details={
                        "output_name": output_name,
                        "available_output_names": sorted(model_outputs.keys()),
                    },
                )
            normalized_outputs.append(output_tensor.detach().cpu().numpy())
        return normalized_outputs
    if isinstance(model_outputs, (list, tuple)):
        normalized_outputs: list[object] = []
        for output_tensor in model_outputs:
            if hasattr(output_tensor, "detach"):
                normalized_outputs.append(output_tensor.detach().cpu().numpy())
        if len(normalized_outputs) == len(output_names):
            return normalized_outputs
    if hasattr(model_outputs, "detach") and len(output_names) == 1:
        return [model_outputs.detach().cpu().numpy()]
    raise ServiceConfigurationError(
        "当前 RF-DETR 模型输出格式不受支持",
        details={
            "output_type": model_outputs.__class__.__name__,
            "expected_output_names": list(output_names),
        },
    )
