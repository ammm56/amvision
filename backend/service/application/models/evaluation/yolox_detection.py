"""YOLOX detection 数据集级评估应用入口。"""

from __future__ import annotations

from typing import Protocol

from backend.service.application.models.yolox_core.evaluators import (
    YoloXDetectionEvaluationRequest,
    YoloXDetectionEvaluationResult,
    run_yolox_detection_evaluation as run_yolox_core_detection_evaluation,
)


class YoloXEvaluator(Protocol):
    """定义 YOLOX 数据集级 evaluator 接口。"""

    def evaluate(self, request: YoloXDetectionEvaluationRequest) -> YoloXDetectionEvaluationResult:
        """执行一次数据集级评估。

        参数：
        - request：评估请求。

        返回：
        - YoloXDetectionEvaluationResult：评估结果。
        """


class PyTorchYoloXEvaluator:
    """基于 PyTorch checkpoint 的 YOLOX 数据集级 evaluator。"""

    def evaluate(self, request: YoloXDetectionEvaluationRequest) -> YoloXDetectionEvaluationResult:
        """执行一次 PyTorch YOLOX 数据集级评估。

        参数：
        - request：评估请求。

        返回：
        - YoloXDetectionEvaluationResult：评估结果。
        """

        return run_yolox_detection_evaluation(request)


def run_yolox_detection_evaluation(
    request: YoloXDetectionEvaluationRequest,
) -> YoloXDetectionEvaluationResult:
    """执行一次 YOLOX 数据集级评估。

    应用层只暴露稳定调用入口，具体 split 选择、PyTorch evaluator 和 COCO mAP
    执行细节都在 yolox_core.evaluators 中维护。
    """

    return run_yolox_core_detection_evaluation(request)
