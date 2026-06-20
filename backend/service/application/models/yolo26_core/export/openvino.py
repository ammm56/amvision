"""YOLO26 OpenVINO IR 构建入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.service.application.models.yolo_core_common.export import (
    build_yolo_openvino_ir,
)


def build_yolo26_openvino_ir(
    *,
    source_path: Path,
    output_path: Path,
    source_object_key: str,
    output_object_key: str,
    build_precision: str,
    run_conversion_script: Any,
) -> dict[str, object]:
    """把 YOLO26 optimized ONNX 构建为 OpenVINO IR。"""

    return build_yolo_openvino_ir(
        source_path=source_path,
        output_path=output_path,
        source_object_key=source_object_key,
        output_object_key=output_object_key,
        build_precision=build_precision,
        run_conversion_script=run_conversion_script,
    )


__all__ = ["build_yolo26_openvino_ir"]
