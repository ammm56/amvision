"""新版本显式映射、划分对照与预检查结果回归。"""
from dataclasses import replace

import pytest

from backend.contracts.datasets.workspace_jobs import DatasetDerivation
from backend.service.application.datasets.workspace_analysis import derivation_plan, derivation_checks
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import DatasetVersion, DatasetSample, DatasetCategory, DetectionAnnotation


def source_version():
    """构造含多个对象和同组样本的来源版本。"""
    samples = tuple(DatasetSample(
        sample_id=f"s{i}", image_id=i, file_name=f"{i}.jpg", width=10, height=10,
        split="train" if i < 2 else "test",
        annotations=tuple(DetectionAnnotation(f"a{i}-{c}", c, (0, 0, 2, 2)) for c in (0, 1)),
        metadata={"capture_group": "batch-a" if i < 2 else "batch-b"},
    ) for i in range(3))
    return DatasetVersion("v1", "d1", "p1", (DatasetCategory(0, "bolt"), DatasetCategory(1, "nut")), samples, "detection")


def test_mapping_merge_and_exclusion_preserve_source():
    """合并只改新版本标注 ID，排除保留负样本且对象统计同步变化。"""
    source = source_version()
    merged, summary = derivation_plan(source, DatasetDerivation(category_mapping={1: 0}), None)
    assert len(merged.categories) == 1
    assert all(a.category_id == 0 for s in merged.samples for a in s.annotations)
    assert summary["object_count"] == summary["source_object_count"] == 6
    assert summary["source_split_object_counts"] == {"train": 4, "test": 2}
    assert summary["category_changes"] == [{"category_id": 1, "before": "nut", "after": "bolt"}]
    excluded, summary = derivation_plan(source, DatasetDerivation(category_mapping={1: None}), None)
    assert len(excluded.samples) == 3
    assert summary["object_count"] == 3
    assert summary["split_object_counts"] == {"train": 2, "test": 1}
    assert summary["excluded_count"] == 0
    assert summary["category_changes"][0]["after"] is None
    assert len(source.categories) == 2
    assert source.samples[0].annotations[1].category_id == 1


@pytest.mark.parametrize("mapping", [{0: 1, 1: 0}, {1: 0, 0: None}, {0: None, 1: None}, {9: 0}, {1: 9}])
def test_invalid_mapping_rejected(mapping):
    """循环、已排除目标、空类别及未知 ID 均阻止创建。"""
    with pytest.raises(InvalidRequestError):
        derivation_plan(source_version(), DatasetDerivation(category_mapping=mapping), None)


def test_grouped_repartition_and_selected_counts():
    """实际划分不拆组，所选样本与对象变化按来源快照计算。"""
    source = source_version()
    config = DatasetDerivation(split_ratios=(50, 50, 0), group_key="capture_group")
    planned, summary = derivation_plan(source, config, {"s0", "s1"})
    assert planned.samples[0].split == planned.samples[1].split
    assert summary["group_integrity"] == "passed"
    assert summary["source_count"] == 3 and summary["sample_count"] == 2
    assert sum(summary["split_object_counts"].values()) == 4
    assert derivation_plan(source, config, {"s0", "s1"}) == (planned, summary)
    assert derivation_plan(source, DatasetDerivation(), None)[1]["group_integrity"] == "not_configured"
    with pytest.raises(InvalidRequestError, match="分组"):
        derivation_plan(source, DatasetDerivation(split_ratios=(80, 20, 0), group_key="missing"), None)


def test_duplicate_check_uses_content_and_reports_unreadable(tmp_path, monkeypatch):
    """跨划分完全重复计数来自文件内容；文件不可读时禁止报告通过。"""
    source = source_version()
    for sample in source.samples:
        (tmp_path / sample.file_name).write_bytes(b"same" if sample.image_id != 1 else b"different")
    monkeypatch.setattr("backend.service.application.datasets.workspace_analysis.image_path", lambda storage, version, sample: tmp_path / sample.file_name)
    report = derivation_checks(None, source, lambda *args: None)
    assert report["cross_split_duplicate_count"] == 2
    assert report["duplicate_check"] == "passed" and report["can_create"]
    (tmp_path / "2.jpg").unlink()
    report = derivation_checks(None, source, lambda *args: None)
    assert report["duplicate_check"] == "incomplete"
    assert report["unreadable_count"] == 1 and not report["can_create"]


def test_pose_does_not_silently_merge_incompatible_schemas():
    """未实现 schema 转换的任务不暴露不安全的类别映射。"""
    with pytest.raises(InvalidRequestError, match="任务类型"):
        derivation_plan(replace(source_version(), task_type="pose"), DatasetDerivation(category_mapping={1: 0}), None)
