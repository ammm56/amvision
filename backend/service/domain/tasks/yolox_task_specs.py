"""YOLOX 相关任务规格定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# 支持的 YOLOX 转换目标类型。
YoloXConversionTarget = Literal[
    "onnx",
    "onnx-optimized",
    "openvino-ir",
    "tensorrt-engine",
    "rknn",
]


@dataclass(frozen=True)
class YoloXTrainingTaskSpec:
    """描述 YOLOX 训练任务的规格。

    字段：
    - project_id：所属项目 id。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的数据集导出 manifest object key。
    - manifest_object_key：训练任务内部统一使用的 manifest object key。
    - recipe_id：训练 recipe id。
    - model_scale：训练目标的模型 scale。
    - output_model_name：训练后登记的模型名。
    - warm_start_model_version_id：warm start 使用的 ModelVersion id。
    - evaluation_interval：每隔多少个 epoch 执行一次真实验证评估。
    - max_epochs：最大训练轮数。
    - batch_size：batch size。
    - gpu_count：请求参与训练的 GPU 数量。
    - precision：请求使用的训练 precision。
    - input_size：训练输入尺寸。
    - extra_options：附加训练选项。
    """

    project_id: str
    dataset_export_manifest_key: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    manifest_object_key: str | None = None
    dataset_export_id: str | None = None
    warm_start_model_version_id: str | None = None
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
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
    - planned_steps：提交时固化的转换步骤图谱。
    - extra_options：附加转换选项。
    """

    project_id: str
    source_model_version_id: str
    target_formats: tuple[YoloXConversionTarget, ...]
    runtime_profile_id: str | None = None
    planned_steps: tuple[dict[str, object], ...] = ()
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXInferenceTaskSpec:
    """描述 YOLOX 推理任务的规格。

    字段：
    - project_id：所属项目 id。
    - deployment_instance_id：执行推理使用的 DeploymentInstance id。
    - input_file_id：平台内输入文件 id。
    - input_uri：外部输入 URI。
    - input_source_kind：输入来源类型。
    - score_threshold：推理阈值。
    - save_result_image：是否保存结果图。
    - return_preview_image_base64：是否直接返回 base64 预览图。
    - runtime_target_snapshot：提交时固化的运行时快照。
    - instance_count：实例化数量；每个实例对应一个独立推理线程和模型会话。
    - extra_options：附加推理选项。
    """

    project_id: str
    deployment_instance_id: str
    input_file_id: str | None = None
    input_uri: str | None = None
    input_source_kind: str = "input_uri"
    score_threshold: float | None = None
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    runtime_target_snapshot: dict[str, object] = field(default_factory=dict)
    instance_count: int = 1
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXEvaluationTaskSpec:
    """描述 YOLOX 评估任务的规格。

    字段：
    - project_id：所属项目 id。
    - model_version_id：待评估 ModelVersion id。
    - dataset_export_id：评估输入使用的 DatasetExport id。
    - dataset_export_manifest_key：评估输入使用的数据集导出 manifest object key。
    - manifest_object_key：评估任务内部统一使用的 manifest object key。
    - score_threshold：评估阈值。
    - nms_threshold：评估 NMS 阈值。
    - save_result_package：是否输出结果包。
    - extra_options：附加评估选项。
    """

    project_id: str
    model_version_id: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    manifest_object_key: str | None = None
    score_threshold: float | None = None
    nms_threshold: float | None = None
    save_result_package: bool = True
    extra_options: dict[str, object] = field(default_factory=dict)