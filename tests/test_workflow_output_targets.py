"""Workflow 节点输出目录解析测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.nodes.output_targets import (
    OUTPUT_TARGET_FILESYSTEM,
    OUTPUT_TARGET_OBJECT_STORE,
    resolve_optional_output_directory,
)
from backend.service.application.errors import InvalidRequestError


def test_relative_output_directory_uses_object_store() -> None:
    """验证混合分隔符相对目录会规范化为 ObjectStore key prefix。"""

    target = resolve_optional_output_directory(r"workflow\roi/./batch")

    assert target is not None
    assert target.kind == OUTPUT_TARGET_OBJECT_STORE
    assert target.object_key_prefix == "workflow/roi/batch"
    assert target.filesystem_path is None


def test_resolve_optional_output_directory_accepts_native_absolute_path(
    tmp_path: Path,
) -> None:
    """验证当前系统绝对目录会保留为本机文件系统目标。"""

    expected_path = (tmp_path / "roi").resolve()
    target = resolve_optional_output_directory(str(expected_path))

    assert target is not None
    assert target.kind == OUTPUT_TARGET_FILESYSTEM
    assert target.filesystem_path == expected_path
    assert target.object_key_prefix is None


@pytest.mark.skipif(os.name != "nt", reason="Windows drive path assertion")
def test_resolve_optional_output_directory_accepts_requested_windows_path() -> None:
    """验证 T:\\temp\\roi 会被识别为系统绝对目录而不是 object key。"""

    target = resolve_optional_output_directory(r"T:\temp\roi")

    assert target is not None
    assert target.kind == OUTPUT_TARGET_FILESYSTEM
    assert target.filesystem_path == Path(r"T:\temp\roi").resolve()


@pytest.mark.parametrize("value", ["../roi", "workflow/../roi", r"T:relative"])
def test_resolve_optional_output_directory_rejects_ambiguous_paths(value: str) -> None:
    """验证路径穿越和 Windows 盘符相对路径不会被误判为 ObjectStore key。"""

    with pytest.raises(InvalidRequestError):
        resolve_optional_output_directory(value)


@pytest.mark.parametrize("value", [None, "", "   ", "."])
def test_resolve_optional_output_directory_treats_empty_value_as_memory_only(
    value: object,
) -> None:
    """验证空输出目录保持纯内存处理。"""

    assert resolve_optional_output_directory(value) is None
