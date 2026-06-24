"""YOLO core 共用基础能力测试。"""

from __future__ import annotations

import numpy as np
import torch
import cv2

from backend.service.application.models.yolo_core_common import (
    Conv,
    DistributionFocalLossDecoder,
    OBB_ANGLE_DECODE_MODE_RAW,
    OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    build_detection_prediction,
    build_obb_prediction,
    decode_detection_boxes,
    decode_detection_training_predictions,
    decode_obb_angle_logits,
    decode_pose_keypoints,
    decode_segmentation_masks,
    dist2bbox_xyxy,
    dist2rbox,
    make_anchors,
)
from backend.service.application.models.yolo_core_common.assigners import (
    assign_detection_targets,
    assign_segmentation_targets,
    box_iou_aligned,
)
from backend.service.application.models.yolo_core_common.export import (
    normalize_segmentation_export_outputs,
    resolve_segmentation_export_output_names,
)
from backend.service.application.models.yolo_core_common.losses import (
    build_pose_box_area,
    build_pose_oks_sigmas,
    build_pose_visibility_mask,
    compute_obb_angle_loss,
    compute_oks_keypoint_loss,
    compute_segmentation_detection_loss,
    compute_segmentation_mask_loss,
    compute_visibility_loss,
    decode_pose_keypoints_xy,
    decode_segmentation_training_boxes,
    distribution_focal_loss,
    probiou_aligned,
    segmentation_bbox_iou_aligned,
)
from backend.service.application.models.yolo26_core.losses import (
    build_yolo26_pose_rle_weights,
    compute_yolo26_rle_loss,
)
from backend.service.application.models.yolo_core_common.postprocess import (
    build_segmentation_postprocess_instances,
    normalize_segmentation_outputs,
    postprocess_segmentation_prediction_array,
    prepare_detection_nms_inputs_array,
    prepare_detection_nms_inputs_tensor,
    prepare_segmentation_nms_inputs_array,
)
from backend.service.application.models.yolo_core_common.targets import (
    anchor_in_rotated_box,
    bbox_xyxy_to_distances,
    decode_distances_to_rboxes,
    normalize_gt_keypoints_tensor,
    rasterize_segmentation_polygons,
    rbox_to_distances,
    select_object_segmentation_polygons,
    xywhr_to_corners,
    xywhr_to_xyxy,
)
from backend.service.application.models.yolo26_core.tasks import OBB26, Pose26, Segment26


def test_yolo26_heads_live_in_yolo26_core() -> None:
    """验证 YOLO26 专用 head 留在 yolo26_core 边界内。"""

    assert Segment26.__module__.endswith("yolo26_core.nn.tasks.segmentation")
    assert Pose26.__module__.endswith("yolo26_core.nn.tasks.pose")
    assert OBB26.__module__.endswith("yolo26_core.nn.tasks.obb")
    assert not hasattr(Pose26, "_decode_keypoints_pose26")
    assert not hasattr(OBB26, "_decode_angle_logits")


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


def test_common_detection_training_decode_builds_loss_bundle() -> None:
    """验证 detection 训练态 decode 会返回 loss 所需的公共预测结构。"""

    feature = torch.zeros(1, 8, 1, 1)
    raw_outputs = {
        "boxes": torch.zeros(1, 16, 1),
        "scores": torch.zeros(1, 2, 1),
        "feats": (feature,),
    }
    head = torch.nn.Module()
    head.reg_max = 4
    head.strides = (8,)
    head.dfl = DistributionFocalLossDecoder(reg_max=4)

    prediction_bundle = decode_detection_training_predictions(
        torch_module=torch,
        detect_head=head,
        raw_outputs=raw_outputs,
    )

    assert prediction_bundle["distance_logits"].shape == (1, 1, 16)
    assert prediction_bundle["boxes_xyxy"].shape == (1, 1, 4)
    assert prediction_bundle["class_logits"].shape == (1, 1, 2)
    assert prediction_bundle["anchor_points"].tolist() == [[0.5, 0.5]]
    assert prediction_bundle["stride_tensor"].tolist() == [[8.0]]
    assert prediction_bundle["reg_max"] == 4


