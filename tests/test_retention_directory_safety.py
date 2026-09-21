"""文件清理的目录边界、保存竞争和取消回归。"""

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from backend.nodes.save_locations import _write_filesystem_bytes_atomically
from backend.service.infrastructure.filesystem.retention_files import (
    delete_empty_local_retention_directories,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows 目录生命周期保护回归")


def test_control_directory_descendants_are_preserved(tmp_path: Path) -> None:
    """内部控制目录的全部后代都必须保留。"""
    child = tmp_path / ".amvision-control" / "child"
    child.mkdir(parents=True)
    delete_empty_local_retention_directories(tmp_path, recursive=True)
    assert child.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction 回归")
def test_empty_cleanup_never_enters_junction(tmp_path: Path) -> None:
    """junction 指向范围外时不能删除目标外空目录。"""
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    (outside / "child").mkdir(parents=True)
    junction = root / "redirect"
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"New-Item -ItemType Junction -Path '{junction}' -Target '{outside}' | Out-Null",
        ],
        check=True,
        capture_output=True,
    )
    try:
        delete_empty_local_retention_directories(root, recursive=True)
        assert (outside / "child").is_dir()
    finally:
        junction.rmdir()


def test_save_survives_cleanup_before_temporary_open(tmp_path: Path) -> None:
    """实际 Save helper 建立临时文件前被清理打断仍可保存。"""
    target = tmp_path / "date" / "result.json"
    original_open = Path.open

    def interleave(path, *args, **kwargs):
        if path.suffix == ".tmp":
            delete_empty_local_retention_directories(tmp_path, recursive=True)
        return original_open(path, *args, **kwargs)

    with patch.object(Path, "open", interleave):
        _write_filesystem_bytes_atomically(target, b'{"ok":true}')
    assert target.read_bytes() == b'{"ok":true}'


def test_scan_can_cancel_without_matching_files(tmp_path: Path) -> None:
    """空子目录扫描也响应取消，并释放目录保护。"""
    from backend.service.infrastructure.filesystem.retention_files import (
        iter_local_retention_pages,
    )

    for i in range(20):
        (tmp_path / str(i)).mkdir()
    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 5:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        list(
            iter_local_retention_pages(
                tmp_path, recursive=True, page_size=512, checkpoint=checkpoint
            )
        )
    assert delete_empty_local_retention_directories(tmp_path, recursive=True) == 20


def test_lock_io_error_is_not_reported_as_contention(tmp_path: Path) -> None:
    """无效句柄/权限错误必须可诊断，不能返回 target_locked。"""
    import errno
    from backend.service.application.runtime.io import path_write_coordinator as locks

    coordinator = locks.PathWriteCoordinator()
    with patch.object(
        locks, "_try_lock_file", side_effect=OSError(errno.EBADF, "bad handle")
    ):
        with pytest.raises(OSError):
            with coordinator.try_acquire((tmp_path / "file",)):
                pytest.fail("must not acquire")
    assert not coordinator._entries


def test_missing_image_fallback_is_explicit_jpeg_and_recoverable(
    tmp_path: Path,
) -> None:
    """只对丢失的 Path 回退，恢复图片后正常读取；不能吞掉坏图片。"""
    from tests.test_workflow_local_file_reading import call, IMAGE
    from backend.service.application.errors import InvalidRequestError
    from PIL import Image

    path = tmp_path / "missing.jpg"
    params = {"local_path": str(path), "missing_file_policy": "blank"}
    with pytest.raises(InvalidRequestError):
        call(IMAGE, {"local_path": str(path)})
    result = call(IMAGE, params)
    summary = result["summary"]["value"]
    assert summary["blank_reason"] == "missing-file"
    assert summary["media_type"] == "image/jpeg"
    assert summary["local_path"] == str(path)
    path.write_bytes(b"broken image")
    with pytest.raises(InvalidRequestError):
        call(IMAGE, params)
    Image.new("RGB", (12, 8)).save(path)
    assert call(IMAGE, params)["summary"]["value"]["generated_blank"] is False


