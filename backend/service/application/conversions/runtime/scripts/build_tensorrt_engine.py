"""TensorRT engine 构建子进程脚本。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import sys

from backend.service.application.runtime.support.tensorrt_runtime import (
    prepare_tensorrt_python_runtime,
)
from backend.service.application.errors import ServiceError
from backend.service.application.conversions.runtime.scripts.tensorrt_int8 import (
    make_calibrator,
    validate_int8_engine,
)
from backend.service.domain.models.tensorrt_engine_capabilities import (
    build_single_input_tensorrt_engine_capabilities,
)
from backend.service.domain.models.model_artifact_provenance import (
    MODEL_ARTIFACT_ORIGIN_MARKER,
)


def build_tensorrt_engine(
    *,
    source_path: Path,
    output_path: Path,
    build_precision: str,
    int8_config: dict | None = None,
) -> dict[str, object]:
    """把 ONNX 文件转换为 TensorRT engine。

    参数：
    - source_path：来源 ONNX 文件路径。
    - output_path：目标 TensorRT engine 文件路径。
    - build_precision：TensorRT engine 构建精度策略。
    - int8_config：Worker 校验后的动态 profile 和本地图片路径。

    返回：
    - dict[str, object]：TensorRT engine 构建摘要。
    """

    prepare_tensorrt_python_runtime()
    import tensorrt as trt

    normalized_precision = build_precision.strip().lower()
    if normalized_precision not in {"fp32", "fp16", "int8"}:
        raise ValueError(f"unsupported tensorrt_engine_precision: {build_precision}")
    if (normalized_precision == "int8") != (int8_config is not None):
        raise ValueError("TensorRT INT8 requires a calibration config")

    resolved_source_path = source_path.resolve()
    resolved_output_path = output_path.resolve()

    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network_flags = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    network = builder.create_network(network_flags)
    parser = trt.OnnxParser(network, logger)
    with resolved_source_path.open("rb") as handle:
        parsed = parser.parse(handle.read())
    if not parsed:
        parser_errors = [
            str(parser.get_error(index)) for index in range(parser.num_errors)
        ]
        raise RuntimeError("failed to parse onnx: " + " | ".join(parser_errors))
    network.name = MODEL_ARTIFACT_ORIGIN_MARKER

    input_tensor = network.get_input(0)
    if input_tensor is None:
        raise RuntimeError("parsed TensorRT network missing input tensor")
    input_shape = tuple(int(dim) for dim in input_tensor.shape)

    config = builder.create_builder_config()
    workspace_bytes = (int8_config["workspace_gib"] if int8_config else 1) << 30
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_bytes)
    input_shape_mode = "static"
    minimum_input_shape = input_shape
    optimum_input_shape = input_shape
    maximum_input_shape = input_shape
    calibrator = None
    if int8_config:
        if not hasattr(trt, "IInt8EntropyCalibrator2") or not builder.platform_has_fast_int8:
            raise RuntimeError("当前 TensorRT 或 NVIDIA GPU 不支持校准式 INT8")
        shapes = tuple(tuple(shape) for shape in int8_config["shapes"])
        minimum_input_shape, optimum_input_shape, maximum_input_shape = shapes
        profile = builder.create_optimization_profile()
        profile.set_shape(input_tensor.name, *shapes)
        if config.add_optimization_profile(profile) < 0:
            raise RuntimeError("TensorRT 无法设置动态 INT8 profile")
        if not config.set_calibration_profile(profile):
            raise RuntimeError("TensorRT 无法设置 INT8 校准 profile")
        calibrator = make_calibrator(trt, int8_config["train"], optimum_input_shape)
        config.set_flag(trt.BuilderFlag.INT8)
        config.int8_calibrator = calibrator
        input_shape_mode = "dynamic"
    elif any(dim <= 0 for dim in input_shape):
        if len(input_shape) != 4:
            raise RuntimeError(f"dynamic input shape is not supported: {input_shape}")
        if any(dim <= 0 for dim in input_shape[1:]):
            raise RuntimeError(
                "TensorRT build 目前只支持 batch 维动态，空间维度必须固定",
            )
        fixed_input_shape = tuple(1 if dim <= 0 else dim for dim in input_shape)
        profile = builder.create_optimization_profile()
        profile.set_shape(
            input_tensor.name,
            fixed_input_shape,
            fixed_input_shape,
            fixed_input_shape,
        )
        if config.add_optimization_profile(profile) < 0:
            raise RuntimeError(
                f"failed to create optimization profile for dynamic input shape: {input_shape}"
            )
        input_shape_mode = "dynamic"
        minimum_input_shape = fixed_input_shape
        optimum_input_shape = fixed_input_shape
        maximum_input_shape = fixed_input_shape
    if normalized_precision == "fp16":
        if not builder.platform_has_fast_fp16:
            raise RuntimeError("current TensorRT platform does not support fast fp16")
        config.set_flag(trt.BuilderFlag.FP16)
    elif hasattr(trt.BuilderFlag, "TF32"):
        # fp32 数值门禁使用完整 mantissa，不能把默认 TF32 运算标记成严格 fp32。
        config.clear_flag(trt.BuilderFlag.TF32)

    serialized_engine = builder.build_serialized_network(network, config)
    if calibrator is not None:
        if calibrator.failure is not None:
            raise calibrator.failure
        if calibrator.consumed != len(int8_config["train"]):
            raise RuntimeError("TensorRT 未使用全部校准样本")
    if serialized_engine is None:
        raise RuntimeError("TensorRT build_serialized_network returned None")

    runtime = trt.Runtime(logger)
    runtime_engine = runtime.deserialize_cuda_engine(serialized_engine)
    if runtime_engine is None:
        raise RuntimeError("TensorRT runtime 无法反序列化新构建的 engine")
    execution_context = runtime_engine.create_execution_context()
    if execution_context is None:
        raise RuntimeError("TensorRT runtime 无法创建 execution context")

    from backend.service.application.models.tensorrt_artifact_validation import (
        validate_tensorrt_engine_against_onnx,
    )

    observations: dict[str, object] = {}
    try:
        runtime_smoke = validate_int8_engine(
            source_path=resolved_source_path, engine=runtime_engine, trt=trt,
            paths=int8_config["val"], profile=shapes,
        ) if int8_config else validate_tensorrt_engine_against_onnx(
            source_path=resolved_source_path,
            engine=runtime_engine,
            builder=builder,
            network=network,
            config=config,
            runtime=runtime,
            trt=trt,
            build_precision=normalized_precision,
            observations=observations,
        )
    except Exception as error:
        from backend.service.application.conversions.runtime.numeric_failure_evidence import (
            preserve_conversion_failure,
        )
        from backend.service.application.errors import ServiceConfigurationError
        diagnostic = preserve_conversion_failure(
            source_path=resolved_source_path, output_path=resolved_output_path,
            engine_bytes=serialized_engine, observations=observations, error=error,
            precision=normalized_precision, runtime_version=trt.__version__,
        )
        details = dict(error.details) if isinstance(error, ServiceError) else {}
        details["failure_evidence"] = diagnostic
        raise ServiceConfigurationError(str(error), details=details) from error

    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_bytes(bytes(serialized_engine))
    return {
        "tensorrt_version": trt.__version__,
        "build_precision": normalized_precision,
        "platform": platform.system().lower(),
        "engine_origin_marker": MODEL_ARTIFACT_ORIGIN_MARKER,
        "input_name": input_tensor.name,
        "input_shape": list(input_shape),
        "input_dtype": str(input_tensor.dtype),
        **build_single_input_tensorrt_engine_capabilities(
            input_shape_mode=input_shape_mode,
            input_name=input_tensor.name,
            min_shape=minimum_input_shape,
            opt_shape=optimum_input_shape,
            max_shape=maximum_input_shape,
        ),
        "workspace_bytes": workspace_bytes,
        **({"calibration": {
            "method": "entropy-v2",
            "sample_count": calibrator.consumed,
            "input_shape": list(optimum_input_shape),
        }} if calibrator is not None else {}),
        "engine_file_bytes": resolved_output_path.stat().st_size,
        "runtime_smoke": {
            **runtime_smoke,
            "engine_deserialized": True,
            "execution_context_created": True,
            "runtime": "tensorrt",
        },
    }


def main() -> None:
    """解析命令行参数并执行 TensorRT engine 构建。

    参数：
    - 无。

    返回：
    - 无。
    """

    try:
        payload = build_tensorrt_engine(
            source_path=Path(sys.argv[1]),
            output_path=Path(sys.argv[2]),
            build_precision=str(sys.argv[3]),
            int8_config=json.loads(Path(sys.argv[4]).read_text(encoding="utf-8")) if len(sys.argv) > 4 else None,
        )
    except ServiceError as error:
        # 子进程 traceback 不含 details；保留数值门禁的具体原因供上层诊断。
        print(json.dumps({"error": {
            "code": error.code, "message": error.message, "details": error.details,
        }}, ensure_ascii=True), flush=True)
        raise
    print(json.dumps(payload))


def _exit_successfully() -> None:
    """在成功输出构建摘要后立即结束子进程。

    参数：
    - 无。

    返回：
    - 无。

    说明：
    - conversion builder 运行在一次性隔离子进程中，成功后无需保留解释器收尾逻辑。
    - 直接退出可以避免三方运行时在解释器关闭阶段拖慢父进程等待时间。
    """

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
    _exit_successfully()
