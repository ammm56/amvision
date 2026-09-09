"""验证分割评估保留原始 mask，显示用轮廓不进入指标计算。"""

import numpy as np
import pytest
from pycocotools import mask as coco_mask

from backend.service.application.models.evaluation.segmentation_evaluation import (
    _build_segmentation_annotation_mask,
    _mask_iou,
)
from backend.service.application.models.evaluation.coco_style_metrics import (
    encode_binary_mask_to_coco_rle,
)
from backend.service.application.runtime.contracts.segmentation.evaluation import (
    SegmentationEvaluationPredictionInstance,
    SegmentationEvaluationPredictionRequest,
    retain_segmentation_metric_mask,
)
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.result import (
    build_rfdetr_segmentation_instances,
)


@pytest.mark.parametrize("shape", ["hole", "line", "empty"])
def test_metric_mask_roundtrip_preserves_all_pixels(shape):
    """孔洞、细线和空 mask 都原样保留，不经过轮廓近似。"""
    import cv2
    import torch

    mask = np.zeros((12, 12), dtype=bool)
    if shape == "hole":
        mask[1:11, 1:11] = True
        mask[3:9, 3:9] = False
    elif shape == "line":
        mask[3, 1:11] = True
    kwargs = dict(
        cv2_module=cv2,
        scores=torch.tensor([[0.92345678]]),
        labels=torch.tensor([[0]]),
        boxes_xyxy=torch.tensor([[[1.0, 1.0, 11.0, 11.0]]]),
        masks=torch.tensor(mask)[None, None],
        label_names=("target",),
        score_threshold=0.01,
        mask_threshold=0.5,
    )
    metric = build_rfdetr_segmentation_instances(**kwargs, retain_metric_mask=True)[0]
    ordinary = build_rfdetr_segmentation_instances(**kwargs)[0]
    assert isinstance(metric, SegmentationEvaluationPredictionInstance)
    np.testing.assert_array_equal(coco_mask.decode(metric.mask_rle), mask)
    assert metric.mask_area == int(mask.sum())
    assert not hasattr(ordinary, "mask_rle")
    assert ordinary.mask_area == metric.mask_area
    if shape == "hole":
        filled = mask.copy()
        filled[3:9, 3:9] = True
        assert _mask_iou(
            metric.mask_rle, encode_binary_mask_to_coco_rle(filled)
        ) == pytest.approx(0.64)


def test_evaluation_mask_mode_requires_internal_request():
    """普通推理协议无法通过自由参数开启评估专用结果。"""
    options = dict(score_threshold=0.01, mask_threshold=0.5, save_result_image=False)
    assert not retain_segmentation_metric_mask(SegmentationPredictionRequest(**options))
    assert retain_segmentation_metric_mask(
        SegmentationEvaluationPredictionRequest(**options)
    )


def test_coco_annotation_polygon_uses_pixel_cell_semantics():
    """COCO 矩形面积为 100，不把端点多填成 Pillow 的 121。"""
    mask = _build_segmentation_annotation_mask(
        annotation={"segmentation": [[0, 0, 10, 0, 10, 10, 0, 10]]},
        width=12,
        height=12,
    )
    assert mask.sum() == 100


def test_coco_annotation_rle_keeps_holes():
    """压缩 RLE 标注包含的孔洞不能被外轮廓填充。"""
    mask = np.ones((12, 12), dtype=bool)
    mask[2:10, 2:10] = False
    rle = encode_binary_mask_to_coco_rle(mask)
    decoded = _build_segmentation_annotation_mask(
        annotation={"segmentation": rle},
        width=12,
        height=12,
    )
    np.testing.assert_array_equal(decoded, mask)
    assert _mask_iou(rle, rle) == 1


def test_coco_annotation_uncompressed_rle():
    """未压缩 COCO RLE 与压缩形式按同一栅格读取。"""
    decoded = _build_segmentation_annotation_mask(
        annotation={"segmentation": {"size": [2, 3], "counts": [1, 2, 3]}},
        width=3,
        height=2,
    )
    np.testing.assert_array_equal(decoded, [[0, 1, 0], [1, 0, 0]])
