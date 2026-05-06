"""OpenVINO IR 构建子进程脚本。"""

from __future__ import annotations

import os
from pathlib import Path
import sys


def build_openvino_ir(*, source_path: Path, output_path: Path, build_precision: str) -> None:
    """把 ONNX 文件转换为 OpenVINO IR。

    参数：
    - source_path：来源 ONNX 文件路径。
    - output_path：目标 OpenVINO XML 文件路径。
    - build_precision：OpenVINO IR 权重压缩策略；当前支持 fp32 或 fp16。
    """

    from openvino import convert_model, save_model

    normalized_precision = build_precision.strip().lower()
    if normalized_precision not in {"fp32", "fp16"}:
        raise ValueError(f"unsupported openvino_ir_precision: {build_precision}")

    resolved_source_path = source_path.resolve()
    resolved_output_path = output_path.resolve()
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    openvino_model = convert_model(str(resolved_source_path))
    save_model(
        openvino_model,
        str(resolved_output_path),
        compress_to_fp16=(normalized_precision == "fp16"),
    )


def main() -> None:
    """解析命令行参数并执行 OpenVINO IR 构建。

    参数：
    - 无。

    返回：
    - 无。
    """

    build_openvino_ir(
        source_path=Path(sys.argv[1]),
        output_path=Path(sys.argv[2]),
        build_precision=str(sys.argv[3]),
    )


def _exit_successfully() -> None:
    """在成功写出产物后立即结束子进程。

    参数：
    - 无。

    返回：
    - 无。

    说明：
    - 当前 Windows/conda 环境下，OpenVINO 子进程在解释器收尾阶段可能长时间不退出。
    - 这里使用 os._exit(0) 绕过收尾阶段，避免父进程长期阻塞在 subprocess.run。
    """

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
    _exit_successfully()
