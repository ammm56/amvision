"""RF-DETR core 导出处理模块：`export._tensorrt`。"""

import argparse
from pathlib import Path
import re
import subprocess
from typing import Any

from backend.service.application.models.rfdetr_core.utilities.logger import get_logger
from backend.service.application.runtime.support.tensorrt_runtime import (
    build_tensorrt_process_environment,
    resolve_trtexec_path,
)
from backend.service.domain.models.tensorrt_engine_capabilities import (
    build_single_input_tensorrt_engine_capabilities,
)
from backend.service.domain.models.model_artifact_provenance import (
    MODEL_ARTIFACT_ORIGIN_MARKER,
)

logger = get_logger()


def run_command(
    command: list[str],
    *,
    dry_run: bool = False,
) -> "subprocess.CompletedProcess[str]":
    """执行 `run_command`。

    参数：
    - `command`：传入的 `command` 参数。
    - `dry_run`：传入的 `dry_run` 参数。

    返回：
    - 当前函数的执行结果。
    """

    display_command = " ".join(f'"{part}"' if " " in part else part for part in command)
    if dry_run:
        logger.info("\n%s\n", display_command)
        return subprocess.CompletedProcess(display_command, 0, "", "")
    try:
        result = subprocess.run(
            command,
            env=build_tensorrt_process_environment(),
            capture_output=True,
            text=True,
            check=True,
        )
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed with exit code {e.returncode}")
        logger.error(f"Error output:\n{e.stderr}")
        raise


def build_tensorrt_engine(
    *,
    onnx_path: str | Path,
    engine_path: str | Path,
    build_precision: str = "fp16",
    dry_run: bool = False,
    verbose: bool = False,
    profile: bool = False,
) -> dict[str, Any]:
    """执行 `build_tensorrt_engine`。

    参数：
    - `onnx_path`：传入的 `onnx_path` 参数。
    - `engine_path`：传入的 `engine_path` 参数。
    - `build_precision`：传入的 `build_precision` 参数。
    - `dry_run`：传入的 `dry_run` 参数。
    - `verbose`：传入的 `verbose` 参数。
    - `profile`：传入的 `profile` 参数。

    返回：
    - 当前函数的执行结果。
    """

    normalized_precision = build_precision.strip().lower()
    if normalized_precision not in {"fp32", "fp16"}:
        raise ValueError(
            f"TensorRT build_precision 必须是 fp32 或 fp16，当前为 {build_precision!r}"
        )

    onnx_file = Path(onnx_path)
    engine_file = Path(engine_path)
    engine_file.parent.mkdir(parents=True, exist_ok=True)
    input_name, input_shape = _read_static_onnx_input(onnx_file)

    trt_command = [
        str(resolve_trtexec_path()),
        f"--onnx={onnx_file}",
        f"--saveEngine={engine_file}",
        "--memPoolSize=workspace:4096",
        "--useCudaGraph",
        "--useSpinWait",
        "--warmUp=500",
        "--avgRuns=1000",
        "--duration=10",
    ]
    if normalized_precision == "fp16":
        trt_command.append("--fp16")
    if verbose:
        trt_command.append("--verbose")
    if profile:
        profile_path = engine_file.with_suffix(".nsys-rep")
        command = [
            "nsys",
            "profile",
            f"--output={profile_path}",
            "--trace=cuda,nvtx",
            "--force-overwrite",
            "true",
            *trt_command,
        ]
        logger.info(f"Profile data will be saved to: {profile_path}")
    else:
        command = trt_command

    output = run_command(command, dry_run=dry_run)
    stats = parse_trtexec_output(output.stdout)
    return {
        "build_precision": normalized_precision,
        "execution_mode": "rfdetr-core-trtexec",
        "engine_origin_marker": MODEL_ARTIFACT_ORIGIN_MARKER,
        "input_name": input_name,
        "input_shape": list(input_shape),
        **build_single_input_tensorrt_engine_capabilities(
            input_shape_mode="static",
            input_name=input_name,
            min_shape=input_shape,
            opt_shape=input_shape,
            max_shape=input_shape,
        ),
        "trtexec_stats": stats,
        "trtexec_stdout": output.stdout,
        "trtexec_stderr": output.stderr,
    }


