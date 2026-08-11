"""YOLOv8 OBB grid 到像素坐标解码测试。"""

from __future__ import annotations

import pytest

from backend.service.application.models.yolov8_core.decode.obb import (
    build_yolov8_obb_prediction,
)


class _IdentityDfl:
    """返回测试传入的四个距离通道。"""

    def __call__(self, value: object) -> object:
        return value


def test_yolov8_obb_prediction_restores_grid_box_to_pixel_coordinates() -> None:
    """OBB 对外框必须乘 stride，angle 保持弧度且不得缩放。"""

    torch = pytest.importorskip("torch")
    raw_outputs = {
        "boxes": torch.ones((1, 4, 1)),
        "scores": torch.zeros((1, 1, 1)),
        "angle": torch.zeros((1, 1, 1)),
        "feats": (torch.zeros((1, 1, 1, 1)),),
    }

    prediction = build_yolov8_obb_prediction(
        raw_outputs=raw_outputs,
        strides=(8,),
        dfl_decoder=_IdentityDfl(),
    )

    assert prediction.shape == (1, 6, 1)
    assert prediction[0, :4, 0].tolist() == pytest.approx([4.0, 4.0, 16.0, 16.0])
    assert float(prediction[0, 5, 0]) == pytest.approx(0.25 * torch.pi)
