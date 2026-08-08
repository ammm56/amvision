"""运行时 launcher 共用辅助。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


WINDOWS_SYSTEM_CONFIGURATION_REQUIRED_EXIT_CODE = 78


def resolve_app_root(
    *,
    script_file: Path,
    explicit_app_root: str | None = None,
) -> Path:
    """解析当前 launcher 对应的应用根目录。"""

    if explicit_app_root is not None and explicit_app_root.strip():
        return Path(explicit_app_root).resolve()

    resolved_script_file = script_file.resolve()
    for candidate in (resolved_script_file.parent, *resolved_script_file.parents):
        if (candidate / "backend").is_dir() and (candidate / "config").is_dir():
            return candidate
        if (candidate / "app" / "backend").is_dir() and (candidate / "config").is_dir():
            return candidate
    raise FileNotFoundError("无法从当前 launcher 位置解析应用根目录")


def resolve_code_root(app_root: Path) -> Path:
    """解析当前应用可导入 backend 包的代码根目录。"""

    if (app_root / "backend").is_dir():
        return app_root
    bundled_code_root = app_root / "app"
    if (bundled_code_root / "backend").is_dir():
        return bundled_code_root
    raise FileNotFoundError(f"未找到 backend 代码目录: {app_root}")


def resolve_path(app_root: Path, path_value: str) -> Path:
    """把相对或绝对路径解析成绝对路径。"""

    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (app_root / candidate).resolve()


def ensure_windows_long_paths_enabled(
    *,
    app_root: Path,
    python_executable: str | None = None,
) -> bool:
    """在 Windows 发行包首次启动时检查并提权启用长路径。"""

    if os.name != "nt" or not (app_root / "manifests" / "release-profiles").is_dir():
        return True
    import winreg

    registry_path = r"SYSTEM\CurrentControlSet\Control\FileSystem"
    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            registry_path,
            0,
            access,
        ) as registry_key:
            value, value_type = winreg.QueryValueEx(registry_key, "LongPathsEnabled")
        if value_type == winreg.REG_DWORD and int(value) == 1:
            return True
    except FileNotFoundError:
        pass

    script_candidates = (
        app_root / "launchers" / "enable_windows_long_paths.py",
        app_root / "runtimes" / "launchers" / "enable_windows_long_paths.py",
    )
    script_path = next((path for path in script_candidates if path.is_file()), None)
    if script_path is None:
        raise FileNotFoundError("发行包缺少 enable_windows_long_paths.py")
    resolved_python = python_executable or str(app_root / "python" / "python.exe")
    completed = subprocess.run(
        [resolved_python, str(script_path)],
        cwd=str(app_root),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("Windows 长路径启用失败或 UAC 授权被取消")
    print("Windows 长路径已启用；请重新启动 amvision 使系统策略对所有进程生效。")
    return False


def load_json_file(app_root: Path, path_value: str) -> dict[str, object]:
    """读取相对应用根目录的 JSON 文件。"""

    file_path = resolve_path(app_root, path_value)
    return json.loads(file_path.read_text(encoding="utf-8"))


def json_env_value(value: object) -> str:
    """把复杂环境变量值序列化为 JSON 字符串。"""

    return json.dumps(value, ensure_ascii=False)


def is_pid_alive(pid: int) -> bool:
    """判断指定 pid 当前是否仍然存活。"""

    if pid <= 0:
        return False
    if os.name == "nt":
        return _is_windows_pid_alive(pid)
    return _is_pid_alive_with_signal_check(pid)


def _is_pid_alive_with_signal_check(pid: int) -> bool:
    """用 `os.kill(pid, 0)` 风格的方式判断进程是否存活。"""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _is_windows_pid_alive(pid: int) -> bool:
    """在 Windows 下直接查询进程句柄，避免依赖受权限和本地化影响的 tasklist。"""

    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    error_invalid_parameter = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    process_handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        pid,
    )
    if not process_handle:
        error_code = ctypes.get_last_error()
        if error_code == error_access_denied:
            return True
        if error_code == error_invalid_parameter:
            return False
        return _is_pid_alive_with_signal_check(pid)

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process_handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(process_handle)


def run_python_module(
    *,
    app_root: Path,
    module_name: str,
    module_args: Sequence[str],
    python_executable: str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> int:
    """用指定 Python 解释器在目标应用根目录启动模块。"""

    runtime_env = build_python_module_environment(app_root, extra_env=extra_env)

    resolved_python_executable = python_executable
    if resolved_python_executable is None:
        bundled_python_executable = app_root / "python" / "python.exe"
        is_release_layout = (app_root / "manifests" / "release-profiles").is_dir()
        if is_release_layout:
            if not bundled_python_executable.is_file():
                raise FileNotFoundError(
                    "发行目录缺少 python/python.exe，禁止回退到系统 Python"
                )
            resolved_python_executable = str(bundled_python_executable)
        else:
            resolved_python_executable = sys.executable

    command = [resolved_python_executable, "-m", module_name, *module_args]
    completed = subprocess.run(
        command,
        cwd=str(app_root),
        env=runtime_env,
        check=False,
    )
    return completed.returncode


def build_python_module_environment(
    app_root: Path,
    *,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """构造 launcher 启动 backend 模块所需的完整环境。"""

    runtime_env = os.environ.copy()
    code_root = resolve_code_root(app_root)
    _prepare_local_runtime_paths(app_root, runtime_env)
    existing_python_path = runtime_env.get("PYTHONPATH")
    runtime_env["PYTHONPATH"] = (
        str(code_root)
        if not existing_python_path
        else os.pathsep.join((str(code_root), existing_python_path))
    )
    if extra_env is not None:
        runtime_env.update(extra_env)
    return runtime_env


def _prepare_local_runtime_paths(app_root: Path, runtime_env: dict[str, str]) -> None:
    """把发布目录或开发目录中的本地运行时加入子进程环境。"""

    cudnn_bin_dir = _resolve_cudnn_bin_dir(app_root)
    if cudnn_bin_dir is not None:
        _prepend_env_path(runtime_env, "PATH", str(cudnn_bin_dir))
        runtime_env.setdefault("AMVISION_CUDNN_BIN_DIR", str(cudnn_bin_dir))
        runtime_env.setdefault("AMVISION_CUDNN_ROOT_DIR", str(_resolve_cudnn_root_dir(cudnn_bin_dir)))

    tensorrt_bin_dir = _resolve_tensorrt_bin_dir(app_root)
    if tensorrt_bin_dir is not None:
        _prepend_env_path(runtime_env, "PATH", str(tensorrt_bin_dir))
        runtime_env.setdefault("AMVISION_TENSORRT_BIN_DIR", str(tensorrt_bin_dir))
        runtime_env.setdefault("AMVISION_TENSORRT_ROOT_DIR", str(tensorrt_bin_dir.parent))


def _resolve_tensorrt_bin_dir(app_root: Path) -> Path | None:
    """解析当前应用根目录下的 TensorRT bin 目录。"""

    candidates = [
        app_root / "tools" / "tensorrt" / "bin",
        app_root / "runtimes" / "tensorrt_bin" / "bin",
        app_root / "runtimes" / "third_party" / "tensorrt" / "bin",
    ]
    code_root = resolve_code_root(app_root)
    candidates.extend(
        [
            code_root / "runtimes" / "tensorrt_bin" / "bin",
            code_root / "runtimes" / "third_party" / "tensorrt" / "bin",
        ]
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _resolve_cudnn_bin_dir(app_root: Path) -> Path | None:
    """解析当前应用根目录下的 cuDNN DLL 目录。"""

    version = os.getenv("AMVISION_CUDNN_CUDA_VERSION", "12.9")
    candidates: list[Path] = []
    env_bin_dir = os.getenv("AMVISION_CUDNN_BIN_DIR")
    if env_bin_dir:
        candidates.append(Path(env_bin_dir))

    env_root_dir = os.getenv("AMVISION_CUDNN_ROOT_DIR")
    if env_root_dir:
        candidates.extend(_build_cudnn_root_candidates(Path(env_root_dir), version=version))

    code_root = resolve_code_root(app_root)
    for root_dir in (
        app_root / "tools" / "cudnn",
        app_root / "runtimes" / "cudnn_dll",
        code_root / "runtimes" / "cudnn_dll",
    ):
        candidates.extend(_build_cudnn_root_candidates(root_dir, version=version))

    for candidate in _dedupe_path_candidates(candidates):
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _build_cudnn_root_candidates(root_dir: Path, *, version: str) -> list[Path]:
    """按 CUDA 版本偏好生成 cuDNN DLL 目录候选。"""

    bin_dir = root_dir / "bin"
    candidates = [
        bin_dir / version / "x64",
        bin_dir / "12.9" / "x64",
        bin_dir,
    ]
    if bin_dir.is_dir():
        version_dirs = sorted(child for child in bin_dir.iterdir() if child.is_dir())
        candidates.extend(version_dir / "x64" for version_dir in version_dirs)
    return candidates


def _resolve_cudnn_root_dir(cudnn_bin_dir: Path) -> Path:
    """从 cuDNN DLL 目录反推出 cuDNN 根目录。"""

    if cudnn_bin_dir.name.lower() == "x64" and cudnn_bin_dir.parent.parent.name.lower() == "bin":
        return cudnn_bin_dir.parent.parent.parent
    if cudnn_bin_dir.name.lower() == "bin":
        return cudnn_bin_dir.parent
    return cudnn_bin_dir


def _dedupe_path_candidates(paths: list[Path]) -> list[Path]:
    """按字符串形式去重并保持原始顺序。"""

    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        path_key = str(path)
        if path_key in seen:
            continue
        seen.add(path_key)
        result.append(path)
    return result


def _prepend_env_path(runtime_env: dict[str, str], key: str, path_value: str) -> None:
    """把目录加入环境变量前面。"""

    current_value = runtime_env.get(key, "")
    path_parts = [part for part in current_value.split(os.pathsep) if part]
    if path_value in path_parts:
        return
    runtime_env[key] = path_value if not current_value else os.pathsep.join((path_value, current_value))