def _read_static_onnx_input(onnx_path: Path) -> tuple[str, tuple[int, ...]]:
    """读取 RF-DETR ONNX 主输入，并确保当前 trtexec 路径只接收静态 shape。"""

    import onnx

    model = onnx.load(str(onnx_path), load_external_data=False)
    initializer_names = {initializer.name for initializer in model.graph.initializer}
    inputs = [
        value_info
        for value_info in model.graph.input
        if value_info.name not in initializer_names
    ]
    if len(inputs) != 1:
        raise RuntimeError(
            f"RF-DETR TensorRT 构建要求一个模型输入，当前为 {len(inputs)} 个"
        )
    input_value = inputs[0]
    dimensions: list[int] = []
    for dimension in input_value.type.tensor_type.shape.dim:
        if dimension.HasField("dim_value") and int(dimension.dim_value) > 0:
            dimensions.append(int(dimension.dim_value))
            continue
        raise RuntimeError(
            "RF-DETR TensorRT 构建检测到动态输入，但当前 trtexec 路径未定义 "
            "optimization profile"
        )
    if not input_value.name or not dimensions:
        raise RuntimeError("RF-DETR ONNX 主输入缺少名称或 shape")
    return input_value.name, tuple(dimensions)


def trtexec(onnx_dir: str, args: argparse.Namespace) -> None:
    engine_dir = onnx_dir.replace(".onnx", ".engine")

    trt_command = [
        str(resolve_trtexec_path()),
        f"--onnx={onnx_dir}",
        f"--saveEngine={engine_dir}",
        "--memPoolSize=workspace:4096",
        "--fp16",
        "--useCudaGraph",
        "--useSpinWait",
        "--warmUp=500",
        "--avgRuns=1000",
        "--duration=10",
    ]
    if args.verbose:
        trt_command.append("--verbose")

    if args.profile:
        profile_dir = onnx_dir.replace(".onnx", ".nsys-rep")
        command = [
            "nsys",
            "profile",
            f"--output={profile_dir}",
            "--trace=cuda,nvtx",
            "--force-overwrite",
            "true",
            *trt_command,
        ]
        logger.info(f"Profile data will be saved to: {profile_dir}")
    else:
        command = trt_command

    output = run_command(command, dry_run=args.dry_run)
    parse_trtexec_output(output.stdout)


def parse_trtexec_output(output_text: str) -> dict[str, Any]:
    logger.info(output_text)
    gpu_compute_pattern = r"GPU Compute Time: min = (\d+\.\d+) ms, max = (\d+\.\d+) ms, mean = (\d+\.\d+) ms, median = (\d+\.\d+) ms"
    h2d_pattern = r"Host to Device Transfer Time: min = (\d+\.\d+) ms, max = (\d+\.\d+) ms, mean = (\d+\.\d+) ms"
    d2h_pattern = r"Device to Host Transfer Time: min = (\d+\.\d+) ms, max = (\d+\.\d+) ms, mean = (\d+\.\d+) ms"
    latency_pattern = (
        r"Latency: min = (\d+\.\d+) ms, max = (\d+\.\d+) ms, mean = (\d+\.\d+) ms"
    )
    throughput_pattern = r"Throughput: (\d+\.\d+) qps"

    stats: dict[str, Any] = {}

    if match := re.search(gpu_compute_pattern, output_text):
        stats.update(
            {
                "compute_min_ms": float(match.group(1)),
                "compute_max_ms": float(match.group(2)),
                "compute_mean_ms": float(match.group(3)),
                "compute_median_ms": float(match.group(4)),
            }
        )

    if match := re.search(h2d_pattern, output_text):
        stats.update(
            {
                "h2d_min_ms": float(match.group(1)),
                "h2d_max_ms": float(match.group(2)),
                "h2d_mean_ms": float(match.group(3)),
            }
        )

    if match := re.search(d2h_pattern, output_text):
        stats.update(
            {
                "d2h_min_ms": float(match.group(1)),
                "d2h_max_ms": float(match.group(2)),
                "d2h_mean_ms": float(match.group(3)),
            }
        )

    if match := re.search(latency_pattern, output_text):
        stats.update(
            {
                "latency_min_ms": float(match.group(1)),
                "latency_max_ms": float(match.group(2)),
                "latency_mean_ms": float(match.group(3)),
            }
        )

    if match := re.search(throughput_pattern, output_text):
        stats["throughput_qps"] = float(match.group(1))

    return stats
