"""mmap 路径归属校验的 Windows 表示形式与跨平台越界回归。"""

import os
from pathlib import Path

import pytest

from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path
from backend.service.infrastructure.ipc.mmap_primitives import build_contained_mmap_path


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path 表示形式")
@pytest.mark.parametrize("root_text", [r"W:\owned", r"\\server\share\owned"])
@pytest.mark.parametrize("root_extended,path_extended", [(False, True), (True, False), (False, False), (True, True)])
def test_windows_resolved_path_prefix_does_not_change_containment(monkeypatch, root_text, root_extended, path_extended):
    """模拟真实 resolve 返回不同前缀，不对文件存在性或内容作兼容降级。"""
    base = Path(root_text)
    target = base / "channel" / "data.mmap"
    resolved_root = to_filesystem_path(base) if root_extended else base
    resolved_target = to_filesystem_path(target) if path_extended else target

    def resolve(path, *_, **__):
        if to_filesystem_path(path) == to_filesystem_path(base):
            return resolved_root
        assert to_filesystem_path(path) == to_filesystem_path(target)
        return resolved_target

    monkeypatch.setattr(Path, "resolve", resolve)
    assert build_contained_mmap_path(root_dir=base, relative_path="channel/data.mmap") == resolved_target


def test_contained_path_rejects_absolute_and_parent_escape(tmp_path):
    """普通路径、绝对路径和上级目录穿越保持原校验语义。"""
    assert build_contained_mmap_path(root_dir=tmp_path, relative_path="inside/data.mmap") == tmp_path / "inside/data.mmap"
    with pytest.raises(ValueError, match="绝对"):
        build_contained_mmap_path(root_dir=tmp_path, relative_path=tmp_path / "data.mmap")
    with pytest.raises(ValueError, match="root"):
        build_contained_mmap_path(root_dir=tmp_path, relative_path="../outside.mmap")


def test_contained_path_rejects_resolved_link_escape(tmp_path):
    """实际符号链接解析后仍不能指向根目录之外。"""
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows 当前账户没有创建符号链接权限")
        raise
    with pytest.raises(ValueError, match="root"):
        build_contained_mmap_path(root_dir=root, relative_path="link/data.mmap")
