"""classification 数据集级评估完整性测试。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.models.evaluation.yolov8_classification_evaluation import (
    _parse_classification_manifest,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_classification_manifest_keeps_zero_class_id(tmp_path: Path) -> None:
    """验证 class_id=0 不会错误回退到 category_id。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    split_name, samples, labels = _parse_classification_manifest(
        {
            "categories": [{"id": 0, "name": "ok"}, {"id": 1, "name": "ng"}],
            "splits": [
                {
                    "name": "validation",
                    "image_root": "exports/images",
                    "annotations": [
                        {
                            "file_name": "sample.png",
                            "class_id": 0,
                            "category_id": 1,
                        }
                    ],
                }
            ],
        },
        storage,
    )

    assert split_name == "validation"
    assert labels == ("ok", "ng")
    assert samples == [{"image_path": "exports/images/sample.png", "class_id": 0}]
