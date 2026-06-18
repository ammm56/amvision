"""COCO-style 指标工具测试。"""

from __future__ import annotations

from backend.service.application.models.coco_style_metrics import (
    bbox_iou_xyxy,
    compute_coco_style_ap,
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
