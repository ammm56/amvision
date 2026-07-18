"""YOLOX 模型规格定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.domain.models.model_build_formats import (
    ModelBuildFormat,
    ONNX_BUILD_FORMAT,
    ONNX_OPTIMIZED_BUILD_FORMAT,
    OPENVINO_IR_BUILD_FORMAT,
    PYTORCH_CHECKPOINT_BUILD_FORMAT,
    TENSORRT_ENGINE_BUILD_FORMAT,
)
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE, ModelTaskType


# 支持的 YOLOX 模型 scale。
YoloXModelScale = Literal["nano", "tiny", "s", "m", "l", "x"]


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
    supported_tasks: tuple[ModelTaskType, ...] = (DETECTION_TASK_TYPE,)
    supported_scales: tuple[YoloXModelScale, ...] = ("nano", "tiny", "s", "m", "l", "x")
    default_dataset_format: str = COCO_DETECTION_DATASET_FORMAT
    supported_build_formats: tuple[ModelBuildFormat, ...] = (
        PYTORCH_CHECKPOINT_BUILD_FORMAT,
        ONNX_BUILD_FORMAT,
        ONNX_OPTIMIZED_BUILD_FORMAT,
        OPENVINO_IR_BUILD_FORMAT,
        TENSORRT_ENGINE_BUILD_FORMAT,
    )

    def supports_task_type(self, task_type: str) -> bool:
        """判断当前规格是否支持指定任务分类。"""

        return task_type in self.supported_tasks

    def supports_model_scale(self, model_scale: str) -> bool:
        """判断当前规格是否支持指定模型 scale。"""

        return model_scale in self.supported_scales

    def supports_build_format(self, build_format: str) -> bool:
        """判断当前规格是否支持指定 build 格式。"""

        return build_format in self.supported_build_formats

    def resolve_default_dataset_format(self, task_type: str) -> str | None:
        """返回指定任务分类对应的默认数据集导出格式。"""

        if not self.supports_task_type(task_type):
            return None
        if task_type == DETECTION_TASK_TYPE:
            return self.default_dataset_format
        return None


# 默认的 YOLOX 模型规格对象。
DEFAULT_YOLOX_MODEL_SPEC = YoloXModelSpec()
