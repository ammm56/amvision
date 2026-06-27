"""模型预处理与公开坐标契约回归测试。"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pytest

from backend.service.application.models.yolox_core.postprocess import build_yolox_detection_records
from backend.service.application.runtime.predictors.rfdetr.io import build_rfdetr_input_array
from backend.service.application.runtime.predictors.yolox.io import preprocess_yolox_image


@dataclass(frozen=True)
class _DetectionRecord:
    """测试用 detection 记录。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None


def test_yolox_runtime_preprocess_keeps_reference_top_left_padding() -> None:
    """YOLOX runtime 必须保持参考实现的左上角 padding 规则。"""

    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[:, :] = (10, 20, 30)

    tensor, resize_ratio = preprocess_yolox_image(
        cv2_module=cv2,
        np_module=np,
        image=image,
        input_size=(640, 640),
    )

    assert tensor.shape == (3, 640, 640)
    assert resize_ratio == pytest.approx(0.5)
    assert tensor[:, 0, 0].tolist() == [30.0, 20.0, 10.0]
    assert tensor[:, 359, 639].tolist() == [30.0, 20.0, 10.0]
    assert tensor[:, 360, 0].tolist() == [114.0, 114.0, 114.0]
    assert tensor[:, 500, 10].tolist() == [114.0, 114.0, 114.0]


def test_yolox_records_are_original_image_xyxy_after_top_left_padding() -> None:
    """YOLOX runtime 对外输出原图坐标 xyxy。"""

    predictions = [
        np.asarray(
            [
                [50.0, 25.0, 150.0, 125.0, 0.8, 0.5, 0.0],
            ],
            dtype=np.float32,
        )
    ]

    records = build_yolox_detection_records(
        np_module=np,
        predictions=predictions,
        resize_ratio=0.5,
        labels=("barcode",),
        image_width=1280,
        image_height=720,
        detection_factory=_DetectionRecord,
    )

    assert len(records) == 1
    assert records[0].bbox_xyxy == (100.0, 50.0, 300.0, 250.0)
    assert records[0].score == 0.4
    assert records[0].class_name == "barcode"


def test_rfdetr_runtime_preprocess_keeps_reference_fixed_resize() -> None:
    """RF-DETR runtime 使用参考实现的固定尺寸 resize 输入。"""

    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[:, :] = (10, 20, 30)

    input_array, preprocess_ms = build_rfdetr_input_array(
        cv2_module=cv2,
        np_module=np,
        image=image,
        input_size=(640, 640),
    )

    assert input_array.shape == (1, 3, 640, 640)
    assert preprocess_ms >= 0
    assert input_array[0, :, 0, 0].tolist() == pytest.approx([
        30.0 / 255.0,
        20.0 / 255.0,
        10.0 / 255.0,
    ])
