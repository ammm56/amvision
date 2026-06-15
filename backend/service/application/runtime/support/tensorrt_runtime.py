"""TensorRT 本地运行时目录解析工具。"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Mapping, MutableMapping

from backend.service.application.errors import ServiceConfigurationError


TENSORRT_BIN_DIR_ENV_VAR = "AMVISION_TENSORRT_BIN_DIR"
TENSORRT_ROOT_DIR_ENV_VAR = "AMVISION_TENSORRT_ROOT_DIR"
CUDNN_BIN_DIR_ENV_VAR = "AMVISION_CUDNN_BIN_DIR"
CUDNN_ROOT_DIR_ENV_VAR = "AMVISION_CUDNN_ROOT_DIR"
CUDNN_CUDA_VERSION_ENV_VAR = "AMVISION_CUDNN_CUDA_VERSION"
DEFAULT_CUDNN_CUDA_VERSION = "12.9"

_DLL_DIRECTORY_HANDLES: list[object] = []
_DLL_DIRECTORY_PATHS: set[str] = set()


def resolve_tensorrt_bin_dir(
    *,
    app_root: Path | None = None,
    required: bool = False,
) -> Path | None:
    """解析当前进程应使用的 TensorRT bin 目录。

    参数：
    - app_root：可选应用根目录；开发态通常是仓库根目录，发布态通常是 `release/full`。
    - required：为 True 时，找不到目录会抛出明确配置错误。

    返回：
    - Path | None：可用的 TensorRT bin 目录；找不到且未要求强制存在时返回 None。
    """

    for candidate in _iter_tensorrt_bin_dir_candidates(app_root=app_root):
        if candidate.is_dir():
            return candidate.resolve()
    if required:
        raise ServiceConfigurationError(
            "未找到 TensorRT bin 目录",
            details={
                "env_bin": os.getenv(TENSORRT_BIN_DIR_ENV_VAR, ""),
                "env_root": os.getenv(TENSORRT_ROOT_DIR_ENV_VAR, ""),
                "expected_release_dir": "tools/tensorrt/bin",
                "expected_development_dir": "runtimes/tensorrt_bin/bin",
            },
        )
    return None


def resolve_trtexec_path(*, app_root: Path | None = None) -> Path:
    """解析当前应调用的 `trtexec` 可执行文件。"""

    executable_name = "trtexec.exe" if os.name == "nt" else "trtexec"
    tensorrt_bin_dir = resolve_tensorrt_bin_dir(app_root=app_root)
    if tensorrt_bin_dir is not None:
        trtexec_path = tensorrt_bin_dir / executable_name
        if trtexec_path.is_file():
            return trtexec_path.resolve()

    path_value = shutil.which(executable_name)
    if path_value:
        return Path(path_value).resolve()

    raise ServiceConfigurationError(
        "未找到 trtexec",
        details={
            "executable_name": executable_name,
            "expected_release_file": f"tools/tensorrt/bin/{executable_name}",
            "expected_development_file": f"runtimes/tensorrt_bin/bin/{executable_name}",
            "env_bin": os.getenv(TENSORRT_BIN_DIR_ENV_VAR, ""),
        },
    )


def build_tensorrt_process_environment(
    *,
    base_env: Mapping[str, str] | None = None,
    app_root: Path | None = None,
) -> dict[str, str]:
    """构造带 TensorRT DLL 搜索路径的子进程环境变量。"""

    runtime_env = dict(os.environ if base_env is None else base_env)
    cudnn_bin_dir = resolve_cudnn_bin_dir(app_root=app_root)
    if cudnn_bin_dir is not None:
        _prepend_path_value(runtime_env, "PATH", str(cudnn_bin_dir))
        runtime_env.setdefault(CUDNN_BIN_DIR_ENV_VAR, str(cudnn_bin_dir))
        runtime_env.setdefault(CUDNN_ROOT_DIR_ENV_VAR, str(_resolve_cudnn_root_dir(cudnn_bin_dir)))

    tensorrt_bin_dir = resolve_tensorrt_bin_dir(app_root=app_root)
    if tensorrt_bin_dir is None:
        return runtime_env
    _prepend_path_value(runtime_env, "PATH", str(tensorrt_bin_dir))
    runtime_env.setdefault(TENSORRT_BIN_DIR_ENV_VAR, str(tensorrt_bin_dir))
    runtime_env.setdefault(TENSORRT_ROOT_DIR_ENV_VAR, str(tensorrt_bin_dir.parent))
    return runtime_env


def prepare_tensorrt_python_runtime(*, app_root: Path | None = None) -> Path | None:
    """为当前 Python 进程准备 TensorRT DLL 搜索路径。

    参数：
    - app_root：可选应用根目录。

    返回：
    - Path | None：实际加入搜索路径的 TensorRT bin 目录。
    """

    cudnn_bin_dir = resolve_cudnn_bin_dir(app_root=app_root)
    if cudnn_bin_dir is not None:
        _prepend_process_path(str(cudnn_bin_dir))
        os.environ.setdefault(CUDNN_BIN_DIR_ENV_VAR, str(cudnn_bin_dir))
        os.environ.setdefault(CUDNN_ROOT_DIR_ENV_VAR, str(_resolve_cudnn_root_dir(cudnn_bin_dir)))
        _add_windows_dll_directory(cudnn_bin_dir)

    tensorrt_bin_dir = resolve_tensorrt_bin_dir(app_root=app_root)
    if tensorrt_bin_dir is None:
        return None

    _prepend_process_path(str(tensorrt_bin_dir))
    os.environ.setdefault(TENSORRT_BIN_DIR_ENV_VAR, str(tensorrt_bin_dir))
    os.environ.setdefault(TENSORRT_ROOT_DIR_ENV_VAR, str(tensorrt_bin_dir.parent))
    _add_windows_dll_directory(tensorrt_bin_dir)
    return tensorrt_bin_dir


def resolve_cudnn_bin_dir(
    *,
    app_root: Path | None = None,
    required: bool = False,
) -> Path | None:
    """解析当前进程应使用的 cuDNN DLL 目录。

    参数：
    - app_root：可选应用根目录；开发态通常是仓库根目录，发布态通常是 `release/full`。
    - required：为 True 时，找不到目录会抛出明确配置错误。

    返回：
    - Path | None：可用的 cuDNN DLL 目录；找不到且未要求强制存在时返回 None。
    """

    for candidate in _iter_cudnn_bin_dir_candidates(app_root=app_root):
        if candidate.is_dir():
            return candidate.resolve()
    if required:
        raise ServiceConfigurationError(
            "未找到 cuDNN DLL 目录",
            details={
                "env_bin": os.getenv(CUDNN_BIN_DIR_ENV_VAR, ""),
                "env_root": os.getenv(CUDNN_ROOT_DIR_ENV_VAR, ""),
                "env_cuda_version": os.getenv(CUDNN_CUDA_VERSION_ENV_VAR, ""),
                "expected_release_dir": "tools/cudnn/bin/12.9/x64",
                "expected_development_dir": "runtimes/cudnn_dll/bin/12.9/x64",
            },
        )
    return None


def _iter_tensorrt_bin_dir_candidates(*, app_root: Path | None) -> list[Path]:
    """生成 TensorRT bin 目录候选路径。"""

    candidates: list[Path] = []
    env_bin_dir = os.getenv(TENSORRT_BIN_DIR_ENV_VAR)
    if env_bin_dir:
        candidates.append(Path(env_bin_dir))

    env_root_dir = os.getenv(TENSORRT_ROOT_DIR_ENV_VAR)
    if env_root_dir:
        candidates.append(Path(env_root_dir) / "bin")

    code_root = _resolve_code_root()
    install_root = _resolve_install_root(code_root)
    if app_root is not None:
        resolved_app_root = app_root.resolve()
        candidates.extend(
            [
                resolved_app_root / "tools" / "tensorrt" / "bin",
                resolved_app_root / "runtimes" / "tensorrt" / "bin",
                resolved_app_root / "runtimes" / "tensorrt_bin" / "bin",
            ]
        )
    candidates.extend(
        [
            install_root / "tools" / "tensorrt" / "bin",
            install_root / "runtimes" / "tensorrt" / "bin",
            install_root / "runtimes" / "tensorrt_bin" / "bin",
            code_root / "runtimes" / "tensorrt_bin" / "bin",
            code_root / "runtimes" / "third_party" / "tensorrt" / "bin",
        ]
    )
    return _dedupe_paths(candidates)


def _iter_cudnn_bin_dir_candidates(*, app_root: Path | None) -> list[Path]:
    """生成 cuDNN DLL 目录候选路径。"""

    candidates: list[Path] = []
    env_bin_dir = os.getenv(CUDNN_BIN_DIR_ENV_VAR)
    if env_bin_dir:
        candidates.append(Path(env_bin_dir))

    env_root_dir = os.getenv(CUDNN_ROOT_DIR_ENV_VAR)
    if env_root_dir:
        candidates.extend(_build_cudnn_root_candidates(Path(env_root_dir)))

    code_root = _resolve_code_root()
    install_root = _resolve_install_root(code_root)
    if app_root is not None:
        resolved_app_root = app_root.resolve()
        candidates.extend(
            [
                candidate
                for root_dir in (
                    resolved_app_root / "tools" / "cudnn",
                    resolved_app_root / "runtimes" / "cudnn_dll",
                )
                for candidate in _build_cudnn_root_candidates(root_dir)
            ]
        )
    candidates.extend(
        [
            candidate
            for root_dir in (
                install_root / "tools" / "cudnn",
                install_root / "runtimes" / "cudnn_dll",
                code_root / "runtimes" / "cudnn_dll",
            )
            for candidate in _build_cudnn_root_candidates(root_dir)
        ]
    )
    return _dedupe_paths(candidates)


def _build_cudnn_root_candidates(root_dir: Path) -> list[Path]:
    """按当前 CUDA 版本偏好生成 cuDNN DLL 目录候选。"""

    version = os.getenv(CUDNN_CUDA_VERSION_ENV_VAR, DEFAULT_CUDNN_CUDA_VERSION)
    bin_dir = root_dir / "bin"
    candidates = [
        bin_dir / version / "x64",
        bin_dir / DEFAULT_CUDNN_CUDA_VERSION / "x64",
        bin_dir,
    ]
    if bin_dir.is_dir():
        version_dirs = sorted(
            (child for child in bin_dir.iterdir() if child.is_dir()),
            key=lambda path: path.name,
        )
        candidates.extend(version_dir / "x64" for version_dir in version_dirs)
    return candidates


def _resolve_cudnn_root_dir(cudnn_bin_dir: Path) -> Path:
    """从 cuDNN DLL 目录反推出 cuDNN 根目录。"""

    if cudnn_bin_dir.name.lower() == "x64" and cudnn_bin_dir.parent.parent.name.lower() == "bin":
        return cudnn_bin_dir.parent.parent.parent
    if cudnn_bin_dir.name.lower() == "bin":
        return cudnn_bin_dir.parent
    return cudnn_bin_dir


def _resolve_code_root() -> Path:
    """解析当前 backend 代码所在根目录。"""

    return Path(__file__).resolve().parents[5]


def _resolve_install_root(code_root: Path) -> Path:
    """把代码根目录映射为应用安装根目录。"""

    if code_root.name == "app" and (code_root.parent / "config").is_dir():
        return code_root.parent
    return code_root


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    """按字符串形式去重并保持原始顺序。"""

    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        path_key = str(path)
        if path_key in seen:
            continue
        seen.add(path_key)
        deduped.append(path)
    return deduped


def _prepend_process_path(path_value: str) -> None:
    """把目录加入当前进程 PATH 前面。"""

    _prepend_path_value(os.environ, "PATH", path_value)


def _add_windows_dll_directory(bin_dir: Path) -> None:
    """在 Windows 下把目录加入当前进程 DLL 搜索路径。"""

    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    normalized_bin_dir = str(bin_dir)
    if normalized_bin_dir in _DLL_DIRECTORY_PATHS:
        return
    handle = os.add_dll_directory(normalized_bin_dir)
    _DLL_DIRECTORY_HANDLES.append(handle)
    _DLL_DIRECTORY_PATHS.add(normalized_bin_dir)


def _prepend_path_value(env: MutableMapping[str, str], key: str, path_value: str) -> None:
    """把目录加入指定环境变量前面。"""

    current_value = env.get(key, "")
    path_parts = [part for part in current_value.split(os.pathsep) if part]
    normalized_parts = {str(Path(part)) for part in path_parts}
    if str(Path(path_value)) in normalized_parts:
        return
    env[key] = path_value if not current_value else os.pathsep.join((path_value, current_value))
