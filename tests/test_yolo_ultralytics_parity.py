"""YOLOv8/11/26 与已固化参考公式的关键训练行为一致性测试。"""

from __future__ import annotations

import gc
import math
from types import SimpleNamespace
from typing import Any, Callable

import pytest
import torch

from backend.service.application.models.yolo11_core import (
    build_yolo11_model,
    compute_yolo11_detection_loss,
    load_yolo11_state_dict,
)
from backend.service.application.models.yolo11_core.assigners import (
    assign_yolo11_detection_targets,
    assign_yolo11_obb_targets,
)
from backend.service.application.models.yolo26_core import (
    build_yolo26_model,
    load_yolo26_state_dict,
)
from backend.service.application.models.yolo26_core.assigners import (
    assign_yolo26_detection_targets,
    assign_yolo26_obb_targets,
)
from backend.service.application.models.yolo26_core.losses import (
    compute_yolo26_detection_loss,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
)
from backend.service.application.models.yolov8_core import (
    build_yolov8_model,
    compute_yolov8_detection_loss,
    load_yolov8_state_dict,
)
from backend.service.application.models.yolov8_core.assigners import (
    assign_yolov8_detection_targets,
    assign_yolov8_obb_targets,
)
from backend.service.application.models.yolov8_core.decode import (
    decode_yolov8_pose_keypoints_xy,
)
from backend.service.application.models.yolov8_core.targets import (
    yolov8_decode_distances_to_rboxes,
)


def _reference_bbox_ciou_matrix(boxes1: Any, boxes2: Any) -> Any:
    """独立实现 xyxy bbox 两两 CIoU 参考公式。"""

    eps = 1e-7
    box1 = boxes1[:, None, :]
    box2 = boxes2[None, :, :]
    b1_x1, b1_y1, b1_x2, b1_y2 = box1.chunk(4, dim=-1)
    b2_x1, b2_y1, b2_x2, b2_y2 = box2.chunk(4, dim=-1)
    width1 = b1_x2 - b1_x1
    height1 = b1_y2 - b1_y1 + eps
    width2 = b2_x2 - b2_x1
    height2 = b2_y2 - b2_y1 + eps
    intersection = (
        (b1_x2.minimum(b2_x2) - b1_x1.maximum(b2_x1)).clamp_min(0.0)
        * (b1_y2.minimum(b2_y2) - b1_y1.maximum(b2_y1)).clamp_min(0.0)
    )
    union = width1 * height1 + width2 * height2 - intersection + eps
    iou = intersection / union
    convex_width = b1_x2.maximum(b2_x2) - b1_x1.minimum(b2_x1)
    convex_height = b1_y2.maximum(b2_y2) - b1_y1.minimum(b2_y1)
    convex_diagonal = convex_width.pow(2) + convex_height.pow(2) + eps
    center_distance = (
        (b2_x1 + b2_x2 - b1_x1 - b1_x2).pow(2)
        + (b2_y1 + b2_y2 - b1_y1 - b1_y2).pow(2)
    ) / 4.0
    aspect_penalty = (4.0 / math.pi**2) * (
        (width2 / height2).atan() - (width1 / height1).atan()
    ).pow(2)
    with torch.no_grad():
        aspect_weight = aspect_penalty / (
            aspect_penalty - iou + (1.0 + eps)
        )
    return (
        iou - (center_distance / convex_diagonal + aspect_weight * aspect_penalty)
    ).squeeze(-1)


def _reference_probiou_aligned(rboxes1: Any, rboxes2: Any) -> Any:
    """独立实现一一对应旋转框的 probabilistic IoU 参考公式。"""

    eps = 1e-7
    x1, y1 = rboxes1[..., :2].split(1, dim=-1)
    x2, y2 = rboxes2[..., :2].split(1, dim=-1)
    a1, b1, c1 = _reference_obb_covariance(rboxes1)
    a2, b2, c2 = _reference_obb_covariance(rboxes2)
    denominator = (a1 + a2) * (b1 + b2) - (c1 + c2).pow(2) + eps
    mean_term = (
        (
            (a1 + a2) * (y1 - y2).pow(2)
            + (b1 + b2) * (x1 - x2).pow(2)
        )
        / denominator
    ) * 0.25
    cross_term = (
        ((c1 + c2) * (x2 - x1) * (y1 - y2)) / denominator
    ) * 0.5
    determinant1 = (a1 * b1 - c1.pow(2)).clamp_min(0.0)
    determinant2 = (a2 * b2 - c2.pow(2)).clamp_min(0.0)
    determinant_sum = (a1 + a2) * (b1 + b2) - (c1 + c2).pow(2)
    scale_term = (
        determinant_sum
        / (4.0 * (determinant1 * determinant2).sqrt() + eps)
        + eps
    ).log() * 0.5
    bhattacharyya_distance = (mean_term + cross_term + scale_term).clamp(
        eps,
        100.0,
    )
    hellinger_distance = (
        1.0 - (-bhattacharyya_distance).exp() + eps
    ).sqrt()
    return (1.0 - hellinger_distance).squeeze(-1)


