"""TensorRT 构建期真实执行与数值门禁，不进入长期推理热路径。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.model_artifact_runtime_smoke import (
    _resolve_numpy_input_dtype,
    _resolve_runtime_input_shape,
    summarize_runtime_output_consistency,
)


def execute_validation_engine(*, engine: Any, trt: Any, image: Any) -> dict[str, Any]:
    """在受控 CUDA stream 上执行全部真实输出，返回独立 CPU 数组。"""
    import numpy as np
    import torch

    context = engine.create_execution_context()
    if context is None:
        raise ServiceConfigurationError("TensorRT 数值验收无法创建 context")
    stream = torch.cuda.Stream()
    buffers: dict[str, Any] = {}
    names = [engine.get_tensor_name(index) for index in range(engine.num_io_tensors)]
    inputs = [
        name for name in names if engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT
    ]
    if len(inputs) != 1:
        raise ServiceConfigurationError("TensorRT 数值验收要求模型只有一个输入")
    input_name = inputs[0]
    if not context.set_input_shape(input_name, tuple(image.shape)):
        raise ServiceConfigurationError("TensorRT 数值验收输入 shape 设置失败")
    try:
        with torch.cuda.stream(stream):
            for name in names:
                dtype = np.dtype(trt.nptype(engine.get_tensor_dtype(name)))
                if name == input_name:
                    value = np.ascontiguousarray(image, dtype=dtype)
                    buffers[name] = torch.from_numpy(value).to("cuda")
                else:
                    shape = tuple(context.get_tensor_shape(name))
                    if any(dim < 1 for dim in shape):
                        raise ServiceConfigurationError(
                            "TensorRT 数值验收输出 shape 尚未解析",
                            details={"name": name, "shape": shape},
                        )
                    torch_dtype = torch.from_numpy(np.empty((), dtype=dtype)).dtype
                    buffers[name] = torch.empty(shape, dtype=torch_dtype, device="cuda")
                if not context.set_tensor_address(name, buffers[name].data_ptr()):
                    raise ServiceConfigurationError("TensorRT 数值验收绑定 buffer 失败")
            if not context.execute_async_v3(stream.cuda_stream):
                raise ServiceConfigurationError("TensorRT 数值验收执行失败")
    finally:
        # 即使绑定或执行失败，也先等待已提交操作，再释放 context 和 buffer。
        stream.synchronize()
    return {
        name: tensor.cpu().numpy().copy()
        for name, tensor in buffers.items()
        if name != input_name
    }


def validate_tensorrt_engine_against_onnx(
    *,
    source_path: Path,
    engine: Any,
    builder: Any,
    network: Any,
    config: Any,
    runtime: Any,
    trt: Any,
    build_precision: str,
) -> dict[str, object]:
    """同时验证正式 engine 和候选观测 engine；不发布带额外输出的调试产物。"""
    import numpy as np
    import onnx
    import onnxruntime as ort
    from backend.service.application.models.yolo26_core.export.validation_graph import (
        instrument_topk_graph,
        read_topk_contract,
    )

    source = ort.InferenceSession(str(source_path), providers=["CPUExecutionProvider"])
    if len(source.get_inputs()) != 1:
        raise ServiceConfigurationError("TensorRT 数值验收要求 ONNX 只有一个输入")
    input_info = source.get_inputs()[0]
    image = (
        np.random.default_rng(0)
        .standard_normal(_resolve_runtime_input_shape(input_info.shape))
        .astype(
            _resolve_numpy_input_dtype(input_info.type, np_module=np),
        )
    )
    source_outputs = source.run(None, {input_info.name: image})
    public_outputs = execute_validation_engine(engine=engine, trt=trt, image=image)
    output_names = [output.name for output in source.get_outputs()]
    target_outputs = [public_outputs[name] for name in output_names]
    graph = onnx.load(str(source_path))
    contract = read_topk_contract(graph)
    if contract is None:
        summary = summarize_runtime_output_consistency(
            source_outputs=source_outputs,
            target_outputs=target_outputs,
            build_precision=build_precision,
            np_module=np,
        )
    else:
        from backend.service.application.models.yolo26_core.export.topk_validation import (
            validate_topk_outputs,
        )

        candidates = [
            network.get_layer(index).get_output(output)
            for index in range(network.num_layers)
            for output in range(network.get_layer(index).num_outputs)
            if network.get_layer(index).get_output(output).name
            == contract.candidates_name
        ]
        if len(candidates) != 1:
            raise ServiceConfigurationError(
                "TensorRT 图丢失唯一的 YOLO26 TopK 候选张量"
            )
        candidate = candidates[0]
        network.mark_output(candidate)
        try:
            observed_bytes = builder.build_serialized_network(network, config)
            if observed_bytes is None:
                raise ServiceConfigurationError("TensorRT 候选观测 engine 构建失败")
            observed_engine = runtime.deserialize_cuda_engine(observed_bytes)
            if observed_engine is None:
                raise ServiceConfigurationError("TensorRT 候选观测 engine 加载失败")
            observed_outputs = execute_validation_engine(
                engine=observed_engine, trt=trt, image=image
            )
        finally:
            network.unmark_output(candidate)
        observed_source = ort.InferenceSession(
            instrument_topk_graph(graph, contract).SerializeToString(),
            providers=["CPUExecutionProvider"],
        )
        source_observed_outputs = observed_source.run(
            [*output_names, contract.candidates_name], {input_info.name: image}
        )
        summary = validate_topk_outputs(
            source_candidates=source_observed_outputs[-1],
            target_candidates=observed_outputs[contract.candidates_name],
            source_outputs=source_outputs,
            target_outputs=target_outputs,
            source_observed_outputs=source_observed_outputs[:-1],
            target_observed_outputs=[observed_outputs[name] for name in output_names],
            class_count=contract.class_count,
            build_precision=build_precision,
            np_module=np,
        )
    if summary["passed"] is not True:
        raise ServiceConfigurationError(
            "TensorRT runtime smoke 数值一致性校验失败", details=summary
        )
    return {
        **summary,
        "stage": "validate-tensorrt",
        "source_runtime": "onnxruntime-cpu",
        "target_runtime": "tensorrt",
        "executed": True,
    }
