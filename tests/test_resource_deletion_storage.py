"""资源删除的文件系统错误与路径边界测试。"""

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_delete_tree_reports_occupied_directory(tmp_path: Path) -> None:
    """目录占用不能被吞掉并错误报告删除成功。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    storage.write_bytes("owned/result.bin", b"retained")
    with patch("shutil.rmtree", side_effect=PermissionError("occupied")):
        with pytest.raises(PermissionError):
            storage.delete_tree("owned")
    assert storage.resolve("owned/result.bin").read_bytes() == b"retained"
    storage.delete_tree("owned")
    storage.delete_tree("owned")
    assert not storage.resolve("owned").exists()


@pytest.mark.parametrize("key", [".", "..", "../outside", "owned/../../outside"])
def test_delete_tree_rejects_root_and_parent_paths(tmp_path: Path, key: str) -> None:
    """根目录和路径穿越在实际删除前被拒绝。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    with pytest.raises(InvalidRequestError):
        storage.delete_tree(key)
    assert tmp_path.exists()


def test_delete_tree_rejects_reparse_ancestor(tmp_path: Path) -> None:
    """目标本身不是链接时也检查祖先目录的 junction。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    storage.write_bytes("owned/result.bin", b"retained")
    original = Path.is_junction
    with patch.object(
        Path, "is_junction", lambda path: path.name == "owned" or original(path)
    ):
        with pytest.raises(InvalidRequestError):
            storage.delete_tree("owned/result.bin")
    assert storage.resolve("owned/result.bin").exists()
