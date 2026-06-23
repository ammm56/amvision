"""YOLO26 export forward 后处理。"""

from __future__ import annotations

from typing import Any


def postprocess_yolo26_detection_export_tensor(
    *,
    torch_module: Any,
    prediction: Any,
    num_classes: int,
    max_detections: int,
) -> Any:
    """按官方 YOLO26 end2end 布局生成 export detection 输出。"""

    boxes, scores = prediction.split([4, int(num_classes)], dim=-1)
    selected_scores, selected_class_ids, selected_indices = (
        select_yolo26_export_topk_indices(
            torch_module=torch_module,
            scores=scores,
            max_detections=max_detections,
        )
    )
    selected_boxes = boxes.gather(dim=1, index=selected_indices.repeat(1, 1, 4))
    return torch_module.cat(
        [selected_boxes, selected_scores, selected_class_ids],
        dim=-1,
    )


def postprocess_yolo26_extra_export_tensor(
    *,
    torch_module: Any,
    prediction: Any,
    num_classes: int,
    extra_channels: int,
    max_detections: int,
) -> Any:
    """按官方 YOLO26 end2end 布局生成 segmentation / pose export 输出。"""

    boxes, scores, extra = prediction.split(
        [4, int(num_classes), int(extra_channels)],
        dim=-1,
    )
    selected_scores, selected_class_ids, selected_indices = (
        select_yolo26_export_topk_indices(
            torch_module=torch_module,
            scores=scores,
            max_detections=max_detections,
        )
    )
    selected_boxes = boxes.gather(dim=1, index=selected_indices.repeat(1, 1, 4))
    selected_extra = extra.gather(
        dim=1,
        index=selected_indices.repeat(1, 1, int(extra_channels)),
    )
    return torch_module.cat(
        [selected_boxes, selected_scores, selected_class_ids, selected_extra],
        dim=-1,
    )


def postprocess_yolo26_obb_export_tensor(
    *,
    torch_module: Any,
    prediction: Any,
    num_classes: int,
    angle_channels: int,
    max_detections: int,
) -> Any:
    """按官方 YOLO26 end2end 布局生成 OBB export 输出。"""

    boxes, scores, angle = prediction.split(
        [4, int(num_classes), int(angle_channels)],
        dim=-1,
    )
    selected_scores, selected_class_ids, selected_indices = (
        select_yolo26_export_topk_indices(
            torch_module=torch_module,
            scores=scores,
            max_detections=max_detections,
        )
    )
    selected_boxes = boxes.gather(dim=1, index=selected_indices.repeat(1, 1, 4))
    selected_angle = angle.gather(
        dim=1,
        index=selected_indices.repeat(1, 1, int(angle_channels)),
    )
    return torch_module.cat(
        [selected_boxes, selected_scores, selected_class_ids, selected_angle],
        dim=-1,
    )


def select_yolo26_export_topk_indices(
    *,
    torch_module: Any,
    scores: Any,
    max_detections: int,
) -> tuple[Any, Any, Any]:
    """按 YOLO26 end2end two-stage top-k 规则选择输出索引。"""

    batch_size, anchor_count, class_count = scores.shape
    # Ultralytics exporter 会在导出前把 max_det 收到 anchor 数以内。
    # 这里也在 core 内兜住小输入，避免 64x64 smoke 的候选框数量小于 max_det。
    top_k = min(int(max_detections), int(anchor_count))
    first_stage_indices = scores.max(dim=-1)[0].topk(top_k, dim=1)[1].unsqueeze(-1)
    first_stage_scores = scores.gather(
        dim=1,
        index=first_stage_indices.repeat(1, 1, int(class_count)),
    )
    selected_scores, flattened_indices = first_stage_scores.flatten(1).topk(
        top_k,
        dim=1,
    )
    batch_indices = torch_module.arange(batch_size, device=scores.device)[:, None]
    selected_indices = first_stage_indices[
        batch_indices,
        flattened_indices // int(class_count),
    ]
    selected_class_ids = (flattened_indices % int(class_count)).unsqueeze(-1).to(
        scores.dtype
    )
    return selected_scores.unsqueeze(-1), selected_class_ids, selected_indices


__all__ = [
    "postprocess_yolo26_detection_export_tensor",
    "postprocess_yolo26_extra_export_tensor",
    "postprocess_yolo26_obb_export_tensor",
    "select_yolo26_export_topk_indices",
]
