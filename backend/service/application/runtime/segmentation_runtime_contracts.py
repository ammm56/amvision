"""segmentation 推理公共规则。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SegmentationRuntimeTensorSpec:
    """描述 segmentation 运行时张量规格。"""

    name: str
    shape: tuple[int, ...]
    dtype: str


@dataclass(frozen=True)
class SegmentationRuntimeSessionInfo:
    """描述 segmentation 运行时会话固定信息。"""

    backend_name: str
    model_uri: str
    device_name: str
    input_spec: SegmentationRuntimeTensorSpec
    output_specs: tuple[SegmentationRuntimeTensorSpec, ...]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SegmentationPredictionRequest:
    """描述一次 segmentation 单图预测请求。"""

    score_threshold: float
    mask_threshold: float
    save_result_image: bool
    input_uri: str | None = None
    input_image_bytes: bytes | None = None
    input_image_payload: dict[str, object] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SegmentationPredictionInstance:
    """描述单条 segmentation 结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None
    segments: tuple[tuple[tuple[float, float], ...], ...] = ()
    mask_area: float | None = None


@dataclass(frozen=True)
class SegmentationPredictionExecutionResult:
    """描述一次 segmentation 单图预测执行结果。"""

    instances: tuple[SegmentationPredictionInstance, ...]
    latency_ms: float | None
    image_width: int
    image_height: int
    preview_image_bytes: bytes | None
    runtime_session_info: SegmentationRuntimeSessionInfo
