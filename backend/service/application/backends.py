"""训练与转换执行边界定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.service.application.conversions.yolox_conversion_planner import YoloXConversionStep
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot


@dataclass(frozen=True)
class TrainingBackendRunRequest:
    """描述一次训练 backend 执行请求。

    字段：
    - training_task_id：训练任务 id。
    - metadata：附加元数据。
    """

    training_task_id: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TrainingBackendRunResult:
    """描述一次训练 backend 执行结果。

    字段：
    - training_task_id：训练任务 id。
    - status：训练任务最终状态。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
    - dataset_version_id：训练使用的 DatasetVersion id。
    - format_id：训练输入导出格式 id。
    - output_object_prefix：训练输出目录前缀。
    - checkpoint_object_key：checkpoint 的 object key。
    - latest_checkpoint_object_key：最新 checkpoint 的 object key。
    - labels_object_key：标签文件的 object key。
    - metrics_object_key：指标文件的 object key。
    - validation_metrics_object_key：验证指标文件的 object key。
    - summary_object_key：训练摘要文件 object key。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - summary：训练摘要。
    """

    training_task_id: str
    status: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    output_object_prefix: str
    checkpoint_object_key: str
    latest_checkpoint_object_key: str | None = None
    labels_object_key: str | None = None
    metrics_object_key: str | None = None
    validation_metrics_object_key: str | None = None
    summary_object_key: str | None = None
    best_metric_name: str | None = None
    best_metric_value: float | None = None
    summary: dict[str, object] = field(default_factory=dict)


class TrainingBackend(Protocol):
    """定义训练 backend 需要满足的最小协议。"""

    def run_training(self, request: TrainingBackendRunRequest) -> TrainingBackendRunResult:
        """执行训练并返回结果。

        参数：
        - request：训练 backend 执行请求。

        返回：
        - TrainingBackendRunResult：训练执行结果。
        """

        ...


@dataclass(frozen=True)
class ConversionBackendRunRequest:
    """描述一次转换 backend 执行请求。

    字段：
    - conversion_task_id：转换任务 id。
    - source_runtime_target：来源 ModelVersion 解析得到的 runtime 快照。
    - target_formats：目标输出格式列表。
    - plan_steps：已经固化的转换步骤图谱。
    - output_object_prefix：输出目录前缀。
    - metadata：附加元数据。
    """

    conversion_task_id: str
    source_runtime_target: RuntimeTargetSnapshot
    target_formats: tuple[str, ...]
    plan_steps: tuple[YoloXConversionStep, ...]
    output_object_prefix: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversionBackendOutput:
    """描述单个转换输出文件。

    字段：
    - target_format：目标格式。
    - object_uri：输出文件 URI。
    - file_type：登记到平台的 file type。
    - metadata：输出元数据摘要。
    """

    target_format: str
    object_uri: str
    file_type: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversionBackendRunResult:
    """描述一次转换 backend 执行结果。

    字段：
    - conversion_task_id：转换任务 id。
    - outputs：转换输出文件列表。
    - metadata：附加元数据。
    """

    conversion_task_id: str
    outputs: tuple[ConversionBackendOutput, ...]
    metadata: dict[str, object] = field(default_factory=dict)


class ConversionBackend(Protocol):
    """定义转换 backend 需要满足的最小协议。"""

    def run_conversion(self, request: ConversionBackendRunRequest) -> ConversionBackendRunResult:
        """执行转换并返回结果。

        参数：
        - request：转换 backend 执行请求。

        返回：
        - ConversionBackendRunResult：转换执行结果。
        """

        ...