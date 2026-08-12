"""obb 推理公共规则。"""

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
    input_image_bytes: bytes | bytearray | memoryview | None = None
    input_image_payload: dict[str, object] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ObbPredictionInstance:
    """描述一个旋转框实例。

    ``bbox_xywhr`` 是旋转框的规范几何表示，顺序为中心点 x/y、宽、高、
    弧度角。``bbox_xyxy`` 仅用于快速裁剪和轴对齐显示，不能结合
    ``angle`` 反推旋转框，否则会把外接矩形再次旋转。
    """

    bbox_xyxy: tuple[float, float, float, float]
    bbox_xywhr: tuple[float, float, float, float, float]
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
