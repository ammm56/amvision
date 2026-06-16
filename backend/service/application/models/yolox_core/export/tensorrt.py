"""YOLOX TensorRT engine 构建。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Callable

from backend.service.application.errors import ServiceConfigurationError


YOLOX_TENSORRT_ENGINE_BUILD_SCRIPT_FILE = "build_tensorrt_engine.py"

ConversionScriptRunner = Callable[..., subprocess.CompletedProcess[str]]


def build_yolox_tensorrt_engine(
    *,
    source_path: Path,
    output_path: Path,
    source_object_key: str,
    output_object_key: str,
    build_precision: str,
    run_conversion_script: ConversionScriptRunner,
) -> dict[str, object]:
    """把 optimized YOLOX ONNX 转换为 TensorRT engine。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed_process = run_conversion_script(
        script_file_name=YOLOX_TENSORRT_ENGINE_BUILD_SCRIPT_FILE,
        args=[
            str(source_path),
            str(output_path),
            build_precision,
        ],
    )
    if completed_process.returncode != 0:
        raise ServiceConfigurationError(
            "TensorRT engine 构建失败",
            details={
                "source_object_uri": source_object_key,
                "output_object_uri": output_object_key,
                "stdout": completed_process.stdout.strip(),
                "stderr": completed_process.stderr.strip(),
            },
        )
    if not output_path.is_file():
        raise ServiceConfigurationError(
            "TensorRT engine 构建未生成 engine 产物",
            details={"output_object_uri": output_object_key},
        )
    build_summary = {
        "stage": "build-tensorrt-engine",
        "object_uri": output_object_key,
        "source_object_uri": source_object_key,
        "build_precision": build_precision,
        "execution_mode": "subprocess-tensorrt-build-engine",
        "engine_file_bytes": output_path.stat().st_size,
    }
    stdout_payload = _parse_last_json_line(completed_process.stdout)
    if stdout_payload is not None:
        build_summary.update(dict(stdout_payload))
    return build_summary


def _parse_last_json_line(stdout: str) -> dict[str, object] | None:
    """从标准输出最后一个非空行解析 JSON 对象。"""

    stdout_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not stdout_lines:
        return None
    try:
        payload = json.loads(stdout_lines[-1])
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return {str(key): value for key, value in payload.items()}
    return None