def test_common_detection_assigner_target_and_dfl_loss() -> None:
    """验证 detection assigner、target 编码和 DFL loss 可以独立工作。"""

    pred_boxes = torch.tensor(
        [
            [0.0, 0.0, 16.0, 16.0],
            [100.0, 100.0, 120.0, 120.0],
        ]
    )
    class_probabilities = torch.tensor([[0.9, 0.1], [0.1, 0.8]])
    anchor_centers_xy = torch.tensor([[8.0, 8.0], [110.0, 110.0]])
    gt_boxes = torch.tensor([[0.0, 0.0, 16.0, 16.0]])
    gt_classes = torch.tensor([0], dtype=torch.long)

    assignment = assign_detection_targets(
        torch_module=torch,
        pred_boxes=pred_boxes,
        class_probabilities=class_probabilities,
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=gt_boxes,
        gt_classes=gt_classes,
        topk=1,
        alpha=0.5,
        beta=6.0,
    )
    target_distances = bbox_xyxy_to_distances(
        torch_module=torch,
        boxes_xyxy=gt_boxes,
        anchor_points=torch.tensor([[1.0, 1.0]]),
        stride_tensor=torch.tensor([[8.0]]),
        reg_max=4,
    )
    dfl_loss = distribution_focal_loss(
        torch_module=torch,
        logits=torch.zeros(1, 4, 4),
        target=target_distances,
    )

    assert assignment["foreground_mask"].tolist() == [True, False]
    assert assignment["assigned_gt_indices"].tolist() == [0, -1]
    assert torch.isclose(assignment["quality_scores"][0], torch.tensor(1.0)).item() is True
    assert torch.allclose(box_iou_aligned(torch_module=torch, boxes1=gt_boxes, boxes2=gt_boxes), torch.ones(1))
    assert target_distances.tolist() == [[1.0, 1.0, 1.0, 1.0]]
    assert dfl_loss.shape == (1,)
    assert torch.isfinite(dfl_loss).all().item() is True


def test_common_segmentation_assigner_and_detection_loss() -> None:
    """验证 segmentation assigner 和检测损失编排可独立工作。"""

    prediction = torch.zeros(2, 6)
    prediction[:, :4] = torch.tensor(
        [
            [4.0, 4.0, 4.0, 4.0],
            [4.0, 4.0, 4.0, 4.0],
        ]
    )
    prediction[0, 4] = 5.0
    prediction[1, 5] = 5.0
    anchor_points = torch.tensor([[8.0, 8.0], [32.0, 32.0]])
    stride_tensor = torch.tensor([[8.0], [8.0]])
    targets = {
        "boxes": [[4.0, 4.0, 12.0, 12.0]],
        "class_ids": [0],
    }

    assignment = assign_segmentation_targets(
        torch_module=torch,
        targets=targets,
        prediction=prediction,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
        topk=1,
        alpha=0.5,
        beta=6.0,
        num_classes=2,
    )

    assert assignment is not None
    assert assignment.fg_mask.tolist() == [True, False]
    decoded_boxes = decode_segmentation_training_boxes(
        torch_module=torch,
        prediction=prediction,
        anchor_points=anchor_points,
    )
    iou = segmentation_bbox_iou_aligned(
        torch_module=torch,
        boxes1=decoded_boxes[:1],
        boxes2=torch.tensor([[4.0, 4.0, 12.0, 12.0]]),
    )
    class_loss, box_loss, dfl_loss = compute_segmentation_detection_loss(
        torch_module=torch,
        prediction=prediction,
        assignment=assignment,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
        dfl_weight=1.5,
        num_classes=2,
    )

    assert torch.allclose(decoded_boxes[0], torch.tensor([4.0, 4.0, 12.0, 12.0]))
    assert torch.allclose(iou, torch.ones(1))
    assert torch.isfinite(class_loss).item() is True
    assert torch.isclose(box_loss, torch.tensor(0.0)).item() is True
    assert torch.isclose(dfl_loss, torch.tensor(0.0)).item() is True


