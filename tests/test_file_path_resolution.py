"""原子替换期间的文件位置及写锁身份必须保持稳定。"""

import os
from pathlib import Path
from threading import Event, Thread

import pytest

from backend.nodes.core_nodes.support.local_io.paths import (
    resolve_local_path_value_from_request,
)
from backend.nodes.save_locations import resolve_optional_save_location
from backend.service.application.runtime.io.path_write_coordinator import _normalize_path
from backend.service.application.runtime.io.write_journal import WriteJournal
from backend.service.infrastructure.filesystem.file_paths import resolve_file_location
from backend.service.infrastructure.filesystem.shared_files import replace_shared_file


def test_replaced_file_identity_is_not_used_as_destination(tmp_path, monkeypatch):
    """模拟已被移入删除区的旧文件，节点、锁、journal 都应保留目标名称。"""
    from types import SimpleNamespace

    target = tmp_path / "summary.json"
    target.write_text("{}")
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == target:
            return tmp_path / "$Deleted" / "old-file"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    request = SimpleNamespace(parameters={"state_path": str(target)}, input_values={})
    assert resolve_local_path_value_from_request(
        request, parameter_name="state_path", description="检查点"
    ) == target
    assert _normalize_path(target) == os.path.normcase(str(target))
    assert resolve_optional_save_location(str(target), scope="file").filesystem_path == target
    assert WriteJournal(
        target_path=target, operation_id="one", operation_kind="test"
    ).target_path == target


def test_explicit_file_link_keeps_target_identity(tmp_path):
    """显式链接仍解析到目标位置，循环链接明确失败。"""
    target, link = tmp_path / "target.json", tmp_path / "link.json"
    try:
        link.symlink_to(target.name)
    except OSError as error:
        pytest.skip(f"环境不允许创建符号链接：{error}")
    assert resolve_file_location(link) == target
    link.unlink()
    link.symlink_to(link.name)
    with pytest.raises(OSError, match="符号链接"):
        resolve_file_location(link)


@pytest.mark.skipif(os.name != "nt", reason="验证 Windows POSIX 原子替换竞态")
def test_concurrent_windows_replacement_keeps_configured_name(tmp_path):
    """真实替换 500 次，解析不得返回 NTFS 删除区，也不得改变锁键。"""
    target = tmp_path / "state.json"
    target.write_text("{}")
    done = Event()
    failures = []

    def writer():
        try:
            for index in range(500):
                source = tmp_path / "new.tmp"
                source.write_text(str(index))
                replace_shared_file(source, target)
        except Exception as error:
            failures.append(error)
        finally:
            done.set()

    thread = Thread(target=writer)
    thread.start()
    count = 0
    try:
        while not done.is_set():
            assert resolve_file_location(target) == target
            assert _normalize_path(target) == os.path.normcase(str(target))
            count += 1
    finally:
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert not failures
    assert count > 0
