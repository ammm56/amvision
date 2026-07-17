"""backend-maintenance release 组装辅助。"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_BACKEND_DIR = REPOSITORY_ROOT / "backend"
SOURCE_CONFIG_DIR = REPOSITORY_ROOT / "config"
SOURCE_CUSTOM_NODES_DIR = REPOSITORY_ROOT / "custom_nodes"
SOURCE_FRONTEND_DIST_DIR = REPOSITORY_ROOT / "frontend" / "web-ui" / "dist"
SOURCE_FRONTEND_RUNTIME_CONFIG_LOCAL_FILE = (
    REPOSITORY_ROOT / "frontend" / "web-ui" / "public" / "runtime-config.local.json"
)
SOURCE_FRONTEND_RUNTIME_CONFIG_TEMPLATE_FILE = (
    REPOSITORY_ROOT / "frontend" / "web-ui" / "public" / "runtime-config.template.json"
)
SOURCE_REQUIREMENTS_FILE = REPOSITORY_ROOT / "requirements.txt"
SOURCE_REQUIREMENTS_CPU_FILE = REPOSITORY_ROOT / "requirements_cpu.txt"
SOURCE_ROOT_DOCUMENTS = (
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "LICENSE",
    REPOSITORY_ROOT / "LICENSE.zh-CN",
    REPOSITORY_ROOT / "COMMERCIAL_LICENSE_REQUIRED.md",
)
SOURCE_LAUNCHERS_DIR = REPOSITORY_ROOT / "runtimes" / "launchers"
SOURCE_FULL_LAUNCHERS_DIR = SOURCE_LAUNCHERS_DIR / "full"
SOURCE_RELEASE_PROFILES_DIR = REPOSITORY_ROOT / "runtimes" / "manifests" / "release-profiles"
SOURCE_WORKER_PROFILES_DIR = REPOSITORY_ROOT / "runtimes" / "manifests" / "worker-profiles"
SOURCE_FFMPEG_RUNTIME_DIR = REPOSITORY_ROOT / "runtimes" / "third_party" / "ffmpeg"
SOURCE_TENSORRT_RUNTIME_DIR = REPOSITORY_ROOT / "runtimes" / "tensorrt_bin"
SOURCE_CUDNN_RUNTIME_DIR = REPOSITORY_ROOT / "runtimes" / "cudnn_dll"

_SUPPORTED_REQUIREMENTS_FILES = {
    "requirements.txt": SOURCE_REQUIREMENTS_FILE,
    "requirements_cpu.txt": SOURCE_REQUIREMENTS_CPU_FILE,
}

_SUPPORTED_RELEASE_TARGETS = {
    ("windows", "x64", "nvidia"),
    ("windows", "x64", "cpu"),
}


@dataclass(frozen=True)
class ReleaseAssemblyRequest:
    """描述一次 release 组装请求。

    字段：
    - profile_id：要组装的 release profile id。
    - output_root：release 输出根目录。
    - overwrite：目标目录已存在时是否允许覆盖。
    - bundled_python_source_dir：可选的 bundled Python 来源目录。
    - frontend_dist_dir：可选的前端构建产物目录。
    - frontend_runtime_config_source_file：优先复制为 runtime-config.json 的配置文件。
    - frontend_runtime_config_template_file：找不到 source_file 时使用的模板文件。
    """

    profile_id: str
    output_root: Path
    overwrite: bool = False
    bundled_python_source_dir: Path | None = None
    frontend_dist_dir: Path | None = None
    frontend_runtime_config_source_file: Path | None = None
    frontend_runtime_config_template_file: Path | None = None

    def resolve_release_dir(self) -> Path:
        """返回当前 profile 的发行目录。"""

        return self.output_root.resolve() / self.profile_id.strip()


@dataclass(frozen=True)
class ReleaseAssemblyResult:
    """描述一次 release 组装结果。

    字段：
    - profile_id：本次组装的 release profile id。
    - release_dir：最终发行目录。
    - release_manifest_path：发行目录里的 release manifest 路径。
    - requirements_path：发行目录里的 requirements.txt 路径。
    - bundled_python_dir：发行目录里的 bundled Python 目录。
    - bundled_python_mode：bundled Python 的来源模式，支持 copied-from-source、preserved-existing 或 placeholder-empty。
    - generated_root_launchers：发行目录根目录的一键启动脚本列表。
    - worker_profile_ids：本次打入发行目录的 worker profile id 列表。
    - generated_worker_launchers：自动生成的 worker wrapper 列表。
    - placeholder_dirs：本次创建但等待后续资产填充的目录列表。
    """

    profile_id: str
    release_dir: Path
    release_manifest_path: Path
    requirements_path: Path
    bundled_python_dir: Path
    bundled_python_mode: str
    generated_root_launchers: tuple[Path, ...]
    worker_profile_ids: tuple[str, ...]
    generated_worker_launchers: tuple[Path, ...]
    copied_root_documents: tuple[Path, ...]
    placeholder_dirs: tuple[Path, ...]


def _load_json_file(file_path: Path) -> dict[str, object]:
    """读取 JSON 文件并返回字典对象。"""

    return json.loads(file_path.read_text(encoding="utf-8"))


def _write_json_file(file_path: Path, payload: dict[str, object]) -> None:
    """把 JSON 对象写入目标文件。"""

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy_file(source_path: Path, target_path: Path) -> None:
    """复制单个文件并确保目标目录存在。"""

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)


def _copy_directory_tree(
    source_dir: Path,
    target_dir: Path,
    *,
    ignore: Callable[[str, list[str]], set[str]] | None = None,
) -> None:
    """复制目录树；如果源目录不存在则仅创建目标目录。

    参数：
    - source_dir：源目录。
    - target_dir：目标目录。
    - ignore：可选忽略规则。
    """

    if source_dir.is_dir():
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True, ignore=ignore)
        return
    target_dir.mkdir(parents=True, exist_ok=True)


def _ignore_custom_nodes_copy(directory: str, names: list[str]) -> set[str]:
    """返回复制 custom_nodes 时需要忽略的目录和文件名。

    参数：
    - directory：当前正在复制的目录。
    - names：当前目录下候选名称列表。

    返回：
    - set[str]：需要忽略的名称集合。
    """

    ignored_names = {"__pycache__"}
    return {
        name
        for name in names
        if name in ignored_names or name.endswith(".pyc") or name.endswith(".pyo")
    }


def _ignore_bundled_python_copy(directory: str, names: list[str]) -> set[str]:
    """返回复制 bundled Python 时需要忽略的目录和文件名。"""

    ignored_names = {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
    return {
        name
        for name in names
        if name in ignored_names or name.endswith(".pyc") or name.endswith(".pyo")
    }


def _copy_launcher_tree(release_dir: Path, *, target_os: str) -> None:
    """按目标操作系统复制通用 launcher 脚本到发行目录。"""

    if target_os != "windows":
        raise ValueError(f"当前 release 组装尚未实现目标操作系统: {target_os}")

    _copy_file(SOURCE_LAUNCHERS_DIR / "common.py", release_dir / "launchers" / "common.py")
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "service" / "start_backend_service.py",
        release_dir / "launchers" / "service" / "start_backend_service.py",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "service" / "start-backend-service.bat",
        release_dir / "launchers" / "service" / "start-backend-service.bat",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "worker" / "start_backend_worker.py",
        release_dir / "launchers" / "worker" / "start_backend_worker.py",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "worker" / "start-backend-worker.bat",
        release_dir / "launchers" / "worker" / "start-backend-worker.bat",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "maintenance" / "invoke_backend_maintenance.py",
        release_dir / "launchers" / "maintenance" / "invoke_backend_maintenance.py",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "maintenance" / "invoke-backend-maintenance.bat",
        release_dir / "launchers" / "maintenance" / "invoke-backend-maintenance.bat",
    )


def _copy_full_root_launchers(release_dir: Path, *, target_os: str) -> tuple[Path, ...]:
    """按目标操作系统复制 full 发布目录根启动和停止脚本。

    参数：
    - release_dir：当前发行目录。

    返回：
    - tuple[Path, ...]：已复制到发行目录根目录的脚本列表。
    """

    if target_os != "windows":
        raise ValueError(f"当前 release 组装尚未实现目标操作系统: {target_os}")

    root_launcher_paths = (
        release_dir / "start_amvision_full.py",
        release_dir / "start-amvision-full.bat",
        release_dir / "stop_amvision_full.py",
        release_dir / "stop-amvision-full.bat",
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "start_amvision_full.py",
        root_launcher_paths[0],
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "start-amvision-full.bat",
        root_launcher_paths[1],
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "stop_amvision_full.py",
        root_launcher_paths[2],
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "stop-amvision-full.bat",
        root_launcher_paths[3],
    )
    return root_launcher_paths


def _copy_root_documents(release_dir: Path) -> tuple[Path, ...]:
    """复制发布根目录需要的项目说明和授权文件。"""

    copied_paths: list[Path] = []
    for source_path in SOURCE_ROOT_DOCUMENTS:
        if not source_path.is_file():
            raise FileNotFoundError(f"发布根文档不存在: {source_path}")
        target_path = release_dir / source_path.name
        _copy_file(source_path, target_path)
        copied_paths.append(target_path)
    return tuple(copied_paths)


def _build_worker_windows_wrapper(profile_id: str) -> str:
    """生成带固定 profile 的 Windows worker wrapper。"""

    return (
        "@echo off\r\n"
        "setlocal\r\n"
        "set \"SCRIPT_DIR=%~dp0\"\r\n"
        "set \"PYTHON_EXE=%AMVISION_PYTHON_EXECUTABLE%\"\r\n"
        "if defined PYTHON_EXE goto run\r\n"
        "if exist \"%SCRIPT_DIR%..\\..\\python\\python.exe\" set \"PYTHON_EXE=%SCRIPT_DIR%..\\..\\python\\python.exe\"\r\n"
        "if defined PYTHON_EXE goto run\r\n"
        "set \"PYTHON_EXE=python\"\r\n"
        ":run\r\n"
        f"\"%PYTHON_EXE%\" \"%SCRIPT_DIR%start_backend_worker.py\" --worker-profile-file \"manifests/worker-profiles/{profile_id}.json\" %*\r\n"
        "endlocal\r\n"
    )


def _normalize_requirement_name(requirement_line: str) -> str | None:
    """从 requirements 行中提取可比较的包名。

    参数：
    - requirement_line：requirements.txt 中的一行文本。

    返回：
    - str | None：归一化后的包名；空行、注释或无法识别时返回 None。
    """

    stripped_line = requirement_line.strip()
    if not stripped_line or stripped_line.startswith("#"):
        return None
    requirement_head = stripped_line.split(";", 1)[0].strip()
    requirement_head = requirement_head.split("[", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9_.-]+)", requirement_head)
    if match is None:
        return None
    return match.group(1).replace("_", "-").lower()


def _resolve_requirements_source_file(artifacts_section: dict[str, object]) -> Path:
    """解析当前 release profile 使用的 requirements 源文件。

    参数：
    - artifacts_section：release profile 中的 artifacts 配置。

    返回：
    - Path：仓库根目录下受支持的 requirements 文件路径。
    """

    raw_requirements_file = artifacts_section.get("requirements_file", "requirements.txt")
    requirements_file = str(raw_requirements_file).strip() or "requirements.txt"
    requirements_file = requirements_file.replace("\\", "/")
    if "/" in requirements_file or requirements_file not in _SUPPORTED_REQUIREMENTS_FILES:
        supported_files = ", ".join(sorted(_SUPPORTED_REQUIREMENTS_FILES))
        raise ValueError(
            "artifacts.requirements_file 只允许使用仓库根目录中的已知文件: "
            f"{supported_files}"
        )

    source_path = _SUPPORTED_REQUIREMENTS_FILES[requirements_file]
    if not source_path.is_file():
        raise FileNotFoundError(f"requirements 源文件不存在: {source_path}")
    return source_path


def _copy_requirements_file(
    target_path: Path,
    *,
    source_path: Path,
    excluded_packages: set[str],
) -> None:
    """按 release profile 复制或过滤 requirements 文件。

    参数：
    - target_path：发行目录中的 requirements.txt 路径。
    - source_path：当前 profile 选择的 requirements 源文件。
    - excluded_packages：当前 profile 明确排除的包名集合。
    """

    if not excluded_packages:
        _copy_file(source_path, target_path)
        return

    filtered_lines: list[str] = []
    skipped_packages: list[str] = []
    for line in source_path.read_text(encoding="utf-8").splitlines():
        package_name = _normalize_requirement_name(line)
        if package_name is not None and package_name in excluded_packages:
            skipped_packages.append(package_name)
            continue
        filtered_lines.append(line)

    filtered_lines.append("")
    filtered_lines.append(
        "# 当前 release profile 已排除这些 GPU-only 依赖: "
        + ", ".join(sorted(set(skipped_packages)))
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(filtered_lines).rstrip() + "\n", encoding="utf-8")


def _extract_excluded_requirement_packages(artifacts_section: dict[str, object]) -> set[str]:
    """读取当前 release profile 要排除的 requirements 包名。"""

    excluded_packages_raw = artifacts_section.get("requirements_exclude_packages", [])
    if not isinstance(excluded_packages_raw, list):
        raise ValueError("artifacts.requirements_exclude_packages 必须是数组")
    return {
        str(package_name).replace("_", "-").lower()
        for package_name in excluded_packages_raw
        if str(package_name).strip()
    }


def _copy_application_sources(
    release_dir: Path,
    *,
    artifacts_section: dict[str, object],
) -> None:
    """复制后端源码和基础配置到发行目录。"""

    shutil.copytree(SOURCE_BACKEND_DIR, release_dir / "app" / "backend", dirs_exist_ok=True)
    shutil.copytree(SOURCE_CONFIG_DIR, release_dir / "config", dirs_exist_ok=True)
    requirements_source_file = _resolve_requirements_source_file(artifacts_section)
    _copy_requirements_file(
        release_dir / "app" / "requirements.txt",
        source_path=requirements_source_file,
        excluded_packages=_extract_excluded_requirement_packages(artifacts_section),
    )


def _copy_runtime_assets(
    release_dir: Path,
    *,
    artifacts_section: dict[str, object],
    platform_tag: str,
) -> None:
    """复制 release 运行期需要的静态资产。

    参数：
    - release_dir：当前发行目录。
    - artifacts_section：当前 release profile 的 artifacts 配置。

    说明：
    - custom_nodes 作为 workflow app 运行期代码资产随包发布。
    - 其他数据库、workflow JSON、预训练模型和开发数据不在这里复制。
    """

    _copy_directory_tree(
        SOURCE_CUSTOM_NODES_DIR,
        release_dir / "custom_nodes",
        ignore=_ignore_custom_nodes_copy,
    )
    ffmpeg_platform = str(artifacts_section.get("ffmpeg_platform") or platform_tag).strip()
    if ffmpeg_platform != platform_tag:
        raise ValueError(
            "artifacts.ffmpeg_platform 必须与 target.platform_tag 一致: "
            f"ffmpeg_platform={ffmpeg_platform}, platform_tag={platform_tag}"
        )
    source_ffmpeg_platform_dir = SOURCE_FFMPEG_RUNTIME_DIR / ffmpeg_platform
    if not source_ffmpeg_platform_dir.is_dir():
        raise FileNotFoundError(f"目标平台 FFmpeg 资产不存在: {source_ffmpeg_platform_dir}")
    _copy_directory_tree(
        source_ffmpeg_platform_dir,
        release_dir / "tools" / "ffmpeg" / ffmpeg_platform,
        ignore=_ignore_custom_nodes_copy,
    )
    if bool(artifacts_section.get("include_tensorrt_runtime", False)):
        _copy_tensorrt_runtime_assets(release_dir)
    if bool(artifacts_section.get("include_cudnn_runtime", False)):
        _copy_cudnn_runtime_assets(release_dir)


def _validate_windows_nvidia_runtime_assets(release_dir: Path) -> None:
    """确认 Windows x64 NVIDIA 包中的 TensorRT/cuDNN 资产可识别。"""

    tensorrt_bin_dir = release_dir / "tools" / "tensorrt" / "bin"
    tensorrt_python_dir = release_dir / "tools" / "tensorrt" / "python"
    cudnn_bin_dir = release_dir / "tools" / "cudnn" / "bin"
    required_paths = (
        tensorrt_bin_dir / "trtexec.exe",
        tensorrt_python_dir,
        cudnn_bin_dir,
    )
    missing_paths = [str(path) for path in required_paths if not path.exists()]
    if missing_paths:
        raise FileNotFoundError(
            "Windows x64 NVIDIA 发布缺少运行时资产: " + ", ".join(missing_paths)
        )
    if not any(tensorrt_bin_dir.glob("nvinfer*.dll")):
        raise FileNotFoundError(f"TensorRT bin 缺少 nvinfer DLL: {tensorrt_bin_dir}")
    if not any(tensorrt_python_dir.glob("*cp312*win_amd64.whl")):
        raise FileNotFoundError(
            f"TensorRT Python 目录缺少 CPython 3.12 Windows x64 wheel: {tensorrt_python_dir}"
        )
    if not any(cudnn_bin_dir.rglob("cudnn64_*.dll")):
        raise FileNotFoundError(f"cuDNN bin 缺少 Windows x64 DLL: {cudnn_bin_dir}")


def _validate_cpu_requirements(requirements_path: Path) -> None:
    """确认 CPU 发布 requirements 不包含 NVIDIA-only 依赖。"""

    package_names = {
        package_name
        for line in requirements_path.read_text(encoding="utf-8").splitlines()
        if (package_name := _normalize_requirement_name(line)) is not None
    }
    forbidden_packages = {"tensorrt-cu12", "cuda-python"}
    included_forbidden = sorted(package_names & forbidden_packages)
    if included_forbidden:
        raise ValueError(
            "Windows x64 CPU requirements 包含 NVIDIA-only 依赖: "
            + ", ".join(included_forbidden)
        )


def _copy_tensorrt_runtime_assets(release_dir: Path) -> None:
    """复制本地 TensorRT 运行时资产到发行目录。"""

    target_root_dir = release_dir / "tools" / "tensorrt"
    target_root_dir.mkdir(parents=True, exist_ok=True)
    if not SOURCE_TENSORRT_RUNTIME_DIR.is_dir():
        return

    for subdir_name in ("bin", "python", "doc"):
        source_subdir = SOURCE_TENSORRT_RUNTIME_DIR / subdir_name
        if not source_subdir.is_dir():
            continue
        _copy_directory_tree(
            source_subdir,
            target_root_dir / subdir_name,
            ignore=_ignore_custom_nodes_copy,
        )


def _copy_cudnn_runtime_assets(release_dir: Path) -> None:
    """复制本地 cuDNN DLL 运行时资产到发行目录。"""

    target_root_dir = release_dir / "tools" / "cudnn"
    target_root_dir.mkdir(parents=True, exist_ok=True)
    if not SOURCE_CUDNN_RUNTIME_DIR.is_dir():
        return

    for subdir_name in ("bin",):
        source_subdir = SOURCE_CUDNN_RUNTIME_DIR / subdir_name
        if not source_subdir.is_dir():
            continue
        _copy_directory_tree(
            source_subdir,
            target_root_dir / subdir_name,
            ignore=_ignore_custom_nodes_copy,
        )

    source_license_file = SOURCE_CUDNN_RUNTIME_DIR / "LICENSE"
    if source_license_file.is_file():
        _copy_file(source_license_file, target_root_dir / "LICENSE")


def _resolve_frontend_dist_dir(request: ReleaseAssemblyRequest) -> Path:
    """解析 release 组装使用的前端构建产物目录。"""

    return (
        request.frontend_dist_dir.resolve()
        if request.frontend_dist_dir is not None
        else SOURCE_FRONTEND_DIST_DIR.resolve()
    )


def _resolve_frontend_runtime_config_source_file(
    request: ReleaseAssemblyRequest,
) -> Path | None:
    """解析优先复制为 runtime-config.json 的前端运行时配置文件。"""

    return (
        request.frontend_runtime_config_source_file.resolve()
        if request.frontend_runtime_config_source_file is not None
        else SOURCE_FRONTEND_RUNTIME_CONFIG_LOCAL_FILE.resolve()
    )


def _resolve_frontend_runtime_config_template_file(
    request: ReleaseAssemblyRequest,
) -> Path:
    """解析前端运行时配置模板文件。"""

    return (
        request.frontend_runtime_config_template_file.resolve()
        if request.frontend_runtime_config_template_file is not None
        else SOURCE_FRONTEND_RUNTIME_CONFIG_TEMPLATE_FILE.resolve()
    )


def _copy_frontend_assets(
    release_dir: Path,
    *,
    request: ReleaseAssemblyRequest,
) -> None:
    """复制前端构建产物，并确保发布目录存在 runtime-config.json。"""

    frontend_dist_dir = _resolve_frontend_dist_dir(request)
    if not frontend_dist_dir.is_dir():
        raise FileNotFoundError(
            f"前端构建产物目录不存在；请先执行 frontend/web-ui 构建: {frontend_dist_dir}"
        )

    _copy_directory_tree(frontend_dist_dir, release_dir / "frontend")
    frontend_root_dir = release_dir / "frontend"
    if not (frontend_root_dir / "index.html").is_file():
        raise FileNotFoundError(f"前端构建产物缺少 index.html: {frontend_root_dir / 'index.html'}")

    runtime_config_target_path = frontend_root_dir / "runtime-config.json"
    if runtime_config_target_path.is_file():
        return

    runtime_config_source_file = _resolve_frontend_runtime_config_source_file(request)
    if runtime_config_source_file is not None and runtime_config_source_file.is_file():
        _copy_file(runtime_config_source_file, runtime_config_target_path)
        return

    runtime_config_template_file = _resolve_frontend_runtime_config_template_file(request)
    if not runtime_config_template_file.is_file():
        raise FileNotFoundError(
            "前端运行时配置模板不存在，无法生成 runtime-config.json: "
            f"{runtime_config_template_file}"
        )
    _copy_file(runtime_config_template_file, runtime_config_target_path)


def _stash_existing_python_dir(release_dir: Path) -> Path | None:
    """把已有 release 目录中的 python 目录临时搬离。

    参数：
    - release_dir：当前发行目录。

    返回：
    - Path | None：临时缓存目录；如果原目录中没有 python 目录则返回 None。
    """

    existing_python_dir = release_dir / "python"
    if not existing_python_dir.is_dir():
        return None

    temporary_root_dir = Path(
        tempfile.mkdtemp(prefix="amvision-release-python-", dir=str(release_dir.parent.resolve()))
    )
    shutil.move(str(existing_python_dir), str(temporary_root_dir / "python"))
    return temporary_root_dir


def _restore_preserved_python_dir(
    release_dir: Path,
    preserved_python_temp_dir: Path | None,
) -> Path:
    """把临时缓存的 python 目录恢复到新的 release 目录。

    参数：
    - release_dir：当前发行目录。
    - preserved_python_temp_dir：之前暂存 python 目录的缓存目录。

    返回：
    - Path：恢复后的发行目录 python 路径。
    """

    if preserved_python_temp_dir is None:
        return _prepare_bundled_python_dir(release_dir)

    release_python_dir = release_dir / "python"
    shutil.move(str(preserved_python_temp_dir / "python"), str(release_python_dir))
    shutil.rmtree(preserved_python_temp_dir, ignore_errors=True)
    return release_python_dir


def _discard_preserved_python_dir(preserved_python_temp_dir: Path | None) -> None:
    """清理已经不再需要的暂存 python 目录。"""

    if preserved_python_temp_dir is None:
        return
    shutil.rmtree(preserved_python_temp_dir, ignore_errors=True)


def _recover_preserved_python_dir(
    release_dir: Path,
    preserved_python_temp_dir: Path | None,
) -> None:
    """在发布失败时把暂存的 python 目录恢复回发行目录。"""

    if preserved_python_temp_dir is None:
        return

    preserved_python_dir = preserved_python_temp_dir / "python"
    if not preserved_python_dir.exists():
        shutil.rmtree(preserved_python_temp_dir, ignore_errors=True)
        return

    release_dir.mkdir(parents=True, exist_ok=True)
    release_python_dir = release_dir / "python"
    if release_python_dir.exists():
        shutil.rmtree(release_python_dir, ignore_errors=True)
    shutil.move(str(preserved_python_dir), str(release_python_dir))
    shutil.rmtree(preserved_python_temp_dir, ignore_errors=True)


def _copy_bundled_python_dir(
    release_dir: Path,
    *,
    source_dir: Path,
) -> Path:
    """把指定 Python 运行时目录复制到发行目录。"""

    if not source_dir.is_dir():
        raise FileNotFoundError(f"bundled Python 来源目录不存在: {source_dir}")

    release_python_dir = release_dir / "python"
    _copy_directory_tree(
        source_dir,
        release_python_dir,
        ignore=_ignore_bundled_python_copy,
    )
    return release_python_dir


def _prepare_bundled_python_dir(release_dir: Path) -> Path:
    """创建发行目录中的空 python 目录。

    参数：
    - release_dir：当前发行目录。

    返回：
    - Path：发行目录中的 python 目录路径。
    """

    release_python_dir = release_dir / "python"
    release_python_dir.mkdir(parents=True, exist_ok=True)
    return release_python_dir


def _materialize_bundled_python_dir(
    release_dir: Path,
    preserved_python_temp_dir: Path | None,
    *,
    bundled_python_source_dir: Path | None,
) -> tuple[Path, str]:
    """为发行目录准备 bundled Python，并返回来源模式。

    参数：
    - release_dir：当前发行目录。
    - preserved_python_temp_dir：覆盖发布时暂存的旧 python 目录。

    返回：
    - tuple[Path, str]：发行目录中的 python 路径和来源模式。
    """

    if bundled_python_source_dir is not None:
        copied_python_dir = _copy_bundled_python_dir(
            release_dir,
            source_dir=bundled_python_source_dir,
        )
        return copied_python_dir, "copied-from-source"
    if preserved_python_temp_dir is not None:
        restored_python_dir = _restore_preserved_python_dir(release_dir, preserved_python_temp_dir)
        return restored_python_dir, "preserved-existing"
    release_python_dir = _prepare_bundled_python_dir(release_dir)
    return release_python_dir, "placeholder-empty"


def _materialize_placeholder_dirs(
    release_dir: Path,
    *,
    include_python_placeholder: bool,
) -> tuple[Path, ...]:
    """创建 release 目录中的占位目录。"""

    placeholder_dirs: list[Path] = [
        release_dir / "data",
        release_dir / "logs",
    ]
    if include_python_placeholder:
        placeholder_dirs.append(release_dir / "python")
    for directory in placeholder_dirs:
        directory.mkdir(parents=True, exist_ok=True)
    return tuple(placeholder_dirs)


def _resolve_release_profile(
    requested_profile_id: str,
) -> tuple[str, dict[str, object], bool]:
    """解析 canonical release profile，并标记旧 profile alias。"""

    requested_profile_path = SOURCE_RELEASE_PROFILES_DIR / f"{requested_profile_id}.json"
    if not requested_profile_path.is_file():
        raise FileNotFoundError(f"release profile 不存在: {requested_profile_path}")
    requested_profile = _load_json_file(requested_profile_path)
    requested_profile_value = str(requested_profile.get("profile_id") or "").strip()
    if requested_profile_value != requested_profile_id:
        raise ValueError(
            "release profile 文件名与 profile_id 不一致: "
            f"file={requested_profile_path.name}, profile_id={requested_profile_value}"
        )
    alias_for = str(requested_profile.get("alias_for") or "").strip()
    canonical_profile_id = alias_for or requested_profile_id
    source_release_profile_path = SOURCE_RELEASE_PROFILES_DIR / f"{canonical_profile_id}.json"
    if not source_release_profile_path.is_file():
        raise FileNotFoundError(f"release profile 不存在: {source_release_profile_path}")
    source_release_profile = _load_json_file(source_release_profile_path)
    profile_id_value = str(source_release_profile.get("profile_id") or "").strip()
    if profile_id_value != canonical_profile_id:
        raise ValueError(
            "release profile 文件名与 profile_id 不一致: "
            f"file={source_release_profile_path.name}, profile_id={profile_id_value}"
        )
    return (
        canonical_profile_id,
        source_release_profile,
        bool(alias_for),
    )


def _resolve_release_target(
    source_release_profile: dict[str, object],
) -> tuple[str, str, str, str]:
    """读取并校验当前阶段支持的 OS、架构和 accelerator。"""

    target_section = source_release_profile.get("target")
    accelerator_section = source_release_profile.get("accelerator")
    if not isinstance(target_section, dict) or not isinstance(accelerator_section, dict):
        raise ValueError("canonical release profile 必须包含 target 和 accelerator")
    target_os = str(target_section.get("os") or "").strip().lower()
    target_arch = str(target_section.get("arch") or "").strip().lower()
    platform_tag = str(target_section.get("platform_tag") or "").strip().lower()
    accelerator_kind = str(accelerator_section.get("kind") or "").strip().lower()
    expected_platform_tag = f"{target_os}-{target_arch}"
    if platform_tag != expected_platform_tag:
        raise ValueError(
            "target.platform_tag 与 os/arch 不一致: "
            f"platform_tag={platform_tag}, expected={expected_platform_tag}"
        )
    target_key = (target_os, target_arch, accelerator_kind)
    if target_key not in _SUPPORTED_RELEASE_TARGETS:
        raise ValueError(
            "当前阶段尚未实现 release target: "
            f"os={target_os}, arch={target_arch}, accelerator={accelerator_kind}"
        )
    return target_os, target_arch, platform_tag, accelerator_kind


def assemble_release(request: ReleaseAssemblyRequest) -> ReleaseAssemblyResult:
    """按指定 release profile 组装发行目录。"""

    requested_profile_id = request.profile_id.strip()
    if not requested_profile_id:
        raise ValueError("release profile id 不能为空")
    canonical_profile_id, source_release_profile, deprecated_alias = _resolve_release_profile(
        requested_profile_id
    )
    target_os, target_arch, platform_tag, accelerator_kind = _resolve_release_target(
        source_release_profile
    )
    artifacts_section = source_release_profile["artifacts"]
    assert isinstance(artifacts_section, dict)
    release_dir = request.resolve_release_dir()
    preserved_python_temp_dir: Path | None = None
    if release_dir.exists():
        if not request.overwrite:
            raise FileExistsError(f"release 目录已存在: {release_dir}")
        preserved_python_temp_dir = _stash_existing_python_dir(release_dir)
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True, exist_ok=True)

    try:
        _copy_application_sources(release_dir, artifacts_section=artifacts_section)
        _copy_runtime_assets(
            release_dir,
            artifacts_section=artifacts_section,
            platform_tag=platform_tag,
        )
        requirements_path = release_dir / "app" / "requirements.txt"
        if accelerator_kind == "nvidia":
            _validate_windows_nvidia_runtime_assets(release_dir)
        else:
            _validate_cpu_requirements(requirements_path)
        _copy_launcher_tree(release_dir, target_os=target_os)
        generated_root_launchers = _copy_full_root_launchers(
            release_dir,
            target_os=target_os,
        )
        copied_root_documents = _copy_root_documents(release_dir)

        worker_section = source_release_profile["worker"]
        assert isinstance(worker_section, dict)
        worker_profile_ids_raw = worker_section.get("worker_profile_ids")
        if not isinstance(worker_profile_ids_raw, list) or not worker_profile_ids_raw:
            raise ValueError("release profile 必须包含非空 worker.worker_profile_ids")
        worker_profile_ids = tuple(str(profile_id) for profile_id in worker_profile_ids_raw)

        worker_entries: list[dict[str, object]] = []
        generated_worker_launchers: list[Path] = []
        for profile_id in worker_profile_ids:
            source_worker_profile_path = SOURCE_WORKER_PROFILES_DIR / f"{profile_id}.json"
            if not source_worker_profile_path.is_file():
                raise FileNotFoundError(f"worker profile 不存在: {source_worker_profile_path}")
            source_worker_profile = _load_json_file(source_worker_profile_path)
            release_worker_profile_path = (
                release_dir / "manifests" / "worker-profiles" / f"{profile_id}.json"
            )
            _write_json_file(release_worker_profile_path, source_worker_profile)

            windows_wrapper_path = (
                release_dir / "launchers" / "worker" / f"start-{profile_id}-worker.bat"
            )
            windows_wrapper_path.write_text(
                _build_worker_windows_wrapper(profile_id),
                encoding="utf-8",
            )
            generated_worker_launchers.append(windows_wrapper_path)

            worker_entries.append(
                {
                    "profile_id": source_worker_profile["profile_id"],
                    "display_name": source_worker_profile["display_name"],
                    "description": source_worker_profile["description"],
                    "manifest": f"manifests/worker-profiles/{profile_id}.json",
                    "python_launcher": "launchers/worker/start_backend_worker.py",
                    "windows_launcher": f"launchers/worker/start-{profile_id}-worker.bat",
                    "enabled_consumer_kinds": source_worker_profile["enabled_consumer_kinds"],
                    "max_concurrent_tasks": source_worker_profile.get("max_concurrent_tasks", 1),
                    "poll_interval_seconds": source_worker_profile.get("poll_interval_seconds", 1.0),
                }
            )

        if bool(artifacts_section.get("include_frontend", False)):
            _copy_frontend_assets(release_dir, request=request)

        bundled_python_source_dir = (
            request.bundled_python_source_dir.resolve()
            if request.bundled_python_source_dir is not None
            else None
        )
        bundled_python_dir, bundled_python_mode = _materialize_bundled_python_dir(
            release_dir,
            preserved_python_temp_dir,
            bundled_python_source_dir=bundled_python_source_dir,
        )
        placeholder_dirs = _materialize_placeholder_dirs(
            release_dir,
            include_python_placeholder=(bundled_python_mode == "placeholder-empty"),
        )

        release_manifest = {
            "profile_id": requested_profile_id,
            "canonical_profile_id": canonical_profile_id,
            "deprecated_alias": deprecated_alias,
            "display_name": source_release_profile["display_name"],
            "description": source_release_profile["description"],
            "target": {
                "os": target_os,
                "arch": target_arch,
                "platform_tag": platform_tag,
            },
            "accelerator": {"kind": accelerator_kind},
            "requirements_file": "app/requirements.txt",
            "bundled_python": {
                "python_dir": "python",
                "mode": bundled_python_mode,
                "included": bundled_python_mode != "placeholder-empty",
                "managed_manually": bundled_python_mode != "copied-from-source",
            },
            "service": {
                "python_launcher": "launchers/service/start_backend_service.py",
                "windows_launcher": "launchers/service/start-backend-service.bat",
                "hosted_task_manager_enabled": source_release_profile["service"][
                    "hosted_task_manager_enabled"
                ],
            },
            "workers": worker_entries,
            "maintenance": {
                "python_launcher": "launchers/maintenance/invoke_backend_maintenance.py",
                "windows_launcher": "launchers/maintenance/invoke-backend-maintenance.bat",
                "default_command": source_release_profile["maintenance"]["default_command"],
            },
            "stack": {
                "python_launcher": "start_amvision_full.py",
                "windows_launcher": "start-amvision-full.bat",
                "logs_dir": "logs/full-stack",
                "state_file": "logs/full-stack/runtime-state.json",
                "stop_python_launcher": "stop_amvision_full.py",
                "stop_windows_launcher": "stop-amvision-full.bat",
            },
            "artifacts": artifacts_section,
            "layout": {
                "app_dir": "app",
                "config_dir": "config",
                "custom_nodes_dir": "custom_nodes",
                "data_dir": "data",
                "logs_dir": "logs",
                "python_dir": "python",
            },
        }
        release_manifest_path = (
            release_dir / "manifests" / "release-profiles" / f"{request.profile_id}.json"
        )
        _write_json_file(release_manifest_path, release_manifest)
        _discard_preserved_python_dir(preserved_python_temp_dir)

        return ReleaseAssemblyResult(
            profile_id=request.profile_id,
            release_dir=release_dir,
            release_manifest_path=release_manifest_path,
            requirements_path=requirements_path,
            bundled_python_dir=bundled_python_dir,
            bundled_python_mode=bundled_python_mode,
            generated_root_launchers=generated_root_launchers,
            worker_profile_ids=worker_profile_ids,
            generated_worker_launchers=tuple(generated_worker_launchers),
            copied_root_documents=copied_root_documents,
            placeholder_dirs=placeholder_dirs,
        )
    except Exception:
        _recover_preserved_python_dir(release_dir, preserved_python_temp_dir)
        raise
