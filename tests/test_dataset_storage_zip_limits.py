"""数据集 ZIP 存储边界测试。"""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path


def test_write_stream_rejects_oversized_package_and_removes_partial_file(
    tmp_path: Path,
) -> None:
    """验证上传超限时不会残留半个压缩包。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path), max_import_package_bytes=4)
    )

    with pytest.raises(InvalidRequestError, match="超过大小限制"):
        storage.write_stream("imports/package.zip", BytesIO(b"12345"), max_bytes=4)

    assert not storage.resolve("imports/package.zip").exists()


def test_extract_zip_rejects_total_size_before_writing_files(tmp_path: Path) -> None:
    """验证解压总量超限时目标目录保持不存在。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(
            root_dir=str(tmp_path),
            max_import_extracted_bytes=4,
            max_import_compression_ratio=1000,
        )
    )
    archive_path = storage.resolve("imports/package.zip")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("images/sample.bin", b"12345")

    with pytest.raises(InvalidRequestError, match="解压后总大小超过限制"):
        storage.extract_zip("imports/package.zip", "imports/extracted")

    assert not storage.resolve("imports/extracted").exists()


def test_extract_zip_rejects_member_count_before_writing_files(tmp_path: Path) -> None:
    """验证 ZIP 成员数超限时不会开始解压。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path), max_import_member_count=1)
    )
    archive_path = storage.resolve("imports/package.zip")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("a.txt", b"a")
        archive.writestr("b.txt", b"b")

    with pytest.raises(InvalidRequestError, match="文件数量超过限制"):
        storage.extract_zip("imports/package.zip", "imports/extracted")

    assert not storage.resolve("imports/extracted").exists()


def test_storage_rejects_windows_parent_path_and_external_absolute_path(
    tmp_path: Path,
) -> None:
    """验证 Windows 分隔符和盘符不能绕过对象存储根目录。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "root")))

    with pytest.raises(InvalidRequestError, match="路径不合法"):
        storage.resolve("..\\escape.txt")
    with pytest.raises(InvalidRequestError, match="路径不合法"):
        storage.resolve(str(tmp_path / "outside.txt"))

    inside_path = storage.resolve("safe/inside.txt")
    assert storage.resolve(str(inside_path)) == inside_path


def test_extract_zip_rejects_windows_style_parent_member(tmp_path: Path) -> None:
    """验证 ZIP 中的反斜杠父目录路径不会写出目标目录。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "root")))
    archive_path = storage.resolve("imports/package.zip")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("..\\escape.txt", b"escape")

    with pytest.raises(InvalidRequestError, match="非法路径"):
        storage.extract_zip("imports/package.zip", "imports/extracted")


def test_local_dataset_storage_reads_and_writes_extended_length_paths(
    tmp_path: Path,
) -> None:
    """验证存储层可在超过传统 MAX_PATH 的路径上原子读写。"""

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "root")))
    nested_parts = tuple(f"segment-{index}-{'x' * 40}" for index in range(6))
    object_key = "/".join((*nested_parts, "payload.json"))
    target_path = storage.resolve(object_key)
    if os.name == "nt":
        assert len(str(target_path)) > 260

    storage.write_json(object_key, {"status": "ok"})

    assert storage.read_json(object_key) == {"status": "ok"}
    assert to_filesystem_path(target_path).is_file()

    assert not storage.resolve("imports/escape.txt").exists()