def test_common_pose_decode_supports_standard_and_yolo26_offsets() -> None:
    """验证 pose decode 可显式区分标准 YOLO 和 YOLO26 偏移规则。"""

    feature = torch.zeros(1, 4, 1, 1)
    raw_outputs = {
        "kpts": torch.tensor([[[1.0], [2.0], [0.0]]]),
        "feats": (feature,),
    }

    standard = decode_pose_keypoints(
        raw_outputs=raw_outputs,
        strides=(8,),
        keypoint_shape=(1, 3),
        offset_multiplier=2.0,
        anchor_offset=-0.5,
    )
    yolo26 = decode_pose_keypoints(
        raw_outputs=raw_outputs,
        strides=(8,),
        keypoint_shape=(1, 3),
        offset_multiplier=1.0,
        anchor_offset=0.0,
    )

    assert standard.shape == (1, 3, 1)
    assert torch.allclose(standard, torch.tensor([[[16.0], [32.0], [0.5]]]))
    assert torch.allclose(yolo26, torch.tensor([[[12.0], [20.0], [0.5]]]))


def test_common_pose_losses_compute_keypoint_and_visibility() -> None:
    """验证 common pose loss 辅助函数可以脱离训练 service 独立工作。"""

    pred_xy = torch.tensor([[[0.0, 0.0], [2.0, 2.0]]])
    gt_keypoints = torch.tensor([[[0.0, 0.0, 2.0], [4.0, 2.0, 1.0]]])
    keypoint_mask = build_pose_visibility_mask(
        torch_module=torch,
        gt_keypoints=gt_keypoints,
        keypoint_dim=3,
    )
    area = build_pose_box_area(gt_boxes=torch.tensor([[0.0, 0.0, 4.0, 4.0]]))
    sigmas = build_pose_oks_sigmas(
        torch_module=torch,
        num_keypoints=2,
        device=pred_xy.device,
        dtype=pred_xy.dtype,
    )

    keypoint_loss = compute_oks_keypoint_loss(
        torch_module=torch,
        pred_keypoints_xy=pred_xy,
        gt_keypoints_xy=gt_keypoints[..., :2],
        keypoint_mask=keypoint_mask,
        area=area,
        sigmas=sigmas,
    )
    visibility_loss = compute_visibility_loss(
        torch_module=torch,
        pred_visibility_logits=torch.zeros(1, 2),
        keypoint_mask=keypoint_mask,
    )
    standard_xy = decode_pose_keypoints_xy(
        pred_xy=torch.ones(1, 2, 2),
        anchors_xy=torch.tensor([[4.0, 8.0]]),
        strides=torch.tensor([[2.0]]),
        is_pose26=False,
    )
    pose26_xy = decode_pose_keypoints_xy(
        pred_xy=torch.ones(1, 2, 2),
        anchors_xy=torch.tensor([[4.0, 8.0]]),
        strides=torch.tensor([[2.0]]),
        is_pose26=True,
    )

    assert keypoint_mask.tolist() == [[True, True]]
    assert torch.isfinite(keypoint_loss).item() is True
    assert torch.isfinite(visibility_loss).item() is True
    assert torch.allclose(standard_xy, torch.tensor([[[8.0, 12.0], [8.0, 12.0]]]))
    assert torch.allclose(pose26_xy, torch.tensor([[[6.0, 10.0], [6.0, 10.0]]]))


def test_yolo26_pose_rle_loss_lives_in_yolo26_core() -> None:
    """验证 YOLO26 pose RLE loss 留在 yolo26_core 边界内。"""

    pred_xy = torch.tensor([[[0.0, 0.0], [2.0, 2.0]]])
    gt_keypoints = torch.tensor([[[0.0, 0.0, 2.0], [4.0, 2.0, 1.0]]])
    keypoint_mask = build_pose_visibility_mask(
        torch_module=torch,
        gt_keypoints=gt_keypoints,
        keypoint_dim=3,
    )
    rle_loss = compute_yolo26_rle_loss(
        torch_module=torch,
        flow_model=_DummyPoseFlowModel(),
        pred_keypoints_xy=pred_xy,
        pred_sigma_logits=torch.zeros(1, 2, 2),
        gt_keypoints_xy=gt_keypoints[..., :2],
        keypoint_mask=keypoint_mask,
        target_weights=build_yolo26_pose_rle_weights(
            torch_module=torch,
            num_keypoints=2,
            device=pred_xy.device,
            dtype=pred_xy.dtype,
        ),
    )

    assert torch.isfinite(rle_loss).item() is True


