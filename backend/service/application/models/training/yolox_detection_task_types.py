"""YOLOX detection 训练任务的数据对象和常量。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


YOLOX_TRAINING_TASK_KIND = "yolox-training"
YOLOX_TRAINING_QUEUE_NAME = "yolox-trainings"
YOLOX_TRAINING_CONTROL_METADATA_KEY = "training_control"
YOLOX_MANUAL_LATEST_REGISTRATION_METADATA_KEY = "manual_model_version_registration"
YOLOX_MANUAL_LATEST_OUTPUT_FILE_TOKEN = "manual-latest"


@dataclass(frozen=True)
class YoloXTrainingTaskRequest:
    """描述一次 YOLOX 训练任务创建请求。

    字段：
    - project_id：所属 Project id。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
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
    recipe_id: str
    model_scale: str
    output_model_name: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    warm_start_model_version_id: str | None = None
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXTrainingTaskSubmission:
    """描述一次 YOLOX 训练任务提交结果。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str


@dataclass(frozen=True)
class YoloXTrainingTaskResult:
    """描述一次 YOLOX 训练任务处理结果。

    字段：
    - task_id：训练任务 id。
    - status：训练任务最终状态。
    - dataset_export_id：训练输入使用的 DatasetExport id。
    - dataset_export_manifest_key：训练输入使用的导出 manifest object key。
    - dataset_version_id：训练使用的 DatasetVersion id。
    - format_id：训练输入导出格式 id。
    - output_object_prefix：训练输出目录前缀。
    - checkpoint_object_key：checkpoint 文件 object key。
    - latest_checkpoint_object_key：最新 checkpoint 文件 object key。
    - labels_object_key：标签文件 object key。
    - metrics_object_key：指标文件 object key。
    - validation_metrics_object_key：验证指标文件 object key。
    - summary_object_key：训练摘要文件 object key。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - summary：训练摘要。
    """

    task_id: str
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


@dataclass(frozen=True)
class ResolvedYoloXWarmStartReference:
    """描述一次 warm start 请求解析出的源模型版本信息。

    字段：
    - source_model_version_id：来源 ModelVersion id。
    - source_kind：来源版本类型。
    - source_model_name：来源模型名。
    - source_model_scale：来源模型 scale。
    - checkpoint_file_id：来源 checkpoint 文件 id。
    - checkpoint_storage_uri：来源 checkpoint 存储 URI。
    - checkpoint_path：来源 checkpoint 的本地绝对路径。
    - catalog_manifest_object_key：可选的预训练目录 manifest object key。
    """

    source_model_version_id: str
    source_kind: str
    source_model_name: str
    source_model_scale: str
    checkpoint_file_id: str
    checkpoint_storage_uri: str
    checkpoint_path: Path
    catalog_manifest_object_key: str | None = None
