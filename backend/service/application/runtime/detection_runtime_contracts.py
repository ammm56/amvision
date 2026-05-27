"""detection 推理公共契约。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DetectionRuntimeTensorSpec:
    """描述 detection 运行时张量规格。

    字段：
    - name：张量名称。
    - shape：张量形状。
    - dtype：张量数据类型。
    """

    name: str
    shape: tuple[int, ...]
    dtype: str


@dataclass(frozen=True)
class DetectionRuntimeSessionInfo:
    """描述 detection 运行时会话固定信息。

    字段：
    - backend_name：运行时 backend 名称。
    - model_uri：当前加载模型 URI。
    - device_name：当前执行 device 名称。
    - input_spec：输入张量规格。
    - output_spec：输出张量规格。
    - metadata：附加元数据。
    """

    backend_name: str
    model_uri: str
    device_name: str
    input_spec: DetectionRuntimeTensorSpec
    output_spec: DetectionRuntimeTensorSpec
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionPredictionRequest:
    """描述一次 detection 单图预测请求。

    字段：
    - score_threshold：预测阈值。
    - save_result_image：是否生成预览图。
    - input_uri：storage 模式下的输入图片 URI 或 object key。
    - input_image_bytes：memory 模式下直接提供的原始图片字节。
    - input_image_payload：跨进程 image-ref payload。
    - extra_options：附加运行时选项。
    """

    score_threshold: float
    save_result_image: bool
    input_uri: str | None = None
    input_image_bytes: bytes | None = None
    input_image_payload: dict[str, object] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionPredictionDetection:
    """描述单条 detection 结果。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None = None


@dataclass(frozen=True)
class DetectionPredictionExecutionResult:
    """描述一次 detection 单图预测执行结果。

    字段：
    - detections：检测框列表。
    - latency_ms：decode、preprocess、infer、postprocess 四段总耗时。
    - image_width：原图宽度。
    - image_height：原图高度。
    - preview_image_bytes：可选预览图字节内容。
    - runtime_session_info：运行时摘要。
    """

    detections: tuple[DetectionPredictionDetection, ...]
    latency_ms: float | None
    image_width: int
    image_height: int
    preview_image_bytes: bytes | None
    runtime_session_info: DetectionRuntimeSessionInfo
