"""所有 YOLO task 的 batch/epoch 进度边界回归测试。"""

from __future__ import annotations

from dataclasses import fields
import inspect

from backend.service.application.models.training.yolo11_classification_training import (
    Yolo11ClassificationTrainingExecutionRequest,
)
from backend.service.application.models.training.yolo11_obb_training import (
    Yolo11ObbTrainingExecutionRequest,
)
from backend.service.application.models.training.yolo11_pose_training import (
    Yolo11PoseTrainingExecutionRequest,
)
from backend.service.application.models.training.yolo11_segmentation_training import (
    Yolo11SegmentationTrainingExecutionRequest,
)
from backend.service.application.models.training.yolo26_classification_training import (
    Yolo26ClassificationTrainingExecutionRequest,
)
from backend.service.application.models.training.yolo26_obb_training import (
    Yolo26ObbTrainingExecutionRequest,
)
from backend.service.application.models.training.yolo26_pose_training import (
    Yolo26PoseTrainingExecutionRequest,
)
from backend.service.application.models.training.yolo26_segmentation_training import (
    Yolo26SegmentationTrainingExecutionRequest,
)
from backend.service.application.models.yolov8_core.training.classification_execution import (
    YoloV8ClassificationTrainingExecutionRequest,
)
from backend.service.application.models.yolov8_core.training.obb_execution import (
    YoloV8ObbTrainingExecutionRequest,
    run_yolov8_obb_training,
)
from backend.service.application.models.yolov8_core.training.pose_execution import (
    YoloV8PoseTrainingExecutionRequest,
)
from backend.service.application.models.yolov8_core.training.segmentation_execution import (
    YoloV8SegmentationTrainingExecutionRequest,
)


def test_all_yolo_non_detection_requests_expose_dedicated_batch_callback() -> None:
    """验证三代 YOLO 四类非 detection 任务均有独立 batch callback。"""

    request_types = (
        YoloV8ClassificationTrainingExecutionRequest,
        YoloV8SegmentationTrainingExecutionRequest,
        YoloV8PoseTrainingExecutionRequest,
        YoloV8ObbTrainingExecutionRequest,
        Yolo11ClassificationTrainingExecutionRequest,
        Yolo11SegmentationTrainingExecutionRequest,
        Yolo11PoseTrainingExecutionRequest,
        Yolo11ObbTrainingExecutionRequest,
        Yolo26ClassificationTrainingExecutionRequest,
        Yolo26SegmentationTrainingExecutionRequest,
        Yolo26PoseTrainingExecutionRequest,
        Yolo26ObbTrainingExecutionRequest,
    )
    for request_type in request_types:
        assert "batch_callback" in {field.name for field in fields(request_type)}


def test_yolov8_obb_never_routes_batch_progress_to_epoch_callback() -> None:
    """锁定历史根因：OBB batch progress 禁止进入 epoch 持久化 callback。"""

    source = inspect.getsource(run_yolov8_obb_training)
    assert "request.batch_callback(" in source
    assert "request.epoch_callback(bp)" not in source
