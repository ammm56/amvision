"""YOLOX 推理 worker 接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class YoloXDetectionRecord:
    """描述单条 detection 结果。

    字段：
    - bbox_xyxy：检测框坐标，格式为 xyxy。
    - score：检测分数。
    - class_id：类别 id。
    """

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int


@dataclass(frozen=True)
class YoloXInferenceRunRequest:
    """描述一次 YOLOX 推理执行请求。

    字段：
    - inference_task_id：推理任务 id。
    - deployment_instance_id：执行推理使用的 DeploymentInstance id。
    - model_build_uri：待加载的 ModelBuild URI。
    - input_uri：输入内容 URI。
    - runtime_backend：推理 backend 名称。
    - device_name：推理 device 名称。
    - score_threshold：置信度阈值。
    - metadata：附加元数据。
    """

    inference_task_id: str
    deployment_instance_id: str
    model_build_uri: str
    input_uri: str
    runtime_backend: str
    device_name: str
    score_threshold: float = 0.3
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXInferenceRunResult:
    """描述一次 YOLOX 推理执行结果。

    字段：
    - inference_task_id：推理任务 id。
    - task_family：任务类型。
    - detections：检测结果列表。
    - preview_image_uri：预览图 URI。
    - raw_result_uri：原始结果 URI。
    - metrics：推理指标。
    - metadata：附加元数据。
    """

    inference_task_id: str
    task_family: str
    detections: tuple[YoloXDetectionRecord, ...]
    preview_image_uri: str | None = None
    raw_result_uri: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


class YoloXInferenceRunner(Protocol):
    """执行 YOLOX 推理任务的 worker 接口。"""

    def run_inference(self, request: YoloXInferenceRunRequest) -> YoloXInferenceRunResult:
        """执行推理并返回结果。

        参数：
        - request：推理执行请求。

        返回：
        - 推理执行结果。
        """

        ...