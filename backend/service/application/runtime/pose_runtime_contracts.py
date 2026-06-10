"""pose 推理公共规则。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PoseRuntimeTensorSpec:
    """描述 pose 运行时张量规格。"""

    name: str
    shape: tuple[int, ...]
    dtype: str


@dataclass(frozen=True)
class PoseRuntimeSessionInfo:
    """描述 pose 运行时会话固定信息。"""

    backend_name: str
    model_uri: str
    device_name: str
    input_spec: PoseRuntimeTensorSpec
    output_specs: tuple[PoseRuntimeTensorSpec, ...]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PosePredictionRequest:
    """描述一次 pose 单图预测请求。"""

    score_threshold: float
    keypoint_confidence_threshold: float
    save_result_image: bool
    input_uri: str | None = None
    input_image_bytes: bytes | None = None
    input_image_payload: dict[str, object] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PosePredictionKeypoint:
    """描述单个关键点。"""

    x: float
    y: float
    confidence: float | None = None


@dataclass(frozen=True)
class PosePredictionInstance:
    """描述单条 pose 结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None
    keypoints: tuple[PosePredictionKeypoint, ...] = ()
    kpt_shape: tuple[int, int] = (17, 3)


@dataclass(frozen=True)
class PosePredictionExecutionResult:
    """描述一次 pose 单图预测执行结果。"""

    instances: tuple[PosePredictionInstance, ...]
    latency_ms: float | None
    image_width: int
    image_height: int
    preview_image_bytes: bytes | None
    runtime_session_info: PoseRuntimeSessionInfo
