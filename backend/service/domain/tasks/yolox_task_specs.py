"""YOLOX 相关任务规格定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# 支持的 YOLOX 转换目标类型。
YoloXConversionTarget = Literal["onnx", "openvino-ir", "tensorrt-engine"]


@dataclass(frozen=True)
class YoloXTrainingTaskSpec:
    """描述 YOLOX 训练任务的规格。

    字段：
    - project_id：所属项目 id。
    - dataset_version_id：训练使用的 DatasetVersion id。
    - recipe_id：训练 recipe id。
    - model_scale：训练目标的模型 scale。
    - output_model_name：训练后登记的模型名。
    - warm_start_model_version_id：warm start 使用的 ModelVersion id。
    - max_epochs：最大训练轮数。
    - batch_size：batch size。
    - input_size：训练输入尺寸。
    - extra_options：附加训练选项。
    """

    project_id: str
    dataset_version_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    warm_start_model_version_id: str | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXConversionTaskSpec:
    """描述 YOLOX 转换任务的规格。

    字段：
    - project_id：所属项目 id。
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：目标格式列表。
    - runtime_profile_id：目标 RuntimeProfile id。
    - extra_options：附加转换选项。
    """

    project_id: str
    source_model_version_id: str
    target_formats: tuple[YoloXConversionTarget, ...]
    runtime_profile_id: str | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXInferenceTaskSpec:
    """描述 YOLOX 推理任务的规格。

    字段：
    - project_id：所属项目 id。
    - deployment_instance_id：执行推理使用的 DeploymentInstance id。
    - input_file_id：平台内输入文件 id。
    - input_uri：外部输入 URI。
    - score_threshold：推理阈值。
    - save_result_image：是否保存结果图。
    - extra_options：附加推理选项。
    """

    project_id: str
    deployment_instance_id: str
    input_file_id: str | None = None
    input_uri: str | None = None
    score_threshold: float | None = None
    save_result_image: bool = False
    extra_options: dict[str, object] = field(default_factory=dict)