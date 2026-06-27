"""YOLO segmentation 评估几何回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from backend.service.application.models.yolo11_core.evaluation import (
    segmentation as yolo11_segmentation,
)
from backend.service.application.models.yolo26_core.evaluation import (
    segmentation as yolo26_segmentation,
)
from backend.service.application.models.yolov8_core.evaluation import (
    segmentation as yolov8_segmentation,
)
from backend.service.application.models.yolov8_core.data import (
    detection_augmentation as yolov8_detection_augmentation,
)
from backend.service.application.models.yolov8_core.data.detection_types import (
    YoloV8DetectionAugmentationOptions,
)


@pytest.mark.parametrize(
    ("module", "normalize_name", "postprocess_name", "builder_name"),
    [
        (
            yolov8_segmentation,
            "normalize_yolov8_segmentation_outputs",
            "build_yolov8_segmentation_postprocess_instances",
            "_build_yolov8_segmentation_prediction_items",
        ),
        (
            yolo11_segmentation,
            "normalize_yolo11_segmentation_outputs",
            "build_yolo11_segmentation_postprocess_instances",
            "_build_yolo11_segmentation_prediction_items",
        ),
        (
            yolo26_segmentation,
            "normalize_yolo26_segmentation_outputs",
            "build_yolo26_segmentation_postprocess_instances",
            "_build_yolo26_segmentation_prediction_items",
        ),
    ],
)
def test_yolo_segmentation_evaluation_masks_use_height_width_order(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    normalize_name: str,
    postprocess_name: str,
    builder_name: str,
) -> None:
    """验证非方形输入下预测 mask 使用 height,width 顺序。"""

    input_size = (24, 40)
    fake_instance = SimpleNamespace(
        class_id=0,
        score=0.9,
        bbox_xyxy=(4.0, 3.0, 18.0, 12.0),
        segments=[[(4.0, 3.0), (18.0, 3.0), (18.0, 12.0), (4.0, 12.0)]],
    )

    def fake_normalize_outputs(
        *,
        outputs: object,
        np_module: object,
        **_: object,
    ) -> tuple[np.ndarray, np.ndarray]:
        return np.zeros((1, 1, 6), dtype=np.float32), np.zeros((1, 1, 2, 2), dtype=np.float32)

    def fake_postprocess_instances(**_: object) -> list[object]:
        return [fake_instance]

    monkeypatch.setattr(module, normalize_name, fake_normalize_outputs)
    monkeypatch.setattr(module, postprocess_name, fake_postprocess_instances)

    _, mask_items, _ = getattr(module, builder_name)(
        outputs=object(),
        labels=("barcode",),
        input_size=input_size,
        score_threshold=0.01,
        nms_threshold=0.7,
        mask_threshold=0.5,
        imports=SimpleNamespace(np=np, cv2=object()),
        image_index=1,
    )

    assert len(mask_items) == 1
    assert np.asarray(mask_items[0]["mask"]).shape == input_size


def test_yolov8_detection_random_affine_filters_heavily_cropped_boxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 YOLOv8 detection 使用 Ultralytics bbox 面积保留阈值。"""

    image = np.zeros((100, 100, 3), dtype=np.uint8)
    matrix = np.eye(3, dtype=np.float32)
    matrix[0, 0] = 0.2
    matrix[1, 1] = 0.2

    def fake_random_affine(**_: object) -> tuple[np.ndarray, np.ndarray, bool]:
        return image.copy(), matrix, True

    monkeypatch.setattr(
        yolov8_detection_augmentation,
        "apply_yolov8_random_affine",
        fake_random_affine,
    )

    _, boxes_xyxy, category_indexes = yolov8_detection_augmentation._apply_random_affine(
        imports=SimpleNamespace(np=np),
        image=image,
        boxes_xyxy=[(0.0, 0.0, 100.0, 100.0)],
        category_indexes=[0],
        output_size=(100, 100),
        augmentation_options=YoloV8DetectionAugmentationOptions(
            flip_prob=0.0,
            hsv_prob=0.0,
            mosaic_prob=0.0,
            mixup_prob=0.0,
            enable_mixup=False,
            affine_prob=1.0,
            degrees=0.0,
            translate=0.0,
            scale=0.0,
            shear=0.0,
            perspective=0.0,
            mosaic_scale=(1.0, 1.0),
            mixup_scale=(1.0, 1.0),
            close_mosaic_epochs=0,
            multi_scale=False,
            multi_scale_range=(1.0, 1.0),
            multi_scale_stride=32,
        ),
    )

    assert boxes_xyxy == []
    assert category_indexes == []
