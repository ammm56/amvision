"""COCO-style 指标工具测试。"""

from __future__ import annotations

from backend.service.application.models.coco_style_metrics import (
    bbox_iou_xyxy,
    compute_object_keypoint_similarity,
    compute_coco_style_ap,
    mask_iou,
    rotated_iou_xywhr,
)


def test_compute_coco_style_ap_returns_full_score_for_exact_match() -> None:
    """完全匹配时 AP50 与 AP50-95 都应为 1。"""

    result = compute_coco_style_ap(
        gt_items=[
            {
                "image_id": 1,
                "category_id": 0,
                "bbox_xyxy": [0.0, 0.0, 10.0, 10.0],
            },
        ],
        pred_items=[
            {
                "image_id": 1,
                "category_id": 0,
                "bbox_xyxy": [0.0, 0.0, 10.0, 10.0],
                "score": 0.9,
            },
        ],
        category_names={0: "part"},
        similarity_func=lambda pred, gt: bbox_iou_xyxy(
            pred["bbox_xyxy"],
            gt["bbox_xyxy"],
        ),
    )

    assert result.ap50 == 1.0
    assert result.ap50_95 == 1.0
    assert result.per_class_metrics[0]["category_name"] == "part"


def test_compute_coco_style_ap_keeps_false_positive_from_matching() -> None:
    """类别不匹配时不应被误判为正确检测。"""

    result = compute_coco_style_ap(
        gt_items=[
            {
                "image_id": 1,
                "category_id": 0,
                "bbox_xyxy": [0.0, 0.0, 10.0, 10.0],
            },
        ],
        pred_items=[
            {
                "image_id": 1,
                "category_id": 1,
                "bbox_xyxy": [0.0, 0.0, 10.0, 10.0],
                "score": 0.9,
            },
        ],
        category_names={0: "part"},
        similarity_func=lambda pred, gt: bbox_iou_xyxy(
            pred["bbox_xyxy"],
            gt["bbox_xyxy"],
        ),
    )

    assert result.ap50 == 0.0
    assert result.ap50_95 == 0.0


def test_mask_iou_matches_binary_overlap() -> None:
    """验证 mask IoU 按二值区域交并比计算。"""

    left = [
        [1, 1, 0],
        [1, 0, 0],
        [0, 0, 0],
    ]
    right = [
        [1, 0, 0],
        [1, 1, 0],
        [0, 0, 0],
    ]

    assert mask_iou(left, right) == 0.5


def test_compute_object_keypoint_similarity_uses_visible_keypoints() -> None:
    """验证 OKS 只按可见关键点计算。"""

    score = compute_object_keypoint_similarity(
        [4.0, 4.0, 2.0, 10.0, 10.0, 0.0],
        [4.0, 4.0, 0.9, 200.0, 200.0, 0.9],
        area=100.0,
    )

    assert score == 1.0


def test_rotated_iou_xywhr_returns_full_score_for_same_box() -> None:
    """验证相同旋转框的 rotated IoU 为 1。"""

    assert rotated_iou_xywhr(
        [8.0, 8.0, 6.0, 4.0, 0.3],
        [8.0, 8.0, 6.0, 4.0, 0.3],
    ) == 1.0
