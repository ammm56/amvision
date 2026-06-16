"""YOLOX boxes 工具回归测试。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from backend.service.application.models.yolox_core.postprocess import (
    build_yolox_detection_records,
    ensure_yolox_prediction_array,
    postprocess_yolox_prediction_array,
)
from backend.service.application.models.yolox_core.utils.boxes import postprocess


@dataclass(frozen=True)
class _DetectionRecord:
    """测试用 detection 记录。"""

    bbox_xyxy: tuple[float, float, float, float]
    score: float
    class_id: int
    class_name: str | None


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


def test_runtime_numpy_postprocess_filters_nms_and_builds_records() -> None:
    """验证 runtime 使用的 NumPy 后处理会执行分数过滤、NMS 和记录组装。"""

    prediction_array = ensure_yolox_prediction_array(
        prediction_value=np.asarray(
            [
                [
                    [50.0, 50.0, 20.0, 20.0, 0.9, 0.8, 0.1],
                    [52.0, 50.0, 20.0, 20.0, 0.85, 0.7, 0.2],
                    [120.0, 120.0, 10.0, 10.0, 0.6, 0.2, 0.9],
                    [20.0, 20.0, 8.0, 8.0, 0.1, 0.8, 0.1],
                ]
            ],
            dtype=np.float32,
        ),
        np_module=np,
        backend_name="test",
    )

    predictions = postprocess_yolox_prediction_array(
        prediction_array=prediction_array,
        np_module=np,
        num_classes=2,
        conf_thre=0.3,
        nms_thre=0.45,
    )
    records = build_yolox_detection_records(
        np_module=np,
        predictions=predictions,
        resize_ratio=1.0,
        labels=("defect", "part"),
        image_width=200,
        image_height=200,
        detection_factory=_DetectionRecord,
    )

    assert [record.class_name for record in records] == ["defect", "part"]
    assert [record.score for record in records] == [0.72, 0.54]
    assert records[0].bbox_xyxy == (40.0, 40.0, 60.0, 60.0)
    assert records[1].bbox_xyxy == (115.0, 115.0, 125.0, 125.0)
