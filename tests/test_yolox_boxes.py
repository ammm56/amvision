"""YOLOX boxes 工具回归测试。"""

from __future__ import annotations

import torch

from backend.service.application.runtime.yolox_core.utils.boxes import postprocess


def test_postprocess_accepts_inference_tensor_without_inplace_error() -> None:
    """验证 postprocess 可以处理 inference_mode 产出的 tensor。"""

    with torch.inference_mode():
        prediction = torch.tensor(
            [[
                [32.0, 32.0, 16.0, 16.0, 0.9, 0.8],
                [16.0, 16.0, 8.0, 8.0, 0.2, 0.7],
            ]],
            dtype=torch.float32,
        )

    outputs = postprocess(
        prediction,
        num_classes=1,
        conf_thre=0.1,
        nms_thre=0.45,
    )

    assert outputs[0] is not None
    assert tuple(float(value) for value in outputs[0][0, :4].tolist()) == (24.0, 24.0, 40.0, 40.0)
    assert tuple(float(value) for value in prediction[0, 0, :4].tolist()) == (32.0, 32.0, 16.0, 16.0)
    assert tuple(float(value) for value in prediction[0, 1, :4].tolist()) == (16.0, 16.0, 8.0, 8.0)