"""COCO-style 指标工具测试。"""

from __future__ import annotations

import numpy as np
import pytest

from backend.service.application.models.evaluation.coco_style_metrics import (
    bbox_iou_xyxy,
    compute_object_keypoint_similarity,
    compute_coco_style_ap,
    compute_pycocotools_detection_ap,
    compute_pycocotools_pose_ap,
    compute_pycocotools_segmentation_ap,
    CocoStyleMetricResult,
    encode_binary_mask_to_coco_rle,
    encode_coco_polygons_to_rle,
    limit_segmentation_prediction_instances,
    mask_iou,
    resize_binary_mask_for_coco_evaluation,
    resolve_keypoint_oks_sigmas,
    resolve_segmentation_primary_metrics,
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


def test_compute_coco_style_ap_applies_max_detections_per_image_before_matching() -> (
    None
):
    """验证每图 maxDets 会按置信度截断预测。"""

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
                "bbox_xyxy": [20.0, 20.0, 30.0, 30.0],
                "score": 0.9,
            },
            {
                "image_id": 1,
                "category_id": 0,
                "bbox_xyxy": [0.0, 0.0, 10.0, 10.0],
                "score": 0.8,
            },
        ],
        category_names={0: "part"},
        max_detections_per_image=1,
        similarity_func=lambda pred, gt: bbox_iou_xyxy(
            pred["bbox_xyxy"],
            gt["bbox_xyxy"],
        ),
    )

    assert result.ap50 == 0.0
    assert result.per_class_metrics[0]["pred_count"] == 1


def test_compute_coco_style_ap_applies_max_detections_per_category() -> None:
    """验证 maxDets 与 COCOeval 一致，按每图、每类分别限制。"""

    result = compute_coco_style_ap(
        gt_items=[
            {
                "image_id": 1,
                "category_id": 0,
                "bbox_xyxy": [0.0, 0.0, 10.0, 10.0],
            },
            {
                "image_id": 1,
                "category_id": 1,
                "bbox_xyxy": [20.0, 20.0, 30.0, 30.0],
            },
        ],
        pred_items=[
            {
                "image_id": 1,
                "category_id": 1,
                "bbox_xyxy": [20.0, 20.0, 30.0, 30.0],
                "score": 0.9,
            },
            {
                "image_id": 1,
                "category_id": 0,
                "bbox_xyxy": [0.0, 0.0, 10.0, 10.0],
                "score": 0.8,
            },
        ],
        max_detections_per_image=1,
        similarity_func=lambda pred, gt: bbox_iou_xyxy(
            pred["bbox_xyxy"],
            gt["bbox_xyxy"],
        ),
    )

    assert result.ap50 == 1.0
    metrics_by_category = {
        item["category_id"]: item for item in result.per_class_metrics
    }
    assert metrics_by_category[0]["pred_count"] == 1
    assert metrics_by_category[1]["pred_count"] == 1


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


def test_non_coco_pose_uses_explicit_equal_oks_sigmas() -> None:
    """非 COCO 关键点拓扑不得把第 18 点以后静默塞入兜底常量。"""

    sigmas = resolve_keypoint_oks_sigmas(21)

    assert len(sigmas) == 21
    assert all(value == 1.0 / 21.0 for value in sigmas)


def test_pose_training_metrics_use_real_pycocotools_keypoints_evaluator() -> None:
    """三模型共享 pose evaluator 必须输出真实 COCO OKS AP。"""

    pytest.importorskip("pycocotools.cocoeval")
    keypoints = [10.0, 10.0, 2.0, 20.0, 20.0, 2.0]
    metrics = compute_pycocotools_pose_ap(
        gt_items=[
            {
                "image_id": 0,
                "category_id": 0,
                "keypoints": keypoints,
                "bbox_xyxy": [4.0, 4.0, 24.0, 24.0],
                "area": 400.0,
            }
        ],
        pred_items=[
            {
                "image_id": 0,
                "category_id": 0,
                "keypoints": [10.0, 10.0, 0.9, 20.0, 20.0, 0.8],
                "score": 0.99,
            }
        ],
        category_names={0: "hand"},
        image_count=1,
        keypoint_count=2,
        keypoint_oks_sigmas=(0.5, 0.5),
    )

    assert metrics.ap50 == pytest.approx(1.0)
    assert metrics.ap50_95 == pytest.approx(1.0)