def test_calendar_overflow_is_rejected_before_deletion(tmp_path: Path) -> None:
    """无效期限在扫描和删除前明确拒绝。"""
    from tests.test_workflow_storage_retention_cleanup import _create_storage, _execute
    from backend.service.application.errors import InvalidRequestError

    target = tmp_path / "results"
    target.mkdir()
    file = target / "keep.json"
    file.write_text("{}")
    with pytest.raises(InvalidRequestError):
        _execute(
            _create_storage(tmp_path),
            target_directory=str(target),
            retention_policy="age",
            retention_value=100000,
            retention_unit="year",
            dry_run=False,
        )
    assert file.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows 目录句柄跨进程语义")
def test_directory_guard_released_after_process_exit(tmp_path: Path) -> None:
    """另一个进程保存时跳过空目录，退出后不遗留占用。"""
    child = tmp_path / "writing"
    child.mkdir()
    script = (
        "import sys\nfrom pathlib import Path\n"
        "from backend.service.infrastructure.filesystem.directory_guard import protect_directory\n"
        "with protect_directory(Path(sys.argv[1])):\n"
        " print('ready', flush=True)\n sys.stdin.readline()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(child)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        assert delete_empty_local_retention_directories(tmp_path, recursive=True) == 0
        process.communicate("exit\n", timeout=15)
        assert process.returncode == 0
        assert delete_empty_local_retention_directories(tmp_path, recursive=True) == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=15)


@pytest.mark.parametrize(
    "kind",
    [
        "bytes",
        "new_bytes",
        "copy",
        "new_copy",
        "object_bytes",
        "object_json",
        "object_text",
        "object_stream",
        "object_copy",
    ],
)
def test_save_variants_keep_directory_during_cleanup(tmp_path: Path, kind: str) -> None:
    """文件和 ObjectStore 各写入路径共用保护，不遗漏复制与流式保存。"""
    import io
    from backend.nodes import save_locations as saves
    from tests.test_workflow_storage_retention_cleanup import _create_storage

    storage = _create_storage(tmp_path)
    source = tmp_path / "source.bin"
    source.write_bytes(b"content")
    target = tmp_path / "output" / "file.bin"
    original_open = Path.open

    def interleave(path, mode="r", *args, **kwargs):
        if "w" in mode:
            delete_empty_local_retention_directories(tmp_path, recursive=True)
        return original_open(path, mode, *args, **kwargs)

    with patch.object(Path, "open", interleave):
        if kind == "bytes":
            saves._write_filesystem_bytes_atomically(target, b"content")
        elif kind == "new_bytes":
            assert saves._write_filesystem_bytes_atomically_if_absent(
                target, b"content"
            )
        elif kind == "copy":
            saves._copy_filesystem_file_atomically(source, target)
        elif kind == "new_copy":
            assert saves._copy_filesystem_file_atomically_if_absent(
                source_path=source, target_path=target
            )
        else:
            key = "output/file.bin"
            if kind == "object_bytes":
                storage.write_bytes(key, b"content")
            elif kind == "object_json":
                storage.write_json(key, {"valid": True})
            elif kind == "object_text":
                storage.write_text(key, "content")
            elif kind == "object_stream":
                storage.write_stream(key, io.BytesIO(b"content"))
            else:
                storage.copy_file(source, key)
            target = storage.resolve(key)
    assert target.read_bytes()