def test_common_pose_target_normalizes_list_and_tensor_keypoints() -> None:
    """验证 pose target 编码会规整 list 和 tensor 两类关键点输入。"""

    assigned_indices = torch.tensor([1, 0], dtype=torch.long)
    list_keypoints = [
        [1.0, 2.0, 2.0, 3.0, 4.0, 1.0],
        [5.0, 6.0, 2.0, 7.0, 8.0, 1.0],
    ]
    tensor_keypoints = torch.tensor(
        [
            [[1.0, 2.0, 2.0], [3.0, 4.0, 1.0]],
            [[5.0, 6.0, 2.0], [7.0, 8.0, 1.0]],
        ]
    )

    normalized_from_list = normalize_gt_keypoints_tensor(
        torch_module=torch,
        raw_keypoints=list_keypoints,
        assigned_indices=assigned_indices,
        num_keypoints=2,
        keypoint_dim=3,
        device=torch.device("cpu"),
        dtype=torch.float32,
    )
    normalized_from_tensor = normalize_gt_keypoints_tensor(
        torch_module=torch,
        raw_keypoints=tensor_keypoints,
        assigned_indices=assigned_indices,
        num_keypoints=2,
        keypoint_dim=3,
        device=torch.device("cpu"),
        dtype=torch.float32,
    )

    expected = torch.tensor(
        [
            [[5.0, 6.0, 2.0], [7.0, 8.0, 1.0]],
            [[1.0, 2.0, 2.0], [3.0, 4.0, 1.0]],
        ]
    )
    assert torch.allclose(normalized_from_list, expected)
    assert torch.allclose(normalized_from_tensor, expected)


def test_common_obb_angle_decode_supports_standard_and_raw_modes() -> None:
    """验证 OBB angle decode 可显式区分标准模式和 YOLO26 raw 模式。"""

    angle_logits = torch.zeros(1, 1, 1)

    standard = decode_obb_angle_logits(
        angle_logits=angle_logits,
        mode=OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    )
    raw = decode_obb_angle_logits(
        angle_logits=angle_logits,
        mode=OBB_ANGLE_DECODE_MODE_RAW,
    )

    assert torch.allclose(standard, torch.full_like(standard, torch.pi / 4))
    assert torch.allclose(raw, torch.zeros_like(raw))


def test_common_obb_decode_builds_prediction_tensor() -> None:
    """验证 OBB decode 入口会组装旋转框、类别分数和角度。"""

    feature = torch.zeros(1, 8, 1, 1)
    raw_outputs = {
        "boxes": torch.zeros(1, 16, 1),
        "scores": torch.zeros(1, 2, 1),
        "angle": torch.zeros(1, 1, 1),
        "feats": (feature,),
    }
    decoder = DistributionFocalLossDecoder(reg_max=4)

    prediction = build_obb_prediction(
        raw_outputs=raw_outputs,
        strides=(8,),
        dfl_decoder=decoder,
        angle_decode_mode=OBB_ANGLE_DECODE_MODE_RAW,
    )

    assert prediction.shape == (1, 7, 1)
    assert torch.allclose(prediction[:, 4:6, :], torch.full((1, 2, 1), 0.5))
    assert torch.allclose(prediction[:, 6:, :], torch.zeros(1, 1, 1))


