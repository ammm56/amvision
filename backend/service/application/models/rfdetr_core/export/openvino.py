"""RF-DETR core 导出处理模块：`export.openvino`。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from backend.service.application.errors import ServiceConfigurationError


def build_rfdetr_openvino_ir(
    *,
    source_path: Path,
    output_path: Path,
    source_object_key: str,
    output_object_key: str,
    build_precision: str,
) -> dict[str, object]:
    """执行 `build_rfdetr_openvino_ir`。
    
    参数：
    - `source_path`：传入的 `source_path` 参数。
    - `output_path`：传入的 `output_path` 参数。
    - `source_object_key`：传入的 `source_object_key` 参数。
    - `output_object_key`：传入的 `output_object_key` 参数。
    - `build_precision`：传入的 `build_precision` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    normalized_precision = build_precision.strip().lower()
    if normalized_precision not in {"fp32", "fp16"}:
        raise ServiceConfigurationError(
            "RF-DETR OpenVINO IR 构建精度必须是 fp32 或 fp16",
            details={"build_precision": build_precision},
        )

    try:
        from openvino import convert_model, save_model
    except ImportError as exc:
        raise ServiceConfigurationError("当前环境缺少 OpenVINO 转换依赖") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    openvino_model = convert_model(str(source_path.resolve()))
    save_model(
        openvino_model,
        str(output_path.resolve()),
        compress_to_fp16=normalized_precision == "fp16",
    )

    weights_path = output_path.with_suffix(".bin")
    if not output_path.is_file() or not weights_path.is_file():
        raise ServiceConfigurationError(
            "RF-DETR OpenVINO IR 构建未生成完整的 xml/bin 产物",
            details={
                "output_object_uri": output_object_key,
                "weights_object_uri": resolve_rfdetr_openvino_weights_object_key(
                    output_object_key
                ),
            },
        )
    return {
        "stage": "build-openvino-ir",
        "object_uri": output_object_key,
        "source_object_uri": source_object_key,
        "weights_object_uri": resolve_rfdetr_openvino_weights_object_key(
            output_object_key
        ),
        "build_precision": normalized_precision,
        "compress_to_fp16": normalized_precision == "fp16",
        "execution_mode": "rfdetr-core-openvino-convert-model",
    }


def resolve_rfdetr_openvino_weights_object_key(output_object_key: str) -> str:
    """执行 `resolve_rfdetr_openvino_weights_object_key`。
    
    参数：
    - `output_object_key`：传入的 `output_object_key` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    path = PurePosixPath(output_object_key)
    return str(path.with_suffix(".bin"))
