"""多任务推理 task_spec 定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BaseInferenceTaskSpec:
    """描述多任务推理任务共享的规格字段。"""

    project_id: str
    deployment_instance_id: str
    input_file_id: str | None = None
    input_uri: str | None = None
    input_source_kind: str = "input_uri"
    input_transport_mode: str = "storage"
    normalized_input: dict[str, object] = field(default_factory=dict)
    async_inference_owner_id: str | None = None
    save_result_image: bool = False
    return_preview_image_base64: bool = False
    runtime_target_snapshot: dict[str, object] = field(default_factory=dict)
    runtime_behavior: dict[str, object] = field(default_factory=dict)
    instance_count: int = 1
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassificationInferenceTaskSpec(BaseInferenceTaskSpec):
    """描述 classification 推理任务规格。"""

    top_k: int = 5


@dataclass(frozen=True)
class SegmentationInferenceTaskSpec(BaseInferenceTaskSpec):
    """描述 segmentation 推理任务规格。"""

    score_threshold: float | None = None
    mask_threshold: float = 0.5


@dataclass(frozen=True)
class PoseInferenceTaskSpec(BaseInferenceTaskSpec):
    """描述 pose 推理任务规格。"""

    score_threshold: float | None = None
    keypoint_confidence_threshold: float | None = None


@dataclass(frozen=True)
class ObbInferenceTaskSpec(BaseInferenceTaskSpec):
    """描述 obb 推理任务规格。"""

    score_threshold: float | None = None