def _reference_obb_covariance(rboxes: Any) -> tuple[Any, Any, Any]:
    """按旋转框宽高和角度计算协方差三元组。"""

    width = rboxes[..., 2:3]
    height = rboxes[..., 3:4]
    angle = rboxes[..., 4:5]
    a = width.pow(2) / 12.0
    b = height.pow(2) / 12.0
    cosine = angle.cos()
    sine = angle.sin()
    return (
        a * cosine.pow(2) + b * sine.pow(2),
        a * sine.pow(2) + b * cosine.pow(2),
        (a - b) * cosine * sine,
    )


def _reference_probiou_matrix(rboxes1: Any, rboxes2: Any) -> Any:
    """计算两组旋转框的两两 probabilistic IoU。"""

    count1 = int(rboxes1.shape[0])
    count2 = int(rboxes2.shape[0])
    expanded1 = rboxes1[:, None, :].expand(-1, count2, -1).reshape(-1, 5)
    expanded2 = rboxes2[None, :, :].expand(count1, -1, -1).reshape(-1, 5)
    return _reference_probiou_aligned(expanded1, expanded2).view(count1, count2)


def _reference_xyxy_inside_mask(
    *,
    anchor_centers: Any,
    gt_boxes: Any,
    minimum_size: float,
    replacement_size: float,
) -> Any:
    """按 tiny box 扩张规则计算水平框候选区域。"""

    centers = (gt_boxes[:, :2] + gt_boxes[:, 2:]) * 0.5
    sizes = gt_boxes[:, 2:] - gt_boxes[:, :2]
    candidate_sizes = torch.where(
        sizes < float(minimum_size),
        torch.full_like(sizes, float(replacement_size)),
        sizes,
    )
    half_sizes = candidate_sizes * 0.5
    candidate_boxes = torch.cat(
        (centers - half_sizes, centers + half_sizes),
        dim=1,
    )
    deltas = torch.cat(
        (
            anchor_centers[None] - candidate_boxes[:, None, :2],
            candidate_boxes[:, None, 2:] - anchor_centers[None],
        ),
        dim=-1,
    )
    return deltas.amin(dim=-1) > 1e-9


def _reference_rbox_inside_mask(
    *,
    anchor_centers: Any,
    gt_rboxes: Any,
) -> Any:
    """按旋转框四边形计算候选 anchor。"""

    center_x, center_y, width, height, angle = gt_rboxes.unbind(dim=-1)
    cosine = angle.cos()
    sine = angle.sin()
    half_width = width * 0.5
    half_height = height * 0.5
    dx = torch.stack(
        (-half_width, half_width, half_width, -half_width),
        dim=-1,
    )
    dy = torch.stack(
        (-half_height, -half_height, half_height, half_height),
        dim=-1,
    )
    corners = torch.stack(
        (
            dx * cosine.unsqueeze(-1)
            - dy * sine.unsqueeze(-1)
            + center_x.unsqueeze(-1),
            dx * sine.unsqueeze(-1)
            + dy * cosine.unsqueeze(-1)
            + center_y.unsqueeze(-1),
        ),
        dim=-1,
    )
    point_a = corners[:, 0:1]
    vector_ab = corners[:, 1:2] - point_a
    vector_ad = corners[:, 3:4] - point_a
    vector_ap = anchor_centers.view(1, -1, 2) - point_a
    dot_ab = (vector_ap * vector_ab).sum(dim=-1)
    dot_ad = (vector_ap * vector_ad).sum(dim=-1)
    norm_ab = (vector_ab * vector_ab).sum(dim=-1)
    norm_ad = (vector_ad * vector_ad).sum(dim=-1)
    return (
        (dot_ab >= 0)
        & (dot_ab <= norm_ab)
        & (dot_ad >= 0)
        & (dot_ad <= norm_ad)
    )


