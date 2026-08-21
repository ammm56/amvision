"""YOLO26 pose loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.losses import (
    write_assignment_quality_scores,
)

from backend.service.application.models.yolo26_core.assigners import (
    assign_yolo26_pose_targets,
    resolve_yolo26_tal_candidate_box_sizes,
    yolo26_pose_box_iou_aligned,
)
from backend.service.application.models.yolo26_core.decode import (
    decode_yolo26_detection_training_predictions,
)
from backend.service.application.models.yolo26_core.losses.detection import (
    resolve_yolo26_input_size_hw,
    yolo26_distribution_focal_loss,
    yolo26_ltrb_l1_loss,
)
from backend.service.application.models.yolo26_core.targets import (
    normalize_yolo26_gt_keypoints_tensor,
    yolo26_bbox_xyxy_to_distances,
)
from backend.service.application.models.yolo_core_common.losses.pose import (
    build_pose_box_area,
    build_pose_oks_sigmas,
    build_pose_visibility_mask,
    compute_oks_keypoint_loss,
    compute_visibility_loss,
)


YOLO26_RLE_WEIGHT = (
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.0,
    1.2,
    1.2,
    1.5,
    1.5,
    1.0,
    1.0,
    1.2,
    1.2,
    1.5,
    1.5,
)


def compute_yolo26_pose_loss(
    *,
    torch: Any,
    model: Any,
    raw_outputs: dict[str, Any],
    batch_targets: tuple[Any, ...],
    num_classes: int,
    kpt_shape: tuple[int, int] = (17, 3),
    class_loss_weight: float = 0.5,
    box_loss_weight: float = 7.5,
    dfl_loss_weight: float = 1.5,
    kpt_loss_weight: float = 12.0,
    visibility_loss_weight: float = 1.0,
    rle_loss_weight: float = 1.0,
    assign_topk: int = 10,
    assign_alpha: float = 0.5,
    assign_beta: float = 6.0,
    assign_topk2: int | None = None,
    runtime_metrics: dict[str, float] | None = None,
) -> dict[str, Any]:
    """计算 YOLO26 pose 的 box、class、DFL、keypoint 和可见性损失。"""

    _ = num_classes
    pose_head = model.model[-1]
    keypoint_count = int(kpt_shape[0])
    keypoint_dim = int(kpt_shape[1])

    prediction_bundle = decode_yolo26_detection_training_predictions(
        torch_module=torch,
        detect_head=pose_head,
        raw_outputs=raw_outputs,
    )
    class_logits = prediction_bundle["class_logits"]
    class_probabilities = class_logits.sigmoid()
    pred_boxes = prediction_bundle["boxes_xyxy"]
    distance_logits = prediction_bundle["distance_logits"]
    anchor_points = prediction_bundle["anchor_points"]
    stride_tensor = prediction_bundle["stride_tensor"]
    anchor_centers_xy = prediction_bundle["anchor_centers_xy"]
    candidate_min_box_size, candidate_replace_box_size = (
        resolve_yolo26_tal_candidate_box_sizes(stride_tensor=stride_tensor)
    )
    reg_max = int(prediction_bundle["reg_max"])

    raw_keypoints = raw_outputs.get("kpts")
    pred_keypoints = (
        raw_keypoints.permute(0, 2, 1).contiguous()
        if raw_keypoints is not None
        else None
    )
    raw_keypoint_sigmas = raw_outputs.get("kpts_sigma")
    pred_keypoint_sigmas = (
        raw_keypoint_sigmas.permute(0, 2, 1).contiguous()
        if raw_keypoint_sigmas is not None
        else None
    )

    batch_size = int(class_logits.shape[0])
    total_class_loss = class_logits.new_zeros(())
    total_box_loss = class_logits.new_zeros(())
    total_dfl_loss = class_logits.new_zeros(())
    total_keypoint_loss = class_logits.new_zeros(())
    total_visibility_loss = class_logits.new_zeros(())
    total_rle_loss = class_logits.new_zeros(())
    rle_batch_items: list[dict[str, Any]] = []
    total_foreground = 0
    total_target_score = class_logits.new_zeros(())

    for batch_index in range(batch_size):
        loss_state = _compute_yolo26_pose_image_loss(
            torch_module=torch,
            batch_index=batch_index,
            image_class_logits=class_logits[batch_index],
            image_class_probabilities=class_probabilities[batch_index],
            image_pred_boxes=pred_boxes[batch_index],
            target=batch_targets[batch_index],
            anchor_centers_xy=anchor_centers_xy,
            anchor_points=anchor_points,
            stride_tensor=stride_tensor,
            distance_logits=distance_logits[batch_index],
            reg_max=reg_max,
            pred_keypoints=pred_keypoints,
            pred_keypoint_sigmas=pred_keypoint_sigmas,
            flow_model=getattr(pose_head, "flow_model", None),
            keypoint_count=keypoint_count,
            keypoint_dim=keypoint_dim,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            assign_topk2=assign_topk2,
            candidate_min_box_size=candidate_min_box_size,
            candidate_replace_box_size=candidate_replace_box_size,
        )
        total_class_loss = total_class_loss + loss_state["class_loss"]
        total_box_loss = total_box_loss + loss_state["box_loss"]
        total_dfl_loss = total_dfl_loss + loss_state["dfl_loss"]
        total_keypoint_loss = total_keypoint_loss + loss_state["keypoint_loss"]
        total_visibility_loss = total_visibility_loss + loss_state["visibility_loss"]
        rle_batch_item = loss_state["rle_batch_item"]
        if rle_batch_item is not None:
            rle_batch_items.append(rle_batch_item)
        total_target_score = total_target_score + loss_state["target_score"]
        total_foreground += int(loss_state["foreground_count"])

    if rle_batch_items:
        total_rle_loss = compute_yolo26_batched_rle_loss(
            torch_module=torch,
            flow_model=getattr(pose_head, "flow_model", None),
            batch_items=tuple(rle_batch_items),
            runtime_metrics=runtime_metrics,
        )
    if runtime_metrics is not None:
        runtime_metrics["foreground_count"] = float(total_foreground)
        runtime_metrics["rle_image_count"] = float(len(rle_batch_items))

    normalizer = total_target_score.clamp_min(1.0)
    foreground_normalizer = max(total_foreground, 1)
    class_loss = total_class_loss / normalizer
    box_loss = total_box_loss / normalizer
    dfl_loss = total_dfl_loss / normalizer
    keypoint_loss = total_keypoint_loss / foreground_normalizer
    visibility_loss = total_visibility_loss / foreground_normalizer
    rle_loss = total_rle_loss / foreground_normalizer
    total_loss = (
        class_loss * class_loss_weight
        + box_loss * box_loss_weight
        + dfl_loss * dfl_loss_weight
        + keypoint_loss * kpt_loss_weight
        + visibility_loss * visibility_loss_weight
        + rle_loss * rle_loss_weight
    )
    batch_size = max(1, len(batch_targets))
    return {
        "loss": total_loss * batch_size,
        "class_loss": class_loss * class_loss_weight,
        "box_loss": box_loss * box_loss_weight,
        "dfl_loss": dfl_loss * dfl_loss_weight,
        "kpt_loss": keypoint_loss * kpt_loss_weight,
        "visibility_loss": visibility_loss * visibility_loss_weight,
        "rle_loss": rle_loss * rle_loss_weight,
    }


def _compute_yolo26_pose_image_loss(
    *,
    torch_module: Any,
    batch_index: int,
    image_class_logits: Any,
    image_class_probabilities: Any,
    image_pred_boxes: Any,
    target: Any,
    anchor_centers_xy: Any,
    anchor_points: Any,
    stride_tensor: Any,
    distance_logits: Any,
    reg_max: int,
    pred_keypoints: Any | None,
    pred_keypoint_sigmas: Any | None,
    flow_model: Any | None,
    keypoint_count: int,
    keypoint_dim: int,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None,
    candidate_min_box_size: float,
    candidate_replace_box_size: float,
) -> dict[str, Any]:
    """计算单张图片的 YOLO26 pose 训练损失。"""

    target_scores = torch_module.zeros_like(image_class_logits)
    zero_loss = image_class_logits.new_zeros(())
    gt_boxes_list = getattr(target, "boxes_xyxy", None) or getattr(
        target, "boxes", None
    )
    gt_classes_list = getattr(target, "category_indexes", None) or getattr(
        target, "class_ids", None
    )
    gt_keypoints = getattr(target, "keypoints", None)

    if gt_boxes_list is None or len(gt_boxes_list) == 0:
        return {
            "class_loss": torch_module.nn.functional.binary_cross_entropy_with_logits(
                image_class_logits,
                target_scores,
                reduction="sum",
            ),
            "box_loss": zero_loss,
            "dfl_loss": zero_loss,
            "keypoint_loss": zero_loss,
            "visibility_loss": zero_loss,
            "rle_batch_item": None,
            "foreground_count": 0,
            "target_score": zero_loss,
        }

    gt_boxes = torch_module.tensor(
        gt_boxes_list,
        device=image_pred_boxes.device,
        dtype=image_pred_boxes.dtype,
    )
    gt_classes = torch_module.tensor(
        gt_classes_list,
        device=image_pred_boxes.device,
        dtype=torch_module.long,
    )
    with torch_module.no_grad():
        assignment = assign_yolo26_pose_targets(
            torch_module=torch_module,
            pred_boxes=image_pred_boxes.detach(),
            class_probabilities=image_class_probabilities.detach(),
            anchor_centers_xy=anchor_centers_xy,
            gt_boxes=gt_boxes,
            gt_classes=gt_classes,
            topk=assign_topk,
            alpha=assign_alpha,
            beta=assign_beta,
            topk2=assign_topk2,
            candidate_min_box_size=candidate_min_box_size,
            candidate_replace_box_size=candidate_replace_box_size,
        )

    foreground_mask = assignment["foreground_mask"]
    foreground_count = int(foreground_mask.sum().item())
    if foreground_count <= 0:
        return {
            "class_loss": torch_module.nn.functional.binary_cross_entropy_with_logits(
                image_class_logits,
                target_scores,
                reduction="sum",
            ),
            "box_loss": zero_loss,
            "dfl_loss": zero_loss,
            "keypoint_loss": zero_loss,
            "visibility_loss": zero_loss,
            "rle_batch_item": None,
            "foreground_count": 0,
            "target_score": zero_loss,
        }

    assigned_indices = assignment["assigned_gt_indices"][foreground_mask]
    quality_scores = assignment["quality_scores"][foreground_mask]
    write_assignment_quality_scores(
        target_scores=target_scores,
        foreground_mask=foreground_mask,
        gt_classes=gt_classes,
        assigned_gt_indices=assigned_indices,
        quality_scores=quality_scores,
    )
    foreground_pred_boxes = image_pred_boxes[foreground_mask]
    foreground_gt_boxes = gt_boxes[assigned_indices]
    foreground_stride = stride_tensor[foreground_mask]
    iou_values = yolo26_pose_box_iou_aligned(
        torch_module=torch_module,
        boxes1=foreground_pred_boxes / foreground_stride.view(-1, 1),
        boxes2=foreground_gt_boxes / foreground_stride.view(-1, 1),
    )
    box_loss = ((1.0 - iou_values) * quality_scores).sum()
    dfl_loss = _compute_yolo26_pose_dfl_loss(
        torch_module=torch_module,
        distance_logits=distance_logits,
        foreground_mask=foreground_mask,
        foreground_gt_boxes=foreground_gt_boxes,
        foreground_anchor_points=anchor_points[foreground_mask],
        foreground_stride=foreground_stride,
        input_size_hw=resolve_yolo26_input_size_hw(
            torch_module=torch_module,
            anchor_points=anchor_points,
            stride_tensor=stride_tensor,
        ),
        quality_scores=quality_scores,
        reg_max=reg_max,
    )
    keypoint_loss = zero_loss
    visibility_loss = zero_loss
    rle_batch_item = None
    if (
        pred_keypoints is not None
        and gt_keypoints is not None
        and len(gt_keypoints) > 0
    ):
        keypoint_loss, visibility_loss, rle_batch_item = (
            _compute_yolo26_pose_keypoint_losses(
                torch_module=torch_module,
                pred_keypoints=pred_keypoints,
                pred_keypoint_sigmas=pred_keypoint_sigmas,
                batch_index=batch_index,
                foreground_mask=foreground_mask,
                assigned_indices=assigned_indices,
                gt_keypoints=gt_keypoints,
                keypoint_count=keypoint_count,
                keypoint_dim=keypoint_dim,
                foreground_anchor_points=anchor_points[foreground_mask],
                foreground_stride=stride_tensor[foreground_mask],
                foreground_gt_boxes=foreground_gt_boxes,
                flow_model=flow_model,
            )
        )

    class_loss = torch_module.nn.functional.binary_cross_entropy_with_logits(
        image_class_logits,
        target_scores,
        reduction="sum",
    )
    return {
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "keypoint_loss": keypoint_loss * foreground_count,
        "visibility_loss": visibility_loss * foreground_count,
        "rle_batch_item": rle_batch_item,
        "foreground_count": foreground_count,
        "target_score": quality_scores.sum(),
    }


def _compute_yolo26_pose_dfl_loss(
    *,
    torch_module: Any,
    distance_logits: Any,
    foreground_mask: Any,
    foreground_gt_boxes: Any,
    foreground_anchor_points: Any,
    foreground_stride: Any,
    input_size_hw: Any,
    quality_scores: Any,
    reg_max: int,
) -> Any:
    """计算 YOLO26 pose DFL 分量。"""

    target_distances = yolo26_bbox_xyxy_to_distances(
        torch_module=torch_module,
        boxes_xyxy=foreground_gt_boxes,
        anchor_points=foreground_anchor_points,
        stride_tensor=foreground_stride,
        reg_max=reg_max,
    )
    if reg_max > 1:
        foreground_distance_logits = distance_logits[foreground_mask].view(
            -1, 4, reg_max
        )
        dfl_loss = yolo26_distribution_focal_loss(
            torch_module=torch_module,
            logits=foreground_distance_logits,
            target=target_distances,
        )
        return (dfl_loss * quality_scores).sum()
    foreground_distance_logits = distance_logits[foreground_mask].view(-1, 4)
    dfl_loss = yolo26_ltrb_l1_loss(
        torch_module=torch_module,
        prediction=foreground_distance_logits,
        target=target_distances,
        stride_tensor=foreground_stride,
        input_size_hw=input_size_hw,
    )
    return (dfl_loss * quality_scores).sum()


def _compute_yolo26_pose_keypoint_losses(
    *,
    torch_module: Any,
    pred_keypoints: Any,
    pred_keypoint_sigmas: Any | None,
    batch_index: int,
    foreground_mask: Any,
    assigned_indices: Any,
    gt_keypoints: Any,
    keypoint_count: int,
    keypoint_dim: int,
    foreground_anchor_points: Any,
    foreground_stride: Any,
    foreground_gt_boxes: Any,
    flow_model: Any | None,
) -> tuple[Any, Any, dict[str, Any] | None]:
    """计算关键点损失，并收集当前图片的 RLE 批处理输入。"""

    foreground_pred_keypoints = pred_keypoints[batch_index][foreground_mask]
    foreground_gt_keypoints = normalize_yolo26_gt_keypoints_tensor(
        torch_module=torch_module,
        raw_keypoints=gt_keypoints,
        assigned_indices=assigned_indices,
        num_keypoints=keypoint_count,
        keypoint_dim=keypoint_dim,
        device=foreground_pred_keypoints.device,
        dtype=foreground_pred_keypoints.dtype,
    )
    foreground_count = int(foreground_pred_keypoints.shape[0])
    pred_keypoints_reshaped = foreground_pred_keypoints.view(
        foreground_count,
        keypoint_count,
        keypoint_dim,
    )
    stride_values = foreground_stride.view(-1, 1)
    decoded_keypoints_xy = _decode_yolo26_pose_keypoints_xy(
        pred_xy=pred_keypoints_reshaped[..., :2],
        anchor_points=foreground_anchor_points,
        strides=stride_values,
    )
    gt_xy = foreground_gt_keypoints[..., :2]
    keypoint_mask = build_pose_visibility_mask(
        torch_module=torch_module,
        gt_keypoints=foreground_gt_keypoints,
        keypoint_dim=keypoint_dim,
    )
    keypoint_loss = compute_oks_keypoint_loss(
        torch_module=torch_module,
        pred_keypoints_xy=decoded_keypoints_xy,
        gt_keypoints_xy=gt_xy,
        keypoint_mask=keypoint_mask,
        area=build_pose_box_area(gt_boxes=foreground_gt_boxes),
        sigmas=build_pose_oks_sigmas(
            torch_module=torch_module,
            num_keypoints=keypoint_count,
            device=foreground_pred_keypoints.device,
            dtype=foreground_pred_keypoints.dtype,
        ),
    )
    visibility_loss = foreground_pred_keypoints.new_zeros(())
    if keypoint_dim > 2:
        visibility_loss = compute_visibility_loss(
            torch_module=torch_module,
            pred_visibility_logits=pred_keypoints_reshaped[..., 2],
            keypoint_mask=keypoint_mask,
        )
    rle_batch_item = None
    if pred_keypoint_sigmas is not None and flow_model is not None:
        foreground_pred_sigmas = pred_keypoint_sigmas[batch_index][
            foreground_mask
        ].view(foreground_count, keypoint_count, 2)
        rle_batch_item = {
            "pred_keypoints_xy": (
                decoded_keypoints_xy / stride_values.unsqueeze(1)
            ),
            "pred_sigma_logits": foreground_pred_sigmas,
            "gt_keypoints_xy": gt_xy / stride_values.unsqueeze(1),
            "keypoint_mask": keypoint_mask,
            "target_weights": build_yolo26_pose_rle_weights(
                torch_module=torch_module,
                num_keypoints=keypoint_count,
                device=foreground_pred_keypoints.device,
                dtype=foreground_pred_keypoints.dtype,
            ),
            "foreground_count": foreground_count,
        }
    return keypoint_loss, visibility_loss, rle_batch_item


def _decode_yolo26_pose_keypoints_xy(
    *,
    pred_xy: Any,
    anchor_points: Any,
    strides: Any,
) -> Any:
    """按 Ultralytics YOLO26 pose 训练规则解码关键点坐标。"""

    anchors_xy = anchor_points.unsqueeze(1)
    return (pred_xy + anchors_xy) * strides.unsqueeze(1)


def compute_yolo26_rle_loss(
    *,
    torch_module: Any,
    flow_model: Any,
    pred_keypoints_xy: Any,
    pred_sigma_logits: Any,
    gt_keypoints_xy: Any,
    keypoint_mask: Any,
    target_weights: Any,
) -> Any:
    """计算 YOLO26 pose 的 RLE 损失。"""

    if flow_model is None:
        return pred_keypoints_xy.new_zeros(())

    image_losses = _compute_yolo26_rle_image_losses(
        torch_module=torch_module,
        flow_model=flow_model,
        batch_items=(
            {
                "pred_keypoints_xy": pred_keypoints_xy,
                "pred_sigma_logits": pred_sigma_logits,
                "gt_keypoints_xy": gt_keypoints_xy,
                "keypoint_mask": keypoint_mask,
                "target_weights": target_weights,
                "foreground_count": int(pred_keypoints_xy.shape[0]),
            },
        ),
    )
    return image_losses[0]


def compute_yolo26_batched_rle_loss(
    *,
    torch_module: Any,
    flow_model: Any,
    batch_items: tuple[dict[str, Any], ...],
    runtime_metrics: dict[str, float] | None = None,
) -> Any:
    """一次执行整批 RealNVP，并保持原逐图 RLE reduction 语义。"""

    if not batch_items:
        return torch_module.zeros((), dtype=torch_module.float32)
    if flow_model is None:
        return batch_items[0]["pred_keypoints_xy"].new_zeros(())

    image_losses = _compute_yolo26_rle_image_losses(
        torch_module=torch_module,
        flow_model=flow_model,
        batch_items=batch_items,
        runtime_metrics=runtime_metrics,
    )
    total_loss = image_losses[0].new_zeros(())
    for item, image_loss in zip(batch_items, image_losses, strict=True):
        total_loss = total_loss + image_loss.clamp_min(0.0) * int(
            item["foreground_count"]
        )
    return total_loss


def _compute_yolo26_rle_image_losses(
    *,
    torch_module: Any,
    flow_model: Any,
    batch_items: tuple[dict[str, Any], ...],
    runtime_metrics: dict[str, float] | None = None,
) -> tuple[Any, ...]:
    """合并可见关键点后调用一次 RealNVP，再按图片恢复原均值。"""

    image_losses = [
        item["pred_keypoints_xy"].new_zeros(()) for item in batch_items
    ]
    if flow_model is None or not batch_items:
        return tuple(image_losses)

    # RLE 中坐标差、sigmoid 极值和 RealNVP 都必须在 FP32 中计算。
    # 仅把输入提升到 FP32 不够：外层 CUDA autocast 仍会把 RealNVP 的
    # ``Linear`` 运算降回 FP16，scratch 训练时会让 flow 参数梯度持续溢出。
    # 在当前设备的 autocast 区域内显式禁用混合精度，同时保留到 pose head
    # FP16 输出的梯度连接。
    with torch_module.amp.autocast(
        device_type=batch_items[0]["pred_keypoints_xy"].device.type,
        enabled=False,
    ):
        batched_errors: list[Any] = []
        batched_sigmas: list[Any] = []
        batched_target_weights: list[Any] = []
        active_image_indexes: list[int] = []
        active_image_lengths: list[int] = []

        for image_index, item in enumerate(batch_items):
            keypoint_mask = item["keypoint_mask"]
            visible_pred_xy = item["pred_keypoints_xy"].float()[keypoint_mask]
            visible_gt_xy = item["gt_keypoints_xy"].float()[keypoint_mask]
            visible_sigma = item["pred_sigma_logits"].float().sigmoid()[
                keypoint_mask
            ]
            if int(visible_pred_xy.shape[0]) <= 0:
                continue

            expanded_target_weights = item["target_weights"].unsqueeze(0).repeat(
                keypoint_mask.shape[0], 1
            )
            visible_target_weights = expanded_target_weights.float()[keypoint_mask]
            error = (visible_pred_xy - visible_gt_xy) / (visible_sigma + 1e-9)
            valid_mask = ~(
                torch_module.isnan(error) | torch_module.isinf(error)
            ).any(dim=-1)
            if not bool(valid_mask.any()):
                continue

            error = error[valid_mask].clamp(-100.0, 100.0)
            visible_sigma = visible_sigma[valid_mask]
            visible_target_weights = visible_target_weights[valid_mask]
            active_image_indexes.append(image_index)
            active_image_lengths.append(int(error.shape[0]))
            batched_errors.append(error)
            batched_sigmas.append(visible_sigma)
            batched_target_weights.append(visible_target_weights)

        if not batched_errors:
            if runtime_metrics is not None:
                runtime_metrics["rle_error_count"] = 0.0
            return tuple(image_losses)

        if runtime_metrics is not None:
            runtime_metrics["rle_error_count"] = float(sum(active_image_lengths))

        error = torch_module.cat(batched_errors, dim=0)
        visible_sigma = torch_module.cat(batched_sigmas, dim=0)
        visible_target_weights = torch_module.cat(
            batched_target_weights,
            dim=0,
        )
        log_phi = flow_model.log_prob(error)
        loss_values = torch_module.log(visible_sigma + 1e-9) - log_phi.unsqueeze(1)
        loss_values = (
            loss_values
            + torch_module.log(visible_sigma * 2.0 + 1e-9)
            + torch_module.abs(error)
        )
        loss_values = loss_values * visible_target_weights.unsqueeze(1)

        offset = 0
        for image_index, image_length in zip(
            active_image_indexes,
            active_image_lengths,
            strict=True,
        ):
            image_loss_values = loss_values[offset : offset + image_length]
            image_losses[image_index] = image_loss_values.sum() / image_length
            offset += image_length
        return tuple(image_losses)


def build_yolo26_pose_rle_weights(
    *,
    torch_module: Any,
    num_keypoints: int,
    device: Any,
    dtype: Any,
) -> Any:
    """构建 YOLO26 pose RLE 权重。"""

    if num_keypoints == len(YOLO26_RLE_WEIGHT):
        values = YOLO26_RLE_WEIGHT
    else:
        values = tuple(1.0 for _ in range(num_keypoints))
    return torch_module.tensor(values, device=device, dtype=dtype)


__all__ = [
    "build_yolo26_pose_rle_weights",
    "compute_yolo26_batched_rle_loss",
    "compute_yolo26_pose_loss",
    "compute_yolo26_rle_loss",
]