def test_pose_bbox_metrics_use_real_pycocotools_detection_evaluator() -> None:
    """pose 的 box 指标必须独立于 OKS，并使用同一共享 COCO evaluator。"""

    pytest.importorskip("pycocotools.cocoeval")
    metrics = compute_pycocotools_detection_ap(
        gt_items=[
            {
                "image_id": 0,
                "category_id": 0,
                "bbox_xyxy": [4.0, 4.0, 24.0, 24.0],
            }
        ],
        pred_items=[
            {
                "image_id": 0,
                "category_id": 0,
                "bbox_xyxy": [4.0, 4.0, 24.0, 24.0],
                "score": 0.99,
            }
        ],
        category_names={0: "hand"},
        image_count=1,
    )

    assert metrics.ap50 == pytest.approx(1.0)
    assert metrics.ap50_95 == pytest.approx(1.0)


def test_segmentation_does_not_fallback_to_bbox_when_masks_are_missing() -> None:
    """有 GT mask 但没有预测 mask 时，主指标必须明确为零。"""

    primary = resolve_segmentation_primary_metrics(
        bbox_metrics=CocoStyleMetricResult(ap50=0.9, ap50_95=0.8),
        mask_metrics=CocoStyleMetricResult(ap50=0.0, ap50_95=0.0),
        has_ground_truth_masks=True,
    )

    assert primary.ap50 == 0.0
    assert primary.ap50_95 == 0.0


def test_segmentation_training_metrics_use_compressed_rle_and_real_cocoeval() -> None:
    """dense mask 必须立即压缩，并由真实 pycocotools 得到完整 AP。"""

    pytest.importorskip("pycocotools.cocoeval")
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[4:20, 6:24] = 1
    rle = encode_binary_mask_to_coco_rle(mask)

    assert isinstance(rle["counts"], str)
    assert rle["size"] == [32, 32]
    assert "mask" not in rle

    bbox_metrics, mask_metrics = compute_pycocotools_segmentation_ap(
        gt_bbox_items=[
            {"image_id": 0, "category_id": 0, "bbox_xyxy": [6, 4, 24, 20]}
        ],
        pred_bbox_items=[
            {
                "image_id": 0,
                "category_id": 0,
                "bbox_xyxy": [6, 4, 24, 20],
                "score": 0.99,
            }
        ],
        gt_mask_items=[
            {"image_id": 0, "category_id": 0, "segmentation": rle}
        ],
        pred_mask_items=[
            {
                "image_id": 0,
                "category_id": 0,
                "segmentation": rle,
                "score": 0.99,
            }
        ],
        category_names={0: "package"},
        image_count=1,
        image_size=(32, 32),
    )

    assert bbox_metrics.ap50 == pytest.approx(1.0)
    assert bbox_metrics.ap50_95 == pytest.approx(1.0)
    assert mask_metrics.ap50 == pytest.approx(1.0)
    assert mask_metrics.ap50_95 == pytest.approx(1.0)


def test_segmentation_predictions_are_limited_before_mask_decode() -> None:
    """低分候选必须在 dense mask 构造前截断。"""

    instances = [
        type("_Instance", (), {"score": float(index)})()
        for index in range(12)
    ]

    limited = limit_segmentation_prediction_instances(instances, max_detections=3)

    assert [instance.score for instance in limited] == [11.0, 10.0, 9.0]


def test_segmentation_polygon_is_encoded_without_dense_mask_materialization() -> None:
    """预测 polygon 应直接进入 pycocotools RLE C 路径。"""

    coco_mask = pytest.importorskip("pycocotools.mask")
    rle = encode_coco_polygons_to_rle(
        (((4.0, 4.0), (20.0, 4.0), (20.0, 20.0), (4.0, 20.0)),),
        width=32,
        height=32,
    )

    assert rle is not None
    assert rle["size"] == [32, 32]
    assert isinstance(rle["counts"], str)
    assert float(coco_mask.area(rle)) == pytest.approx(256.0)


def test_downsampled_training_mask_is_restored_before_coco_encoding() -> None:
    """训练用低分辨率 GT mask 必须恢复到 COCO image 尺寸。"""

    cv2 = pytest.importorskip("cv2")
    restored = resize_binary_mask_for_coco_evaluation(
        binary_mask=np.asarray([[1, 0], [0, 1]], dtype=np.uint8),
        image_size=(4, 4),
        cv2_module=cv2,
        np_module=np,
    )
    rle = encode_binary_mask_to_coco_rle(restored)

    assert restored.shape == (4, 4)
    assert int(restored.sum()) == 8
    assert rle["size"] == [4, 4]


def test_rotated_iou_xywhr_returns_full_score_for_same_box() -> None:
    """验证相同旋转框的 rotated IoU 为 1。"""

    assert (
        rotated_iou_xywhr(
            [8.0, 8.0, 6.0, 4.0, 0.3],
            [8.0, 8.0, 6.0, 4.0, 0.3],
        )
        == 1.0
    )
