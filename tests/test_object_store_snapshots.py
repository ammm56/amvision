"""本地 ObjectStore 不可变对象与稳定读取快照测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_immutable_object_is_content_addressed_idempotent_and_not_overwritable(
    tmp_path: Path,
) -> None:
    """同一内容复用稳定 identity，普通写接口不能覆盖不可变对象。"""

    storage = _storage(tmp_path)
    first = storage.write_immutable_object(
        object_prefix="workflow-results/run-1",
        content=b"same-content",
        media_type="image/png",
        extension=".png",
    )
    second = storage.write_immutable_object(
        object_prefix="workflow-results/run-1",
        content=b"same-content",
        media_type="image/png",
        extension=".png",
    )
    assert first == second
    metadata = storage.stat_object(first.metadata.object_key)
    assert metadata.is_immutable is True
    assert metadata.checksum_algorithm == "sha256"
    assert metadata.immutable_version == f"sha256:{metadata.checksum}"
    assert storage.resolve(metadata.object_key).read_bytes() == b"same-content"
    with pytest.raises(InvalidRequestError, match="禁止覆盖"):
        storage.write_bytes(metadata.object_key, b"different")


def test_open_read_snapshot_holds_original_mutable_file_version(tmp_path: Path) -> None:
    """打开的 snapshot 在同 key 原子替换后仍读取原版本。"""

    storage = _storage(tmp_path)
    storage.write_bytes("mutable/image.bin", b"before")
    with storage.open_read_snapshot("mutable/image.bin") as snapshot:
        storage.write_bytes("mutable/image.bin", b"after")
        assert snapshot.stream.read() == b"before"
        assert snapshot.metadata.content_length == len(b"before")
    assert storage.resolve("mutable/image.bin").read_bytes() == b"after"


def test_materialize_mutable_object_freezes_content_and_validates_identity(
    tmp_path: Path,
) -> None:
    """旧对象物化后不再受源 key 更新影响，并支持 expected identity 校验。"""

    storage = _storage(tmp_path)
    storage.write_bytes("mutable/source.jpg", b"version-one")
    receipt = storage.materialize_immutable_object(
        source_object_key="mutable/source.jpg",
        object_prefix="results/run-1",
        media_type="image/jpeg",
    )
    storage.write_bytes("mutable/source.jpg", b"version-two")
    metadata = receipt.metadata
    with storage.open_read_snapshot(
        metadata.object_key,
        expected_version=metadata.immutable_version,
        expected_checksum=metadata.checksum,
    ) as snapshot:
        assert snapshot.stream.read() == b"version-one"
    with pytest.raises(InvalidRequestError, match="version 不匹配"):
        with storage.open_read_snapshot(
            metadata.object_key,
            expected_version="sha256:wrong",
        ):
            pass


def test_invalid_or_missing_immutable_manifest_is_rejected(tmp_path: Path) -> None:
    """不可变目录中的缺失或损坏 manifest 不能降级为普通可变对象。"""

    storage = _storage(tmp_path)
    receipt = storage.write_immutable_object(
        object_prefix="results/run-1",
        content=b"content",
        media_type="application/octet-stream",
    )
    metadata_path = storage.resolve(receipt.metadata.object_key).parent / "metadata.json"
    metadata_path.unlink()
    with pytest.raises(InvalidRequestError, match="manifest 缺失"):
        storage.stat_object(receipt.metadata.object_key)


def _storage(tmp_path: Path) -> LocalDatasetStorage:
    """构造隔离的本地 ObjectStore。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