def _reference_task_aligned_assignment(
    *,
    overlaps: Any,
    inside_mask: Any,
    class_probabilities: Any,
    gt_classes: Any,
    topk: int,
    alpha: float,
    beta: float,
    topk2: int | None,
) -> dict[str, Any]:
    """固化 TAL 候选、冲突消解和 target score 归一化公式。"""

    gt_class_probabilities = class_probabilities[:, gt_classes].transpose(0, 1)
    alignment_metric = (
        gt_class_probabilities.pow(alpha)
        * overlaps.clamp_min(0.0).pow(beta)
        * inside_mask.to(overlaps.dtype)
    )
    candidate_mask = torch.zeros_like(inside_mask)
    candidate_count = min(max(1, int(topk)), int(overlaps.shape[1]))
    candidate_indices = torch.topk(
        alignment_metric,
        k=candidate_count,
        dim=-1,
        largest=True,
    ).indices
    candidate_mask.scatter_(-1, candidate_indices, True)
    candidate_mask &= inside_mask

    foreground_counts = candidate_mask.sum(dim=0)
    if bool((foreground_counts > 1).any()):
        multi_gt_mask = (foreground_counts > 1).unsqueeze(0).expand_as(
            candidate_mask
        )
        highest_overlap_indices = overlaps.argmax(dim=0)
        highest_overlap_mask = torch.zeros_like(candidate_mask)
        highest_overlap_mask.scatter_(
            0,
            highest_overlap_indices.unsqueeze(0),
            True,
        )
        candidate_mask = torch.where(
            multi_gt_mask,
            highest_overlap_mask,
            candidate_mask,
        )

    if topk2 is not None and int(topk2) != int(topk):
        refined_count = min(max(1, int(topk2)), int(overlaps.shape[1]))
        refined_metric = alignment_metric * candidate_mask.to(
            alignment_metric.dtype
        )
        refined_indices = torch.topk(
            refined_metric,
            k=refined_count,
            dim=-1,
            largest=True,
        ).indices
        refined_mask = torch.zeros_like(candidate_mask)
        refined_mask.scatter_(-1, refined_indices, True)
        candidate_mask &= refined_mask

    foreground_mask = candidate_mask.any(dim=0)
    assigned_indices = candidate_mask.to(alignment_metric.dtype).argmax(dim=0)
    masked_alignment = alignment_metric * candidate_mask.to(
        alignment_metric.dtype
    )
    masked_overlaps = overlaps * candidate_mask.to(overlaps.dtype)
    max_alignment = masked_alignment.amax(dim=-1, keepdim=True)
    max_overlap = masked_overlaps.amax(dim=-1, keepdim=True)
    quality_scores = (
        masked_alignment * max_overlap / (max_alignment + 1e-9)
    ).amax(dim=0)
    quality_scores = quality_scores.where(
        foreground_mask,
        torch.zeros_like(quality_scores),
    )
    return {
        "foreground_mask": foreground_mask,
        "assigned_gt_indices": assigned_indices,
        "quality_scores": quality_scores,
    }


def _reference_make_anchors(
    *,
    raw_outputs: dict[str, Any],
    strides: tuple[int, ...],
) -> tuple[Any, Any]:
    """从 feature maps 独立构建中心偏移为 0.5 的 anchor 网格。"""

    anchor_groups: list[Any] = []
    stride_groups: list[Any] = []
    for feature_map, stride in zip(raw_outputs["feats"], strides, strict=True):
        height, width = feature_map.shape[-2:]
        y_grid, x_grid = torch.meshgrid(
            torch.arange(
                height,
                device=feature_map.device,
                dtype=feature_map.dtype,
            ),
            torch.arange(
                width,
                device=feature_map.device,
                dtype=feature_map.dtype,
            ),
            indexing="ij",
        )
        anchor_groups.append(
            torch.stack((x_grid, y_grid), dim=-1).reshape(-1, 2) + 0.5
        )
        stride_groups.append(
            torch.full(
                (height * width, 1),
                float(stride),
                device=feature_map.device,
                dtype=feature_map.dtype,
            )
        )
    return torch.cat(anchor_groups), torch.cat(stride_groups)


