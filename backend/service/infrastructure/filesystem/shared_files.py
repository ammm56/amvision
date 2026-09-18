"""本地共享读取和单步原子替换，不增加读锁、等待或重试。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    # 单次绑定 Win32 签名；use_last_error 保证线程内错误码准确。
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _create_file = _kernel32.CreateFileW
    _create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _create_file.restype = wintypes.HANDLE
    _close_handle = _kernel32.CloseHandle
    _close_handle.argtypes = (wintypes.HANDLE,)
    _close_handle.restype = wintypes.BOOL
    _set_file_information = _kernel32.SetFileInformationByHandle
    _set_file_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _set_file_information.restype = wintypes.BOOL

    class _FileRenameInfo(ctypes.Structure):
        """64-bit Windows 的 FILE_RENAME_INFO 布局，FileName 后接完整路径。"""

        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]


def open_shared_read(path: Path) -> BinaryIO:
    """只读打开 path；允许替换目录项，已有读者仍持有原文件。

    适用于以完整新文件替换的控制文件，不保证原地写入文件的快照一致性。
    调用方负责关闭返回的 stream；权限错误与文件不存在分别保留原错误类型。
    """
    filesystem_path = to_filesystem_path(path)
    if os.name != "nt":
        return filesystem_path.open("rb")
    if "\0" in str(filesystem_path):
        raise ValueError("文件路径不能包含 NUL 字符")
    handle = _create_file(
        str(filesystem_path),
        0x80000000,  # GENERIC_READ
        0x00000001 | 0x00000002 | 0x00000004,  # SHARE_READ | WRITE | DELETE
        None,
        3,
        0x00000080,
        None,  # OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.WinError(ctypes.get_last_error())
        error.filename = str(path)
        raise error
    try:
        descriptor = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _close_handle(handle)
        raise
    try:
        return os.fdopen(descriptor, "rb", closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def replace_shared_file(source: Path, target: Path) -> None:
    """同卷原子发布 source 到 target，允许共享删除的旧读者继续读旧版本。

    Windows 使用 FileRenameInfoEx 的替换和 POSIX 语义，不先删除目标，
    不忽略只读属性或权限。系统不支持或外部不共享句柄占用时保留错误。
    """
    if os.name != "nt":
        os.replace(source, target)
        return
    source_path = to_filesystem_path(source)
    target_path = to_filesystem_path(target)
    if "\0" in str(source_path) or "\0" in str(target_path):
        raise ValueError("文件路径不能包含 NUL 字符")
    target_bytes = str(target_path).encode("utf-16-le")
    handle = _create_file(
        str(source_path),
        0x00010000,
        7,
        None,
        3,
        0x00000080,
        None,  # DELETE
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.WinError(ctypes.get_last_error())
        error.filename = str(source)
        error.filename2 = str(target)
        raise error
    try:
        # Win32 转换层需要 NUL 结尾；Length 是不含 NUL 的 UTF-16 字节数。
        buffer = ctypes.create_string_buffer(
            ctypes.sizeof(_FileRenameInfo) + len(target_bytes) + 2
        )
        info = _FileRenameInfo.from_buffer(buffer)
        info.Flags = 0x1 | 0x2  # REPLACE_IF_EXISTS | POSIX_SEMANTICS
        info.FileNameLength = len(target_bytes)
        ctypes.memmove(
            ctypes.addressof(buffer) + _FileRenameInfo.FileName.offset,
            target_bytes,
            len(target_bytes),
        )
        if not _set_file_information(
            handle, 22, buffer, len(buffer)
        ):  # FileRenameInfoEx
            error = ctypes.WinError(ctypes.get_last_error())
            error.filename = str(source)
            error.filename2 = str(target)
            raise error
    finally:
        _close_handle(handle)
