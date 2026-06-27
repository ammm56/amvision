from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from backend.service.application.models.yolo_core_common.geometry import (
    build_yolo_letterbox_transform,
)
from backend.service.application.models.yolo11_core.evaluation.detection import (
    convert_yolo11_predictions_to_coco_detections,
)
from backend.service.application.models.yolov8_core.training.detection_execution import (
    _convert_yolov8_predictions_to_coco_detections,
)


class _FakePredictionTensor:
    """提供训练评估转换函数需要的最小 Tensor 接口。"""

    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def detach(self) -> "_FakePredictionTensor":
        return self

    def cpu(self) -> "_FakePredictionTensor":
        return self

    def numpy(self) -> np.ndarray:
        return self._array


def _build_letterbox_xywh_prediction() -> _FakePredictionTensor:
    """构造一个 YOLO raw detection 输出，前四位是 LetterBox 输入坐标 cx/cy/w/h。"""

    return _FakePredictionTensor(
        np.asarray([[[320.0, 320.0, 160.0, 80.0, 0.9, 0.1]]], dtype=np.float32)
    )


def _build_target() -> SimpleNamespace:
    """构造 COCO 转换需要的非方形原图 target 对象。"""

    return SimpleNamespace(
        image_id=7,
        image_width=1920,
        image_height=1080,
        letterbox_transform=build_yolo_letterbox_transform(
            source_width=1920,
            source_height=1080,
            input_size=(640, 640),
        ),
    )


def test_yolo11_evaluation_converts_raw_xywh_boxes_to_coco_bbox() -> None:
    detections = convert_yolo11_predictions_to_coco_detections(
        np_module=np,
        prediction_tensor=_build_letterbox_xywh_prediction(),
        batch_targets=(_build_target(),),
        input_size=(640, 640),
        category_ids=(1, 2),
        confidence_threshold=0.01,
        nms_threshold=0.65,
    )

    assert detections == [
        {
            "image_id": 7,
            "category_id": 1,
            "bbox": [720.0, 420.0, 480.0, 240.0],
            "score": 0.8999999761581421,
        }
    ]


def test_yolov8_evaluation_converts_raw_xywh_boxes_to_coco_bbox() -> None:
    detections = _convert_yolov8_predictions_to_coco_detections(
        imports=SimpleNamespace(np=np),
        prediction_tensor=_build_letterbox_xywh_prediction(),
        batch_targets=(_build_target(),),
        input_size=(640, 640),
        category_ids=(1, 2),
        confidence_threshold=0.01,
        nms_threshold=0.65,
    )

    assert detections == [
        {
            "image_id": 7,
            "category_id": 1,
            "bbox": [720.0, 420.0, 480.0, 240.0],
            "score": 0.8999999761581421,
        }
    ]
