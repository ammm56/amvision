"""YOLOX 运行时最小接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class RuntimeTensorSpec:
    """描述运行时张量规格。

    字段：
    - name：张量名称。
    - shape：张量形状。
    - dtype：张量数据类型。
    """

    name: str
    shape: tuple[int, ...]
    dtype: str


@dataclass(frozen=True)
class YoloXRuntimeSessionInfo:
    """描述运行时会话的固定信息。

    字段：
    - backend_name：运行时 backend 名称。
    - model_uri：当前加载的模型 URI。
    - device_name：当前 device 名称。
    - input_spec：输入张量规格。
    - output_spec：输出张量规格。
    - metadata：附加元数据。
    """

    backend_name: str
    model_uri: str
    device_name: str
    input_spec: RuntimeTensorSpec
    output_spec: RuntimeTensorSpec
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXRuntimePredictRequest:
    """描述一次运行时预测请求。

    字段：
    - image_uri：输入图片 URI。
    - image_bytes：输入图片二进制内容。
    - score_threshold：置信度阈值。
    - metadata：附加元数据。
    """

    image_uri: str | None = None
    image_bytes: bytes | None = None
    score_threshold: float = 0.3
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXRuntimePredictResult:
    """描述一次运行时预测结果。

    字段：
    - raw_output_uri：原始输出 URI。
    - preview_image_uri：预览图 URI。
    - latency_ms：推理耗时，单位为毫秒。
    - metadata：附加元数据。
    """

    raw_output_uri: str | None = None
    preview_image_uri: str | None = None
    latency_ms: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class YoloXRuntimeSession(Protocol):
    """YOLOX 推理运行时会话接口。"""

    def describe(self) -> YoloXRuntimeSessionInfo:
        """返回当前运行时会话信息。"""

        ...

    def predict(self, request: YoloXRuntimePredictRequest) -> YoloXRuntimePredictResult:
        """执行一次预测。

        参数：
        - request：预测请求。

        返回：
        - 预测结果。
        """

        ...