def test_common_obb_loss_and_target_helpers_work_independently() -> None:
    """验证 OBB loss、target 编码和旋转框几何辅助函数可以独立工作。"""

    rboxes = torch.tensor([[10.0, 10.0, 4.0, 2.0, 0.0]])
    probiou = probiou_aligned(torch_module=torch, obb1=rboxes, obb2=rboxes)
    corners = xywhr_to_corners(torch_module=torch, rboxes=rboxes)
    inside_mask = anchor_in_rotated_box(
        torch_module=torch,
        anchor_points=torch.tensor([[10.0, 10.0], [20.0, 20.0]]),
        corners=corners,
    )
    encoded_distances = rbox_to_distances(
        torch_module=torch,
        rboxes=rboxes,
        anchor_points=torch.tensor([[1.25, 1.25]]),
        stride_tensor=torch.tensor([[8.0]]),
        reg_max=4,
    )
    decoded_rboxes = decode_distances_to_rboxes(
        torch_module=torch,
        pred_dist=torch.tensor([[[1.0, 1.0, 1.0, 1.0]]]),
        pred_angle=torch.zeros(1, 1, 1),
        anchor_points=torch.tensor([[[2.0, 3.0]]]),
    )
    angle_loss = compute_obb_angle_loss(
        torch_module=torch,
        pred_angle=torch.zeros(1, 1),
        gt_angle=torch.zeros(1, 1),
        gt_wh=torch.tensor([[4.0, 2.0]]),
        target_scores=torch.ones(1),
    )
    xyxy = xywhr_to_xyxy(torch_module=torch, rboxes=rboxes)

    assert probiou.shape == (1,)
    assert probiou.item() > 0.999
    assert corners.shape == (1, 4, 2)
    assert inside_mask.tolist() == [[True, False]]
    assert encoded_distances.tolist() == [[0.25, 0.125, 0.25, 0.125]]
    assert torch.allclose(decoded_rboxes, torch.tensor([[[2.0, 3.0, 2.0, 2.0, 0.0]]]))
    assert torch.allclose(angle_loss, torch.zeros(()))
    assert xyxy.tolist() == [[8.0, 9.0, 12.0, 11.0]]


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


def test_common_segmentation_nms_inputs_preserve_mask_coefficients() -> None:
    """验证 segmentation NMS 前置后处理会保留 mask coeff。"""

    image_prediction = np.asarray(
        [
            [0.0, 0.0, 10.0, 10.0, 0.1, 0.8, 0.25, 0.5],
            [1.0, 1.0, 2.0, 2.0, 0.7, 0.2, 0.75, 1.0],
            [3.0, 3.0, 4.0, 4.0, 0.2, 0.3, 0.10, 0.2],
        ],
        dtype=np.float32,
    )

    nms_inputs = prepare_segmentation_nms_inputs_array(
        image_prediction=image_prediction,
        np_module=np,
        num_classes=2,
        score_threshold=0.5,
    )

    assert nms_inputs is not None
    assert nms_inputs.boxes_xyxy.shape == (2, 4)
    assert nms_inputs.scores.tolist() == [0.800000011920929, 0.699999988079071]
    assert nms_inputs.class_ids.tolist() == [1, 0]
    assert nms_inputs.mask_coefficients.tolist() == [[0.25, 0.5], [0.75, 1.0]]


def test_common_segmentation_mask_decode_thresholds_proto_masks() -> None:
    """验证 segmentation mask decode 会把 proto 与 coeff 还原为二值 mask。"""

    proto = np.asarray([[[10.0, -10.0], [-10.0, 10.0]]], dtype=np.float32)
    mask_coefficients = np.asarray([[1.0]], dtype=np.float32)

    masks = decode_segmentation_masks(
        cv2_module=cv2,
        np_module=np,
        proto=proto,
        mask_coefficients=mask_coefficients,
        input_size=(2, 2),
        resized_width=2,
        resized_height=2,
        image_width=2,
        image_height=2,
        mask_threshold=0.5,
    )

    assert len(masks) == 1
    assert masks[0].dtype == np.uint8
    assert masks[0].tolist() == [[1, 0], [0, 1]]


