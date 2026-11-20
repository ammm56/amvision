"""TensorRT 动态 INT8 校准及真实图片校验。"""

from pathlib import Path
from typing import Any

from backend.service.application.conversions.runtime.scripts.int8_samples import load_detection_tensor as _load_image
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.tensorrt_artifact_validation import execute_validation_engine

_MAX_NORMALIZED_ERROR = 0.20
_MEAN_NORMALIZED_ERROR = 0.02


def make_calibrator(trt: Any, paths: list[str], shape: tuple[int, ...]) -> Any:
    """在 opt 尺寸逐张校准，并保留设备缓冲区直到构建结束。"""
    import torch

    class Calibrator(trt.IInt8EntropyCalibrator2):
        """TensorRT 调用的校准数据源。"""

        def __init__(self) -> None:
            super().__init__()
            self.buffer = torch.empty(shape, dtype=torch.float32, device="cuda")
            self.consumed = 0
            self.failure: Exception | None = None

        def get_batch_size(self) -> int:
            return 1

        def get_batch(self, names: list[str]) -> list[int] | None:
            if self.failure is not None or self.consumed >= len(paths):
                return None
            try:
                self.buffer.copy_(torch.from_numpy(_load_image(paths[self.consumed], shape)))
                torch.cuda.synchronize()
                self.consumed += 1
                return [self.buffer.data_ptr()]
            except Exception as error:
                self.failure = error
                return None

        def read_calibration_cache(self) -> None:
            return None

        def write_calibration_cache(self, cache: bytes) -> None:
            """每次构建从当前样本校准，不将缓存作为产物保存。"""

    return Calibrator()


def validate_int8_engine(
    *, engine: Any, trt: Any, source_path: Path, paths: list[str],
    profile: tuple[tuple[int, ...], ...],
) -> dict[str, object]:
    """校验所有 val 图片及 profile 两端，记录归一化坐标及分数偏差。"""
    import numpy as np
    import onnxruntime as ort

    session = ort.InferenceSession(str(source_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    actual_profile = tuple(tuple(shape) for shape in engine.get_tensor_profile_shape(input_name, 0))
    if actual_profile != profile:
        raise ServiceConfigurationError("TensorRT engine profile 与请求不一致")
    if not paths:
        raise ServiceConfigurationError("TensorRT INT8 数值校验需要验证图片")
    cases = [("opt", profile[1], path) for path in paths]
    cases += [("min", profile[0], paths[0]), ("max", profile[2], paths[0])]
    results: dict[str, list[dict[str, object]]] = {"min": [], "opt": [], "max": []}
    failures: list[dict[str, object]] = []
    for label, shape, path in cases:
        image = _load_image(path, shape)
        expected = session.run([output_name], {input_name: image})[0]
        actual = execute_validation_engine(engine=engine, trt=trt, image=image)[output_name]
        if (
            actual.shape != expected.shape or actual.dtype != expected.dtype
            or actual.ndim != 3 or actual.shape[1] < 5 or not actual.size
            or not np.isfinite(actual).all() or not np.isfinite(expected).all()
        ):
            raise ServiceConfigurationError("TensorRT INT8 输出形状、类型或数值无效")
        error = np.abs(expected.astype(np.float64) - actual.astype(np.float64))
        height, width = shape[2:]
        scales = (width, height, width, height)
        error[:, :4, :] /= np.asarray(scales)[None, :, None]
        maximum, mean = float(error.max()), float(error.mean())
        if maximum > _MAX_NORMALIZED_ERROR or mean > _MEAN_NORMALIZED_ERROR:
            index = tuple(int(part) for part in np.unravel_index(error.argmax(), error.shape))
            scale = scales[index[1]] if index[1] < len(scales) else 1
            failures.append({
                "sample_name": Path(path).name,
                "profile": label,
                "input_shape": list(shape),
                "input_dtype": str(image.dtype),
                "output_name": output_name,
                "output_shape": list(error.shape),
                "output_dtype": str(expected.dtype),
                "index": list(index),
                "source_value": float(expected[index]) / scale,
                "target_value": float(actual[index]) / scale,
                "max_error": maximum,
                "mean_error": mean,
            })
        results[label].append({"input_shape": list(shape), "max_error": maximum, "mean_error": mean})
    if failures:
        raise ServiceConfigurationError(
            "TensorRT INT8 输出偏差超过校验阈值",
            details={"numeric_validation": {
                "source_runtime": "ONNX Runtime (CPU)",
                "target_runtime": "TensorRT INT8",
                "input_kind": "validation_image",
                "rule": "normalized_error",
                "sample_count": len(paths),
                "check_count": len(cases),
                "max_error_limit": _MAX_NORMALIZED_ERROR,
                "mean_error_limit": _MEAN_NORMALIZED_ERROR,
                "failures": failures,
            }},
        )
    return {
        "status": "passed",
        "passed": True,
        "validation_sample_count": len(paths),
        "reference": "onnxruntime",
        "normalization": "box_xywh_divided_by_input_width_height",
        "max_error_limit": _MAX_NORMALIZED_ERROR,
        "mean_error_limit": _MEAN_NORMALIZED_ERROR,
        "profiles": {
            label: {
                "input_shape": entries[0]["input_shape"],
                "runs": len(entries),
                "max_error": max(item["max_error"] for item in entries),
                "mean_error": sum(item["mean_error"] for item in entries) / len(entries),
            }
            for label, entries in results.items()
        },
    }
