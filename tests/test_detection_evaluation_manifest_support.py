"""Detection evaluation manifest 解析回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from backend.service.application.models.evaluation.detection_evaluation import (
    _parse_detection_manifest,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_parse_detection_manifest_supports_coco_detection_export(
    tmp_path: Path,
) -> None:
    """验证 detection evaluation 可以直接解析 COCO detection manifest。"""

    storage_root = tmp_path / "dataset-storage"
    image_root = storage_root / "exports" / "sample" / "images" / "val"
    annotation_root = storage_root / "exports" / "sample" / "annotations"
    image_root.mkdir(parents=True, exist_ok=True)
    annotation_root.mkdir(parents=True, exist_ok=True)

    image = np.full((32, 48, 3), 120, dtype=np.uint8)
    assert cv2.imwrite(str(image_root / "sample-1.jpg"), image) is True
    annotation_path = annotation_root / "instances_val.json"
    annotation_path.write_text(
        json.dumps(
            {
                "images": [{"id": 1, "file_name": "sample-1.jpg", "width": 48, "height": 32}],
                "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 8, 20, 12]}],
                "categories": [{"id": 1, "name": "barcode"}],
            }
        ),
        encoding="utf-8",
    )

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(storage_root)))
    split_name, images, categories = _parse_detection_manifest(
        {
            "format_id": "coco-detection-v1",
            "splits": [
                {
                    "name": "val",
                    "image_root": "exports/sample/images/val",
                    "annotation_file": "exports/sample/annotations/instances_val.json",
                }
            ],
        },
        storage,
    )

    assert split_name == "val"
    assert categories == [{"id": 1, "name": "barcode"}]
    assert len(images) == 1
    assert images[0]["image_path"] == "exports/sample/images/val/sample-1.jpg"
    assert images[0]["annotations"][0]["bbox"] == [10, 8, 20, 12]


def test_parse_detection_manifest_supports_yolo_detection_export(
    tmp_path: Path,
) -> None:
    """验证 detection evaluation 可以直接解析 YOLO detection manifest。"""

    storage_root = tmp_path / "dataset-storage"
    image_root = storage_root / "exports" / "sample" / "images" / "test"
    label_root = storage_root / "exports" / "sample" / "labels" / "test"
    image_root.mkdir(parents=True, exist_ok=True)
    label_root.mkdir(parents=True, exist_ok=True)

    image = np.full((100, 200, 3), 150, dtype=np.uint8)
    assert cv2.imwrite(str(image_root / "sample-1.jpg"), image) is True
    (label_root / "sample-1.txt").write_text("0 0.5 0.5 0.2 0.4\n", encoding="utf-8")

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(storage_root)))
    split_name, images, categories = _parse_detection_manifest(
        {
            "format_id": "yolo-detection-v1",
            "category_names": ["barcode"],
            "splits": [
                {
                    "name": "test",
                    "image_root": "exports/sample/images/test",
                    "label_root": "exports/sample/labels/test",
                }
            ],
        },
        storage,
    )

    assert split_name == "test"
    assert categories == [{"id": 1, "name": "barcode"}]
    assert len(images) == 1
    assert images[0]["image_path"] == "exports/sample/images/test/sample-1.jpg"
    assert images[0]["annotations"][0]["category_id"] == 1
    assert images[0]["annotations"][0]["bbox"] == [80.0, 30.0, 40.0, 40.0]
