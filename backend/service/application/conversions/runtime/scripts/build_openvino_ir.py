"""OpenVINO IR 构建子进程脚本。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from backend.service.application.conversions.runtime.scripts.openvino_int8 import quantize_model, validate_ir
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.model_artifact_metadata import (
    attach_openvino_model_artifact_provenance,
)
from backend.service.application.models.model_artifact_runtime_smoke import (
    validate_openvino_ir_against_onnx,
)
from backend.service.domain.models.model_artifact_provenance import (
    build_model_artifact_provenance,
)


def build_openvino_ir(
    *,
    source_path: Path,
    output_path: Path,
    build_precision: str,
    int8_config: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    """把 ONNX 文件转换为 OpenVINO IR。

    参数：
    - source_path：来源 ONNX 文件路径。
    - output_path：目标 OpenVINO XML 文件路径。
    - build_precision：OpenVINO IR 的 fp32、fp16 或 int8 构建精度。
    - int8_config：Worker 解析后的 train 校准和 val 独立校验图片。
    """

    from openvino import convert_model, save_model

    normalized_precision = build_precision.strip().lower()
    if normalized_precision not in {"fp32", "fp16", "int8"}:
        raise ValueError(f"unsupported openvino_ir_precision: {build_precision}")

    resolved_source_path = source_path.resolve()
    resolved_output_path = output_path.resolve()
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    openvino_model = convert_model(str(resolved_source_path))
    model_inputs = list(openvino_model.inputs)
    if len(model_inputs) != 1:
        raise RuntimeError(
            f"converted OpenVINO model must have exactly one input: {len(model_inputs)}"
        )
    model_input = model_inputs[0]
    input_shape = [
        int(dimension.get_length()) if dimension.is_static else -1
        for dimension in model_input.get_partial_shape()
    ]
    input_name = next(iter(model_input.get_names()), model_input.get_any_name())
    # OpenVINO 新版 ``str(Type.f32)`` 会返回 ``<Type: 'float32'>``，
    # 该展示文本不是稳定的跨版本契约。构建摘要统一保存规范类型名。
    input_dtype = str(model_input.get_element_type().get_type_name())
    calibration = {}
    if normalized_precision == "int8":
        if int8_config is None:
            raise ServiceConfigurationError("OpenVINO INT8 Worker 未收到校准配置")
        openvino_model, calibration = quantize_model(openvino_model, int8_config["train"], tuple(input_shape))
    attach_openvino_model_artifact_provenance(
        openvino_model=openvino_model,
        provenance=build_model_artifact_provenance(
            artifact_kind="converted-model",
            trace={"build_format": "openvino-ir"},
        ),
    )
    save_model(
        openvino_model,
        str(resolved_output_path),
        compress_to_fp16=(normalized_precision == "fp16"),
    )
    runtime_smoke = validate_ir(
        source_path=resolved_source_path, output_path=resolved_output_path,
        paths=int8_config["val"], shape=tuple(input_shape),
    ) if int8_config is not None and normalized_precision == "int8" else validate_openvino_ir_against_onnx(
        source_path=resolved_source_path,
        openvino_model_path=resolved_output_path,
        build_precision=normalized_precision,
    )
    return {
        "input_name": input_name,
        "input_shape": input_shape,
        "input_dtype": input_dtype,
        "runtime_smoke": runtime_smoke,
        **({"calibration": calibration} if calibration else {}),
    }


def main() -> None:
    """解析命令行参数并执行 OpenVINO IR 构建。

    参数：
    - 无。

    返回：
    - 无。
    """

    int8_config = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8")) if len(sys.argv) > 4 else None
    try:
        payload = build_openvino_ir(
            source_path=Path(sys.argv[1]),
            output_path=Path(sys.argv[2]),
            build_precision=str(sys.argv[3]),
            int8_config=int8_config,
        )
    except ServiceConfigurationError as error:
        print(json.dumps({"message": str(error), "details": error.details}), flush=True)
        sys.stderr.flush()
        os._exit(1)
    print(json.dumps(payload))


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
    # NNCF 的终端进度含 Unicode 字符，Worker 日志管道在 Windows 上也固定使用 UTF-8。
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
    _exit_successfully()
