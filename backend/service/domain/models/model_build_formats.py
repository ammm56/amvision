"""模型 build 格式定义。"""

from __future__ import annotations

from typing import Final, Literal


ModelBuildFormat = Literal[
    "pytorch-checkpoint",
    "onnx",
    "onnx-optimized",
    "openvino-ir",
    "tensorrt-engine",
    "rknn",
]


PYTORCH_CHECKPOINT_BUILD_FORMAT: Final[ModelBuildFormat] = "pytorch-checkpoint"
ONNX_BUILD_FORMAT: Final[ModelBuildFormat] = "onnx"
ONNX_OPTIMIZED_BUILD_FORMAT: Final[ModelBuildFormat] = "onnx-optimized"
OPENVINO_IR_BUILD_FORMAT: Final[ModelBuildFormat] = "openvino-ir"
TENSORRT_ENGINE_BUILD_FORMAT: Final[ModelBuildFormat] = "tensorrt-engine"
RKNN_BUILD_FORMAT: Final[ModelBuildFormat] = "rknn"

SUPPORTED_MODEL_BUILD_FORMATS: Final[tuple[ModelBuildFormat, ...]] = (
    PYTORCH_CHECKPOINT_BUILD_FORMAT,
    ONNX_BUILD_FORMAT,
    ONNX_OPTIMIZED_BUILD_FORMAT,
    OPENVINO_IR_BUILD_FORMAT,
    TENSORRT_ENGINE_BUILD_FORMAT,
    RKNN_BUILD_FORMAT,
)


def is_model_build_format(value: str) -> bool:
    """判断给定字符串是否属于当前已登记的 build 格式。"""

    return value in SUPPORTED_MODEL_BUILD_FORMATS
