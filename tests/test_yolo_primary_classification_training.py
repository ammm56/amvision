"""classification 训练链烟雾验证。"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.yolo_primary_classification_training import (
    YoloPrimaryClassificationTrainingExecutionRequest,
    run_yolo_primary_classification_training,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def _build_classification_smoke_data(
    root: Path,
) -> tuple[LocalDatasetStorage, dict[str, object]]:
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(root)))
    for split_name in ("train", "val"):
        image_dir = root / f"exports/demo/images/{split_name}"
        ann_dir = root / "exports/demo/annotations"
        image_dir.mkdir(parents=True, exist_ok=True)
        ann_dir.mkdir(parents=True, exist_ok=True)
        for i in range(4):
            image = np.zeros((128, 128, 3), dtype=np.uint8)
            color = 255 if i < 2 else 128
            cv2.rectangle(image, (10, 10), (118, 118), (color, color, color), -1)
            file_name = f"{split_name}-{i}.jpg"
            cv2.imwrite(str(image_dir / file_name), image)
        annotations = {
            "images": [
                {
                    "id": j + 1,
                    "file_name": f"{split_name}-{j}.jpg",
                    "width": 128,
                    "height": 128,
                }
                for j in range(4)
            ],
            "annotations": [
                {"id": j + 1, "image_id": j + 1, "category_id": 1 if j < 2 else 2}
                for j in range(4)
            ],
            "categories": [{"id": 1, "name": "bright"}, {"id": 2, "name": "dim"}],
        }
        (ann_dir / f"{split_name}.json").write_text(
            json.dumps(annotations), encoding="utf-8"
        )
    manifest = {
        "splits": [
            {
                "name": "train",
                "image_root": "exports/demo/images/train",
                "annotation_file": "exports/demo/annotations/train.json",
            },
            {
                "name": "val",
                "image_root": "exports/demo/images/val",
                "annotation_file": "exports/demo/annotations/val.json",
            },
        ],
    }
    return storage, manifest


def test_classification_training_runs_one_epoch():
    """验证分类训练可以执行一个 epoch 并返回有效的指标。"""
    import shutil

    root = Path(".tmp/classification-training-smoke").resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    storage, manifest = _build_classification_smoke_data(root)
    request = YoloPrimaryClassificationTrainingExecutionRequest(
        dataset_storage=storage,
        manifest_payload=manifest,
        model_type="yolov8",
        model_scale="nano",
        batch_size=2,
        max_epochs=1,
        evaluation_interval=1,
        input_size=(64, 64),
        precision="fp32",
        extra_options={"device": "cpu"},
    )
    result = run_yolo_primary_classification_training(request)
    assert result.best_metric_name == "val_top1_accuracy"
    assert result.best_metric_value >= 0.0
    assert len(result.labels) == 2
    assert result.latest_checkpoint_bytes
    final_metrics = result.metrics_payload.get("final_metrics", {})
    assert "loss" in final_metrics
    assert "accuracy" in final_metrics
    shutil.rmtree(root)


def test_primary_classification_runner_rejects_yolo11():
    """验证 YOLO11 classification 不再回落到 primary 执行器。"""
    import shutil

    root = Path(".tmp/classification-training-yolo11-reject").resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    storage, manifest = _build_classification_smoke_data(root)
    request = YoloPrimaryClassificationTrainingExecutionRequest(
        dataset_storage=storage,
        manifest_payload=manifest,
        model_type="yolo11",
        model_scale="nano",
        batch_size=2,
        max_epochs=1,
        evaluation_interval=1,
        input_size=(64, 64),
        precision="fp32",
        extra_options={"device": "cpu"},
    )

    with pytest.raises(InvalidRequestError, match="yolo11_classification_training"):
        run_yolo_primary_classification_training(request)
    shutil.rmtree(root)


def test_classification_training_imports():
    """验证分类训练模块可以被导入。"""
    from backend.service.application.models.training.yolo_primary_classification_training import (
        YoloPrimaryClassificationTrainingExecutionRequest,
        run_yolo_primary_classification_training,
    )
    from backend.service.application.models.training.yolo_primary_classification_training_service import (
        SqlAlchemyYoloPrimaryClassificationTrainingTaskService,
        YoloPrimaryClassificationTrainingTaskRequest,
    )

    assert YoloPrimaryClassificationTrainingExecutionRequest is not None
    assert run_yolo_primary_classification_training is not None
    assert SqlAlchemyYoloPrimaryClassificationTrainingTaskService is not None
    assert YoloPrimaryClassificationTrainingTaskRequest is not None
