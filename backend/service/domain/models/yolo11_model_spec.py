"""YOLO11 模型规格定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.service.domain.models.model_build_formats import (
    ModelBuildFormat,
)
from backend.service.domain.models.model_task_types import ModelTaskType
from backend.service.domain.models.yolo_model_profiles import YOLO11_MODEL_PROFILE


Yolo11ModelScale = Literal["nano", "s", "m", "l", "x"]


@dataclass(frozen=True)
class Yolo11ModelSpec:
    """描述 YOLO11 在平台中的稳定模型规格。"""

    model_name: str = "yolo11"
    supported_tasks: tuple[ModelTaskType, ...] = YOLO11_MODEL_PROFILE.supported_tasks
    supported_scales: tuple[Yolo11ModelScale, ...] = YOLO11_MODEL_PROFILE.supported_scales
    supported_build_formats: tuple[ModelBuildFormat, ...] = YOLO11_MODEL_PROFILE.supported_build_formats

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

        return YOLO11_MODEL_PROFILE.resolve_default_dataset_format(task_type)


DEFAULT_YOLO11_MODEL_SPEC = Yolo11ModelSpec()
