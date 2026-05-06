"""TensorRT engine 构建子进程脚本。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import sys


def build_tensorrt_engine(
    *,
    source_path: Path,
    output_path: Path,
    build_precision: str,
) -> dict[str, object]:
    """把 ONNX 文件转换为 TensorRT engine。

    参数：
    - source_path：来源 ONNX 文件路径。
    - output_path：目标 TensorRT engine 文件路径。
    - build_precision：TensorRT engine 构建精度策略；当前支持 fp32 或 fp16。

    返回：
    - dict[str, object]：TensorRT engine 构建摘要。
    """

    import tensorrt as trt

    normalized_precision = build_precision.strip().lower()
    if normalized_precision not in {"fp32", "fp16"}:
        raise ValueError(f"unsupported tensorrt_engine_precision: {build_precision}")

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
        parser_errors = [str(parser.get_error(index)) for index in range(parser.num_errors)]
        raise RuntimeError("failed to parse onnx: " + " | ".join(parser_errors))

    input_tensor = network.get_input(0)
    if input_tensor is None:
        raise RuntimeError("parsed TensorRT network missing input tensor")
    input_shape = tuple(int(dim) for dim in input_tensor.shape)
    if any(dim <= 0 for dim in input_shape):
        raise RuntimeError(f"dynamic input shape is not supported: {input_shape}")

    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1 << 30)
    if normalized_precision == "fp16":
        if not builder.platform_has_fast_fp16:
            raise RuntimeError("current TensorRT platform does not support fast fp16")
        config.set_flag(trt.BuilderFlag.FP16)

    serialized_engine = builder.build_serialized_network(network, config)
    if serialized_engine is None:
        raise RuntimeError("TensorRT build_serialized_network returned None")

    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_bytes(bytes(serialized_engine))
    return {
        "tensorrt_version": trt.__version__,
        "build_precision": normalized_precision,
        "platform": platform.system().lower(),
        "input_name": input_tensor.name,
        "input_shape": list(input_shape),
        "workspace_bytes": 1 << 30,
        "engine_file_bytes": resolved_output_path.stat().st_size,
    }


def main() -> None:
    """解析命令行参数并执行 TensorRT engine 构建。

    参数：
    - 无。

    返回：
    - 无。
    """

    payload = build_tensorrt_engine(
        source_path=Path(sys.argv[1]),
        output_path=Path(sys.argv[2]),
        build_precision=str(sys.argv[3]),
    )
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
