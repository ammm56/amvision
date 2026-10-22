"""不可变目录重复提交的 Windows/POSIX 语义与错误传播。"""

import errno
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_repeated_and_concurrent_same_content_publish(tmp_path):
    """相同内容只复用同一已提交身份，不留下暂存目录。"""
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))

    def write(_index):
        return storage.write_immutable_object(
            object_prefix="objects", content=b"same-content", media_type="text/plain"
        )

    first = write(0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, range(8)))
    assert all(result == first for result in results)
    assert not list(tmp_path.rglob(".stream-*.tmp"))
    with storage.open_read_snapshot(first.metadata.object_key) as snapshot:
        assert snapshot.stream.read() == b"same-content"


@pytest.mark.parametrize("code", [errno.EACCES, errno.EIO, errno.ENOSPC])
def test_other_rename_errors_are_not_treated_as_existing(tmp_path, monkeypatch, code):
    """不能因为目标已存在就掩盖权限、磁盘或 I/O 故障。"""
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    first = storage.write_immutable_object(
        object_prefix="objects", content=b"safe", media_type="text/plain"
    )

    def fail(_source, _target):
        raise OSError(code, "injected publication error")

    monkeypatch.setattr(
        "backend.service.infrastructure.object_store.local_dataset_storage.os.rename",
        fail,
    )
    with pytest.raises(OSError) as error:
        storage.write_immutable_object(
            object_prefix="objects", content=b"safe", media_type="text/plain"
        )
    assert error.value.errno == code
    assert storage.resolve(first.metadata.object_key).read_bytes() == b"safe"
    assert not list(tmp_path.rglob(".stream-*.tmp"))
