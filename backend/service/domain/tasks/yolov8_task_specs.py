"""YOLOv8 detection 相关任务规格定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class YoloV8TrainingTaskSpec:
    """描述 YOLOv8 detection 训练任务的规格。"""

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
