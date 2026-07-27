"""模型预处理与公开坐标契约回归测试。"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pytest
import torch

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.rfdetr_core.runtime import (
    resolve_rfdetr_runtime_input_size,
)
from backend.service.application.models.yolox_core.postprocess import (
    build_yolox_detection_records,
)
from backend.service.application.runtime.predictors.rfdetr.io import (
    build_rfdetr_input_array,
)
from backend.service.application.runtime.predictors.yolox.io import (
    preprocess_yolox_image,
)


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
    assert input_array.dtype == np.float32
    assert preprocess_ms >= 0
    assert input_array[0, :, 0, 0].tolist() == pytest.approx(
        [
            (30.0 / 255.0 - 0.485) / 0.229,
            (20.0 / 255.0 - 0.456) / 0.224,
            (10.0 / 255.0 - 0.406) / 0.225,
        ]
    )


def test_yolox_non_square_preprocess_uses_reference_floor_dimensions() -> None:
    """YOLOX 非方形缩放使用 int 向下取整，不能回退到 round。"""

    image = np.full((333, 717, 3), (10, 20, 30), dtype=np.uint8)
    tensor, resize_ratio = preprocess_yolox_image(
        cv2_module=cv2,
        np_module=np,
        image=image,
        input_size=(416, 672),
    )
    resized_height = int(333 * resize_ratio)
    resized_width = int(717 * resize_ratio)

    assert tensor.shape == (3, 416, 672)
    assert tensor[:, resized_height - 1, resized_width - 1].tolist() == [
        30.0,
        20.0,
        10.0,
    ]
    assert tensor[:, resized_height, 0].tolist() == [114.0, 114.0, 114.0]


def test_rfdetr_non_square_float_resize_matches_independent_tensor_reference() -> None:
    """RF-DETR float resize 与独立 tensor bilinear 计算保持数值一致。"""

    rng = np.random.default_rng(20260726)
    image = rng.integers(0, 256, size=(73, 121, 3), dtype=np.uint8)
    actual, _ = build_rfdetr_input_array(
        cv2_module=cv2,
        np_module=np,
        image=image,
        input_size=(96, 160),
    )
    rgb = image[:, :, ::-1].copy()
    reference = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).float() / 255.0
    reference = torch.nn.functional.interpolate(
        reference,
        size=(96, 160),
        mode="bilinear",
        align_corners=False,
    )
    mean = torch.tensor((0.485, 0.456, 0.406)).view(1, 3, 1, 1)
    std = torch.tensor((0.229, 0.224, 0.225)).view(1, 3, 1, 1)
    reference = ((reference - mean) / std).numpy()

    assert actual.shape == (1, 3, 96, 160)
    np.testing.assert_allclose(actual, reference, rtol=1e-5, atol=1e-4)


def test_rfdetr_runtime_preserves_aligned_non_square_contract() -> None:
    """RF-DETR runtime 不得把合法非方形 ModelBuild 输入改回方形。"""

    assert resolve_rfdetr_runtime_input_size(
        task_type="detection",
        model_scale="nano",
        input_size=(384, 640),
    ) == (384, 640)


def test_rfdetr_runtime_rejects_missing_or_implicitly_aligned_size() -> None:
    """RF-DETR runtime 不兼容缺失尺寸，也不允许静默向上对齐。"""

    with pytest.raises(ServiceConfigurationError, match="缺少显式"):
        resolve_rfdetr_runtime_input_size(
            task_type="detection",
            model_scale="nano",
            input_size=None,
        )
    with pytest.raises(ServiceConfigurationError, match="禁止静默对齐"):
        resolve_rfdetr_runtime_input_size(
            task_type="detection",
            model_scale="nano",
            input_size=(385, 641),
        )
