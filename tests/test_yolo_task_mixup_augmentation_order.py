"""普通 YOLO segmentation/pose/OBB MixUp 预变换顺序回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from backend.service.application.models.yolo11_core.data import obb as yolo11_obb
from backend.service.application.models.yolo11_core.data import pose as yolo11_pose
from backend.service.application.models.yolo11_core.data import (
    segmentation as yolo11_segmentation,
)
from backend.service.application.models.yolo26_core.data import obb as yolo26_obb
from backend.service.application.models.yolo26_core.data import pose as yolo26_pose
from backend.service.application.models.yolo26_core.data import (
    segmentation as yolo26_segmentation,
)
from backend.service.application.models.yolov8_core.data import obb as yolov8_obb
from backend.service.application.models.yolov8_core.data import pose as yolov8_pose
from backend.service.application.models.yolov8_core.data import (
    segmentation as yolov8_segmentation,
)


@pytest.mark.parametrize(
    "module,prefix,task",
    [
        (yolov8_segmentation, "yolov8", "segmentation"),
        (yolov8_pose, "yolov8", "pose"),
        (yolov8_obb, "yolov8", "obb"),
        (yolo11_segmentation, "yolo11", "segmentation"),
        (yolo11_pose, "yolo11", "pose"),
        (yolo11_obb, "yolo11", "obb"),
        (yolo26_segmentation, "yolo26", "segmentation"),
        (yolo26_pose, "yolo26", "pose"),
        (yolo26_obb, "yolo26", "obb"),
    ],
)
def test_task_mixup_applies_affine_to_both_inputs_before_blending(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    prefix: str,
    task: str,
) -> None:
    """两路 Mosaic/LetterBox 都必须先裁到目标尺寸，再进入 MixUp。"""

    calls: list[str] = []
    target = object()

    def build_mosaic(**_kwargs: object):
        calls.append("mosaic")
        return np.zeros((1280, 1280, 3), dtype=np.uint8), target

    def apply_affine(**kwargs: object):
        calls.append("affine")
        assert kwargs["image"].shape[:2] == (1280, 1280)
        return np.zeros((640, 640, 3), dtype=np.uint8), kwargs["target"]

    def blend(**kwargs: object):
        calls.append("mixup")
        assert kwargs["image"].shape[:2] == (640, 640)
        assert kwargs["other_image"].shape[:2] == (640, 640)
        return kwargs["image"]

    monkeypatch.setattr(module, f"_build_{prefix}_{task}_mosaic_sample", build_mosaic)
    monkeypatch.setattr(module, f"_apply_{prefix}_{task}_random_affine", apply_affine)
    monkeypatch.setattr(module, f"blend_{prefix}_mixup_images", blend)
    monkeypatch.setattr(
        module,
        f"_merge_{prefix}_{task}_targets",
        lambda **kwargs: kwargs["primary"],
    )
    monkeypatch.setattr(module.random, "random", lambda: 0.0)
    monkeypatch.setattr(module.random, "choice", lambda values: values[0])

    prepare = getattr(module, f"_prepare_{prefix}_{task}_sample_with_mix")
    prepare_kwargs = {
        "training": True,
        "imports": SimpleNamespace(np=np),
        "primary_sample": SimpleNamespace(),
        "available_samples": (SimpleNamespace(),),
        "target_width": 640,
        "target_height": 640,
        "augmentation_options": SimpleNamespace(
            mosaic_prob=1.0,
            mixup_prob=1.0,
        ),
    }
    if task == "segmentation":
        prepare_kwargs["scaleup"] = True
    image, result_target = prepare(**prepare_kwargs)

    assert calls == ["mosaic", "affine", "mosaic", "affine", "mixup"]
    assert image.shape[:2] == (640, 640)
    assert result_target is target
