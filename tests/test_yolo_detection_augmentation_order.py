"""普通 YOLO detection 数据增强顺序回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from backend.service.application.models.yolo11_core.data import detection as yolo11_detection
from backend.service.application.models.yolo11_core.data.augmentation import (
    blend_yolo11_mixup_images,
)
from backend.service.application.models.yolo26_core.data import detection as yolo26_detection
from backend.service.application.models.yolo26_core.data.augmentation import (
    blend_yolo26_mixup_images,
)
from backend.service.application.models.yolov8_core.data import (
    detection_augmentation as yolov8_detection,
)
from backend.service.application.models.yolov8_core.data.augmentation import (
    blend_yolov8_mixup_images,
)


@pytest.mark.parametrize(
    "module,prepare_name,mosaic_name,affine_name,hsv_name,flip_name",
    [
        (
            yolov8_detection,
            "prepare_yolov8_detection_sample_with_augmentation",
            "_build_mosaic_detection_sample",
            "_apply_random_affine",
            "_apply_random_hsv",
            "_apply_random_flip",
        ),
        (
            yolo11_detection,
            "_prepare_yolo11_detection_sample_with_augmentation",
            "_build_yolo11_detection_mosaic_sample",
            "_apply_yolo11_detection_affine",
            "apply_yolo11_random_hsv",
            "_apply_yolo11_detection_flip",
        ),
        (
            yolo26_detection,
            "_prepare_yolo26_detection_sample_with_augmentation",
            "_build_yolo26_detection_mosaic_sample",
            "_apply_yolo26_detection_affine",
            "apply_yolo26_random_hsv",
            "_apply_yolo26_detection_flip",
        ),
    ],
)
def test_detection_mosaic_is_cropped_before_hsv_and_flip(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    prepare_name: str,
    mosaic_name: str,
    affine_name: str,
    hsv_name: str,
    flip_name: str,
) -> None:
    """Mosaic 大画布必须先裁为目标尺寸，随后才能做 HSV 和水平翻转。"""

    call_order: list[str] = []
    mosaic_image = np.zeros((1280, 1280, 3), dtype=np.uint8)
    cropped_image = np.zeros((640, 640, 3), dtype=np.uint8)

    def build_mosaic(**_kwargs: object):
        call_order.append("mosaic")
        return mosaic_image, [(100.0, 100.0, 200.0, 200.0)], [0]

    def apply_affine(**kwargs: object):
        call_order.append("affine")
        assert kwargs["image"].shape[:2] == (1280, 1280)
        return cropped_image, [(50.0, 50.0, 150.0, 150.0)], [0]

    def apply_hsv(**kwargs: object):
        call_order.append("hsv")
        assert kwargs["image"].shape[:2] == (640, 640)
        return kwargs["image"]

    def apply_flip(**kwargs: object):
        call_order.append("flip")
        assert kwargs["image"].shape[:2] == (640, 640)
        return kwargs["image"], kwargs["boxes_xyxy"]

    monkeypatch.setattr(module, mosaic_name, build_mosaic)
    monkeypatch.setattr(module, affine_name, apply_affine)
    monkeypatch.setattr(module, hsv_name, apply_hsv)
    monkeypatch.setattr(module, flip_name, apply_flip)

    prepare = getattr(module, prepare_name)
    image, boxes, categories = prepare(
        imports=SimpleNamespace(np=np),
        primary_sample=SimpleNamespace(),
        available_samples=(SimpleNamespace(),),
        input_size=(640, 640),
        augmentation_options=SimpleNamespace(
            mosaic_prob=1.0,
            mixup_prob=0.0,
            flip_prob=0.5,
        ),
    )

    assert call_order == ["mosaic", "affine", "hsv", "flip"]
    assert image.shape[:2] == (640, 640)
    assert boxes == [(50.0, 50.0, 150.0, 150.0)]
    assert categories == [0]


@pytest.mark.parametrize(
    "blend",
    [
        blend_yolov8_mixup_images,
        blend_yolo11_mixup_images,
        blend_yolo26_mixup_images,
    ],
)
def test_ordinary_yolo_mixup_uses_reference_beta_ratio(
    monkeypatch: pytest.MonkeyPatch,
    blend,
) -> None:
    """MixUp 使用参考实现的 Beta(32, 32)，不再固定为 0.5。"""

    monkeypatch.setattr(np.random, "beta", lambda alpha, beta: 0.25)
    image = np.full((2, 2, 3), 100, dtype=np.uint8)
    other_image = np.full((2, 2, 3), 20, dtype=np.uint8)

    mixed = blend(
        imports=SimpleNamespace(np=np),
        image=image,
        other_image=other_image,
    )

    assert np.all(mixed == 40)


@pytest.mark.parametrize(
    "module,prepare_name,mosaic_name",
    [
        (
            yolov8_detection,
            "prepare_yolov8_detection_sample_with_augmentation",
            "_build_mosaic_detection_sample",
        ),
        (
            yolo11_detection,
            "_prepare_yolo11_detection_sample_with_augmentation",
            "_build_yolo11_detection_mosaic_sample",
        ),
        (
            yolo26_detection,
            "_prepare_yolo26_detection_sample_with_augmentation",
            "_build_yolo26_detection_mosaic_sample",
        ),
    ],
)
def test_detection_mosaic_crop_and_flip_keep_pixels_aligned_with_boxes(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    prepare_name: str,
    mosaic_name: str,
) -> None:
    """真实 affine crop 和 flip 后，像素区域必须仍与 bbox 严格对齐。"""

    cv2 = pytest.importorskip("cv2")
    mosaic_image = np.zeros((1280, 1280, 3), dtype=np.uint8)
    mosaic_image[400:500, 800:900] = 255

    def build_mosaic(**_kwargs: object):
        return mosaic_image.copy(), [(800.0, 400.0, 900.0, 500.0)], [0]

    monkeypatch.setattr(module, mosaic_name, build_mosaic)
    monkeypatch.setattr(module.random, "random", lambda: 0.0)

    prepare = getattr(module, prepare_name)
    image, boxes, categories = prepare(
        imports=SimpleNamespace(cv2=cv2, np=np),
        primary_sample=SimpleNamespace(),
        available_samples=(SimpleNamespace(),),
        input_size=(640, 640),
        augmentation_options=SimpleNamespace(
            mosaic_prob=1.0,
            mixup_prob=0.0,
            flip_prob=1.0,
            hsv_h=0.0,
            hsv_s=0.0,
            hsv_v=0.0,
            affine_prob=0.0,
            degrees=0.0,
            translate=0.0,
            scale=0.0,
            shear=0.0,
            perspective=0.0,
        ),
    )

    foreground_y, foreground_x = np.where(image[..., 0] > 200)
    assert image.shape[:2] == (640, 640)
    assert categories == [0]
    assert boxes == pytest.approx([(60.0, 80.0, 160.0, 180.0)])
    assert (
        int(foreground_x.min()),
        int(foreground_y.min()),
        int(foreground_x.max()) + 1,
        int(foreground_y.max()) + 1,
    ) == (60, 80, 160, 180)
