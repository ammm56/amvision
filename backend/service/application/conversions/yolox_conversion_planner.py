"""YOLOX 转换规划接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


# 当前骨架支持的转换步骤类型。
YoloXConversionStepKind = Literal["export-onnx", "build-openvino-ir", "build-tensorrt-engine"]


@dataclass(frozen=True)
class YoloXConversionPlanningRequest:
    """描述一次转换规划请求。

    字段：
    - project_id：所属项目 id。
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：目标格式列表。
    - runtime_profile_id：目标 RuntimeProfile id。
    - preferred_device：优先使用的 device。
    - metadata：附加元数据。
    """

    project_id: str
    source_model_version_id: str
    target_formats: tuple[str, ...]
    runtime_profile_id: str | None = None
    preferred_device: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXConversionStep:
    """描述转换计划中的单个步骤。

    字段：
    - kind：步骤类型。
    - source_format：来源格式。
    - target_format：目标格式。
    - required_file_type：执行该步骤需要的 file type。
    - produced_file_type：该步骤产出的 file type。
    """

    kind: YoloXConversionStepKind
    source_format: str
    target_format: str
    required_file_type: str
    produced_file_type: str


@dataclass(frozen=True)
class YoloXConversionPlan:
    """描述一次完整的转换执行计划。

    字段：
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：目标格式列表。
    - steps：计划中的转换步骤列表。
    """

    source_model_version_id: str
    target_formats: tuple[str, ...]
    steps: tuple[YoloXConversionStep, ...]


class YoloXConversionPlanner(Protocol):
    """根据平台对象生成 YOLOX 转换执行计划。"""

    def build_plan(self, request: YoloXConversionPlanningRequest) -> YoloXConversionPlan:
        """构建转换计划。

        参数：
        - request：转换规划请求。

        返回：
        - 转换执行计划。
        """

        ...