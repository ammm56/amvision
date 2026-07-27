"""YOLOE 非方形 LetterBox 正反变换回归测试。"""

from __future__ import annotations

import io

import cv2
import numpy as np
import pytest
import torch
from PIL import Image

from backend.service.application.models.yolo_core_common.geometry import (
    build_yolo_letterbox_transform,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.core.postprocess.segmentation import (
    postprocess_prompt_free_outputs,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.core.prompts.visual import (
    build_visual_prompt_tensor,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.payloads.types import (
    YoloeVisualPromptItem,
)


def test_yoloe_postprocess_restores_non_square_box_and_mask_with_odd_padding() -> None:
    """验证非方形原图和奇数 padding 会正确反算 bbox 与 mask。"""

    transform = build_yolo_letterbox_transform(
        source_width=101,
        source_height=51,
        input_size=(96, 128),
    )
    assert (transform.pad_top, transform.pad_bottom) == (15, 16)

    source_box = (10.0, 5.0, 90.0, 45.0)
    prediction = np.asarray(
        [
            [
                [
                    source_box[0] * transform.gain + transform.pad_left,
                    source_box[1] * transform.gain + transform.pad_top,
                    source_box[2] * transform.gain + transform.pad_left,
                    source_box[3] * transform.gain + transform.pad_top,
                    0.95,
                    10.0,
                ]
            ]
        ],
        dtype=np.float32,
    )
    proto = np.ones((1, 1, 24, 32), dtype=np.float32)

    detections, regions = postprocess_prompt_free_outputs(
        cv2_module=cv2,
        np_module=np,
        prediction_array=prediction,
        proto_array=proto,
        class_names={0: "part"},
        confidence_threshold=0.25,
        iou_threshold=0.7,
        max_detections=10,
        letterbox_transform=transform,
    )

    assert detections[0]["bbox_xyxy"] == pytest.approx(source_box, abs=1e-3)
    assert regions[0]["mask_width"] == 101
    assert regions[0]["mask_height"] == 51
    with Image.open(io.BytesIO(regions[0]["mask_png_bytes"])) as mask_image:
        restored_mask = np.asarray(mask_image)
    assert restored_mask.shape == (51, 101)
    assert np.all(restored_mask == 255)


def test_yoloe_visual_prompt_uses_same_non_square_letterbox_transform() -> None:
    """验证 visual prompt 与参考图共享非方形 LetterBox 几何。"""

    transform = build_yolo_letterbox_transform(
        source_width=101,
        source_height=51,
        input_size=(96, 128),
    )
    visual_tensor = build_visual_prompt_tensor(
        torch_module=torch,
        np_module=np,
        prompts=(
            YoloeVisualPromptItem(
                prompt_id="full-image",
                prompt_kind="box",
                bbox_xyxy=(0.0, 0.0, 101.0, 51.0),
                point_xy=None,
                point_label=None,
                polygon_xy=None,
                prompt_mask=None,
                display_name="full image",
            ),
        ),
        letterbox_transform=transform,
        device_name="cpu",
        dtype=torch.float32,
    )

    assert tuple(visual_tensor.shape) == (1, 1, 12, 16)
    assert int(torch.count_nonzero(visual_tensor[:, :, 0])) == 0
    assert int(torch.count_nonzero(visual_tensor[:, :, -1])) == 0
    assert int(torch.count_nonzero(visual_tensor[:, :, 2:10])) > 0
