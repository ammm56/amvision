"""obb 推理公共契约。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ObbRuntimeTensorSpec:
    name: str
    shape: tuple[int, ...]
    dtype: str


@dataclass(frozen=True)
class ObbRuntimeSessionInfo:
    backend_name: str
    model_uri: str
    device_name: str
    input_spec: ObbRuntimeTensorSpec
    output_specs: tuple[ObbRuntimeTensorSpec, ...]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ObbPredictionRequest:
    score_threshold: float
    save_result_image: bool
    input_uri: str | None = None
    input_image_bytes: bytes | None = None
    input_image_payload: dict[str, object] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ObbPredictionInstance:
    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None
    angle: float | None = None


@dataclass(frozen=True)
class ObbPredictionExecutionResult:
    instances: tuple[ObbPredictionInstance, ...]
    latency_ms: float | None
    image_width: int
    image_height: int
    preview_image_bytes: bytes | None
    runtime_session_info: ObbRuntimeSessionInfo