def _reference_detection_loss(
    *,
    raw_outputs: dict[str, Any],
    detect_head: Any,
    gt_boxes: Any,
    gt_classes: Any,
    box_weight: float,
    class_weight: float,
    dfl_weight: float,
) -> dict[str, Any]:
    """使用固化公式独立计算单图片 detection loss。"""

    class_logits = raw_outputs["scores"].permute(0, 2, 1).contiguous()[0]
    distance_logits = raw_outputs["boxes"].permute(0, 2, 1).contiguous()[0]
    reg_max = int(detect_head.reg_max)
    anchor_points, stride_tensor = _reference_make_anchors(
        raw_outputs=raw_outputs,
        strides=tuple(int(item) for item in detect_head.strides),
    )
    if reg_max > 1:
        distribution = distance_logits.view(-1, 4, reg_max).softmax(dim=-1)
        projection = torch.arange(
            reg_max,
            device=distribution.device,
            dtype=distribution.dtype,
        )
        distances = (distribution * projection).sum(dim=-1)
    else:
        distances = distance_logits.view(-1, 4)
    left_top, right_bottom = distances.chunk(2, dim=-1)
    pred_boxes_grid = torch.cat(
        (anchor_points - left_top, anchor_points + right_bottom),
        dim=-1,
    )
    pred_boxes_pixel = pred_boxes_grid * stride_tensor.repeat(1, 4)
    overlaps = _reference_bbox_ciou_matrix(gt_boxes, pred_boxes_pixel).clamp(
        0.0,
        1.0,
    )
    inside_mask = _reference_xyxy_inside_mask(
        anchor_centers=anchor_points * stride_tensor,
        gt_boxes=gt_boxes,
        minimum_size=float(detect_head.strides[0]),
        replacement_size=float(detect_head.strides[1]),
    )
    assignment = _reference_task_aligned_assignment(
        overlaps=overlaps,
        inside_mask=inside_mask,
        class_probabilities=class_logits.sigmoid(),
        gt_classes=gt_classes,
        topk=10,
        alpha=0.5,
        beta=6.0,
        topk2=None,
    )
    foreground_mask = assignment["foreground_mask"]
    assigned_indices = assignment["assigned_gt_indices"][foreground_mask]
    quality_scores = assignment["quality_scores"][foreground_mask]
    target_scores = torch.zeros_like(class_logits)
    target_scores[
        foreground_mask,
        gt_classes[assigned_indices],
    ] = quality_scores
    normalizer = quality_scores.sum().clamp_min(1.0)
    class_loss = torch.nn.functional.binary_cross_entropy_with_logits(
        class_logits,
        target_scores,
        reduction="sum",
    ) / normalizer

    foreground_stride = stride_tensor[foreground_mask]
    foreground_gt_boxes = gt_boxes[assigned_indices]
    foreground_pred_boxes = pred_boxes_grid[foreground_mask]
    foreground_gt_boxes_grid = (
        foreground_gt_boxes / foreground_stride.repeat(1, 4)
    )
    iou = _reference_bbox_ciou_matrix(
        foreground_pred_boxes,
        foreground_gt_boxes_grid,
    ).diagonal()
    box_loss = ((1.0 - iou) * quality_scores).sum() / normalizer

    target_distances = torch.cat(
        (
            anchor_points[foreground_mask]
            - foreground_gt_boxes_grid[:, :2],
            foreground_gt_boxes_grid[:, 2:]
            - anchor_points[foreground_mask],
        ),
        dim=-1,
    ).clamp_min(0.0)
    foreground_logits = distance_logits[foreground_mask].view(
        -1,
        4,
        reg_max,
    )
    if reg_max > 1:
        target_distances = target_distances.clamp(
            max=float(reg_max) - 1.0 - 0.01
        )
        target_left = target_distances.long()
        target_right = target_left + 1
        left_weight = target_right.to(target_distances.dtype) - target_distances
        right_weight = 1.0 - left_weight
        flat_logits = foreground_logits.reshape(-1, reg_max)
        dfl = (
            torch.nn.functional.cross_entropy(
                flat_logits,
                target_left.reshape(-1),
                reduction="none",
            ).view_as(target_distances)
            * left_weight
            + torch.nn.functional.cross_entropy(
                flat_logits,
                target_right.reshape(-1),
                reduction="none",
            ).view_as(target_distances)
            * right_weight
        ).mean(dim=-1)
    else:
        input_height = (
            int(raw_outputs["feats"][0].shape[-2])
            * int(detect_head.strides[0])
        )
        input_width = (
            int(raw_outputs["feats"][0].shape[-1])
            * int(detect_head.strides[0])
        )
        scale = foreground_logits.new_tensor(
            (input_width, input_height, input_width, input_height)
        )
        normalized_prediction = (
            foreground_logits.view(-1, 4) * foreground_stride / scale
        )
        normalized_target = target_distances * foreground_stride / scale
        dfl = torch.nn.functional.l1_loss(
            normalized_prediction,
            normalized_target,
            reduction="none",
        ).mean(dim=-1)
    dfl_loss = (dfl * quality_scores).sum() / normalizer
    total_loss = (
        box_loss * box_weight
        + class_loss * class_weight
        + dfl_loss * dfl_weight
    )
    return {
        "loss": total_loss,
        "box_loss": box_loss,
        "class_loss": class_loss,
        "dfl_loss": dfl_loss,
    }


