"""模型类别信息在登记、文件和运行时快照中的一致性测试。"""

from pathlib import Path

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.targets.runtime_target import (
    _require_payload_labels,
    resolve_labels,
)
from backend.service.domain.files.model_file import ModelFile
from backend.service.domain.datasets.category_names import parse_category_names
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


@pytest.mark.parametrize(
    "value", [[], ["ok", "", "ng"], ["ok", None], ["ok", 2], ["ok", "ok"], ["ok\nng"]]
)
def test_model_labels_reject_invalid_indices(value: object) -> None:
    """非法条目不能被过滤后冒充有效类别映射。"""

    with pytest.raises(ValueError):
        parse_category_names(value, field_name="category_names")
    with pytest.raises(InvalidRequestError):
        _require_payload_labels({"labels": value})


def test_labels_keep_class_order() -> None:
    """模型输出类别顺序保持不变，不按名称排序。"""

    assert parse_category_names([" screw ", "bolt", "nut"], field_name="labels") == (
        "screw",
        "bolt",
        "nut",
    )


@pytest.mark.parametrize("separator", ["\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_labels_reject_every_line_separator(separator: str) -> None:
    """metadata 中的单类不能在 labels.txt 的 splitlines 中变为两个类别。"""

    with pytest.raises(ValueError):
        parse_category_names([f"part{separator}other"], field_name="labels")


@pytest.mark.parametrize("text", ["ok\nng\n", "ok\nng"])
def test_label_file_matches_metadata(tmp_path: Path, text: str) -> None:
    """文件和 metadata 同时存在时必须描述同一有序类别映射。"""

    storage, labels_file = _labels_file(tmp_path, text)
    assert resolve_labels(
        dataset_storage=storage,
        model_version_metadata={"category_names": ["ok", "ng"]},
        model_version_id="version-1",
        labels_file=labels_file,
    ) == ("ok", "ng")


@pytest.mark.parametrize(
    ("text", "metadata"),
    [
        ("ok\n\nng\n", {}),
        ("", {"category_names": ["ok", "ng"]}),
        ("ok\nng\n", {"category_names": ["ng", "ok"]}),
        ("ok\nng\n", {"category_names": ["ok", None, "ng"]}),
    ],
)
def test_labels_reject_inconsistent_sources(
    tmp_path: Path, text: str, metadata: dict[str, object]
) -> None:
    """文件损坏、条目丢失或顺序冲突均拒绝转换和部署。"""

    storage, labels_file = _labels_file(tmp_path, text)
    with pytest.raises(InvalidRequestError):
        resolve_labels(
            dataset_storage=storage,
            model_version_metadata=metadata,
            model_version_id="version-1",
            labels_file=labels_file,
        )


def _labels_file(tmp_path: Path, text: str) -> tuple[LocalDatasetStorage, ModelFile]:
    """创建当前测试自己的类别文件及登记记录。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    storage.write_text("labels.txt", text)
    return storage, ModelFile(
        file_id="labels-1",
        project_id="project-1",
        scope_kind="project",
        model_id="model-1",
        model_version_id="version-1",
        file_type="yolo11-label-map",
        logical_name="labels.txt",
        storage_uri="labels.txt",
    )
