"""独立检查并启用 Windows 长路径支持。"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys


_REGISTRY_PATH = r"SYSTEM\CurrentControlSet\Control\FileSystem"
_REGISTRY_VALUE = "LongPathsEnabled"
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_INFINITE = 0xFFFFFFFF


def is_windows_long_paths_enabled() -> bool:
    """读取 64 位系统注册表中的长路径策略。"""

    if os.name != "nt":
        return True
    import winreg

    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            _REGISTRY_PATH,
            0,
            access,
        ) as registry_key:
            value, value_type = winreg.QueryValueEx(registry_key, _REGISTRY_VALUE)
    except FileNotFoundError:
        return False
    return value_type == winreg.REG_DWORD and int(value) == 1


def enable_windows_long_paths() -> None:
    """在管理员进程中启用系统长路径策略并立即复核。"""

    if os.name != "nt":
        return
    import winreg

    access = winreg.KEY_SET_VALUE | winreg.KEY_READ | getattr(
        winreg,
        "KEY_WOW64_64KEY",
        0,
    )
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        _REGISTRY_PATH,
        0,
        access,
    ) as registry_key:
        winreg.SetValueEx(
            registry_key,
            _REGISTRY_VALUE,
            0,
            winreg.REG_DWORD,
            1,
        )
    if not is_windows_long_paths_enabled():
        raise RuntimeError("Windows 长路径策略写入后复核失败")


def _is_windows_administrator() -> bool:
    """判断当前 Windows 进程是否具有管理员权限。"""

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def _run_elevated_and_wait() -> int:
    """通过 UAC 启动同一 Python 文件并等待管理员进程结束。"""

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    parameters = subprocess.list2cmdline(
        [str(Path(__file__).resolve()), "--elevated"]
    )
    execute_info = ShellExecuteInfo()
    execute_info.cbSize = ctypes.sizeof(execute_info)
    execute_info.fMask = _SEE_MASK_NOCLOSEPROCESS
    execute_info.lpVerb = "runas"
    execute_info.lpFile = sys.executable
    execute_info.lpParameters = parameters
    execute_info.lpDirectory = str(Path(__file__).resolve().parent)
    execute_info.nShow = 1
    if not shell32.ShellExecuteExW(ctypes.byref(execute_info)):
        raise OSError(ctypes.get_last_error(), "无法启动管理员进程")
    try:
        kernel32.WaitForSingleObject(execute_info.hProcess, _INFINITE)
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(
            execute_info.hProcess,
            ctypes.byref(exit_code),
        ):
            raise OSError(ctypes.get_last_error(), "无法读取管理员进程退出码")
        return int(exit_code.value)
    finally:
        kernel32.CloseHandle(execute_info.hProcess)


def _print_result(*, status: str, changed: bool, message: str) -> None:
    """输出可供用户和 launcher 读取的稳定 JSON 结果。"""

    print(
        json.dumps(
            {
                "platform": sys.platform,
                "status": status,
                "enabled": is_windows_long_paths_enabled(),
                "changed": changed,
                "message": message,
            },
            ensure_ascii=False,
        )
    )


def main(argv: list[str] | None = None) -> int:
    """执行检查、直接启用或 UAC 提权启用。"""

    parser = argparse.ArgumentParser(description="启用 Windows 系统长路径支持")
    parser.add_argument("--check", action="store_true", help="只检查，不修改系统")
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if os.name != "nt":
        _print_result(status="not-required", changed=False, message="当前系统不需要设置")
        return 0
    if is_windows_long_paths_enabled():
        _print_result(status="enabled", changed=False, message="Windows 长路径已启用")
        return 0
    if args.check:
        _print_result(status="disabled", changed=False, message="Windows 长路径未启用")
        return 1
    try:
        if _is_windows_administrator():
            enable_windows_long_paths()
            _print_result(status="enabled", changed=True, message="Windows 长路径已启用")
            return 0
        if args.elevated:
            raise PermissionError("管理员进程仍不具备注册表写权限")
        exit_code = _run_elevated_and_wait()
        if exit_code != 0 or not is_windows_long_paths_enabled():
            _print_result(status="failed", changed=False, message="管理员进程未完成设置")
            return exit_code or 1
        _print_result(status="enabled", changed=True, message="Windows 长路径已启用")
        return 0
    except (OSError, PermissionError, RuntimeError) as error:
        _print_result(status="failed", changed=False, message=str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
