"""YOLO 主线 detection 训练增强与 E2E 路径测试。"""

from __future__ import annotations

import random
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import torch

from backend.service.application.models.yolo_primary_detection_model import (
    build_yolo_primary_detection_model,
)
from backend.service.application.models.detection_postprocess import (
    DETECTION_POSTPROCESS_MODE_END2END_TOPK,
    DETECTION_POSTPROCESS_MODE_NMS,
    postprocess_detection_prediction_array,
)
from backend.service.application.models.yolo_primary_detection_training import (
    _PreparedTrainingTarget,
    _ResolvedTrainingAnnotation,
    _ResolvedTrainingSample,
    _build_training_batch,
    _compute_e2e_detection_loss,
    _load_coco_ground_truth_silently,
    _load_training_samples,
    _resolve_detection_augmentation_options,
    _resolve_detection_splits,
    _unwrap_e2e_detection_outputs,
)
from backend.service.application.runtime.yolo_primary_predictor import (
    _resolve_yolo_primary_postprocess_strategy,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_build_training_batch_flip_prob_one_flips_bbox_horizontally(
    tmp_path: Path,
) -> None:
    """验证 detection 训练 batch 在 flip_prob=1 时会正确翻转 bbox。"""

    sample = _write_detection_sample(
        tmp_path=tmp_path,
        file_name="flip-sample.jpg",
        color=(60, 120, 180),
        bbox_xyxy=(10.0, 20.0, 30.0, 50.0),
    )
    images, batch_targets = _build_training_batch(
        imports=SimpleNamespace(cv2=cv2, np=np, torch=torch),
        samples=[sample],
        input_size=(64, 64),
        device="cpu",
        runtime_precision="fp32",
        augment_training=True,
        available_samples=(sample,),
        augmentation_options=_resolve_detection_augmentation_options(
            {
                "flip_prob": 1.0,
                "hsv_prob": 0.0,
                "mosaic_prob": 0.0,
                "mixup_prob": 0.0,
                "degrees": 0.0,
                "translate": 0.0,
                "shear": 0.0,
            }
        ),
    )

    assert tuple(images.shape) == (1, 3, 64, 64)
    assert len(batch_targets) == 1
    assert len(batch_targets[0].boxes_xyxy) == 1
    x1, y1, x2, y2 = batch_targets[0].boxes_xyxy[0]
    assert x1 == pytest.approx(44.8, abs=1e-3)
    assert y1 == pytest.approx(12.8, abs=1e-3)
    assert x2 == pytest.approx(57.6, abs=1e-3)
    assert y2 == pytest.approx(32.0, abs=1e-3)


def test_build_training_batch_mosaic_mixup_keeps_boxes_in_bounds(
    tmp_path: Path,
) -> None:
    """验证 Mosaic + MixUp 进入正式训练 batch 后 bbox 仍保持在输入范围内。"""

    samples = tuple(
        _write_detection_sample(
            tmp_path=tmp_path,
            file_name=f"mosaic-sample-{index}.jpg",
            color=(40 + index * 20, 90 + index * 10, 140 + index * 5),
            bbox_xyxy=(10.0 + index, 12.0 + index, 34.0 + index, 40.0 + index),
        )
        for index in range(4)
    )
    random.seed(0)
    images, batch_targets = _build_training_batch(
        imports=SimpleNamespace(cv2=cv2, np=np, torch=torch),
        samples=[samples[0], samples[1]],
        input_size=(64, 64),
        device="cpu",
        runtime_precision="fp32",
        augment_training=True,
        available_samples=samples,
        augmentation_options=_resolve_detection_augmentation_options(
            {
                "flip_prob": 0.0,
                "hsv_prob": 0.0,
                "mosaic_prob": 1.0,
                "enable_mixup": True,
                "mixup_prob": 1.0,
                "degrees": 0.0,
                "translate": 0.0,
                "shear": 0.0,
                "mosaic_scale": [1.0, 1.0],
                "mixup_scale": [1.0, 1.0],
            }
        ),
    )

    assert tuple(images.shape) == (2, 3, 64, 64)
    for target in batch_targets:
        assert len(target.boxes_xyxy) >= 1
        for x1, y1, x2, y2 in target.boxes_xyxy:
            assert 0.0 <= x1 < x2 <= 64.0
            assert 0.0 <= y1 < y2 <= 64.0


def test_yolo26_e2e_loss_path_runs_with_dual_branch_outputs() -> None:
    """验证 YOLO26 E2E 双分支损失路径可以稳定执行。"""

    model = build_yolo_primary_detection_model(
        model_type="yolo26",
        model_scale="nano",
        num_classes=2,
    )
    model.train()
    outputs = model(torch.randn(1, 3, 64, 64))
    one2many_outputs, one2one_outputs = _unwrap_e2e_detection_outputs(outputs)

    assert "boxes" in one2many_outputs
    assert "scores" in one2many_outputs
    assert "boxes" in one2one_outputs
    assert "scores" in one2one_outputs

    loss_components = _compute_e2e_detection_loss(
        imports=SimpleNamespace(torch=torch),
        model=model,
        raw_outputs=(one2many_outputs, one2one_outputs),
        batch_targets=(
            _PreparedTrainingTarget(
                image_id=1,
                image_width=64,
                image_height=64,
                boxes_xyxy=((10.0, 10.0, 30.0, 30.0),),
                category_indexes=(1,),
            ),
        ),
        num_classes=2,
        class_loss_weight=0.5,
        box_loss_weight=7.5,
        dfl_loss_weight=1.5,
        assign_topk=10,
        assign_alpha=0.5,
        assign_beta=6.0,
        e2e_o2m_weight=0.8,
        e2e_o2o_weight=0.2,
    )

    assert torch.isfinite(loss_components["loss"]).item() is True
    assert torch.isfinite(loss_components["class_loss"]).item() is True
    assert torch.isfinite(loss_components["box_loss"]).item() is True
    assert torch.isfinite(loss_components["dfl_loss"]).item() is True
    assert torch.isfinite(loss_components["one2many_loss"]).item() is True
    assert torch.isfinite(loss_components["one2one_loss"]).item() is True

    loss_components["loss"].backward()
    grad_tensors = [parameter.grad for parameter in model.parameters() if parameter.grad is not None]
    assert grad_tensors
    assert all(torch.isfinite(gradient).all().item() for gradient in grad_tensors)


def test_postprocess_detection_prediction_array_end2end_topk_keeps_duplicate_boxes() -> None:
    """验证 end-to-end detection 后处理会使用 top-k，而不是通用 NMS。"""

    prediction_array = np.array(
        [
            [
                [10.0, 10.0, 30.0, 30.0, 0.95, 0.05],
                [10.0, 10.0, 30.0, 30.0, 0.90, 0.10],
                [11.0, 11.0, 31.0, 31.0, 0.85, 0.15],
            ]
        ],
        dtype=np.float32,
    )

    nms_results = postprocess_detection_prediction_array(
        prediction_array=prediction_array,
        np_module=np,
        num_classes=2,
        score_threshold=0.1,
        nms_threshold=0.5,
        postprocess_mode=DETECTION_POSTPROCESS_MODE_NMS,
    )
    topk_results = postprocess_detection_prediction_array(
        prediction_array=prediction_array,
        np_module=np,
        num_classes=2,
        score_threshold=0.1,
        nms_threshold=0.5,
        postprocess_mode=DETECTION_POSTPROCESS_MODE_END2END_TOPK,
        max_detections=3,
    )

    assert nms_results[0] is not None
    assert topk_results[0] is not None
    assert len(nms_results[0].scores) == 1
    assert len(topk_results[0].scores) == 3
    assert list(topk_results[0].scores) == pytest.approx([0.95, 0.9, 0.85])


def test_yolo26_runtime_postprocess_strategy_uses_end2end_topk() -> None:
    """验证 YOLO26 detection runtime 会走 end-to-end top-k 后处理。"""

    assert _resolve_yolo_primary_postprocess_strategy(model_type="yolo26") == (
        DETECTION_POSTPROCESS_MODE_END2END_TOPK,
        300,
    )
    assert _resolve_yolo_primary_postprocess_strategy(model_type="yolov8") == (
        DETECTION_POSTPROCESS_MODE_NMS,
        None,
    )


def test_resolve_detection_splits_supports_yolo_detection_manifest(
    tmp_path: Path,
) -> None:
    """验证 YOLO detection manifest 可以直接被主线 detection 训练加载。"""

    storage_root = tmp_path / "dataset-storage"
    image_root = storage_root / "exports" / "sample" / "images" / "train"
    label_root = storage_root / "exports" / "sample" / "labels" / "train"
    image_root.mkdir(parents=True, exist_ok=True)
    label_root.mkdir(parents=True, exist_ok=True)

    image_path = image_root / "sample-1.jpg"
    image = np.full((100, 200, 3), 180, dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image) is True
    label_path = label_root / "sample-1.txt"
    label_path.write_text("0 0.5 0.5 0.2 0.4\n", encoding="utf-8")

    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(storage_root)))
    resolved_splits = _resolve_detection_splits(
        dataset_storage=dataset_storage,
        imports=SimpleNamespace(cv2=cv2, np=np, torch=torch, COCO=None, COCOeval=None),
        manifest_payload={
            "format_id": "yolo-detection-v1",
            "category_names": ["barcode"],
            "splits": [
                {
                    "name": "train",
                    "image_root": "exports/sample/images/train",
                    "label_root": "exports/sample/labels/train",
                }
            ],
        },
    )

    assert len(resolved_splits) == 1
    resolved_split = resolved_splits[0]
    assert resolved_split.annotation_file is None
    assert resolved_split.sample_count == 1

    samples, category_names, category_ids = _load_training_samples(
        imports=SimpleNamespace(),
        split=resolved_split,
    )
    assert category_names == ("barcode",)
    assert category_ids == (1,)
    assert len(samples) == 1
    assert samples[0].image_width == 200
    assert samples[0].image_height == 100
    assert len(samples[0].annotations) == 1
    x1, y1, x2, y2 = samples[0].annotations[0].bbox_xyxy
    assert x1 == pytest.approx(80.0)
    assert y1 == pytest.approx(30.0)
    assert x2 == pytest.approx(120.0)
    assert y2 == pytest.approx(70.0)