def test_cancel_after_first_delete_reports_progress_and_releases_locks(
    tmp_path: Path,
) -> None:
    """中途取消报告已完成删除，后续调用能继续，不能误报整批成功。"""
    from threading import Event
    from backend.nodes.core_nodes.io.output.storage import (
        storage_retention_cleanup as node,
    )
    from backend.service.application.errors import OperationCancelledError
    from tests.test_workflow_storage_retention_cleanup import _create_storage, _request

    target = tmp_path / "results"
    target.mkdir()
    for index in range(3):
        (target / f"{index}.json").write_text("{}")
    event = Event()
    request = _request(
        _create_storage(tmp_path),
        {
            "target_directory": str(target),
            "retention_policy": "count",
            "max_file_count": 1,
            "dry_run": False,
        },
    )
    from dataclasses import replace

    request = replace(request, node_cancellation_event=event)
    real_delete = node.delete_local_retention_file_if_version

    def interrupted(*args, **kwargs):
        result = real_delete(*args, **kwargs)
        event.set()
        return result

    with patch.object(node, "delete_local_retention_file_if_version", interrupted):
        with pytest.raises(OperationCancelledError) as error:
            node._storage_retention_cleanup_handler(request)
    assert error.value.details["deleted_file_count"] == 1
    event.clear()
    result = node._storage_retention_cleanup_handler(request)["result"]["value"]
    assert result["deleted_file_count"] == 1
    assert len(list(target.glob("*.json"))) == 1


def test_cleanup_failure_keeps_original_error(tmp_path: Path) -> None:
    """写入失败同时临时文件清理失败时，原始原因仍然可见。"""
    from backend.service.infrastructure.filesystem.atomic_files import (
        discard_temporary_file,
    )

    with patch.object(Path, "unlink", side_effect=PermissionError("cleanup")):
        with pytest.raises(OSError, match="original") as error:
            try:
                raise OSError("original")
            except OSError:
                discard_temporary_file(tmp_path / "x.tmp")
                raise
    assert "cleanup" in error.value.__notes__[0]


@pytest.mark.skipif(os.name != "nt", reason="Windows 建立目录保护时的共享冲突")
def test_prepare_directory_retries_transient_conflict_only(tmp_path: Path) -> None:
    """准备窗口冲突立即重试且有次数上限，权限错误不当作正常占用。"""
    from backend.service.infrastructure.filesystem import directory_guard as guard
    from contextlib import contextmanager

    target = tmp_path / "date"
    target.mkdir()
    original = guard.protect_child_directory
    calls = 0

    @contextmanager
    def collision(path):
        nonlocal calls
        if path == target:
            calls += 1
            if calls < 3:
                error = PermissionError("sharing")
                error.winerror = 32
                raise error
        with original(path):
            yield

    with patch.object(guard, "protect_child_directory", collision):
        _write_filesystem_bytes_atomically(target / "result.json", b"{}")
    assert calls == 3
    error = PermissionError("access denied")
    error.winerror = 5
    with patch.object(guard, "protect_child_directory", side_effect=error) as mocked:
        with pytest.raises(PermissionError):
            _write_filesystem_bytes_atomically(target / "next.json", b"{}")
    assert mocked.call_count == 1
    error = PermissionError("sharing remains")
    error.winerror = 32
    with (
        patch.object(guard, "protect_child_directory", side_effect=error),
        patch.object(guard, "monotonic", side_effect=[1.0, 1.05, 1.101]),
        patch.object(guard, "sleep") as wait,
    ):
        with pytest.raises(PermissionError) as exhausted:
            _write_filesystem_bytes_atomically(target / "blocked.json", b"{}")
    assert wait.call_count == 2
    assert exhausted.value.file_io_stage == "protect_directory"


@pytest.mark.skipif(os.name != "nt", reason="Windows 保存/清理并行边界")
def test_parallel_saves_and_cleanup_preserve_every_file(tmp_path: Path) -> None:
    """同目录并行保存期间反复清理，所有发布内容完整且不残留临时文件。"""
    from concurrent.futures import ThreadPoolExecutor

    def write(index):
        for item in range(20):
            _write_filesystem_bytes_atomically(
                tmp_path / "date" / f"{index}-{item}.bin", bytes([index]) * 8192
            )

    def cleanup():
        for _ in range(40):
            delete_empty_local_retention_directories(tmp_path, recursive=True)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(write, i) for i in range(4)] + [pool.submit(cleanup)]
        for future in futures:
            future.result(timeout=15)
    for index in range(4):
        for item in range(20):
            assert (tmp_path / "date" / f"{index}-{item}.bin").read_bytes() == bytes(
                [index]
            ) * 8192
    assert not list(tmp_path.rglob("*.tmp"))