def test_common_segmentation_full_postprocess_builds_instances() -> None:
    """验证 segmentation 完整后处理会生成 bbox、mask 面积和类别实例。"""

    prediction_array, proto_array = normalize_segmentation_outputs(
        outputs=(
            np.asarray([[0.0, 0.0, 2.0, 2.0, 0.9, 1.0]], dtype=np.float32),
            np.asarray([[[10.0, 10.0], [10.0, 10.0]]], dtype=np.float32),
        ),
        np_module=np,
    )

    nms_results = postprocess_segmentation_prediction_array(
        prediction_array=prediction_array,
        np_module=np,
        num_classes=1,
        score_threshold=0.5,
        nms_threshold=0.65,
        nms_indices_func=_keep_all_nms_indices,
    )
    instances = build_segmentation_postprocess_instances(
        cv2_module=cv2,
        np_module=np,
        prediction_array=prediction_array,
        proto_array=proto_array,
        labels=("defect",),
        score_threshold=0.5,
        nms_threshold=0.65,
        mask_threshold=0.5,
        resize_ratio=1.0,
        image_width=2,
        image_height=2,
        input_size=(2, 2),
        nms_indices_func=_keep_all_nms_indices,
    )

    assert nms_results[0] is not None
    assert nms_results[0].scores.tolist() == [0.8999999761581421]
    assert len(instances) == 1
    assert instances[0].bbox_xyxy == (0.0, 0.0, 2.0, 2.0)
    assert instances[0].class_name == "defect"
    assert instances[0].mask_area == 4.0


def test_common_segmentation_export_boundary_requires_prediction_and_proto() -> None:
    """验证 segmentation export 边界固定为 prediction/proto 双输出。"""

    prediction = np.zeros((1, 1, 6), dtype=np.float32)
    proto = np.zeros((1, 1, 2, 2), dtype=np.float32)

    normalized_prediction, normalized_proto = normalize_segmentation_export_outputs(
        outputs=[prediction, proto],
    )

    assert resolve_segmentation_export_output_names() == ("predictions", "proto")
    assert normalized_prediction is prediction
    assert normalized_proto is proto


def test_common_segmentation_mask_target_and_loss_helpers_work_independently() -> None:
    """验证 segmentation polygon target 和 mask loss 可以独立工作。"""

    segmentations = [[2.0, 2.0, 6.0, 2.0, 6.0, 6.0, 2.0, 6.0]]
    polygons = select_object_segmentation_polygons(
        segmentations,
        object_index=0,
        object_count=1,
    )
    mask, valid = rasterize_segmentation_polygons(
        cv2_module=cv2,
        np_module=np,
        polygons=polygons,
        output_size=(8, 8),
        resize_scale=1.0,
        pad_xy=(0, 0),
    )
    prediction = torch.tensor(
        [
            [0.0, 0.0, 1.0, 1.0, 4.0, 1.0],
            [0.0, 0.0, 1.0, 1.0, -4.0, -1.0],
        ],
        dtype=torch.float32,
    )
    proto = torch.zeros(1, 2, 2)
    proto[0, 0, 0] = 1.0
    proto[0, 0, 1] = -1.0
    proto[0, 1, 0] = -1.0
    proto[0, 1, 1] = -1.0
    target_masks = torch.tensor(
        [
            [
                [1.0, 0.0],
                [0.0, 0.0],
            ]
        ]
    )
    mask_loss = compute_segmentation_mask_loss(
        torch_module=torch,
        prediction=prediction,
        proto=proto,
        foreground_mask=torch.tensor([True, False]),
        target_masks=target_masks,
        target_mask_valid=torch.tensor([True]),
        matched_gt_indices=torch.tensor([0, 0]),
        num_classes=1,
    )

    assert valid is True
    assert int(mask.sum()) > 0
    assert torch.isfinite(mask_loss).item() is True
    assert float(mask_loss.item()) < 0.5


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


def _keep_all_nms_indices(*, scores, np_module, **_kwargs):
    """测试用 NMS：保留所有候选。"""

    return np_module.arange(int(scores.shape[0]))


class _DummyPoseFlowModel:
    """测试用的最小 flow 模型。"""

    def log_prob(self, x: torch.Tensor) -> torch.Tensor:
        """返回稳定的伪 log probability。"""

        return -(x.pow(2).sum(dim=1))
