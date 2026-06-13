"""YOLO core 共用基础能力测试。"""

from __future__ import annotations

import torch
import numpy as np

from backend.service.application.models import yolo_detection_model
from backend.service.application.models.yolo_core_common import (
    Classify,
    Conv,
    Detect,
    DistributionFocalLossDecoder,
    OBB,
    Pose,
    Segment,
    build_detection_prediction,
    decode_detection_boxes,
    dist2bbox_xyxy,
    dist2rbox,
    make_anchors,
)
from backend.service.application.models.yolo_core_common.postprocess import (
    prepare_detection_nms_inputs_array,
    prepare_detection_nms_inputs_tensor,
)
from backend.service.application.models.yolo26_core.tasks import OBB26, Pose26, Segment26


def test_yolo_detection_model_uses_common_conv_layer() -> None:
    """验证 detection 结构文件不再本地定义 Conv 基础层。"""

    assert yolo_detection_model.Conv is Conv
    assert yolo_detection_model.Conv.__module__.endswith("yolo_core_common.layers")


def test_yolo_detection_model_uses_common_task_heads() -> None:
    """验证 detection 结构文件不再本地定义通用任务 head。"""

    assert yolo_detection_model.Detect is Detect
    assert yolo_detection_model.Classify is Classify
    assert yolo_detection_model.Segment is Segment
    assert yolo_detection_model.Pose is Pose
    assert yolo_detection_model.OBB is OBB
    assert not hasattr(yolo_detection_model.Detect, "_decode_boxes")
    assert not hasattr(yolo_detection_model.Detect, "_build_inference_prediction")
    assert yolo_detection_model.Detect.__module__.endswith(
        "yolo_core_common.tasks.detection"
    )
    assert yolo_detection_model.Classify.__module__.endswith(
        "yolo_core_common.tasks.classification"
    )
    assert yolo_detection_model.Segment.__module__.endswith(
        "yolo_core_common.tasks.segmentation"
    )
    assert yolo_detection_model.Pose.__module__.endswith("yolo_core_common.tasks.pose")
    assert yolo_detection_model.OBB.__module__.endswith("yolo_core_common.tasks.obb")


def test_yolo26_heads_live_in_yolo26_core() -> None:
    """验证 YOLO26 专用 head 留在 yolo26_core 边界内。"""

    assert Segment26.__module__.endswith("yolo26_core.tasks.segmentation")
    assert Pose26.__module__.endswith("yolo26_core.tasks.pose")
    assert OBB26.__module__.endswith("yolo26_core.tasks.obb")


def test_common_conv_preserves_spatial_shape_with_same_padding() -> None:
    """验证 common Conv 的 same padding 行为。"""

    layer = Conv(3, 8, k=3, s=1)
    layer.eval()

    with torch.inference_mode():
        output = layer(torch.randn(2, 3, 16, 16))

    assert output.shape == (2, 8, 16, 16)


def test_common_dfl_decoder_returns_distance_channels() -> None:
    """验证 DFL 解码器输出 4 个距离通道。"""

    decoder = DistributionFocalLossDecoder(reg_max=4)
    logits = torch.zeros(1, 16, 3)

    distances = decoder(logits)

    assert distances.shape == (1, 4, 3)
    assert torch.allclose(distances, torch.full_like(distances, 1.5))


def test_common_anchor_and_bbox_decode_match_expected_grid() -> None:
    """验证 anchor 生成和 xyxy 解码的基础几何行为。"""

    feature = torch.zeros(1, 4, 2, 2)
    anchor_points, stride_tensor = make_anchors(
        feature_maps=(feature,),
        strides=(8,),
    )
    distances = torch.ones(1, 4, 4)

    decoded = dist2bbox_xyxy(
        distances=distances,
        anchor_points=anchor_points.unsqueeze(0),
        stride_tensor=stride_tensor.unsqueeze(0),
    )

    assert anchor_points.tolist() == [
        [0.5, 0.5],
        [1.5, 0.5],
        [0.5, 1.5],
        [1.5, 1.5],
    ]
    assert decoded.shape == (1, 4, 4)
    assert decoded[0, :, 0].tolist() == [-4.0, -4.0, 12.0, 12.0]


def test_common_detection_decode_builds_prediction_tensor() -> None:
    """验证 detection decode 入口会组装 box 与类别分数。"""

    feature = torch.zeros(1, 8, 1, 2)
    raw_outputs = {
        "boxes": torch.zeros(1, 16, 2),
        "scores": torch.zeros(1, 2, 2),
        "feats": (feature,),
    }
    decoder = DistributionFocalLossDecoder(reg_max=4)

    decoded_boxes = decode_detection_boxes(
        raw_outputs=raw_outputs,
        strides=(8,),
        dfl_decoder=decoder,
    )
    prediction = build_detection_prediction(
        raw_outputs=raw_outputs,
        strides=(8,),
        dfl_decoder=decoder,
    )

    assert decoded_boxes.shape == (1, 4, 2)
    assert prediction.shape == (1, 6, 2)
    assert torch.allclose(prediction[:, 4:, :], torch.full((1, 2, 2), 0.5))


def test_common_detection_tensor_nms_inputs_filter_candidates() -> None:
    """验证 tensor 版 NMS 前置后处理会筛出高分候选。"""

    prediction = torch.tensor(
        [
            [
                [0.0, 0.0, 10.0, 10.0, 0.1, 0.8],
                [1.0, 1.0, 2.0, 2.0, 0.7, 0.2],
                [3.0, 3.0, 4.0, 4.0, 0.2, 0.3],
            ]
        ]
    )

    nms_inputs = prepare_detection_nms_inputs_tensor(
        prediction_tensor=prediction,
        num_classes=2,
        score_threshold=0.5,
    )

    assert nms_inputs is not None
    assert nms_inputs.boxes_xyxy.shape == (2, 4)
    assert nms_inputs.scores.tolist() == [0.800000011920929, 0.699999988079071]
    assert nms_inputs.class_ids.tolist() == [1, 0]
    assert nms_inputs.batch_indices.tolist() == [0, 0]


def test_common_detection_array_nms_inputs_filter_candidates() -> None:
    """验证数组版 NMS 前置后处理会筛出高分候选。"""

    image_prediction = np.asarray(
        [
            [0.0, 0.0, 10.0, 10.0, 0.1, 0.8],
            [1.0, 1.0, 2.0, 2.0, 0.7, 0.2],
            [3.0, 3.0, 4.0, 4.0, 0.2, 0.3],
        ],
        dtype=np.float32,
    )

    nms_inputs = prepare_detection_nms_inputs_array(
        image_prediction=image_prediction,
        np_module=np,
        num_classes=2,
        score_threshold=0.5,
    )

    assert nms_inputs is not None
    assert nms_inputs.boxes_xyxy.shape == (2, 4)
    assert nms_inputs.scores.tolist() == [0.800000011920929, 0.699999988079071]
    assert nms_inputs.class_ids.tolist() == [1, 0]


def test_common_rotated_bbox_decode_preserves_axis_aligned_width_height() -> None:
    """验证零角度 rotated bbox 解码会保留距离宽高。"""

    distances = torch.tensor([[[1.0], [2.0], [3.0], [4.0]]])
    angle = torch.zeros(1, 1, 1)
    anchor_points = torch.tensor([[10.0, 20.0]])

    decoded = dist2rbox(
        pred_dist=distances,
        pred_angle=angle,
        anchor_points=anchor_points,
    )

    assert decoded.shape == (1, 4, 1)
    assert torch.allclose(
        decoded,
        torch.tensor([[[12.0], [22.0], [4.0], [6.0]]]),
    )