@pytest.mark.parametrize(
    ("builder", "loader"),
    (
        (build_yolov8_model, load_yolov8_state_dict),
        (build_yolo11_model, load_yolo11_state_dict),
        (build_yolo26_model, load_yolo26_state_dict),
    ),
)
def test_eighty_class_warm_start_keeps_few_class_bias_priors(
    builder: Callable[..., Any],
    loader: Callable[..., Any],
) -> None:
    """验证 80 类权重迁移到少类别模型时保留目标 head 的正确先验。"""

    source_model = builder(
        task_type="detection",
        model_scale="nano",
        num_classes=80,
    )
    target_model = builder(
        task_type="detection",
        model_scale="nano",
        num_classes=3,
    )
    target_head = target_model.model[-1]
    expected_class_biases = tuple(
        math.log(5.0 / 3.0 / (640.0 / stride) ** 2)
        for stride in target_head.strides
    )
    load_result = loader(
        model=target_model,
        source_state_dict=source_model.state_dict(),
        minimum_loadable_ratio=YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
        strict_shape=False,
    )

    assert load_result.coverage.loadable_ratio >= YOLO_WARM_START_MINIMUM_LOADABLE_RATIO
    assert any(".cv3." in key for key in load_result.shape_mismatch_keys)
    for expected_bias, class_branch, box_branch in zip(
        expected_class_biases,
        target_head.cv3,
        target_head.cv2,
        strict=True,
    ):
        assert torch.allclose(
            class_branch[-1].bias,
            torch.full_like(class_branch[-1].bias, expected_bias),
        )
        assert torch.equal(
            box_branch[-1].bias,
            torch.full_like(box_branch[-1].bias, 2.0),
        )
    if target_head.end2end:
        for expected_bias, class_branch, box_branch in zip(
            expected_class_biases,
            target_head.one2one_cv3,
            target_head.one2one_cv2,
            strict=True,
        ):
            assert torch.allclose(
                class_branch[-1].bias,
                torch.full_like(class_branch[-1].bias, expected_bias),
            )
            assert torch.equal(
                box_branch[-1].bias,
                torch.full_like(box_branch[-1].bias, 2.0),
            )

    del source_model, target_model
    gc.collect()


@pytest.mark.parametrize(
    ("builder", "task_type"),
    tuple(
        (builder, task_type)
        for builder in (build_yolov8_model, build_yolo11_model, build_yolo26_model)
        for task_type in (
            "detection",
            "classification",
            "segmentation",
            "pose",
            "obb",
        )
    ),
)
def test_yolo_model_initialization_matches_reference_batch_norm(
    builder: Callable[..., Any],
    task_type: str,
) -> None:
    """验证所有模型任务共享固化的 BatchNorm 参数。"""

    model = builder(task_type=task_type, model_scale="nano", num_classes=3)
    batch_norms = tuple(
        module
        for module in model.modules()
        if isinstance(module, torch.nn.BatchNorm2d)
    )

    assert batch_norms
    assert all(module.eps == 1e-3 for module in batch_norms)
    assert all(module.momentum == 0.03 for module in batch_norms)


