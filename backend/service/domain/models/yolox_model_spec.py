"""YOLOX 模型规格定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# 支持的 YOLOX 模型 scale。
YoloXModelScale = Literal["nano", "tiny", "s", "m", "l", "x"]

# 当前骨架支持的 YOLOX 任务类型。
YoloXTaskType = Literal["detection"]

# 当前骨架支持登记的 YOLOX build 格式。
YoloXBuildFormat = Literal[
    "pytorch-checkpoint",
    "onnx",
    "openvino-ir",
    "tensorrt-engine",
]


@dataclass(frozen=True)
class YoloXModelSpec:
    """描述 YOLOX 在平台中的稳定模型规格。

    字段：
    - model_name：平台中的模型名。
    - supported_tasks：支持的任务类型列表。
    - supported_scales：支持的模型 scale 列表。
    - default_dataset_format：默认数据集导出格式。
    - supported_build_formats：支持登记的 build 格式列表。
    """

    model_name: str = "yolox"
    supported_tasks: tuple[YoloXTaskType, ...] = ("detection",)
    supported_scales: tuple[YoloXModelScale, ...] = ("nano", "tiny", "s", "m", "l", "x")
    default_dataset_format: str = "coco-detection-v1"
    supported_build_formats: tuple[YoloXBuildFormat, ...] = (
        "pytorch-checkpoint",
        "onnx",
        "openvino-ir",
        "tensorrt-engine",
    )


# 默认的 YOLOX 模型规格对象。
DEFAULT_YOLOX_MODEL_SPEC = YoloXModelSpec()