"""RF-DETR core 导出处理模块：`export.onnx_optimize`。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.errors import ServiceConfigurationError


def optimize_rfdetr_onnx_model(
    *,
    source_path: Path,
    optimized_path: Path,
    source_object_key: str,
    output_object_key: str,
    onnx_module: object,
    onnx_simplify: object,
) -> dict[str, object]:
    """执行 `optimize_rfdetr_onnx_model`。
    
    参数：
    - `source_path`：传入的 `source_path` 参数。
    - `optimized_path`：传入的 `optimized_path` 参数。
    - `source_object_key`：传入的 `source_object_key` 参数。
    - `output_object_key`：传入的 `output_object_key` 参数。
    - `onnx_module`：传入的 `onnx_module` 参数。
    - `onnx_simplify`：传入的 `onnx_simplify` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    optimized_path.parent.mkdir(parents=True, exist_ok=True)
    source_model = onnx_module.load(str(source_path))
    simplified_model, check_passed = onnx_simplify(source_model)
    if not check_passed:
        raise ServiceConfigurationError(
            "RF-DETR ONNX simplify 校验失败",
            details={"source_object_uri": source_object_key},
        )
    onnx_module.checker.check_model(simplified_model)
    onnx_module.save(simplified_model, str(optimized_path))
    return {
        "stage": "optimize-onnx",
        "object_uri": output_object_key,
        "source_object_uri": source_object_key,
        "optimizer": "onnxsim",
    }