def test_yolov8_pose_training_decode_matches_reference_anchor_offset() -> None:
    """验证 YOLOv8 pose 训练解码包含固化公式的 -0.5 anchor offset。"""

    decoded = decode_yolov8_pose_keypoints_xy(
        pred_xy=torch.tensor([[[0.25, 0.25]], [[0.25, 0.25]]]),
        anchors_xy=torch.tensor(((4.0, 4.0), (24.0, 24.0))),
        strides=torch.tensor(((8.0,), (16.0,))),
    )

    assert torch.equal(decoded[:, 0], torch.tensor(((4.0, 4.0), (24.0, 24.0))))


def test_yolov8_obb_decode_matches_reference_half_offset() -> None:
    """验证 YOLOv8 OBB center offset 使用 (rb-lt)/2。"""

    decoded = yolov8_decode_distances_to_rboxes(
        torch_module=torch,
        pred_dist=torch.tensor(((1.0, 2.0, 3.0, 4.0),)),
        pred_angle=torch.zeros((1, 1)),
        anchor_points=torch.tensor(((10.0, 20.0),)),
    )

    assert torch.equal(decoded, torch.tensor(((11.0, 21.0, 4.0, 6.0, 0.0),)))


@pytest.mark.parametrize(
    "assigner",
    (
        assign_yolov8_detection_targets,
        assign_yolo11_detection_targets,
        assign_yolo26_detection_targets,
    ),
)
def test_detection_tal_matches_copied_reference_equations(
    assigner: Callable[..., dict[str, Any]],
) -> None:
    """验证重叠 GT 的冲突归属和 target score 与固化 TAL 公式一致。"""

    torch.manual_seed(4)
    anchor_centers = torch.tensor(
        [
            (4.0, 4.0),
            (12.0, 4.0),
            (20.0, 4.0),
            (28.0, 4.0),
            (4.0, 12.0),
            (12.0, 12.0),
            (20.0, 12.0),
            (28.0, 12.0),
            (4.0, 20.0),
            (12.0, 20.0),
            (20.0, 20.0),
            (28.0, 20.0),
            (4.0, 28.0),
            (12.0, 28.0),
            (20.0, 28.0),
            (28.0, 28.0),
        ]
    )
    gt_boxes = torch.tensor(((2.0, 2.0, 24.0, 24.0), (8.0, 8.0, 30.0, 30.0)))
    pred_boxes = torch.cat((anchor_centers - 7.0, anchor_centers + 7.0), dim=1)
    pred_boxes = pred_boxes + torch.randn(16, 4) * 1.5
    class_probabilities = torch.rand(16, 2) * 0.7 + 0.15
    gt_classes = torch.tensor((0, 1), dtype=torch.long)
    assignment_kwargs: dict[str, Any] = {}
    if assigner is assign_yolo26_detection_targets:
        assignment_kwargs = {
            "candidate_min_box_size": 8.0,
            "candidate_replace_box_size": 16.0,
        }
    actual = assigner(
        torch_module=torch,
        pred_boxes=pred_boxes,
        class_probabilities=class_probabilities,
        anchor_centers_xy=anchor_centers,
        gt_boxes=gt_boxes,
        gt_classes=gt_classes,
        topk=5,
        alpha=0.5,
        beta=6.0,
        topk2=3,
        **assignment_kwargs,
    )
    expected = _reference_task_aligned_assignment(
        overlaps=_reference_bbox_ciou_matrix(gt_boxes, pred_boxes).clamp(0.0, 1.0),
        inside_mask=_reference_xyxy_inside_mask(
            anchor_centers=anchor_centers,
            gt_boxes=gt_boxes,
            minimum_size=8.0,
            replacement_size=16.0,
        ),
        class_probabilities=class_probabilities,
        gt_classes=gt_classes,
        topk=5,
        alpha=0.5,
        beta=6.0,
        topk2=3,
    )

    assert torch.equal(actual["foreground_mask"], expected["foreground_mask"])
    foreground_mask = expected["foreground_mask"]
    assert torch.equal(
        actual["assigned_gt_indices"][foreground_mask],
        expected["assigned_gt_indices"][foreground_mask],
    )
    assert torch.allclose(
        actual["quality_scores"],
        expected["quality_scores"],
        atol=1e-7,
        rtol=1e-6,
    )


