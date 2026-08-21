"""YOLO detection DataLoader 生命周期回归测试。"""

from __future__ import annotations

import inspect

import pytest

from backend.service.application.models.training.yolo11_detection_training import (
    run_yolo11_detection_training,
)
from backend.service.application.models.training.yolo26_detection_training import (
    run_yolo26_detection_training,
)
from backend.service.application.models.yolov8_core.training.detection_execution import (
    run_yolov8_detection_training,
)


@pytest.mark.parametrize(
    "training_entrypoint",
    (
        run_yolov8_detection_training,
        run_yolo11_detection_training,
        run_yolo26_detection_training,
    ),
)
def test_yolo_detection_training_reuses_dataloader_across_epochs(
    training_entrypoint: object,
) -> None:
    """验证 detection 训练通过生命周期对象复用同一增强阶段的 worker。"""

    source = inspect.getsource(training_entrypoint)

    assert "training_loader_lifecycle = YoloTaskTrainingDataLoaderLifecycle()" in source
    assert "training_loader_lifecycle.resolve(" in source
    assert "training_loader_lifecycle.close()" in source


@pytest.mark.parametrize(
    "training_entrypoint",
    (
        run_yolo11_detection_training,
        run_yolo26_detection_training,
    ),
)
def test_yolo_detection_training_closes_dataloader_in_finally(
    training_entrypoint: object,
) -> None:
    """验证暂停、终止和异常退出都显式回收 persistent worker。"""

    source = inspect.getsource(training_entrypoint)

    assert "finally:" in source
    assert "training_loader_lifecycle.close()" in source
