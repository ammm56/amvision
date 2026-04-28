"""YOLOX 训练 worker 接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class YoloXTrainingRunRequest:
    """描述一次 YOLOX 训练执行请求。

    字段：
    - training_task_id：训练任务 id。
    - dataset_export_manifest_key：训练导出 manifest 的 object key。
    - recipe_id：训练 recipe id。
    - output_object_prefix：训练输出目录前缀。
    - checkpoint_output_name：checkpoint 输出文件名。
    - metadata：附加元数据。
    """

    training_task_id: str
    dataset_export_manifest_key: str
    recipe_id: str
    output_object_prefix: str
    checkpoint_output_name: str = "best_ckpt.pth"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXTrainingRunResult:
    """描述一次 YOLOX 训练执行结果。

    字段：
    - training_task_id：训练任务 id。
    - checkpoint_object_key：checkpoint 的 object key。
    - labels_object_key：标签文件的 object key。
    - metrics_object_key：指标文件的 object key。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - summary：训练摘要。
    """

    training_task_id: str
    checkpoint_object_key: str
    labels_object_key: str | None = None
    metrics_object_key: str | None = None
    best_metric_name: str | None = None
    best_metric_value: float | None = None
    summary: dict[str, object] = field(default_factory=dict)


class YoloXTrainerRunner(Protocol):
    """执行 YOLOX 训练任务的 worker 接口。"""

    def run_training(self, request: YoloXTrainingRunRequest) -> YoloXTrainingRunResult:
        """执行训练并返回结果。

        参数：
        - request：训练执行请求。

        返回：
        - 训练执行结果。
        """

        ...