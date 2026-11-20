"""使用 NNCF 校准 OpenVINO IR，并用独立图片核对导出的 IR。"""

from pathlib import Path
from typing import Any

from backend.service.application.conversions.runtime.scripts.int8_samples import load_detection_tensor
from backend.service.application.errors import ServiceConfigurationError


def quantize_model(model: Any, paths: list[str], shape: tuple[int, ...]) -> tuple[Any, dict[str, object]]:
    """逐张量化固定批次模型，检查量化图确实包含 FakeQuantize。"""
    try:
        import nncf
    except ImportError as error:
        raise ServiceConfigurationError("OpenVINO INT8 Worker 缺少 NNCF") from error
    if not paths or len(shape) != 4 or shape[:2] != (1, 3) or min(shape[2:]) <= 0:
        raise ServiceConfigurationError("OpenVINO INT8 需要静态 NCHW 输入与校准图片")
    calibrated = nncf.quantize(
        model, nncf.Dataset(paths, lambda path: load_detection_tensor(path, shape)),
        subset_size=len(paths), target_device=nncf.TargetDevice.CPU,
        # YOLO11 使用 SiLU，保留非对称激活量化范围。
        preset=nncf.QuantizationPreset.MIXED,
    )
    quantized_ops = sum(op.get_type_name() == "FakeQuantize" for op in calibrated.get_ops())
    if not quantized_ops:
        raise ServiceConfigurationError("NNCF 未生成量化算子")
    return calibrated, {
        "method": "nncf", "preset": "mixed", "sample_count": len(paths), "quantized_ops": quantized_ops,
    }


def validate_ir(
    *, source_path: Path, output_path: Path, paths: list[str], shape: tuple[int, ...],
) -> dict[str, object]:
    """重新加载落盘的 IR，与来源 ONNX 逐张比较坐标和分类分数。"""
    import numpy as np
    import onnxruntime as ort
    from openvino import Core

    if not paths:
        raise ServiceConfigurationError("OpenVINO INT8 需要独立的校验图片")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    source = ort.InferenceSession(str(source_path), sess_options=options, providers=["CPUExecutionProvider"])
    target = Core().compile_model(
        str(output_path), "CPU", {"INFERENCE_PRECISION_HINT": "f32", "INFERENCE_NUM_THREADS": 4},
    )
    input_name = source.get_inputs()[0].name
    output_name = source.get_outputs()[0].name
    if len(source.get_outputs()) != 1 or len(target.outputs) != 1 or output_name not in target.output(0).get_names():
        raise ServiceConfigurationError("OpenVINO INT8 输出名称与 ONNX 不一致")
    height, width = shape[2:]
    scales = (width, height, width, height)
    p99_limit, mean_limit = 0.10, 0.02
    max_errors, mean_errors, dense_max_errors, failures = [], [], [], []
    for path in paths:
        tensor = load_detection_tensor(path, shape)
        expected = source.run([output_name], {input_name: tensor})[0]
        actual = target([tensor])[0]
        if (
            actual.shape != expected.shape or actual.dtype != expected.dtype or actual.ndim != 3
            or actual.shape[1] < 5 or not actual.size
            or not np.isfinite(actual).all() or not np.isfinite(expected).all()
        ):
            raise ServiceConfigurationError("OpenVINO INT8 输出形状、类型或数值无效")
        errors = np.abs(expected.astype(np.float64) - actual.astype(np.float64))
        errors[:, :4, :] /= np.asarray(scales)[None, :, None]
        # 检测头输出含大量密集候选。逐图检查 P99 和均值，并保留单点最大误差。
        percentile_index = min(errors.size - 1, int(errors.size * 0.99))
        percentile = float(np.partition(errors.reshape(-1), percentile_index)[percentile_index])
        mean = float(errors.mean())
        max_errors.append(percentile)
        mean_errors.append(mean)
        dense_max_errors.append(float(errors.max()))
        if percentile > p99_limit or mean > mean_limit:
            flat_index = np.argpartition(errors.reshape(-1), percentile_index)[percentile_index]
            index = tuple(int(part) for part in np.unravel_index(flat_index, errors.shape))
            scale = scales[index[1]] if index[1] < len(scales) else 1
            failures.append({
                "sample_name": Path(path).name, "profile": "static",
                "input_shape": list(shape), "input_dtype": str(tensor.dtype),
                "output_name": output_name, "output_shape": list(actual.shape), "output_dtype": str(actual.dtype),
                "index": list(index), "source_value": float(expected[index]) / scale,
                "target_value": float(actual[index]) / scale, "max_error": percentile, "mean_error": mean,
                "unfiltered_max_error": float(errors.max()),
            })
    summary = {
        "source_runtime": "ONNX Runtime (CPU)", "target_runtime": "OpenVINO INT8 (CPU)",
        "input_kind": "validation_image", "rule": "normalized_error",
        "peak_rule": "p99", "sample_count": len(paths), "check_count": len(paths),
        "max_error_limit": p99_limit, "mean_error_limit": mean_limit,
    }
    if failures:
        raise ServiceConfigurationError(
            "OpenVINO INT8 输出偏差超过校验阈值",
            details={"numeric_validation": {**summary, "failed_check_count": len(failures), "failures": failures[:10]}},
        )
    return {
        **summary, "stage": "validate-openvino", "status": "passed", "passed": True, "validation_sample_count": len(paths),
        "reference": "onnxruntime", "normalization": "box_xywh_divided_by_input_width_height",
        "profiles": {"static": {
            "input_shape": list(shape), "runs": len(paths),
            "max_error": max(max_errors), "mean_error": sum(mean_errors) / len(mean_errors),
            "unfiltered_max_error": max(dense_max_errors),
        }},
    }
