"""YOLOX ONNX 导出和校验。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.export.onnx_export import (
    TORCH_ONNX_DYNAMO_EXPORTER_MODE,
    TORCH_ONNX_DYNAMO_EXPORTER_OPSET_VERSION,
    export_torch_model_to_onnx,
)
from backend.service.application.models.yolo_core_common.export.execution import (
    validate_yolo_converted_input_tensor,
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
        "input_size": session.runtime_target.model_input_spec.spatial_size.to_payload(),
        "model_input_spec": session.runtime_target.model_input_spec.to_payload(),
        "input_tensor": {
            "name": YOLOX_EXPORT_INPUT_NAMES[0],
            "layout": session.runtime_target.model_input_spec.layout,
            "shape": list(session.runtime_target.model_input_spec.tensor_shape),
            "dtype": session.runtime_target.model_input_spec.dtype,
        },
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
    ort_input = ort_session.get_inputs()[0]
    input_tensor = _build_yolox_input_tensor(
        name=ort_input.name,
        shape=ort_input.shape,
        dtype=ort_input.type,
    )
    validate_yolo_converted_input_tensor(
        input_tensor=input_tensor,
        model_input_spec_payload=session.runtime_target.model_input_spec.to_payload(),
        artifact_format="onnx",
    )
    ort_outputs = ort_session.run(
        None,
        {ort_input.name: dummy_input.detach().cpu().numpy()},
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
    summary["input_tensor"] = input_tensor
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
    initializer_names = {value.name for value in simplified_model.graph.initializer}
    graph_inputs = [
        item
        for item in simplified_model.graph.input
        if item.name not in initializer_names
    ]
    if len(graph_inputs) != 1:
        raise ServiceConfigurationError(
            "YOLOX ONNX 必须且只能包含一个外部输入",
            details={"input_count": len(graph_inputs)},
        )
    graph_input = graph_inputs[0]
    tensor_type = graph_input.type.tensor_type
    input_tensor = _build_yolox_input_tensor(
        name=graph_input.name,
        shape=[
            int(dimension.dim_value) if int(dimension.dim_value) > 0 else -1
            for dimension in tensor_type.shape.dim
        ],
        dtype=onnx_module.TensorProto.DataType.Name(tensor_type.elem_type),
    )
    return {
        "stage": "optimize-onnx",
        "object_uri": output_object_key,
        "source_object_uri": source_object_key,
        "optimizer": "onnxsim",
        "input_tensor": input_tensor,
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


def _build_yolox_input_tensor(
    *,
    name: object,
    shape: object,
    dtype: object,
) -> dict[str, object]:
    """规整 YOLOX 转换产物报告的真实输入张量。"""

    if not isinstance(name, str) or not isinstance(shape, (list, tuple)):
        raise ServiceConfigurationError("YOLOX 转换产物输入张量不完整")
    dtype_aliases = {
        "tensor(float)": "float32",
        "float": "float32",
        "float32": "float32",
    }
    normalized_dtype = dtype_aliases.get(str(dtype).strip().lower())
    if normalized_dtype is None:
        raise ServiceConfigurationError(
            "YOLOX 转换产物输入 dtype 不受支持",
            details={"dtype": str(dtype)},
        )
    return {
        "name": name,
        "layout": "NCHW",
        "shape": [
            int(value) if isinstance(value, int) and not isinstance(value, bool) else -1
            for value in shape
        ],
        "dtype": normalized_dtype,
    }