def test_load_coco_ground_truth_silently_supports_in_memory_payload() -> None:
    """验证验证阶段可以直接使用内存中的 COCO ground truth。"""

    imports = SimpleNamespace(
        cv2=cv2,
        np=np,
        torch=torch,
        COCO=pytest.importorskip("pycocotools.coco").COCO,
        COCOeval=pytest.importorskip("pycocotools.cocoeval").COCOeval,
    )
    ground_truth = _load_coco_ground_truth_silently(
        imports=imports,
        annotation_file=None,
        annotation_payload={
            "images": [{"id": 1, "file_name": "sample-1.jpg", "width": 200, "height": 100}],
            "annotations": [
                {
                    "id": 1,
                    "image_id": 1,
                    "category_id": 1,
                    "bbox": [80.0, 30.0, 40.0, 40.0],
                    "area": 1600.0,
                    "iscrowd": 0,
                }
            ],
            "categories": [{"id": 1, "name": "barcode"}],
        },
    )

    assert ground_truth.getImgIds() == [1]
    assert ground_truth.getCatIds() == [1]
    assert ground_truth.getAnnIds(imgIds=[1]) == [1]


def _write_detection_sample(
    *,
    tmp_path: Path,
    file_name: str,
    color: tuple[int, int, int],
    bbox_xyxy: tuple[float, float, float, float],
) -> _ResolvedTrainingSample:
    """写入一张最小训练图片并返回解析后的训练样本。"""

    image_path = tmp_path / file_name
    image = np.full((100, 100, 3), color, dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image) is True
    return _ResolvedTrainingSample(
        image_id=1,
        image_path=image_path,
        image_width=100,
        image_height=100,
        annotations=(
            _ResolvedTrainingAnnotation(
                category_index=0,
                category_id=1,
                bbox_xyxy=bbox_xyxy,
            ),
        ),
    )
