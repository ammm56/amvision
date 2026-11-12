"""专用媒体版本比较：实际附件、物理语义、派生显示和中断边界。"""

from dataclasses import replace

import pytest

from backend.service.application.datasets.imports.formats.sample_media import asset_path
from backend.service.application.datasets.workspace_analysis import (
    compare_versions,
    image_path,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetSample,
    DatasetVersion,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def versions(tmp_path, kind, assets):
    """构造稳定来源相同、独立文件路径的两个受管版本。"""
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    result = []
    for i in range(2):
        media = {
            "kind": kind,
            "assets": list(assets),
            "unit": "mm",
            "scale": 1.0,
            "invalid": 0,
        }
        sample = DatasetSample(
            f"s{i}",
            1,
            "sample.png",
            2,
            2,
            "test",
            metadata={
                "origin_sample_id": "original",
                "sample_media": media,
                "image_object_key": "images/sample.png",
            },
        )
        version = DatasetVersion(f"v{i}", "d", "p", (), (sample,), kind)
        path = image_path(storage, version, sample)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"same source image")
        for name in assets:
            asset_path(path, name).write_bytes(b"same asset")
        result.append(version)
    return storage, *result


@pytest.mark.parametrize(
    "kind,assets,changed",
    [
        ("rgbd", ["depth"], "depth"),
        ("point-cloud", ["cloud"], "cloud"),
        ("anomaly", ["mask"], "mask"),
        ("rgbd", ["depth", "calibration"], "calibration"),
        ("connector-reference", ["calibration"], "calibration"),
    ],
)
def test_original_asset_changes_are_reported(tmp_path, kind, assets, changed):
    """同图换深度、同预览换原云、改掩膜和标定均必须可见。"""
    storage, before, after = versions(tmp_path, kind, assets)
    asset_path(image_path(storage, after, after.samples[0]), changed).write_bytes(
        b"changed original"
    )
    result = compare_versions(storage, before, after, lambda *args: None)
    assert result["counts"] == {changed: 1, "changed_samples": 1}
    assert result["changes"][0]["kinds"] == [changed]


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("rgbd", "unit", "m"),
        ("rgbd", "scale", 0.001),
        ("rgbd", "invalid", 65535),
        ("rgbd", "alignment", "registered"),
        ("point-cloud", "frame", "fixture"),
        ("anomaly", "label", "anomaly"),
        ("connector-reference", "pitch", 2.5),
        ("connector-reference", "pins", [{"id": "P", "x": 1, "y": 2}]),
        (
            "connector-reference",
            "measured",
            [{"name": "height", "value": 3, "unit": "mm", "source": "gauge"}],
        ),
    ],
)
def test_physical_and_reference_metadata_changes(tmp_path, kind, field, value):
    """字段集合取自公开输入契约，不能仅检查单位而漏掉其他测量含义。"""
    assets = {"rgbd": ["depth"], "point-cloud": ["cloud"]}.get(kind, [])
    storage, before, after = versions(tmp_path, kind, assets)
    after.samples[0].metadata["sample_media"][field] = value
    assert compare_versions(storage, before, after, lambda *args: None)["counts"] == {
        "media_metadata": 1,
        "changed_samples": 1,
    }


def test_optional_asset_added_removed_and_unchanged(tmp_path):
    """附件新增/删除算变化，逐字节相同则不报变化。"""
    storage, before, after = versions(tmp_path, "anomaly", ["mask"])
    assert compare_versions(storage, before, after, lambda *args: None)["changes"] == []
    after.samples[0].metadata["sample_media"]["assets"] = []
    for a, b in [(before, after), (after, before)]:
        assert (
            compare_versions(storage, a, b, lambda *args: None)["counts"]["mask"] == 1
        )


def test_derived_previews_and_storage_names_are_not_source_changes(tmp_path):
    """点云预览重建、统计值和包内名称改变不能误报原始数据变化。"""
    storage, before, after = versions(tmp_path, "point-cloud", ["cloud", "points"])
    path = image_path(storage, after, after.samples[0])
    path.write_bytes(b"new preview")
    asset_path(path, "points").write_bytes(b"new display sampling")
    after.samples[0].metadata["sample_media"].update(
        preview_count=123, calibration_name="other.json", origin=[1, 2, 3]
    )
    assert compare_versions(storage, before, after, lambda *args: None)["changes"] == []


def test_missing_declared_source_fails_and_cancel_propagates(tmp_path):
    """附件缺失不等于未变化；摘要分块期间必须响应取消。"""
    storage, before, after = versions(tmp_path, "rgbd", ["depth"])
    path = asset_path(image_path(storage, after, after.samples[0]), "depth")
    path.unlink()
    with pytest.raises(FileNotFoundError):
        compare_versions(storage, before, after, lambda *args: None)
    after.samples[0].metadata["sample_media"]["assets"] = []
    with pytest.raises(InvalidRequestError):
        compare_versions(storage, before, after, lambda *args: None)

    def cancel(*args):
        """仅在实际读块的 tick 中取消，不在样本遍历入口取消。"""
        if not args:
            raise InterruptedError("cancel")

    with pytest.raises(InterruptedError):
        compare_versions(storage, before, before, cancel)


def test_ordinary_image_comparison_preserved(tmp_path):
    """非专用媒体的原图比较保持原行为。"""
    storage, before, after = versions(tmp_path, "rgbd", [])
    before, after = [
        replace(
            v,
            task_type="detection",
            samples=(
                replace(
                    v.samples[0],
                    metadata={
                        "origin_sample_id": "original",
                        "image_object_key": "images/sample.png",
                    },
                ),
            ),
        )
        for v in (before, after)
    ]
    image_path(storage, after, after.samples[0]).write_bytes(b"different image")
    assert compare_versions(storage, before, after, lambda *args: None)["counts"] == {
        "image": 1,
        "changed_samples": 1,
    }