@pytest.mark.parametrize(
    ("assigner", "topk2"),
    (
        (assign_yolov8_obb_targets, None),
        (assign_yolo11_obb_targets, 3),
        (assign_yolo26_obb_targets, 3),
    ),
)
def test_obb_tal_matches_copied_reference_equations(
    assigner: Callable[..., dict[str, Any]],
    topk2: int | None,
) -> None:
    """验证 OBB 任务也符合固化的冲突消解和 score 归一化公式。"""

    torch.manual_seed(8)
    anchor_centers = torch.cartesian_prod(
        torch.tensor((4.0, 12.0, 20.0, 28.0)),
        torch.tensor((4.0, 12.0, 20.0, 28.0)),
    )
    gt_rboxes = torch.tensor(
        ((14.0, 14.0, 20.0, 16.0, 0.2), (19.0, 18.0, 18.0, 20.0, -0.3))
    )
    pred_rboxes = torch.cat(
        (
            anchor_centers,
            torch.rand(16, 2) * 8.0 + 10.0,
            torch.rand(16, 1) - 0.5,
        ),
        dim=1,
    )
    class_probabilities = torch.rand(16, 2) * 0.7 + 0.15
    gt_classes = torch.tensor((0, 1), dtype=torch.long)
    assignment_kwargs: dict[str, Any] = {}
    if topk2 is not None:
        assignment_kwargs["topk2"] = topk2
    actual = assigner(
        torch_module=torch,
        pred_rboxes=pred_rboxes,
        class_probabilities=class_probabilities,
        anchor_centers_xy=anchor_centers,
        gt_rboxes=gt_rboxes,
        gt_classes=gt_classes,
        topk=5,
        alpha=0.5,
        beta=6.0,
        **assignment_kwargs,
    )
    expected = _reference_task_aligned_assignment(
        overlaps=_reference_probiou_matrix(gt_rboxes, pred_rboxes).clamp(0.0, 1.0),
        inside_mask=_reference_rbox_inside_mask(
            anchor_centers=anchor_centers,
            gt_rboxes=gt_rboxes,
        ),
        class_probabilities=class_probabilities,
        gt_classes=gt_classes,
        topk=5,
        alpha=0.5,
        beta=6.0,
        topk2=topk2,
    )

    assert torch.equal(actual["foreground_mask"], expected["foreground_mask"])
    foreground_mask = expected["foreground_mask"]
    assert torch.equal(
        actual["assigned_gt_indices"][foreground_mask],
        expected["assigned_gt_indices"][foreground_mask],
    )
    assert torch.allclose(
        actual["quality_scores"],
        expected["quality_scores"],
        atol=1e-7,
        rtol=1e-6,
    )


@pytest.mark.parametrize(
    ("builder", "loss_function", "end2end"),
    (
        (build_yolov8_model, compute_yolov8_detection_loss, False),
        (build_yolo11_model, compute_yolo11_detection_loss, False),
        (build_yolo26_model, compute_yolo26_detection_loss, True),
    ),
)
def test_detection_loss_matches_copied_reference_equations(
    builder: Callable[..., Any],
    loss_function: Callable[..., dict[str, Any]],
    end2end: bool,
) -> None:
    """验证 box/class/DFL loss 与测试内固化的独立公式一致。"""

    torch.manual_seed(13)
    model = builder(
        task_type="detection",
        model_scale="nano",
        num_classes=2,
    )
    model.train()
    raw_outputs = model(torch.randn(1, 3, 64, 64))
    if end2end:
        raw_outputs = raw_outputs["one2many"]
    gt_boxes = torch.tensor(((8.0, 8.0, 40.0, 40.0),))
    gt_classes = torch.tensor((0,), dtype=torch.long)
    actual = loss_function(
        torch_module=torch,
        detect_head=model.model[-1],
        raw_outputs=raw_outputs,
        batch_targets=(
            SimpleNamespace(
                boxes_xyxy=((8.0, 8.0, 40.0, 40.0),),
                category_indexes=(0,),
            ),
        ),
        class_loss_weight=0.5,
        box_loss_weight=7.5,
        dfl_loss_weight=1.5,
        assign_topk=10,
        assign_alpha=0.5,
        assign_beta=6.0,
    )
    expected = _reference_detection_loss(
        raw_outputs=raw_outputs,
        detect_head=model.model[-1],
        gt_boxes=gt_boxes,
        gt_classes=gt_classes,
        box_weight=7.5,
        class_weight=0.5,
        dfl_weight=1.5,
    )

    for component_name in ("box_loss", "class_loss", "dfl_loss", "loss"):
        assert torch.allclose(
            actual[component_name],
            expected[component_name],
            atol=3e-6,
            rtol=1e-5,
        )
