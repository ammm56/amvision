"""数据集格式严格校验与资源边界测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.application.datasets.imports.formats.coco import (
    CocoDatasetImportParserMixin,
)
from backend.service.application.datasets.imports.formats.yolo.manifest import (
    YoloManifestMixin,
)
from backend.service.application.datasets.imports.formats.yolo.scanner import (
    YoloScannerMixin,
)
from backend.service.application.datasets.imports.support import DatasetImportSupportMixin
from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


class _ImportParserHarness(
    YoloScannerMixin,
    YoloManifestMixin,
    CocoDatasetImportParserMixin,
    DatasetImportSupportMixin,
):
    """只组合格式校验所需的 mixin。"""

    def __init__(self, storage: LocalDatasetStorage) -> None:
        self.dataset_storage = storage


def _build_harness(tmp_path: Path, **setting_overrides: int) -> _ImportParserHarness:
    """创建使用显式安全上限的格式解析测试对象。"""

    return _ImportParserHarness(
        LocalDatasetStorage(
            DatasetStorageSettings(
                root_dir=str(tmp_path / "files"),
                **setting_overrides,
            )
        )
    )


def test_yolo_default_scanner_accepts_roboflow_valid_directory(tmp_path: Path) -> None:
    """验证 images/valid 与 labels/valid 会规范化为 val，不被错误跳过。"""

    parser = _build_harness(tmp_path)
    dataset_root = tmp_path / "dataset"
    (dataset_root / "images" / "valid").mkdir(parents=True)
    (dataset_root / "labels" / "valid").mkdir(parents=True)
    (dataset_root / "images" / "valid" / "sample.jpg").write_bytes(b"image")
    (dataset_root / "labels" / "valid" / "sample.txt").write_text(
        "",
        encoding="utf-8",
    )

    splits = parser._collect_default_yolo_split_image_entries(dataset_root)

    assert tuple(splits) == ("val",)
    assert splits["val"][0][1].name == "sample.jpg"


@pytest.mark.parametrize(
    "config_payload",
    [
        {"names": ["part", "part"]},
        {"names": {1: "part"}},
        {"names": {0: "part"}, "nc": 2},
        {"names": {0: " part"}},
    ],
)
def test_yolo_category_schema_rejects_ambiguous_definitions(
    tmp_path: Path,
    config_payload: dict[str, object],
) -> None:
    """验证重复名称、非连续 id、nc 错配和空白名称都会明确失败。"""

    parser = _build_harness(tmp_path)

    with pytest.raises(InvalidRequestError):
        parser._read_yolo_source_category_names(
            config_payload=config_payload,
            export_manifest_payload=None,
        )


def test_coco_ids_and_iscrowd_are_strict_integers(tmp_path: Path) -> None:
    """验证 COCO id 不接受字符串或 bool，iscrowd 不接受扩展值。"""

    parser = _build_harness(tmp_path)

    with pytest.raises(InvalidRequestError, match="非负整数"):
        parser._read_coco_id({"id": "1"}, "id", item_kind="image")
    with pytest.raises(InvalidRequestError, match="非负整数"):
        parser._read_coco_id({"id": True}, "id", item_kind="image")
    with pytest.raises(InvalidRequestError, match="0 或 1"):
        parser._read_coco_iscrowd({"iscrowd": 2})


def test_import_text_and_object_counts_fail_before_unbounded_allocation(
    tmp_path: Path,
) -> None:
    """验证 metadata、label、样本和标注都有可配置硬上限。"""

    parser = _build_harness(
        tmp_path,
        max_import_metadata_file_bytes=4,
        max_import_label_file_bytes=3,
        max_import_sample_count=2,
        max_import_annotation_count=3,
    )
    metadata_path = tmp_path / "metadata.json"
    label_path = tmp_path / "sample.txt"
    metadata_path.write_bytes(b"12345")
    label_path.write_bytes(b"1234")

    with pytest.raises(InvalidRequestError, match="安全读取上限"):
        parser._read_import_text(metadata_path, file_kind="metadata")
    with pytest.raises(InvalidRequestError, match="安全读取上限"):
        parser._read_import_text(label_path, file_kind="label")
    with pytest.raises(InvalidRequestError, match="样本数"):
        parser._require_import_capacity(sample_count=3, annotation_count=0)
    with pytest.raises(InvalidRequestError, match="标注数"):
        parser._require_import_capacity(sample_count=1, annotation_count=4)
