"""转换模型的最小运行时加载、执行与数值一致性门禁。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.service.application.errors import ServiceConfigurationError


def validate_openvino_ir_against_onnx(
    *,
    source_path: Path,
    openvino_model_path: Path,
    build_precision: str,
) -> dict[str, object]:
    """在 CPU 上执行 ONNX 与 OpenVINO，并比较相同输入下的原始输出。"""

    try:
        import numpy as np
        import onnxruntime as ort
        from openvino import Core
    except ImportError as error:
        raise ServiceConfigurationError(
            "OpenVINO runtime smoke 缺少 numpy、onnxruntime 或 openvino 依赖"
        ) from error

    normalized_precision = build_precision.strip().lower()
    if normalized_precision not in {"fp32", "fp16"}:
        raise ServiceConfigurationError(
            "OpenVINO runtime smoke 构建精度必须是 fp32 或 fp16",
            details={"build_precision": build_precision},
        )

    source_session = ort.InferenceSession(
        str(source_path.resolve()),
        providers=["CPUExecutionProvider"],
    )
    source_inputs = source_session.get_inputs()
    if len(source_inputs) != 1:
        raise ServiceConfigurationError(
            "OpenVINO runtime smoke 要求来源 ONNX 只有一个输入",
            details={"input_count": len(source_inputs)},
        )
    source_input = source_inputs[0]
    input_shape = _resolve_runtime_input_shape(source_input.shape)
    input_dtype = _resolve_numpy_input_dtype(source_input.type, np_module=np)
    random_input = (
        np.random.default_rng(0)
        .standard_normal(input_shape)
        .astype(
            input_dtype,
            copy=False,
        )
    )

    compiled_model = Core().compile_model(
        str(openvino_model_path.resolve()),
        "CPU",
        {"INFERENCE_PRECISION_HINT": "f32"},
    )
    if len(compiled_model.inputs) != 1:
        raise ServiceConfigurationError(
            "OpenVINO runtime smoke 要求目标模型只有一个输入",
            details={"input_count": len(compiled_model.inputs)},
        )
    source_outputs = [
        np.asarray(value)
        for value in source_session.run(None, {source_input.name: random_input})
    ]
    output_names = [output.name for output in source_session.get_outputs()]
    if len(compiled_model.outputs) != len(output_names):
        raise ServiceConfigurationError("OpenVINO runtime smoke 输出数量不一致")
    target_result = compiled_model([random_input])
    # 编译器可重排多输出端口；只按名称集合对应，不依赖端口顺序或任意别名。
    try:
        target_outputs = [
            np.asarray(target_result[compiled_model.output(name)])
            for name in output_names
        ]
    except RuntimeError as error:
        raise ServiceConfigurationError(
            "OpenVINO runtime smoke 输出名称与来源 ONNX 不一致"
        ) from error
    import onnx
    from backend.service.application.models.yolo26_core.export.validation_graph import (
        instrument_topk_graph,
        read_topk_contract,
    )

    source_graph = onnx.load(str(source_path))
    topk_contract = read_topk_contract(source_graph)
    if topk_contract is None:
        numeric_summary = summarize_runtime_output_consistency(
            source_outputs=source_outputs,
            target_outputs=target_outputs,
            build_precision=normalized_precision,
            np_module=np,
        )
    else:
        from backend.service.application.models.yolo26_core.export.topk_validation import (
            validate_topk_outputs,
        )

        observed_source = ort.InferenceSession(
            instrument_topk_graph(source_graph, topk_contract).SerializeToString(),
            providers=["CPUExecutionProvider"],
        )
        source_observed_outputs = observed_source.run(
            [*output_names, topk_contract.candidates_name],
            {source_input.name: random_input},
        )
        observed_target_graph = Core().read_model(str(openvino_model_path.resolve()))
        try:
            observed_target_graph.add_outputs(topk_contract.candidates_name)
        except RuntimeError as error:
            raise ServiceConfigurationError(
                "OpenVINO 图丢失 YOLO26 TopK 候选观测张量"
            ) from error
        observed_target = Core().compile_model(
            observed_target_graph,
            "CPU",
            {"INFERENCE_PRECISION_HINT": "f32"},
        )
        observed_result = observed_target([random_input])
        target_observed_outputs = [
            np.asarray(observed_result[observed_target.output(name)])
            for name in output_names
        ]
        target_candidates = np.asarray(
            observed_result[observed_target.output(topk_contract.candidates_name)]
        )
        numeric_summary = validate_topk_outputs(
            source_candidates=source_observed_outputs[-1],
            target_candidates=target_candidates,
            source_outputs=source_outputs,
            target_outputs=target_outputs,
            source_observed_outputs=source_observed_outputs[:-1],
            target_observed_outputs=target_observed_outputs,
            class_count=topk_contract.class_count,
            build_precision=normalized_precision,
            np_module=np,
        )
    if numeric_summary["passed"] is not True:
        raise ServiceConfigurationError(
            "OpenVINO runtime smoke 数值一致性校验失败",
            details=numeric_summary,
        )
    return {
        **numeric_summary,
        "stage": "validate-openvino",
        "source_runtime": "onnxruntime-cpu",
        "target_runtime": "openvino-cpu",
        "input_shape": list(input_shape),
        "input_dtype": str(random_input.dtype),
    }


def summarize_runtime_output_consistency(
    *,
    source_outputs: list[Any],
    target_outputs: list[Any],
    build_precision: str,
    np_module: Any,
) -> dict[str, object]:
    """汇总两个运行时对相同模型原始输出的数值差异。"""

    if not source_outputs or len(source_outputs) != len(target_outputs):
        raise ServiceConfigurationError(
            "运行时 smoke 输出数量不一致",
            details={
                "source_output_count": len(source_outputs),
                "target_output_count": len(target_outputs),
            },
        )
    normalized_precision = build_precision.strip().lower()
    relative_tolerance = 1e-3 if normalized_precision == "fp32" else 2e-2
    absolute_tolerance = 1e-4 if normalized_precision == "fp32" else 5e-3
    finite = True
    allclose = True
    max_abs_diff = 0.0
    mean_abs_diff = 0.0
    for source_output, target_output in zip(
        source_outputs,
        target_outputs,
        strict=True,
    ):
        source_array = np_module.asarray(source_output)
        target_array = np_module.asarray(target_output)
        if tuple(source_array.shape) != tuple(target_array.shape):
            raise ServiceConfigurationError(
                "运行时 smoke 输出 shape 不一致",
                details={
                    "source_shape": list(source_array.shape),
                    "target_shape": list(target_array.shape),
                },
            )
        finite = finite and bool(np_module.isfinite(source_array).all())
        finite = finite and bool(np_module.isfinite(target_array).all())
        if source_array.size:
            absolute_difference = np_module.abs(
                source_array.astype(np_module.float64)
                - target_array.astype(np_module.float64)
            )
            max_abs_diff = max(
                max_abs_diff,
                float(np_module.max(absolute_difference)),
            )
            mean_abs_diff += float(np_module.mean(absolute_difference))
        allclose = allclose and bool(
            np_module.allclose(
                source_array,
                target_array,
                rtol=relative_tolerance,
                atol=absolute_tolerance,
            )
        )
    mean_abs_diff /= len(source_outputs)
    return {
        "passed": finite and allclose,
        "finite": finite,
        "allclose": allclose,
        "output_count": len(source_outputs),
        "max_abs_diff": max_abs_diff,
        "mean_abs_diff": mean_abs_diff,
        "relative_tolerance": relative_tolerance,
        "absolute_tolerance": absolute_tolerance,
    }


def _resolve_runtime_input_shape(raw_shape: list[Any]) -> tuple[int, ...]:
    """把 ONNX Runtime 的动态维度收敛为单样本 smoke shape。"""

    if not raw_shape:
        raise ServiceConfigurationError("运行时 smoke 输入 shape 为空")
    resolved: list[int] = []
    for dimension in raw_shape:
        if isinstance(dimension, int) and dimension > 0:
            resolved.append(dimension)
        else:
            resolved.append(1)
    return tuple(resolved)


def _resolve_numpy_input_dtype(input_type: str, *, np_module: Any) -> Any:
    """把 ONNX Runtime 输入类型映射为 numpy dtype。"""

    normalized = input_type.strip().lower()
    if normalized == "tensor(float)":
        return np_module.float32
    if normalized == "tensor(float16)":
        return np_module.float16
    raise ServiceConfigurationError(
        "运行时 smoke 暂不支持当前 ONNX 输入类型",
        details={"input_type": input_type},
    )


__all__ = [
    "summarize_runtime_output_consistency",
    "validate_openvino_ir_against_onnx",
]
