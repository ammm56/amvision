"""YOLOX OpenVINO IR 构建。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import subprocess
from typing import Callable

from backend.service.application.errors import ServiceConfigurationError


YOLOX_OPENVINO_IR_BUILD_SCRIPT_FILE = "build_openvino_ir.py"

ConversionScriptRunner = Callable[..., subprocess.CompletedProcess[str]]


def build_yolox_openvino_ir(
    *,
    source_path: Path,
    output_path: Path,
    source_object_key: str,
    output_object_key: str,
    build_precision: str,
    run_conversion_script: ConversionScriptRunner,
) -> dict[str, object]:
    """把 optimized YOLOX ONNX 转换为 OpenVINO IR。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    compress_to_fp16 = build_precision == "fp16"
    completed_process = run_conversion_script(
        script_file_name=YOLOX_OPENVINO_IR_BUILD_SCRIPT_FILE,
        args=[
            str(source_path),
            str(output_path),
            build_precision,
        ],
    )
    if completed_process.returncode != 0:
        raise ServiceConfigurationError(
            "OpenVINO IR 构建失败",
            details={
                "source_object_uri": source_object_key,
                "output_object_uri": output_object_key,
                "stdout": completed_process.stdout.strip(),
                "stderr": completed_process.stderr.strip(),
            },
        )

    weights_path = output_path.with_suffix(".bin")
    if not output_path.is_file() or not weights_path.is_file():
        raise ServiceConfigurationError(
            "OpenVINO IR 构建未生成完整的 xml/bin 产物",
            details={
                "output_object_uri": output_object_key,
                "weights_object_uri": resolve_yolox_openvino_weights_object_key(
                    output_object_key
                ),
            },
        )
    return {
        "stage": "build-openvino-ir",
        "object_uri": output_object_key,
        "source_object_uri": source_object_key,
        "weights_object_uri": resolve_yolox_openvino_weights_object_key(output_object_key),
        "build_precision": build_precision,
        "compress_to_fp16": compress_to_fp16,
        "execution_mode": "subprocess-openvino-convert-model",
    }


def resolve_yolox_openvino_weights_object_key(output_object_key: str) -> str:
    """根据 OpenVINO XML object key 推导同名 bin object key。"""

    return PurePosixPath(output_object_key).with_suffix(".bin").as_posix()
